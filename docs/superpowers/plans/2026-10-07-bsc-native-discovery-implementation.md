# BSC Native Meme Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Discover new BSC Meme pools from verified PancakeSwap factory events, provide a fail-closed Four.meme adapter hook, and merge native candidates with GeckoTerminal fallback in the paper runtime.

**Architecture:** `BscPoolDiscovery` scans configured BSC protocol contracts through the existing `EvmChainAdapter`, maintains independent block cursors and bounded stale caches, and emits normalized `PoolCandidate` values. `CompositePoolDiscovery` merges native and GeckoTerminal candidates with native identity precedence; Robinhood remains GeckoTerminal/RPC based. Existing event decoding, GMGN enrichment, fusion, security gates, and paper execution remain unchanged.

**Tech Stack:** Python 3.12, Pydantic 2, `web3.py` 7, `eth-abi`, `pytest-asyncio`, SQLite repository, Ruff, mypy strict.

## Global Constraints

- Target BSC chain ID is `56`; native discovery is disabled for Robinhood.
- PancakeSwap V2 factory is `0xca143ce32fe78f1f7019d7d551a6402fc5350c73`.
- PancakeSwap V3 factory is `0x0bfbcf9fa4f9c56b0f40a671ad40e0805a091865`.
- Four.meme is enabled only when a configured address and event schema pass validation; no unverified default address is added.
- Native discovery uses the existing RPC proxy and per-chain timeout settings; all GeckoTerminal and GMGN HTTP requests continue through `http://127.0.0.1:7890`.
- A failed log range never advances its cursor; a stale cache is observation-only and cannot bypass fusion, security, liquidity, freshness, or risk gates.
- Paper mode remains the only running mode; no signer or private key is loaded and no transaction is broadcast.
- Existing user changes in `configs/networks.yaml` and `env/` are preserved and not committed by feature changes.
- Every feature change follows a failing test, minimal implementation, focused test, then full verification.

---

### Task 1: Add native discovery configuration and protocol metadata

**Files:**
- Modify: `app/config.py`
- Modify: `configs/default.yaml`
- Test: `tests/test_config.py`

**Interfaces:**
- Add `NativeProtocolSettings(enabled: bool, chain: str, contract_address: str | None, event_kind: Literal["v2_pair_created", "v3_pool_created", "four_meme"], dex_id: str)`.
- Add `NativeDiscoverySettings(enabled: bool = True, initial_backfill_blocks: int = 500, max_log_block_span: int = 1000, max_pools_per_protocol: int = 50, stale_cache_seconds: int = 300, protocols: dict[str, NativeProtocolSettings])`.
- Add `Settings.native_discovery: NativeDiscoverySettings`.

- [ ] **Step 1: Write the failing configuration test.**

```python
def test_native_bsc_discovery_defaults_are_verified(tmp_path: Path) -> None:
    settings = load_settings(tmp_path / "missing.yaml")
    protocols = settings.native_discovery.protocols
    assert settings.native_discovery.enabled is True
    assert protocols["pancakeswap_v2"].contract_address == (
        "0xca143ce32fe78f1f7019d7d551a6402fc5350c73"
    )
    assert protocols["pancakeswap_v3"].contract_address == (
        "0x0bfbcf9fa4f9c56b0f40a671ad40e0805a091865"
    )
    assert "four_meme" not in protocols
```

- [ ] **Step 2: Run the test and verify it fails.**

Run: `.venv/bin/python -m pytest tests/test_config.py::test_native_bsc_discovery_defaults_are_verified -q`

Expected: failure because `Settings.native_discovery` does not exist.

- [ ] **Step 3: Implement the minimum configuration.**

Add the two Pydantic models, validate positive numeric limits, validate enabled protocol addresses with `Web3.is_address`, and add the two Pancake defaults under `native_discovery.protocols`. Do not add a default Four.meme address. Keep `configs/networks.yaml` unchanged.

