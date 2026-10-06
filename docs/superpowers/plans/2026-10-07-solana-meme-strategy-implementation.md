# Solana Meme Strategy Implementation Plan

> For agentic workers: use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

Goal: Add a paper-only Solana meme lane using https://api.mainnet.solana.com while preserving independent BNB and Robinhood scheduling and existing risk gates.

Architecture: Generalize PoolCandidate for EVM and Solana Base58 addresses. Add a proxy-aware Solana JSON-RPC adapter and a candidate-driven collector that validates pool/mint accounts, consumes incremental signatures, and emits normalized events. Register Solana as a third collector in PaperRuntime; do not change signer or live broadcast behavior.

Tech Stack: Python 3.12, Pydantic 2, httpx, pytest/pytest-asyncio, existing GeckoTerminal source, PaperRuntime, and PaperBroker.

## Global Constraints

- Default execution mode remains paper.
- Solana RPC is https://api.mainnet.solana.com, overridable with SOLANA_RPC_URL.
- All HTTP/RPC requests use http://127.0.0.1:7890 by default.
- Solana uses confirmed commitment, a 10-second poll interval, and a 20-second collection timeout.
- Maximum Solana candidates per cycle is 3; maximum new signatures per pool per cycle is 20.
- Unknown transaction formats are observation-only and never become guessed swaps.
- Never read, write, stage, or commit wallet private keys, env/, .env, or secret values.
- Every task follows TDD: failing test, observed failure, minimal implementation, focused green run, regression run, commit.

## File Map

- Modify app/data/sources/models.py, app/data/sources/composite_discovery.py, app/config.py, configs/default.yaml, and configs/networks.yaml.
- Create app/chains/solana.py and app/data/sources/solana_market.py.
- Modify app/data/sources/geckoterminal.py, app/main.py, and README.md.
- Modify existing model/config/e2e tests and create tests/chains/test_solana.py, tests/data/test_solana_market.py, and tests/fixtures/geckoterminal_solana_pools.json.

### Task 1: Cross-chain Candidate Model and Configuration

Files:
- Modify: app/data/sources/models.py
- Modify: app/data/sources/composite_discovery.py
- Modify: app/config.py
- Modify: configs/default.yaml
- Modify: configs/networks.yaml
- Test: tests/data/test_source_models.py
- Test: tests/data/test_composite_discovery.py
- Test: tests/test_config.py

Interfaces:
- PoolCandidate(chain="sol", ...) accepts strict 32-byte Solana Base58 public keys and preserves case.
- BNB and Robinhood retain lower-cased EVM validation.
- ChainSettings.rpc_kind is "evm" by default and "solana" for sol.
- settings.chains["sol"] defaults to the public RPC and honors SOLANA_RPC_URL.

- [ ] Step 1: Write failing tests.

Add valid and invalid Solana address cases. The valid case uses:
    pool_address="So11111111111111111111111111111111111111112"
    base_token="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
The invalid case asserts ValueError with "Solana". Add a composite-discovery test with one BNB and one Solana candidate and assert their private candidate keys differ because the deduplication key is (chain, pool_address); assert both survive the merge. Add config assertions for sol, its 10/20-second settings, and a SOLANA_RPC_URL override.

- [ ] Step 2: Run the focused tests and observe the intended failure.

    .venv/bin/python -m pytest -q tests/data/test_source_models.py tests/data/test_composite_discovery.py tests/test_config.py

Expected: Solana addresses fail EVM validation and settings.chains["sol"] is missing; existing EVM tests remain green.

- [ ] Step 3: Implement the minimum change.

In app/data/sources/models.py, add a strict Base58 decoder requiring exactly 32 decoded bytes and a chain-aware model validator. Do not lowercase Solana addresses. Keep Web3.is_address and lowercasing for non-Solana chains.

In app/data/sources/composite_discovery.py, use this key helper:

~~~python
def _candidate_key(candidate: PoolCandidate) -> tuple[str, str]:
    address = candidate.pool_address if candidate.chain == "sol" else candidate.pool_address.lower()
    return candidate.chain, address
~~~

In app/config.py, add RpcKind = Literal["evm", "solana"], ChainSettings.rpc_kind = "evm", a sol per-chain market default, and the SOLANA_RPC_URL override.

Add sol to both YAML files. The registry entry contains name Solana Mainnet, chain_id null, native_symbol SOL, rpc_kind solana, and literal rpc_env https://api.mainnet.solana.com.

- [ ] Step 4: Run focused and regression tests.

    .venv/bin/python -m pytest -q tests/data/test_source_models.py tests/data/test_composite_discovery.py tests/test_config.py

Expected: all selected tests pass, including existing EVM normalization.

- [ ] Step 5: Commit.

    git add app/data/sources/models.py app/data/sources/composite_discovery.py app/config.py configs/default.yaml configs/networks.yaml tests/data/test_source_models.py tests/data/test_composite_discovery.py tests/test_config.py
    git commit -m "feat: add solana chain configuration"

