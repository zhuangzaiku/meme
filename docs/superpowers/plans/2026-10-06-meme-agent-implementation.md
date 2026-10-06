# Realtime Meme Strategy Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a realtime, paper-first Meme strategy agent for BNB Smart Chain and Robinhood Chain, with deterministic risk controls and gated approval/automatic live execution.

**Architecture:** Use one asynchronous Python service with independent EVM chain adapters, normalized events, a pure strategy/risk core, a realistic paper broker, and execution adapters for approval and auto modes. Chain data is authoritative; FOMO/GMGN-style wallet feeds are optional auxiliary inputs and never bypass safety or freshness checks.

**Tech Stack:** Python 3.12, `asyncio`, `web3.py`, Pydantic 2, SQLAlchemy 2 with SQLite WAL, FastAPI/WebSocket, `httpx`, macOS Keychain via `keyring`, pytest/pytest-asyncio, Ruff, and mypy.

## Global Constraints

- Target networks are BNB Smart Chain and Robinhood Chain; network metadata must be verified from an authoritative source before live use.
- The default execution mode is `paper`; live signing is disabled unless the mode is explicitly changed.
- BNB and Robinhood use separate hot wallets by default.
- Private keys never enter Git, logs, database rows, model prompts, or ordinary configuration files.
- Risk vetoes are deterministic and cannot be overridden by AI output.
- New positions are prohibited when required data is stale, conflicting, or unavailable.
- Averaging down is disabled.
- The live auto executor is implemented only after virtual validation and approval-mode testing.
- Every order, fill, decision, risk veto, mode change, and emergency action is auditable.
- Every task ends with focused tests and a commit.

---

## Phase 1: Foundation and Read-Only Chain Access

### Task 1: Scaffold the Python service and configuration

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `README.md`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Create: `configs/default.yaml`
- Create: `tests/test_config.py`

**Interfaces:**
- Produces `Settings` and `load_settings(path: Path | None = None) -> Settings`.
- Produces `Settings.execution_mode` with values `paper`, `approval`, or `auto`.
- Produces chain settings containing `name`, `chain_id`, `rpc_http`, `rpc_ws`, and `native_symbol`.

- [ ] **Step 1: Write the failing configuration tests**

```python
from pathlib import Path

from app.config import load_settings


def test_default_mode_is_paper(tmp_path: Path) -> None:
    settings = load_settings(tmp_path / "missing.yaml")
    assert settings.execution_mode == "paper"
    assert settings.risk.risk_per_trade == 0.0025


def test_chain_endpoints_are_loaded_from_environment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BNB_RPC_URL", "https://bnb.example")
    monkeypatch.setenv("ROBINHOOD_RPC_URL", "https://robinhood.example")
    settings = load_settings(tmp_path / "missing.yaml")
    assert settings.chains["bnb"].rpc_http == "https://bnb.example"
    assert settings.chains["robinhood"].rpc_http == "https://robinhood.example"


def test_invalid_mode_is_rejected(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("execution_mode: unsafe\n", encoding="utf-8")
    try:
        load_settings(config)
    except ValueError as exc:
        assert "execution_mode" in str(exc)
    else:
        raise AssertionError("invalid mode was accepted")
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `python3 -m pytest tests/test_config.py -q`

Expected: collection fails because `app.config` does not yet exist.

- [ ] **Step 3: Add the minimal package and configuration implementation**

`pyproject.toml` must declare Python `>=3.12,<3.13`, runtime dependencies for
Pydantic, PyYAML, SQLAlchemy, aiosqlite, web3, FastAPI, uvicorn, httpx, and
keyring, plus pytest, pytest-asyncio, Ruff, and mypy development dependencies.

`app/config.py` must define:

```python
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

ExecutionMode = Literal["paper", "approval", "auto"]


class RiskSettings(BaseModel):
    risk_per_trade: float = 0.0025
    max_position_percent: float = 0.03
    max_concurrent_positions: int = 5
    max_narrative_exposure: float = 0.08
    max_slippage_percent: float = 1.5
    daily_loss_limit: float = 0.015
    max_consecutive_losses: int = 3
    reserve_balance_percent: float = 20.0
    cooldown_after_exit_minutes: int = 30
    allow_averaging_down: bool = False