- [ ] **Step 4: Run focused checks.**

Run: `.venv/bin/python -m pytest tests/test_config.py -q && .venv/bin/ruff check app/config.py tests/test_config.py && .venv/bin/mypy app/config.py`

Expected: all configuration tests pass with no static errors.

- [ ] **Step 5: Commit only feature files.**

```bash
git add app/config.py configs/default.yaml tests/test_config.py
git commit -m "feat: configure native bsc protocol discovery"
```

### Task 2: Decode Pancake factory events and scan BSC ranges

**Files:**
- Create: `app/data/sources/bsc_discovery.py`
- Create: `tests/data/test_bsc_discovery.py`
- Create: `tests/fixtures/bsc_factory_logs.json`

**Interfaces:**
- Define `BscDiscoveryRpc` with `get_latest_block()`, `get_logs(address, topics, from_block, to_block)`, and `get_block_timestamp(block_number)`.
- Define `ProtocolSpec(name: str, contract_address: str, event_kind: Literal["v2_pair_created", "v3_pool_created", "four_meme"], dex_id: str, enabled: bool = True)`.
- Define `BscPoolDiscovery(rpc: BscDiscoveryRpc, specs: list[ProtocolSpec], initial_backfill_blocks: int, max_log_block_span: int, max_pools_per_protocol: int, stale_cache_seconds: int)` with `specs: tuple[ProtocolSpec, ...]`, `discover_pools() -> list[PoolCandidate]`, `health: SourceHealth`, and `cursor(protocol_name: str) -> int`.
- Export `V2_PAIR_CREATED_TOPIC` and `V3_POOL_CREATED_TOPIC` derived with `Web3.keccak` from the canonical event signatures.

- [ ] **Step 1: Write failing V2, V3, and cursor tests.**

```python
@pytest.mark.asyncio
async def test_discovery_decodes_v2_pair_created_and_advances_cursor():
    rpc = FakeDiscoveryRpc(logs=[v2_pair_created_log()])
    source = BscPoolDiscovery(rpc, [v2_spec()], 100, 50, 10, 300)
    pools = await source.discover_pools()
    assert pools[0].dex_id == "pancakeswap-v2"
    assert pools[0].pool_address == "0x00000000000000000000000000000000000000aa"
    assert source.cursor("pancakeswap_v2") == 100

@pytest.mark.asyncio
async def test_discovery_decodes_v3_pool_created():
    source = BscPoolDiscovery(FakeDiscoveryRpc(logs=[v3_pool_created_log()]), [v3_spec()], 100, 50, 10, 300)
    pools = await source.discover_pools()
    assert pools[0].dex_id == "pancakeswap-v3"
    assert pools[0].base_token == "0x00000000000000000000000000000000000000bb"

@pytest.mark.asyncio
async def test_failed_range_does_not_advance_cursor_or_emit_candidates():
    rpc = FakeDiscoveryRpc(fail=True)
    source = BscPoolDiscovery(rpc, [v2_spec()], 100, 50, 10, 300)
    assert await source.discover_pools() == []
    assert source.cursor("pancakeswap_v2") == 0
    assert source.health.status == "degraded"
```

- [ ] **Step 2: Run the focused tests and verify they fail.**

Run: `.venv/bin/python -m pytest tests/data/test_bsc_discovery.py -q`

Expected: import failure because `BscPoolDiscovery` and factory decoders do not exist.

- [ ] **Step 3: Implement canonical topic and log decoders.**

Decode V2 `PairCreated(address,address,address,uint256)` from two indexed token topics and two ABI data fields. Decode V3 `PoolCreated(address,address,uint24,int24,address)` from three indexed fields and two ABI data fields. Normalize every address through `PoolCandidate`, set `chain="bnb"`, `network_id="bsc"`, attach the block timestamp, and use the configured `dex_id`. For `four_meme`, return no candidate unless the configured event kind has a supported decoder; an unknown schema is a health observation, never a guessed pool.