### Task 2: Proxy-aware Solana JSON-RPC Adapter

Files:
- Create: app/chains/solana.py
- Create: tests/chains/test_solana.py

Interfaces:
- SolanaSignature(signature: str, slot: int, block_time: datetime | None).
- SolanaRpc.get_account_info(address), get_signatures_for_address(address, limit, until), and get_transaction(signature).
- SolanaRpcAdapter(rpc_http, proxy_url, timeout_seconds, max_retries, commitment="confirmed", transport=None).

- [ ] Step 1: Write failing tests.

Use httpx.MockTransport to assert exact JSON-RPC request shapes:

~~~python
getAccountInfo = [address, {"encoding": "jsonParsed", "commitment": "confirmed"}]
getSignaturesForAddress = [address, {"limit": 20, "commitment": "confirmed"}]
getTransaction = [signature, {
    "encoding": "jsonParsed",
    "commitment": "confirmed",
    "maxSupportedTransactionVersion": 0,
}]
~~~

Assert that a 429 followed by a 200 retries once, parses signature, slot, and UTC block_time, and that an RPC error object raises ConnectionError. Inject the transport so no public network is used.

- [ ] Step 2: Run the focused test and observe the intended failure.

    .venv/bin/python -m pytest -q tests/chains/test_solana.py

Expected: import failure because app.chains.solana does not exist.

- [ ] Step 3: Implement the minimum adapter.

Implement _request(method, params) with httpx.AsyncClient(timeout=..., proxy=proxy_url, transport=transport). Retry timeouts, transport errors, HTTP 429, and HTTP 5xx up to max_retries; validate the JSON-RPC envelope and reject RPC error objects and malformed results.

Send getAccountInfo with jsonParsed; send getSignaturesForAddress with limit, commitment, and optional until; send getTransaction with jsonParsed, confirmed, and maxSupportedTransactionVersion: 0. Convert non-null blockTime to datetime.fromtimestamp(value, UTC).

- [ ] Step 4: Run focused and adapter regression tests.

    .venv/bin/python -m pytest -q tests/chains/test_solana.py tests/chains/test_probe.py

Expected: all selected tests pass.

- [ ] Step 5: Commit.

    git add app/chains/solana.py tests/chains/test_solana.py
    git commit -m "feat: add solana rpc adapter"

### Task 3: Solana Discovery Normalization and Verified Market Events

Files:
- Modify: app/data/sources/geckoterminal.py
- Create: app/data/sources/solana_market.py
- Modify: tests/data/test_geckoterminal.py
- Create: tests/data/test_solana_market.py
- Create: tests/fixtures/geckoterminal_solana_pools.json

Interfaces:
- SolanaMarketCollector(rpc, max_pools=3, max_signatures_per_pool=20) implements MarketCollector.collect.
- The collector depends on the SolanaRpc protocol from app.chains.solana, so tests can inject a deterministic fake without HTTP.
- cursor(chain, pool_address) -> str | None exposes the high-water signature.
- All emitted Solana events use chain="sol", Base58 addresses, and stable source_event_id values.

- [ ] Step 1: Write failing tests.

Add a GeckoTerminal fixture using solana_<address> relationship IDs. Assert the parser returns chain == "sol", network_id == "solana", dex_id == "raydium", and the numeric price.

Create a fake RPC and a parsed transaction with one signer and a positive signer-owned base-token balance delta. Assert the collector emits PriceTick, LiquidityChange, a passing TokenSecurityUpdate, and one Swap(side="buy") with the signer wallet. Add cases for negative delta -> sell, active freeze authority -> failed security, unknown direction -> no swap, duplicate signature -> one swap, and transaction RPC failure -> no cursor advancement.

- [ ] Step 2: Run focused tests and observe the intended failure.

    .venv/bin/python -m pytest -q tests/data/test_geckoterminal.py tests/data/test_solana_market.py

Expected: solana maps to the wrong internal chain and SolanaMarketCollector is missing.

- [ ] Step 3: Implement the minimum collector.

In GeckoTerminalSource, map bsc -> bnb, solana -> sol, and preserve other network IDs.

In solana_market.py, for each of the first three candidates:
1. Call get_account_info(pool_address); skip a missing account.
2. Call get_signatures_for_address(pool_address, limit=20, until=cursor).
3. Fetch every returned transaction; on any transport/shape failure, discard that candidate batch and leave cursor/seen state unchanged.
4. Find the first signer in message.accountKeys. Compare signer-owned preTokenBalances and postTokenBalances for candidate.base_token; positive delta is buy, negative delta is sell, and zero/ambiguous delta is skipped.
5. Emit Swap with amount=abs(delta), price=candidate.price_usd, and source_event_id=f"solana:{signature}".
6. Emit one PriceTick when price_usd exists and one LiquidityChange when reserve_usd exists, only after pool validation.
7. Read the base mint account. Emit passed security only when both mintAuthority and freezeAuthority are None; otherwise emit failed security with the relevant indicators.
8. After the complete batch succeeds, update the cursor to the newest signature and add signatures to the seen set.