class ChainSettings(BaseModel):
    name: str
    chain_id: int
    rpc_http: str
    rpc_ws: str | None = None
    native_symbol: str


class Settings(BaseModel):
    execution_mode: ExecutionMode = "paper"
    risk: RiskSettings = Field(default_factory=RiskSettings)
    chains: dict[str, ChainSettings]
```

`load_settings` must merge `configs/default.yaml`, an optional requested YAML
file, and `BNB_RPC_URL`/`ROBINHOOD_RPC_URL` environment overrides. Missing RPC
URLs must be represented as unavailable connector configuration, not replaced
with invented endpoints.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `python3 -m pytest tests/test_config.py -q`

Expected: all three tests pass.

- [ ] **Step 5: Add repository hygiene and run static checks**

Run: `python3 -m ruff check app tests` and `git diff --check`

Expected: both commands exit with status 0.

- [ ] **Step 6: Commit the scaffold**

```bash
git add pyproject.toml .gitignore README.md app configs tests
git commit -m "feat: scaffold meme agent configuration"
```

### Task 2: Verify network metadata and define the chain adapter contract

**Files:**
- Create: `configs/networks.yaml`
- Create: `app/chains/base.py`
- Create: `app/chains/evm.py`
- Create: `app/chains/probe.py`
- Create: `tests/chains/test_probe.py`
- Create: `tests/chains/fakes.py`
- Modify: `app/config.py`

**Interfaces:**
- Produces `ChainAdapter` protocol methods: `get_latest_block`, `get_chain_id`, `get_balance`, `get_quote`, `simulate_swap`, `subscribe_events`.
- Produces `NetworkProbe(adapter).verify(expected_chain_id: int) -> ProbeResult`.
- Produces `ProbeResult(ok: bool, chain_id: int | None, errors: list[str])`.

- [ ] **Step 1: Write failing adapter and probe tests**

```python
import pytest

from app.chains.probe import NetworkProbe
from tests.chains.fakes import FakeAdapter


@pytest.mark.asyncio
async def test_probe_accepts_expected_chain_id() -> None:
    result = await NetworkProbe(FakeAdapter(chain_id=56)).verify(56)
    assert result.ok is True
    assert result.chain_id == 56


@pytest.mark.asyncio
async def test_probe_rejects_wrong_chain_id() -> None:
    result = await NetworkProbe(FakeAdapter(chain_id=56)).verify(999)
    assert result.ok is False
    assert "chain id" in result.errors[0].lower()
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `python3 -m pytest tests/chains/test_probe.py -q`

Expected: import failure because the adapter contract and probe do not exist.

- [ ] **Step 3: Implement the adapter contract and probe**

Define the adapter contract with typed methods:

```python
class ChainAdapter(Protocol):
    async def get_latest_block(self) -> int: ...
    async def get_chain_id(self) -> int: ...
    async def get_balance(self, address: str) -> int: ...
    async def get_quote(self, token: str, amount: int, side: str) -> Quote: ...
    async def simulate_swap(self, order: OrderIntent) -> SimulationResult: ...
    async def subscribe_events(self) -> AsyncIterator[ChainEvent]: ...
```

`EvmChainAdapter` must use an injected Web3 provider and never silently fall
back to an unverified chain. `NetworkProbe` must compare the provider chain ID
with the configured value and return a failure result on connection errors.

`configs/networks.yaml` must keep BNB and Robinhood metadata separate. The
Robinhood entry must be populated only after official documentation or a
working authoritative RPC probe confirms its chain ID and gas symbol.

- [ ] **Step 4: Run tests and a read-only probe**

Run: `python3 -m pytest tests/chains/test_probe.py -q`

Expected: all probe tests pass.

Run with configured endpoints: `python3 -m app.chains.probe --network bnb`

Expected: the command prints the observed chain ID and either `OK` or a
specific connection/metadata error; it never broadcasts a transaction.

