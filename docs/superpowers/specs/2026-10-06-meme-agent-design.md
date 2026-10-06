# Realtime Meme Strategy Agent Design

Date: 2026-10-06
Status: Approved design

## Objective

Build a realtime Meme strategy agent for BNB Smart Chain and Robinhood Chain.
The system uses FOMO/GMGN-style wallet and token signals where available, but
uses chain data as the source of truth for executable decisions. It starts in
an automatically trading virtual account and later supports two live modes:

- `approval`: the agent prepares a transaction and a human approves it before signing.
- `auto`: a guarded hot wallet signs and broadcasts automatically.

The system must optimize for repeatable risk-adjusted execution, not claim or
assume a guaranteed win rate.

## Evidence, assumptions, and unknowns

Observed requirements:

- Target networks are BNB Smart Chain and Robinhood Chain.
- Virtual trading should automatically buy and sell to validate the strategy.
- Live execution must be switchable between human approval and automatic execution.
- Live signing uses an independent hot-wallet private key.
- The selected architecture is a hybrid: one core service with independent
  chain adapters, risk boundaries, and execution boundaries.

Assumptions:

- Both target networks expose EVM-compatible RPC and transaction interfaces.
- The initial deployment is local on macOS and is primarily a single-user system.
- FOMO and GMGN data may be auxiliary inputs rather than guaranteed public APIs.

Unknowns to verify before implementation:

- Robinhood Chain official RPC, chain ID, gas token, explorer, DEX ecosystem,
  and supported public data interfaces.
- Stable, authorized FOMO and GMGN interfaces or export formats.
- Available DEX routing and quote APIs on each target network.

If any data source cannot be verified, the affected signal is downgraded to
observation-only and cannot trigger a live order.

## Architecture

```text
RPC / WebSocket / DEX / auxiliary wallet data
                    |
              Chain adapters
                    |
           Normalized market events
                    |
     Wallet graph + token risk + capital flow
                    |
              Signal engine
                    |
           Strategy state machine
                    |
                Risk engine
                    |
       Paper broker / approval / auto executor
                    |
       Orders, positions, PnL, alerts, audit log
```

The core service is asynchronous Python. Chain-specific behavior is isolated
behind `ChainAdapter`; scoring, strategy, risk, storage, and paper execution
operate on normalized events and do not depend on a particular chain.

### Components

- `ChainAdapter`: blocks, events, token metadata, quotes, balances, swap
  simulation, transaction signing, and transaction broadcast.
- `MarketData`: consumes chain and auxiliary events, normalizes them, and
  enforces freshness limits.
- `WalletGraph`: clusters wallet funding and behavior to distinguish
  independent wallets from one coordinated source.
- `TokenRisk`: evaluates permissions, liquidity, holders, Dev, Insider,
  Bundler, Sniper, and related-wallet risks.
- `SignalEngine`: calculates the person, token, position, and flow score.
- `StrategyEngine`: controls the trade lifecycle state machine.
- `RiskEngine`: has authority to reject every order and runs independently of
  the AI reasoning layer.
- `PaperBroker`: simulates fills using live quotes, liquidity, gas, slippage,
  and delay.
- `ExecutionEngine`: implements paper, approval, and automatic execution.
- `WalletManager`: loads chain-specific secrets only when live signing is
  explicitly enabled.
- `API/Monitor`: exposes status, signals, orders, positions, controls, and
  realtime events.

## Data model and freshness

Normalized event types:

```text
PriceTick
Swap
LiquidityChange
HolderSnapshot
WalletBuy
WalletSell
DevTransfer
TokenSecurityUpdate
SocialActivity
```

Recommended freshness limits:

```yaml
max_data_age:
  quote: 15s
  liquidity: 60s
  holder_snapshot: 120s
  security: 300s
  social: 600s
```

New positions are prohibited when any required decision input is stale,
conflicting, or unavailable.

Persistent entities:

```text
tokens
wallets
wallet_relationships
market_events
security_snapshots
signals
orders
fills
positions
risk_events
equity_snapshots
strategy_runs
```

Every decision-relevant entity includes `chain`, `source`, `data_timestamp`,
`created_at`, and `updated_at`.

## Strategy rules

### Hard vetoes

Any of the following produces `BLOCK` and cannot be overridden by an AI score:

- Risky Mint, Freeze, Blacklist, or Honeypot behavior.
- Abnormal Dev or related-wallet selling.
- LP removal or liquidity below the configured minimum.
- Extreme Insider, Bundler, Sniper, or related-wallet concentration.
- Apparent wallet coordination rather than independent participation.
- Quote slippage above the configured maximum.
- Stale or conflicting data.
- Daily loss, consecutive-loss, or total-exposure limit reached.

Top-10 concentration below 30% is only a reference signal, not a safety proof.

### Score

```yaml
score:
  wallet_quality: 25
  contract_distribution: 30
  capital_flow: 25
  narrative_social: 10
  market_position: 10
```

```text
score < 70        WATCH
70 <= score < 75  WATCH
75 <= score < 80  PROBE_ONLY
score >= 80       ARMED
```

An entry additionally requires a passed safety check, at least three
independent high-quality wallets, and at least two live confirmation signals.

Only three trade shapes are allowed:

1. Early smart-money convergence.
2. First valid pullback after migration.
3. Second-leg restart after a deep retracement.

Vertical pumps, single-wallet launches, low-liquidity tokens, and social-only
hype are observation-only by default.