Route only the explicitly supported DEX identifiers containing raydium, meteora, orca, or pump in the candidate dex_id through the known transaction-shape parser. Unknown DEX identifiers or transaction shapes may provide context events but never guessed swaps. Return events in timestamp order.

- [ ] Step 4: Run focused collector and fusion regressions.

    .venv/bin/python -m pytest -q tests/data/test_geckoterminal.py tests/data/test_solana_market.py tests/data/test_freshness.py tests/data/test_fusion.py

Expected: all selected tests pass.

- [ ] Step 5: Commit.

    git add app/data/sources/geckoterminal.py app/data/sources/solana_market.py tests/data/test_geckoterminal.py tests/data/test_solana_market.py tests/fixtures/geckoterminal_solana_pools.json
    git commit -m "feat: parse verified solana meme events"

### Task 4: Runtime Wiring and Three-chain Scheduling

Files:
- Modify: app/main.py
- Modify: tests/e2e/test_market_event_pipeline.py

Interfaces:
- build_market_source(settings, "sol", repository) returns a Solana-backed Collector.
- run_paper includes Solana's configured interval and timeout.
- --check-connectors reports Solana configured when its RPC exists, despite chain_id being None.

- [ ] Step 1: Write failing wiring tests.

Add a build_market_source(..., "sol", ...) test asserting source name sol, a scheduler test with BNB, Robinhood, and Solana at distinct intervals, and a failure-isolation test that makes only Solana raise and asserts BNB remains observation_only while Solana is degraded.

- [ ] Step 2: Run the focused tests and observe the intended failure.

    .venv/bin/python -m pytest -q tests/e2e/test_market_event_pipeline.py

Expected: sol currently enters the EVM branch or becomes unavailable because it has no numeric chain ID.

- [ ] Step 3: Implement the runtime branch.

Import SolanaRpcAdapter and SolanaMarketCollector. Use this connector condition:

~~~python
configured = bool(chain.rpc_http) and (
    chain.rpc_kind == "solana" or chain.chain_id is not None
)
~~~

Before the EVM branch in app/main.py, construct GeckoTerminalSource("solana", ...), SolanaRpcAdapter(..., timeout_seconds=20), and SolanaMarketCollector(max_pools=3, max_signatures_per_pool=20); wrap them with LiveMarketSource(..., MarketFusion()) and Collector("sol", ...).

Do not change BSC native discovery, GeckoTerminal fallback, GMGN enrichment, or the EVM adapter path. The existing scheduler includes sol because it is in settings.chains.

- [ ] Step 4: Run runtime and e2e tests.

    .venv/bin/python -m pytest -q tests/e2e/test_market_event_pipeline.py tests/e2e/test_paper_pipeline.py tests/api/test_controls.py

Expected: BNB and Robinhood regressions pass, Solana failure is isolated, and no signer is loaded.

- [ ] Step 5: Commit.

    git add app/main.py tests/e2e/test_market_event_pipeline.py
    git commit -m "feat: schedule solana paper market lane"

### Task 5: Documentation and Full Verification

Files:
- Modify: README.md

- [ ] Step 1: Write the documentation check.

    rg -n "Solana|SOLANA_RPC_URL|three-chain" README.md

Expected: current README has no complete Solana runtime instructions.

- [ ] Step 2: Update the README.

Document BNB, Robinhood, and Solana paper mode; SOLANA_RPC_URL; the public default RPC; proxy use; confirmed commitment; 10-second polling; 20-second timeout; candidate-driven signature polling; observation-only behavior for unknown transaction formats; and the existing no-private-key/live-broadcast restrictions.

- [ ] Step 3: Run the full verification suite.

    .venv/bin/python -m pytest -q
    .venv/bin/python -m ruff check app tests
    .venv/bin/python -m mypy app
    git diff --check

Expected: pytest has zero failures, Ruff exits 0, mypy exits 0, and git diff --check is silent.

- [ ] Step 4: Verify three-chain configuration and repository safety.

    .venv/bin/python -m app.main --check-connectors
    git status --short
    git diff --stat HEAD

Expected: connector output includes sol; no private key is loaded or transaction broadcast; env/ remains untracked and unstaged.

- [ ] Step 5: Commit the documentation.

    git add README.md
    git commit -m "docs: document three-chain meme runtime"
    git status --short --branch
    git log -6 --oneline --decorate

The final report must cite fresh pytest, Ruff, mypy, and diff-check results and state that live execution remains disabled.