- [ ] **Step 5: Commit the chain contract**

```bash
git add configs/networks.yaml app/chains app/config.py tests/chains
git commit -m "feat: add verified chain adapter contract"
```

### Task 3: Add persistent storage and normalized event schemas

**Files:**
- Create: `app/storage/models.py`
- Create: `app/storage/repository.py`
- Create: `app/data/events.py`
- Create: `app/data/freshness.py`
- Create: `tests/storage/test_repository.py`
- Create: `tests/data/test_freshness.py`

**Interfaces:**
- Produces Pydantic event models `PriceTick`, `Swap`, `LiquidityChange`, `HolderSnapshot`, `WalletBuy`, `WalletSell`, `DevTransfer`, `TokenSecurityUpdate`, and `SocialActivity`.
- Produces `EventRepository.save_event(event: MarketEvent) -> None` and `EventRepository.list_events(chain: str, token: str, limit: int) -> list[MarketEvent]`.
- Produces `FreshnessPolicy.is_fresh(kind: str, timestamp: datetime, now: datetime) -> bool`.

- [ ] **Step 1: Write failing tests for round-trip persistence and freshness**

```python
from datetime import datetime, timedelta, timezone

from app.data.events import PriceTick
from app.data.freshness import FreshnessPolicy


def test_quote_older_than_fifteen_seconds_is_stale() -> None:
    now = datetime.now(timezone.utc)
    policy = FreshnessPolicy()
    assert policy.is_fresh("quote", now - timedelta(seconds=16), now) is False


def test_price_tick_round_trips_through_repository(repository) -> None:
    event = PriceTick(chain="bnb", token="0x1", price=1.25, timestamp=datetime.now(timezone.utc))
    repository.save_event(event)
    assert repository.list_events("bnb", "0x1", 1)[0].price == 1.25
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `python3 -m pytest tests/storage/test_repository.py tests/data/test_freshness.py -q`

Expected: import or fixture failures because models, repository, and policy do
not exist.

- [ ] **Step 3: Implement schemas, SQLAlchemy models, and SQLite WAL repository**

Use UTC-aware timestamps, a `chain` field on every event, and JSON columns for
evidence payloads. Configure SQLite with WAL mode and foreign keys enabled.
Implement the freshness values exactly as specified:

```python
DEFAULT_MAX_AGE_SECONDS = {
    "quote": 15,
    "liquidity": 60,
    "holder_snapshot": 120,
    "security": 300,
    "social": 600,
}
```

Reject events with a naive timestamp at the model boundary.

- [ ] **Step 4: Run tests and verify they pass**

Run: `python3 -m pytest tests/storage/test_repository.py tests/data/test_freshness.py -q`

Expected: all focused tests pass.

- [ ] **Step 5: Commit normalized storage**

```bash
git add app/storage app/data tests/storage tests/data
git commit -m "feat: add normalized events and persistence"
```

---

## Phase 2: Market Data, Intelligence, and Deterministic Strategy

### Task 4: Implement realtime collectors and connector health

**Files:**
- Create: `app/data/collectors.py`
- Create: `app/data/connector_health.py`
- Create: `app/data/auxiliary_feed.py`
- Create: `tests/data/test_collectors.py`
- Create: `tests/data/test_connector_health.py`

**Interfaces:**
- Produces `Collector.run_once() -> list[MarketEvent]` and `Collector.stream() -> AsyncIterator[MarketEvent]`.
- Produces `ConnectorHealth(name, status, last_event_at, error)`.
- Produces `AuxiliaryFeed` for authorized FOMO/GMGN-style JSON events; unavailable feeds are marked `observation_only`.

- [ ] **Step 1: Write failing tests for event normalization and stale connectors**

```python
import pytest

from app.data.collectors import normalize_swap
from app.data.connector_health import ConnectorHealth


def test_swap_normalization_preserves_chain_and_token() -> None:
    event = normalize_swap({"chain": "bnb", "token": "0x1", "amount": "2.5"})
    assert event.chain == "bnb"
    assert event.token == "0x1"
    assert event.amount == 2.5