### State machine

```text
WATCH -> ARMED -> PROBE -> CONFIRMED -> HOLD -> REDUCE -> EXIT
   |       |        |          |          |        |
 BLOCK   WATCH    EXIT       WATCH      EXIT     EXIT
```

The operational states are `WATCH`, `ARMED`, `PROBE`, `CONFIRMED`, `HOLD`,
`REDUCE`, `EXIT`, `BLOCK`, and `PAUSE`.

Target position sizing is staged as 30% probe, 30% confirmation, and at most
40% after a second confirmation. Averaging down is disabled.

AI may summarize narrative, wallet relationships, anomalies, and evidence. It
may not override vetoes, increase limits, postpone exits, or trade on stale data.

## Risk and execution

Default values are configurable and must be validated in virtual trading:

```yaml
execution_mode: paper

risk:
  risk_per_trade: 0.0025
  max_position_percent: 0.03
  max_concurrent_positions: 5
  max_narrative_exposure: 0.08
  max_slippage_percent: 1.5
  daily_loss_limit: 0.015
  max_consecutive_losses: 3
  reserve_balance_percent: 20
  cooldown_after_exit_minutes: 30
  allow_averaging_down: false
```

`risk_per_trade` is the maximum account loss, including fees, gas, and
slippage; it is not the position size.

The risk engine can permit reductions and exits while rejecting new entries.
It enters `PAUSE` after the daily loss limit, three consecutive losses, data
integrity failure, or balance protection failure.

Exit triggers include structure invalidation, Dev/Insider distribution,
collective smart-money exit, rapid holder or liquidity deterioration,
narrative invalidation, time stop, and stop loss. Partial profit-taking occurs
at 1R and 2R, with a trailing exit for the remainder. `R` includes all
estimated execution costs.

### Paper broker

Paper fills use the live quote and estimate:

- Directional slippage.
- Pool depth and price impact.
- Gas cost.
- Network delay.
- Buy and sell fees.
- Partial or failed fill behavior where applicable.

The paper broker and live executor share the same order interface so that the
strategy is tested against realistic execution assumptions.

### Execution modes

```text
paper    automatic decisions and simulated fills; no private-key access
approval automatic order preparation; human approval before signing
auto     risk-approved order signing and broadcasting through a hot wallet
```

Mode changes are audited. `auto` requires explicit confirmation and can be
disabled immediately through a global pause switch.

## Wallet security

- BNB and Robinhood use separate hot wallets by default.
- Private keys are stored in macOS Keychain or encrypted local secret storage.
- Private keys, seed phrases, and signed transaction material never enter logs,
  Git, strategy files, or model prompts.
- The paper mode never loads private keys.
- Approval mode displays chain, token, side, amount, slippage, gas, score,
  evidence, and veto status before signing.
- Balance reserve limits and a global emergency pause are mandatory.

## Project layout

```text
meme-agent/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── chains/{base.py,bnb.py,robinhood.py}
│   ├── data/{collectors.py,normalizer.py,freshness.py}
│   ├── intelligence/{wallet_graph.py,token_risk.py,scoring.py,narrative.py}
│   ├── strategy/{state_machine.py,signals.py,rules.py}
│   ├── risk/{limits.py,circuit_breaker.py,position_sizing.py}
│   ├── execution/{paper_broker.py,approval_executor.py,auto_executor.py,wallet.py}
│   ├── storage/{models.py,repository.py}
│   └── api/{routes.py,websocket.py}
├── configs/{default.yaml,networks.yaml}
├── tests/
├── docs/
├── pyproject.toml
└── README.md
```

## Interfaces

```python
class ChainAdapter(Protocol):
    async def get_latest_block(self) -> int: ...
    async def subscribe_events(self): ...
    async def get_quote(self, token: str, amount: int, side: str): ...
    async def simulate_swap(self, order): ...
    async def sign_and_send(self, transaction): ...
    async def get_balance(self, address: str): ...
```

```python
class Broker(Protocol):
    async def submit(self, order): ...
    async def cancel(self, order_id): ...
    async def positions(self): ...
    async def equity(self): ...
```

## Control API

```text
GET  /health
GET  /status
GET  /positions
GET  /orders
GET  /signals
POST /execution-mode
POST /orders/{id}/approve
POST /pause
POST /resume
POST /positions/{id}/exit
WS   /events
```

The normal mode progression is `paper -> approval -> auto`. Switching out of
`auto` is immediate; entering `auto` requires explicit confirmation and an
audit record.

## Implementation and validation order

1. Verify official network metadata, RPC, gas, DEX, explorer, and data sources.
2. Create configuration, storage, logging, and health checks.
3. Implement read-only BNB and Robinhood adapters.
4. Implement block, swap, liquidity, wallet, and holder event collection.
5. Implement wallet clustering, token safety, scoring, and freshness checks.
6. Implement the strategy state machine and independent risk engine.
7. Implement paper fills, costs, delay, and order lifecycle.
8. Add API, realtime monitoring, controls, and audit logs.
9. Run at least 100 virtual trades on both chains.
10. Verify positive net expectancy after simulated fees, gas, and slippage.
11. Verify drawdown, circuit breakers, and all entry/exit paths.
12. Implement approval signing.
13. Implement guarded automatic signing and broadcasting last.

Live trading is not enabled by the design alone. It requires successful
virtual validation, verified network integrations, explicit mode selection, and
an independently tested emergency stop.
