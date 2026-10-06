# DEX/Meme Market Event Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add proxy-aware GeckoTerminal discovery and RPC-verified EVM market-event collection for BNB Smart Chain and Robinhood Chain in paper mode.

**Architecture:** A per-chain `GeckoTerminalSource` discovers candidate pools through `http://127.0.0.1:7890` and caches validated JSON. A per-chain `EvmMarketCollector` validates chain/pool identity and decodes bounded V2/V3 logs into normalized events with block cursors and deduplication. The existing `Collector` and `PaperRuntime` consume only fused, fresh events; unavailable or conflicting sources remain observation-only and cannot open positions.

**Tech Stack:** Python 3.12, Pydantic 2, `httpx.AsyncClient`, `web3.py` 7, SQLAlchemy/SQLite, pytest/pytest-asyncio, Ruff, mypy strict.

## Global Constraints

- Target networks are BNB Smart Chain (`chain_id=56`, GeckoTerminal `bsc`) and Robinhood Chain (`chain_id=4663`, GeckoTerminal `robinhood`).
- External HTTP requests use `MARKET_PROXY_URL`, default `http://127.0.0.1:7890`.
- API discovery never authorizes a trade; RPC identity and event validation are required.
- Stale, conflicting, unavailable, or undecodable data blocks new entries.
- No HTML scraping, synthetic market events, private-key loading, or transaction broadcasting.
- Every new event is deduplicated by `chain + transaction_hash + log_index` when those values exist.
- All tests use fixtures or fake transports; public network tests are explicit read-only smoke checks only.

---

### Task 1: Add market-source configuration and normalized source models

**Files:**
- Modify: `app/config.py`
- Modify: `configs/default.yaml`
- Create: `app/data/sources/__init__.py`
- Create: `app/data/sources/models.py`
- Test: `tests/test_config.py`
- Test: `tests/data/test_source_models.py`

**Interfaces:**
- `MarketSourceSettings(proxy_url: str = "http://127.0.0.1:7890", discovery_interval_seconds: int = 60, max_pools_per_chain: int = 50, max_log_block_span: int = 1000, http_timeout_seconds: float = 10.0, max_retries: int = 3)`.
- `PoolCandidate(chain: str, network_id: str, pool_address: str, dex_id: str, base_token: str, quote_token: str, price_usd: float | None, reserve_usd: float | None, observed_at: datetime)`.
- `SourceHealth(name: str, status: ConnectorStatus, error: str | None, observed_at: datetime | None)`.

- [ ] **Step 1: Write failing configuration and model tests.**

```python
from datetime import UTC, datetime

from app.config import load_settings
from app.data.sources.models import PoolCandidate


def test_market_defaults_use_the_local_proxy(tmp_path):
    settings = load_settings(tmp_path / "missing.yaml")
    assert settings.market.proxy_url == "http://127.0.0.1:7890"
    assert settings.market.discovery_interval_seconds == 60


def test_pool_candidate_normalizes_addresses():
    candidate = PoolCandidate(
        chain="robinhood",
        network_id="robinhood",
        pool_address="0xABC",
        dex_id="uniswap-v3-robinhood",
        base_token="0xDEF",
        quote_token="0x123",
        observed_at=datetime.now(UTC),
    )
    assert candidate.pool_address == "0xabc"
    assert candidate.base_token == "0xdef"
```

- [ ] **Step 2: Run the focused tests and verify they fail.**

Run: `.venv/bin/python -m pytest tests/test_config.py tests/data/test_source_models.py -q`

Expected: collection or attribute failures because `Settings.market` and source models do not yet exist.

- [ ] **Step 3: Implement the minimal settings and Pydantic models.**

Add a `MarketSourceSettings` Pydantic model with the values above, add `market: MarketSourceSettings` to `Settings`, and add the same defaults to `configs/default.yaml`. Use a field validator in `PoolCandidate` to lowercase and validate EVM addresses with `web3.Web3.is_address`; reject a missing or timezone-naive `observed_at`.