def test_connector_is_not_trade_ready_when_observation_only() -> None:
    health = ConnectorHealth(name="gmgn", status="observation_only")
    assert health.trade_ready is False
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `python3 -m pytest tests/data/test_collectors.py tests/data/test_connector_health.py -q`

Expected: import failure because collectors and health models do not exist.

- [ ] **Step 3: Implement collectors with explicit source status**

The collectors must support RPC polling and WebSocket streams when configured,
emit normalized events into `EventRepository`, and record connector health on
every successful or failed cycle. Auxiliary feeds accept only validated JSON
with source, timestamp, chain, token, wallet, and event type. No HTML scraping
is part of the implementation.

The collector must return an empty event list and a degraded health record on a
recoverable source error; it must not fabricate prices, holder counts, or wallet
labels.

- [ ] **Step 4: Run tests and a disconnected-source check**

Run: `python3 -m pytest tests/data/test_collectors.py tests/data/test_connector_health.py -q`

Expected: all focused tests pass.

Run: `python3 -m app.main --mode paper --check-connectors`

Expected: each unavailable source is reported as `unavailable` or
`observation_only`; the process does not place an order.

- [ ] **Step 5: Commit collectors**

```bash
git add app/data tests/data
git commit -m "feat: collect normalized realtime market events"
```

### Task 5: Implement wallet graph, token risk, scoring, and AI evidence boundary

**Files:**
- Create: `app/intelligence/wallet_graph.py`
- Create: `app/intelligence/token_risk.py`
- Create: `app/intelligence/scoring.py`
- Create: `app/intelligence/narrative.py`
- Create: `tests/intelligence/test_wallet_graph.py`
- Create: `tests/intelligence/test_scoring.py`
- Create: `tests/intelligence/test_vetoes.py`

**Interfaces:**
- Produces `WalletGraph.are_independent(wallets: list[WalletSnapshot]) -> bool`.
- Produces `TokenRisk.evaluate(snapshot: TokenRiskSnapshot) -> RiskDecision`.
- Produces `score_candidate(candidate: CandidateSnapshot) -> ScoreResult`.
- Produces `NarrativeAnalyzer.summarize(events) -> NarrativeEvidence` with no order authority.

- [ ] **Step 1: Write failing tests for wallet independence, vetoes, and scoring**

```python
def test_funded_by_same_source_wallets_are_not_independent(wallet_graph, snapshots):
    assert wallet_graph.are_independent(snapshots.same_funder_group) is False


def test_dev_distribution_is_a_hard_veto(token_risk, risky_snapshot):
    decision = token_risk.evaluate(risky_snapshot)
    assert decision.action == "BLOCK"
    assert "dev" in decision.reasons[0].lower()


def test_candidate_needs_three_independent_wallets(candidate):
    result = score_candidate(candidate.with_independent_wallets(2))
    assert result.action == "WATCH"
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `python3 -m pytest tests/intelligence -q`

Expected: import failures because the intelligence modules do not exist.

- [ ] **Step 3: Implement deterministic intelligence rules**

Implement the approved weights exactly:

```python
WEIGHTS = {
    "wallet_quality": 25,
    "contract_distribution": 30,
    "capital_flow": 25,
    "narrative_social": 10,
    "market_position": 10,
}
```

Implement hard vetoes for risky permissions, honeypot indicators, Dev/related
selling, LP removal, extreme concentration, coordinated wallets, excessive
slippage, stale/conflicting data, and risk-limit activation. The narrative
module returns evidence and uncertainty only; its result cannot change a veto,
score threshold, position size, or exit.

- [ ] **Step 4: Run tests and verify they pass**

Run: `python3 -m pytest tests/intelligence -q`

Expected: all intelligence tests pass, including tests proving that narrative
output cannot turn `BLOCK` into `ARMED`.

- [ ] **Step 5: Commit intelligence**

```bash
git add app/intelligence tests/intelligence
git commit -m "feat: add wallet risk and candidate scoring"
```

### Task 6: Implement the strategy state machine

**Files:**
- Create: `app/strategy/signals.py`
- Create: `app/strategy/rules.py`
- Create: `app/strategy/state_machine.py`
- Create: `tests/strategy/test_state_machine.py`
- Create: `tests/strategy/test_trade_shapes.py`

**Interfaces:**
- Produces `StrategyState` values `WATCH`, `ARMED`, `PROBE`, `CONFIRMED`, `HOLD`, `REDUCE`, `EXIT`, `BLOCK`, and `PAUSE`.
- Produces `StrategyEngine.evaluate(snapshot: StrategySnapshot) -> Decision`.
- Produces `Decision(action, state, score, evidence, vetoes, expiry)`.

- [ ] **Step 1: Write failing transition tests**

```python
def test_three_independent_wallets_and_two_confirmations_arm(candidate):
    decision = StrategyEngine().evaluate(candidate.armed_snapshot())
    assert decision.state == "ARMED"
    assert decision.action == "BUY_PROBE"