- [ ] **Step 4: Implement bounded scanning and cache behavior.**

Start each protocol at `max(0, latest_block - initial_backfill_blocks + 1)`, split through `latest_block` by `max_log_block_span`, and advance the cursor only after all ranges complete. Deduplicate by `(protocol, transactionHash, logIndex)` and cap each protocol at `max_pools_per_protocol`. On RPC failure, return the protocol's candidates from the last successful scan only when their age is within `stale_cache_seconds`, mark health `observation_only`, and otherwise return `degraded` with the error.

- [ ] **Step 5: Run focused tests and static checks.**

Run: `.venv/bin/python -m pytest tests/data/test_bsc_discovery.py -q && .venv/bin/ruff check app/data/sources/bsc_discovery.py tests/data/test_bsc_discovery.py && .venv/bin/mypy app/data/sources/bsc_discovery.py`

Expected: decoder, cursor, deduplication, and failure tests pass.

- [ ] **Step 6: Commit.**

```bash
git add app/data/sources/bsc_discovery.py tests/data/test_bsc_discovery.py tests/fixtures/bsc_factory_logs.json
git commit -m "feat: discover bsc pools from factory events"
```

### Task 3: Merge native candidates with GeckoTerminal fallback

**Files:**
- Create: `app/data/sources/composite_discovery.py`
- Create: `tests/data/test_composite_discovery.py`

**Interfaces:**
- Define `CompositePoolDiscovery(sources: list[PoolDiscovery])` with `discover_pools() -> list[PoolCandidate]` and `health: SourceHealth`.

- [ ] **Step 1: Write failing merge and isolation tests.**

```python
@pytest.mark.asyncio
async def test_native_identity_wins_and_gecko_metadata_is_retained():
    source = CompositePoolDiscovery([FakeSource("bsc:native", [native_candidate()]), FakeSource("gecko:bsc", [gecko_candidate()])])
    pools = await source.discover_pools()
    assert len(pools) == 1
    assert pools[0].dex_id == "pancakeswap-v2"
    assert pools[0].reserve_usd == 1234.0

@pytest.mark.asyncio
async def test_one_failed_source_does_not_block_healthy_source():
    source = CompositePoolDiscovery([FailingSource("bsc:native"), FakeSource("gecko:bsc", [gecko_candidate()])])
    pools = await source.discover_pools()
    assert len(pools) == 1
    assert source.health.status in {"ready", "observation_only"}
```

- [ ] **Step 2: Run tests and verify they fail.**

Run: `.venv/bin/python -m pytest tests/data/test_composite_discovery.py -q`

Expected: import failure because `CompositePoolDiscovery` does not exist.

- [ ] **Step 3: Implement concurrent source collection and deterministic merge.**

Run sources with `asyncio.gather(..., return_exceptions=True)`, retain successful candidates, merge by lowercase pool address, and order native sources before external sources. Copy non-identity metadata from GeckoTerminal only when the native candidate field is absent. Report `ready` when at least one source returns candidates without fatal failure, `observation_only` when sources are reachable but empty, and `degraded` only when every source fails without a usable cache.

- [ ] **Step 4: Run focused checks.**

Run: `.venv/bin/python -m pytest tests/data/test_composite_discovery.py -q && .venv/bin/ruff check app/data/sources/composite_discovery.py tests/data/test_composite_discovery.py && .venv/bin/mypy app/data/sources/composite_discovery.py`

Expected: merge and source-isolation tests pass.

- [ ] **Step 5: Commit.**

```bash
git add app/data/sources/composite_discovery.py tests/data/test_composite_discovery.py
git commit -m "feat: merge native and external pool discovery"
```

### Task 4: Wire BSC native discovery into the paper runtime

**Files:**
- Modify: `app/main.py`
- Modify: `app/data/sources/smoke.py`
- Modify: `README.md`
- Test: `tests/e2e/test_market_event_pipeline.py`