- [ ] **Step 4: Run focused tests and static checks.**

Run: `.venv/bin/python -m pytest tests/test_config.py tests/data/test_source_models.py -q && .venv/bin/ruff check app tests && .venv/bin/mypy app`

Expected: focused tests pass and static checks report no errors.

- [ ] **Step 5: Commit.**

```bash
git add app/config.py configs/default.yaml app/data/sources tests/test_config.py tests/data/test_source_models.py
git commit -m "feat: add market source configuration models"
```

### Task 2: Implement proxy-aware GeckoTerminal discovery

**Files:**
- Create: `app/data/sources/geckoterminal.py`
- Test: `tests/data/test_geckoterminal.py`
- Create: `tests/fixtures/geckoterminal_bsc_pools.json`
- Create: `tests/fixtures/geckoterminal_robinhood_pools.json`

**Interfaces:**
- `GeckoTerminalSource(network_id: str, proxy_url: str, timeout_seconds: float, max_retries: int, max_pools: int, transport: httpx.AsyncBaseTransport | None = None)`.
- `await GeckoTerminalSource.discover_pools() -> list[PoolCandidate]`.
- `GeckoTerminalSource.health -> SourceHealth`.

- [ ] **Step 1: Write failing parser and retry tests.**

```python
import httpx
import pytest

from app.data.sources.geckoterminal import GeckoTerminalSource


@pytest.mark.asyncio
async def test_discovery_parses_bsc_and_keeps_base_token():
    source = GeckoTerminalSource("bsc", "http://127.0.0.1:7890", transport=fixture_transport("geckoterminal_bsc_pools.json"))
    pools = await source.discover_pools()
    assert pools[0].chain == "bnb"
    assert pools[0].network_id == "bsc"
    assert pools[0].base_token.startswith("0x")


@pytest.mark.asyncio
async def test_discovery_retries_then_marks_degraded():
    source = GeckoTerminalSource("robinhood", "http://127.0.0.1:7890", max_retries=2, transport=always_timeout_transport())
    assert await source.discover_pools() == []
    assert source.health.status == "degraded"
```

- [ ] **Step 2: Run the focused tests and verify they fail.**

Run: `.venv/bin/python -m pytest tests/data/test_geckoterminal.py -q`

Expected: import failure because `GeckoTerminalSource` and fixture helpers do not exist.

- [ ] **Step 3: Implement the source with explicit HTTP behavior.**

Use `httpx.AsyncClient(proxy=proxy_url, timeout=timeout_seconds, transport=transport)` and call `/api/v2/networks/{network_id}/pools?page=1`. Parse only the `data[].attributes` and `relationships` fields required by `PoolCandidate`; derive token addresses from relationship IDs after checking their network prefix. Retry `httpx.TimeoutException`, `httpx.TransportError`, and HTTP 5xx responses with bounded exponential backoff. A 4xx response returns no candidates and a degraded health record. Never replace a failed response with fabricated values.

The fixture transport helper must return an `httpx.Response(200, json=fixture_payload)` for the requested path, while the timeout helper must raise `httpx.ReadTimeout` on every request. Tests must assert that retries never exceed `max_retries`.

- [ ] **Step 4: Run focused tests and lint.**

Run: `.venv/bin/python -m pytest tests/data/test_geckoterminal.py -q && .venv/bin/ruff check app tests && .venv/bin/mypy app`

Expected: all focused tests pass and no static errors remain.

- [ ] **Step 5: Commit.**

```bash
git add app/data/sources/geckoterminal.py tests/data/test_geckoterminal.py tests/fixtures
git commit -m "feat: discover meme pools through geckoterminal"
```

### Task 3: Add EVM log decoding for V2 and V3 pools

**Files:**
- Create: `app/data/sources/evm_logs.py`
- Modify: `app/data/events.py`
- Modify: `app/storage/repository.py`
- Test: `tests/data/test_evm_logs.py`
- Create: `tests/fixtures/evm_v2_logs.json`
- Create: `tests/fixtures/evm_v3_logs.json`