def test_stale_quote_blocks_new_position(candidate):
    decision = StrategyEngine().evaluate(candidate.with_stale_quote())
    assert decision.state == "BLOCK"
    assert decision.action == "BLOCK"


def test_vertical_pump_is_not_a_trade_shape(candidate):
    decision = StrategyEngine().evaluate(candidate.vertical_pump())
    assert decision.action == "WATCH"
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `python3 -m pytest tests/strategy -q`

Expected: import failures because the strategy modules do not exist.

- [ ] **Step 3: Implement pure transitions and staged entries**

Implement only these trade shapes: early convergence, migration pullback, and
second-leg restart. Require a passed risk decision, score at least 75 for a
probe, three independent high-quality wallets, and two live confirmations.
Return probe/confirmation sizing as 30%, 30%, and maximum 40% of the target
position. Do not mutate storage inside the pure transition function.

- [ ] **Step 4: Run tests and verify they pass**

Run: `python3 -m pytest tests/strategy -q`

Expected: all transition and trade-shape tests pass.

- [ ] **Step 5: Commit the strategy state machine**

```bash
git add app/strategy tests/strategy
git commit -m "feat: add deterministic meme strategy state machine"
```

---

## Phase 3: Paper Trading and Validation

### Task 7: Implement independent risk engine and paper broker

**Files:**
- Create: `app/risk/limits.py`
- Create: `app/risk/position_sizing.py`
- Create: `app/risk/circuit_breaker.py`
- Create: `app/execution/orders.py`
- Create: `app/execution/paper_broker.py`
- Create: `tests/risk/test_limits.py`
- Create: `tests/risk/test_circuit_breaker.py`
- Create: `tests/execution/test_paper_broker.py`

**Interfaces:**
- Produces `RiskEngine.check(order, account, market) -> RiskDecision`.
- Produces `PositionSizer.size(account_equity, entry, invalidation, costs) -> SizeResult`.
- Produces `CircuitBreaker.record(result)` and `CircuitBreaker.status() -> CircuitStatus`.
- Produces `PaperBroker.submit(order) -> OrderResult`, `positions()`, and `equity()`.

- [ ] **Step 1: Write failing risk and fill tests**