**Interfaces:**
- Add `build_native_discovery(settings: Settings, adapter: EvmChainAdapter) -> BscPoolDiscovery | None`.
- Keep `build_market_source(settings, name, repository) -> Collector` and `PaperRuntime` interfaces unchanged.

- [ ] **Step 1: Write the failing wiring test.**

```python
from typing import cast

from app.chains.evm import EvmChainAdapter
from app.main import build_native_discovery


def test_bnb_builds_native_discovery_when_enabled(tmp_path: Path):
    settings = load_settings(tmp_path / "missing.yaml")
    source = build_native_discovery(settings, cast(EvmChainAdapter, object()))
    assert source is not None
    assert {spec.name for spec in source.specs} == {"pancakeswap_v2", "pancakeswap_v3"}
```

- [ ] **Step 2: Run the focused test and inspect the existing failure.**

Run: `.venv/bin/python -m pytest tests/e2e/test_market_event_pipeline.py::test_bnb_builds_native_discovery_when_enabled -q`

Expected: collection fails because `build_native_discovery` is not defined.

- [ ] **Step 3: Wire the source without changing execution safety.**

Create the EVM adapter once per configured chain. For `bnb`, construct `BscPoolDiscovery` from enabled protocol settings and combine it with `GeckoTerminalSource` through `CompositePoolDiscovery`; for `robinhood`, keep GeckoTerminal as the only discovery source. Pass the composite discovery to `LiveMarketSource`, keep the existing `EvmMarketCollector`, GMGN source, fusion, security checks, and paper broker unchanged. Extend the smoke output with native protocol counts and cursor health; it must remain read-only.

- [ ] **Step 4: Run integration checks.**

Run: `.venv/bin/python -m pytest tests/e2e/test_market_event_pipeline.py tests/data/test_market_smoke.py -q`

Expected: fake native candidates reach the existing runtime, source failures remain isolated, and no signer is loaded.

- [ ] **Step 5: Document operations.**

Update `README.md` with the native BSC discovery path, the distinction between BNB Agent SDK and JSON-RPC, the Pancake protocol registry, Four.meme fail-closed behavior, and the read-only smoke command.

- [ ] **Step 6: Commit.**

```bash
git add app/main.py app/data/sources/smoke.py README.md tests/e2e/test_market_event_pipeline.py
git commit -m "feat: wire native bsc discovery into paper runtime"
```

### Task 5: Full verification and controlled runtime restart

**Files:**
- No source changes unless verification exposes a test failure.

- [ ] **Step 1: Run the complete verification suite.**

Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check app tests && .venv/bin/mypy app && git diff --check`

Expected: all tests pass, Ruff and mypy report no errors, and `git diff --check` is clean.

- [ ] **Step 2: Run a bounded read-only smoke check through the local proxy.**

Run: `MARKET_PROXY_URL=http://127.0.0.1:7890 .venv/bin/python -m app.data.sources.smoke --chains bnb,robinhood --max-pools 2 --max-log-span 25`

Expected: BNB reports native protocol health and RPC chain ID `56`; Robinhood reports chain ID `4663` or an explicit source health error; `broadcasted=False` remains true.

- [ ] **Step 3: Stop duplicate paper processes and start exactly one instance.**

Identify only processes matching `.venv/bin/python -u -m app.main --mode paper`, stop the stale duplicates by PID, then start one process with:

```bash
MARKET_PROXY_URL=http://127.0.0.1:7890 \
.venv/bin/python -u -m app.main --mode paper --interval 5
```

Do not start an approval or auto process, and do not load `GMGN_AK`, `GMGN_SK`, or any wallet private key into source files.

- [ ] **Step 4: Observe at least three status reports.**

Confirm the output includes one process, `signer=disabled`, BNB poll cadence of 5 seconds, Robinhood poll cadence of 15 seconds, and no paper fill unless all existing security/liquidity/freshness gates pass.