**Interfaces:**
- `decode_v2_swap(log: Mapping[str, object], candidate: PoolCandidate, block_timestamp: datetime) -> Swap | None`.
- `decode_v3_swap(log: Mapping[str, object], candidate: PoolCandidate, block_timestamp: datetime) -> Swap | None`.
- `decode_sync_or_liquidity(log: Mapping[str, object], candidate: PoolCandidate, block_timestamp: datetime) -> LiquidityChange | None`.
- `event_id(log: Mapping[str, object], chain: str) -> str | None`.

- [ ] **Step 1: Write failing V2/V3 decoding and dedup tests.**

```python
def test_v2_swap_marks_base_token_buy_from_amount_out():
    event = decode_v2_swap(v2_buy_log(), bsc_candidate(), datetime.now(UTC))
    assert event is not None
    assert event.side == "buy"
    assert event.amount > 0
    assert event.source_event_id == "bnb:0xabc:3"


def test_v3_unknown_topic_is_ignored():
    assert decode_v3_swap(unknown_log(), robinhood_candidate(), datetime.now(UTC)) is None
```

- [ ] **Step 2: Run tests and verify they fail.**

Run: `.venv/bin/python -m pytest tests/data/test_evm_logs.py -q`

Expected: import or missing-field failures because the decoder and event identity fields do not exist.

- [ ] **Step 3: Extend event identity and implement decoders.**

Add optional `source_event_id`, `block_number`, and `transaction_hash` fields to `MarketEvent`. Add the corresponding source identity to persisted JSON; keep existing events backward compatible. Decode indexed sender/recipient and signed or unsigned amount fields using fixed ABI definitions. For V2, identify buy direction from the base-token amount sent out of the pool; for V3, identify buy direction from the signed base-token delta. Compute an event price only when both token legs are positive and finite. Return `None` for unsupported topics or incomplete logs.

The V2 fixture must contain one `Swap` log with the base token as token0 and a positive token0 output. The V3 fixture must contain one signed `amount0`/`amount1` swap and one unknown topic. The helper `event_id` must return `"<chain>:<transactionHash>:<logIndex>"` for hexadecimal log fields and `None` when either identity field is absent.

- [ ] **Step 4: Run focused tests and persistence round-trip.**

Run: `.venv/bin/python -m pytest tests/data/test_evm_logs.py tests/storage/test_repository.py -q && .venv/bin/ruff check app tests && .venv/bin/mypy app`

Expected: decoded events and existing repository tests pass with no static errors.

- [ ] **Step 5: Commit.**

```bash
git add app/data/events.py app/data/sources/evm_logs.py app/storage/repository.py tests/data/test_evm_logs.py tests/fixtures/evm_*.json
git commit -m "feat: decode verified evm pool events"
```

### Task 4: Implement cursors, RPC validation, and source fusion

**Files:**
- Create: `app/data/sources/evm_market.py`
- Create: `app/data/sources/fusion.py`
- Modify: `app/chains/evm.py`
- Test: `tests/data/test_evm_market.py`
- Test: `tests/data/test_fusion.py`

**Interfaces:**
- `EvmMarketCollector(adapter: EvmChainAdapter, max_log_block_span: int)`.
- `await EvmMarketCollector.collect(candidates: list[PoolCandidate]) -> list[MarketEvent]`.
- `MarketFusion.fuse(candidate: PoolCandidate, events: list[MarketEvent], now: datetime) -> FusionResult`.
- `FusionResult.events: list[MarketEvent]`, `FusionResult.status: ConnectorStatus`, `FusionResult.reasons: list[str]`.

- [ ] **Step 1: Write failing cursor, range, and conflict tests.**