```python
def test_daily_loss_limit_blocks_new_entries(risk_engine, account_at_daily_limit, order):
    decision = risk_engine.check(order, account_at_daily_limit, order.market)
    assert decision.allowed is False
    assert decision.code == "daily_loss_limit"


def test_paper_fill_includes_slippage_and_gas(paper_broker, quote, order):
    result = paper_broker.submit(order)
    assert result.fill_price != quote.mid_price
    assert result.fees.total > 0


def test_three_consecutive_losses_pause_trading(circuit_breaker):
    for _ in range(3):
        circuit_breaker.record("loss")
    assert circuit_breaker.status().paused is True
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `python3 -m pytest tests/risk tests/execution/test_paper_broker.py -q`

Expected: import failures because risk and paper execution modules do not exist.

- [ ] **Step 3: Implement risk limits and realistic paper fills**

Enforce the approved defaults: 0.25% risk per trade, 3% maximum position,
five concurrent positions, 8% narrative exposure, 1.5% maximum slippage, 1.5%
daily loss, three consecutive losses, 20% reserve balance, 30-minute cooldown,
and no averaging down.

The paper broker must use the quote, pool depth, direction, configured delay,
gas, and fee model. It must model rejected fills when the quote is stale or
slippage exceeds the limit. It must write orders, fills, positions, and risk
events to the repository.

- [ ] **Step 4: Run tests and verify they pass**

Run: `python3 -m pytest tests/risk tests/execution/test_paper_broker.py -q`

Expected: all focused tests pass.

- [ ] **Step 5: Commit paper execution and risk controls**

```bash
git add app/risk app/execution tests/risk tests/execution
git commit -m "feat: add paper broker and independent risk controls"
```

### Task 8: Add replay harness, metrics, and virtual validation gate

**Files:**
- Create: `app/replay/runner.py`
- Create: `app/replay/metrics.py`
- Create: `app/replay/fixtures.py`
- Create: `tests/replay/test_metrics.py`
- Create: `tests/replay/test_validation_gate.py`
- Create: `scripts/run_paper_validation.py`

**Interfaces:**
- Produces `ReplayRunner.run(events, broker) -> ReplayResult`.
- Produces `calculate_metrics(fills, equity) -> PerformanceMetrics`.
- Produces `ValidationGate.evaluate(metrics) -> ValidationResult`.

- [ ] **Step 1: Write failing metric and gate tests**

```python
def test_metrics_include_costs_and_max_drawdown(sample_fills):
    metrics = calculate_metrics(sample_fills, sample_fills.equity_curve)
    assert metrics.net_pnl == metrics.gross_pnl - metrics.total_costs
    assert metrics.max_drawdown >= 0


def test_validation_gate_requires_one_hundred_virtual_trades(metrics):
    result = ValidationGate().evaluate(metrics.with_trade_count(99))
    assert result.approved_for_live is False
    assert "100" in result.reasons[0]
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `python3 -m pytest tests/replay -q`

Expected: import failures because replay and metric modules do not exist.

- [ ] **Step 3: Implement replay and validation metrics**

Calculate trade count, win rate, gross/net PnL, average win/loss, expectancy,
profit factor, maximum drawdown, maximum consecutive losses, fees, gas,
slippage, and per-chain/per-shape breakdowns. The validation gate must require
at least 100 virtual trades, positive net expectancy after costs, an in-range
drawdown, and passing circuit-breaker tests before it can approve live mode.

- [ ] **Step 4: Run tests and generate a paper report**

Run: `python3 -m pytest tests/replay -q`

Expected: all focused tests pass.

Run: `python3 scripts/run_paper_validation.py --chains bnb,robinhood --trades 100`

Expected: a report with per-chain and per-strategy metrics and an explicit
`approved_for_live: false|true` result. The command must not load a private key.

- [ ] **Step 5: Commit the validation harness**

```bash
git add app/replay scripts/run_paper_validation.py tests/replay
git commit -m "feat: add paper replay and validation gate"
```

---

## Phase 4: Controls, Approval Signing, and Gated Automatic Execution

### Task 9: Add FastAPI controls, realtime status, and audit logging

**Files:**
- Create: `app/api/routes.py`
- Create: `app/api/websocket.py`
- Create: `app/api/audit.py`
- Create: `app/main.py`
- Create: `tests/api/test_controls.py`

**Interfaces:**
- Provides `GET /health`, `/status`, `/positions`, `/orders`, and `/signals`.
- Provides `POST /orders`, `/execution-mode`, `/pause`, `/resume`, `/orders/{id}/approve`, and `/positions/{id}/exit`.
- Provides `WS /events`.

- [ ] **Step 1: Write failing control tests**

```python
def test_server_starts_in_paper_mode(client):
    response = client.get("/status")
    assert response.status_code == 200
    assert response.json()["execution_mode"] == "paper"


def test_auto_mode_requires_validation_gate(client):
    response = client.post("/execution-mode", json={"mode": "auto"})
    assert response.status_code == 409


def test_pause_blocks_new_orders(client):
    client.post("/pause")
    response = client.post("/orders", json={"token": "0x1", "side": "buy"})
    assert response.status_code == 423
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `python3 -m pytest tests/api/test_controls.py -q`

Expected: import or route failures because the API does not exist.

- [ ] **Step 3: Implement controls and audit records**

Make `paper` the process default. Require a passed `ValidationGate` result and
an explicit confirmation token before `auto`. Ensure pause is idempotent,
blocks new orders and adds, and still allows an explicit exit. Log every mode
change, approval, rejection, pause, resume, and forced exit without sensitive
wallet material.

- [ ] **Step 4: Run tests and verify they pass**

Run: `python3 -m pytest tests/api/test_controls.py -q`

Expected: all control tests pass.

- [ ] **Step 5: Commit the controls layer**

```bash
git add app/api app/main.py tests/api
git commit -m "feat: add realtime controls and audit logging"
```

### Task 10: Implement Keychain-backed approval execution

**Files:**
- Create: `app/execution/wallet.py`
- Create: `app/execution/approval_executor.py`
- Create: `tests/execution/test_wallet.py`
- Create: `tests/execution/test_approval_executor.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces `WalletManager.load_signer(chain: str, mode: ExecutionMode) -> Signer | None`.
- Produces `ApprovalExecutor.prepare(order) -> ApprovalRequest`.
- Produces `ApprovalExecutor.approve(request_id) -> BroadcastResult`.

- [ ] **Step 1: Write failing secret and approval tests**

```python
def test_paper_mode_does_not_load_signer(wallet_manager):
    assert wallet_manager.load_signer("bnb", "paper") is None


def test_approval_request_contains_cost_and_risk_fields(approval_executor, order):
    request = approval_executor.prepare(order)
    assert request.chain == order.chain
    assert request.max_slippage_percent is not None
    assert request.risk_decision.allowed is True
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `python3 -m pytest tests/execution/test_wallet.py tests/execution/test_approval_executor.py -q`

Expected: import failures because wallet and approval modules do not exist.

- [ ] **Step 3: Implement Keychain-backed loading and approval flow**

Use separate Keychain service names for `meme-agent/bnb` and
`meme-agent/robinhood`. Refuse to load secrets in paper mode. In approval mode,
render a request containing chain, token, side, amount, quote, maximum slippage,
estimated gas, score, evidence, vetoes, and expiry. Re-run the risk check at
approval time and reject expired, changed, or newly unsafe requests.

Never store the private key in a Pydantic settings object, database record,
exception, log line, or test fixture.

- [ ] **Step 4: Run tests and perform a no-secret smoke test**

Run: `python3 -m pytest tests/execution/test_wallet.py tests/execution/test_approval_executor.py -q`

Expected: all focused tests pass.

Run: `python3 -m app.main --mode approval --dry-run`

Expected: an approval request is generated without broadcasting or requiring a
private key.

- [ ] **Step 5: Commit approval execution**

```bash
git add app/execution/wallet.py app/execution/approval_executor.py tests/execution .gitignore
git commit -m "feat: add keychain-backed approval execution"
```

### Task 11: Implement gated automatic execution and emergency stop

**Files:**
- Create: `app/execution/auto_executor.py`
- Create: `app/execution/transaction_guard.py`
- Create: `tests/execution/test_auto_executor.py`
- Create: `tests/execution/test_transaction_guard.py`

**Interfaces:**
- Produces `AutoExecutor.execute(order, simulation: SimulationResult | None = None, breaker: CircuitBreaker | None = None) -> BroadcastResult`.
- Produces `TransactionGuard.validate(order, simulation) -> GuardDecision`.
- Requires `ValidationGate` approval and `CircuitBreaker` not paused.

- [ ] **Step 1: Write failing guard tests**

```python
def test_auto_executor_rejects_without_validation_gate(auto_executor, order):
    result = auto_executor.execute(order)
    assert result.status == "rejected"
    assert result.code == "validation_gate_required"