```python
@pytest.mark.asyncio
async def test_collector_splits_large_gap_and_advances_only_after_success():
    collector = EvmMarketCollector(fake_rpc(latest_block=120), max_log_block_span=50)
    await collector.collect([bsc_candidate()])
    assert fake_rpc.calls == [(1, 50), (51, 100), (101, 120)]
    assert collector.cursor("bnb", bsc_candidate().pool_address) == 120


def test_fusion_blocks_api_rpc_pool_mismatch():
    result = MarketFusion().fuse(mismatched_candidate(), [], datetime.now(UTC))
    assert result.status == "degraded"
    assert "pool identity" in result.reasons[0]
```

- [ ] **Step 2: Run tests and verify they fail.**

Run: `.venv/bin/python -m pytest tests/data/test_evm_market.py tests/data/test_fusion.py -q`

Expected: import failures because cursor collection and fusion do not exist.

- [ ] **Step 3: Implement bounded collection and fusion.**

Add adapter methods for `get_code`, `get_logs`, `get_block_timestamp`, and chain validation. Initialize a new pool cursor at `latest_block - max_log_block_span + 1` so first collection is bounded. Query only supported topics and candidate pool addresses, decode logs, suppress duplicate source-event IDs, and advance a pool cursor only after the full range succeeds. Fusion must check network, lowercase addresses, candidate freshness, and event freshness before returning `ready`.

The fake RPC helper must expose `latest_block`, record `(from_block, to_block)` calls, return deterministic logs per range, and raise on a selected range. The collector test must assert that a failed range leaves the cursor at its previous value. The fusion helper must construct candidates with the same pool address for the passing case and distinct lowercase addresses for the conflict case.

- [ ] **Step 4: Run focused tests and static checks.**

Run: `.venv/bin/python -m pytest tests/data/test_evm_market.py tests/data/test_fusion.py -q && .venv/bin/ruff check app tests && .venv/bin/mypy app`

Expected: all focused tests pass and no static errors remain.

- [ ] **Step 5: Commit.**

```bash
git add app/data/sources/evm_market.py app/data/sources/fusion.py app/chains/evm.py tests/data/test_evm_market.py tests/data/test_fusion.py
git commit -m "feat: fuse api discovery with rpc market events"
```

### Task 5: Wire market sources into the paper runtime

**Files:**
- Modify: `app/main.py`
- Modify: `app/runtime.py`
- Modify: `app/data/collectors.py`
- Test: `tests/e2e/test_market_event_pipeline.py`

**Interfaces:**
- `build_market_source(settings: Settings, chain_name: str, repository: EventRepository) -> Collector`.
- `PaperRuntime` receives real market collectors instead of heartbeat-only sources.
- Existing `RuntimeReport` includes event counts and source health without changing paper/live mode semantics.

- [ ] **Step 1: Write the failing two-chain integration test.**

```python
@pytest.mark.asyncio
async def test_verified_market_events_reach_paper_runtime(tmp_path):
    runtime = runtime_with_fake_gecko_and_rpc(tmp_path, chains=("bnb", "robinhood"))
    report = await runtime.run_once()
    assert report.events_seen > 0
    assert set(report.health) == {"bnb", "robinhood"}
    assert all(health.status in {"ready", "observation_only"} for health in report.health.values())
```

- [ ] **Step 2: Run the integration test and verify it fails.**

Run: `.venv/bin/python -m pytest tests/e2e/test_market_event_pipeline.py -q`

Expected: the current main/runtime wiring reports zero events because it only runs RPC heartbeats.

- [ ] **Step 3: Replace heartbeat-only sources with fused market collectors.**

Build one `GeckoTerminalSource` and one `EvmMarketCollector` per configured chain. Cache discovery results at the configured interval while collecting bounded logs each runtime cycle. Route only fused events through the existing `Collector`, persist them, and preserve the `observation_only` status when no supported logs or security events are present. Do not alter `approval` or `auto` behavior.

The `runtime_with_fake_gecko_and_rpc` helper must inject one valid candidate and one decoded swap fixture per chain, use a temporary SQLite repository, and construct the existing `PaperRuntime` with a `PaperBroker`. The integration test must also assert that no `source_event_id` is persisted twice when the same block range is returned on consecutive cycles.

- [ ] **Step 4: Run the full paper integration tests.**

Run: `.venv/bin/python -m pytest tests/e2e/test_market_event_pipeline.py tests/e2e/test_paper_pipeline.py -q && .venv/bin/ruff check app tests && .venv/bin/mypy app`

Expected: fake events are persisted and paper decisions remain blocked when required security data is absent.

- [ ] **Step 5: Commit.**

```bash
git add app/main.py app/runtime.py app/data/collectors.py tests/e2e/test_market_event_pipeline.py
git commit -m "feat: wire live market events into paper runtime"
```

### Task 6: Add read-only smoke command and operational documentation

**Files:**
- Create: `app/data/sources/smoke.py`
- Modify: `README.md`
- Test: `tests/data/test_market_smoke.py`

**Interfaces:**
- `await run_market_smoke(settings: Settings) -> list[MarketSmokeResult]`.
- `MarketSmokeResult(chain: str, status: ConnectorStatus, chain_id: int | None, latest_block: int | None, discovered_pools: int, events: int, reasons: list[str], broadcasted: bool = False)`.
- CLI: `.venv/bin/python -m app.data.sources.smoke --chains bnb,robinhood`.

- [ ] **Step 1: Write failing smoke-output tests.**

```python
def test_smoke_result_never_reports_broadcasting():
    result = MarketSmokeResult(
        chain="bnb",
        status="ready",
        chain_id=56,
        latest_block=1,
        discovered_pools=1,
        events=2,
        reasons=[],
    )
    assert result.broadcasted is False
```

- [ ] **Step 2: Run the focused test and verify it fails.**

Run: `.venv/bin/python -m pytest tests/data/test_market_smoke.py -q`

Expected: import failure because the smoke result and command do not exist.

- [ ] **Step 3: Implement the read-only smoke command.**

Print chain ID, latest block, discovery count, decoded event count, source status, and reasons. Catch per-chain errors so one chain does not hide the other. Never construct a signer or call a transaction method.

- [ ] **Step 4: Document proxy setup, paper startup, and source limitations.**

Add commands for setting `MARKET_PROXY_URL`, running the smoke check, starting paper mode, and stopping it. State that `ready` market events still do not bypass token-security vetoes.

- [ ] **Step 5: Run release verification and commit.**

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check app tests
.venv/bin/mypy app
git diff --check
git add app/data/sources/smoke.py tests/data/test_market_smoke.py README.md
git commit -m "docs: add market source smoke checks"
```

### Task 7: Run the proxy-backed read-only smoke test and paper runtime

**Files:**
- No source changes unless a verified test exposes a defect.

- [ ] **Step 1: Verify configured connectors through the proxy.**

Run: `.venv/bin/python -m app.data.sources.smoke --chains bnb,robinhood`

Expected: chain IDs `56` and `4663`, discovered pool counts, event counts, and no broadcast/signing fields set to true.

- [ ] **Step 2: Start paper mode with five-second collection and reporting.**

Run: `MARKET_PROXY_URL=http://127.0.0.1:7890 .venv/bin/python -u -m app.main --mode paper --interval 5`

Expected: both chains are independently reported; valid events are persisted; invalid, stale, or security-incomplete candidates remain observation-only; no private key is loaded.

- [ ] **Step 3: Verify the persisted event stream.**

Run: `.venv/bin/python -m pytest tests/storage/test_repository.py tests/e2e/test_market_event_pipeline.py -q`

Expected: event round-trips and two-chain isolation pass.

- [ ] **Step 4: Final verification before completion.**

Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check app tests && .venv/bin/mypy app && git diff --check`

Expected: all tests pass, static checks are clean, and no uncommitted source changes remain except user-owned configuration.