def test_auto_executor_rejects_excessive_slippage(auto_executor, order, bad_simulation):
    result = auto_executor.execute(order, simulation=bad_simulation)
    assert result.status == "rejected"
    assert result.code == "slippage_limit"


def test_pause_prevents_broadcast(auto_executor, order, paused_breaker):
    result = auto_executor.execute(order, breaker=paused_breaker)
    assert result.status == "rejected"
    assert result.code == "paused"
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `python3 -m pytest tests/execution/test_auto_executor.py tests/execution/test_transaction_guard.py -q`

Expected: import failures because the automatic executor and guard do not exist.

- [ ] **Step 3: Implement the final execution gate**

Before loading the signer or broadcasting, require all of the following:

```text
execution mode == auto
validation gate approved
risk engine allowed
circuit breaker not paused
quote and security data fresh
simulation succeeds
slippage within limit
gas within configured limit
position and narrative exposure within limits
balance reserve remains intact
```

Simulate the transaction, re-check the order hash and target chain ID, sign with
the chain-specific Keychain signer, broadcast, wait for confirmation, and
record the receipt. Any failed preflight returns a typed rejection and never
calls the signer.

- [ ] **Step 4: Run tests and an explicitly disabled live smoke test**

Run: `python3 -m pytest tests/execution/test_auto_executor.py tests/execution/test_transaction_guard.py -q`

Expected: all focused tests pass.

Run: `python3 -m app.main --mode auto --dry-run`

Expected: the process refuses to broadcast because dry-run has no live
confirmation and writes a safe rejection to the audit log.

- [ ] **Step 5: Commit automatic execution**

```bash
git add app/execution/auto_executor.py app/execution/transaction_guard.py tests/execution
git commit -m "feat: gate automatic execution with transaction checks"
```

---

## Final System Verification

### Task 12: Run end-to-end paper validation and release checks

**Files:**
- Create: `tests/e2e/test_paper_pipeline.py`
- Modify: `README.md`

- [ ] **Step 1: Add the end-to-end paper test**

Test this sequence with fake BNB and Robinhood adapters:

```text
market events -> normalized events -> candidate score -> ARMED
-> BUY_PROBE -> paper fill -> CONFIRMED -> simulated stop/target
-> REDUCE or EXIT -> persisted PnL and audit record
```

Assert that both chains remain isolated, a stale event blocks entry, a hard
veto blocks entry, and a pause blocks new orders while allowing an exit.

- [ ] **Step 2: Run the complete test suite**

Run: `python3 -m pytest -q`

Expected: all tests pass.

- [ ] **Step 3: Run static checks and package checks**

Run: `python3 -m ruff check app tests scripts`

Expected: no lint errors.

Run: `python3 -m mypy app`

Expected: no type errors for the configured strictness level.

- [ ] **Step 4: Run the two-chain paper process**

Run: `python3 -m app.main --mode paper --chains bnb,robinhood`

Expected: the service starts, reports connector health, never loads a private
key, and records paper decisions and fills only when data is valid.

- [ ] **Step 5: Verify live gates without broadcasting**

Run: `python3 scripts/run_paper_validation.py --chains bnb,robinhood --trades 100`

Expected: the validation report includes net costs, drawdown, expectancy,
per-chain results, and the live eligibility decision.

Run: `python3 -m app.main --mode approval --dry-run`

Expected: approval payloads can be generated but no transaction is broadcast.

Run: `python3 -m app.main --mode auto --dry-run`

Expected: automatic execution is rejected by the dry-run guard.

- [ ] **Step 6: Commit the verified release state**

```bash
git add app tests scripts README.md
git commit -m "test: verify paper-first meme agent pipeline"
```

## Handoff and Execution Choice

Plan complete and saved to `docs/superpowers/plans/2026-10-06-meme-agent-implementation.md`.

Two execution options:

1. **Subagent-Driven** (recommended): dispatch a fresh worker per task and review between tasks.
2. **Inline Execution**: execute the plan in this session with checkpoints.

Do not enable automatic live execution until the final validation gate passes
and approval-mode signing has been tested without exposing private-key material.
