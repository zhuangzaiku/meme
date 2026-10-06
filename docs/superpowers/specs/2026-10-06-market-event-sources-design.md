# DEX/Meme Market Event Sources Design

**Date:** 2026-10-06  
**Status:** Approved design, pending implementation-plan review

## Goal

Connect the paper-first Meme agent to live market events for BNB Smart Chain
and Robinhood Chain. External discovery data may identify candidate pools, but
RPC-verified chain data is required before an event can be considered
trade-ready. The paper runtime must continue to operate safely when either
source is unavailable.

## Scope

The first implementation covers:

- GeckoTerminal pool discovery for the `bsc` and `robinhood` networks.
- HTTP requests through the local proxy `http://127.0.0.1:7890`.
- RPC validation against the configured chain IDs `56` and `4663`.
- Candidate-pool validation by contract code and pool address.
- Incremental EVM log collection for Uniswap/PancakeSwap-style V2 and V3
  pools.
- Normalized `PriceTick`, `Swap`, and `LiquidityChange` events for the paper
  strategy.
- Event deduplication, freshness checks, source health, and conflict vetoes.
- Paper-mode integration only. No private key loading or transaction
  broadcasting is part of this change.

The implementation does not scrape HTML, infer prices from social posts, or
assume a Robinhood DEX deployment that is not returned by the discovery source.
Contract security checks remain a separate hard gate; missing security data
cannot be treated as a pass.

## Data Flow

```text
GeckoTerminal pool discovery
        |
        v
candidate pool cache (chain, pool, DEX, base token, freshness)
        |
        +--> RPC chain ID and contract-code validation
        |
        +--> RPC eth_getLogs from the last block cursor
                    |
                    v
        V2/V3 Swap, Sync, Mint, Burn decoding
                    |
                    v
        normalized events -> repository -> market fusion -> strategy/risk
                                                    |
                                                    v
                                                PaperBroker
```

GeckoTerminal is a discovery and context source. It may provide current pool
metadata and a reference price, but it cannot authorize an order by itself.
The RPC source is authoritative for chain identity, pool existence, block
ordering, and decoded logs. If API and RPC observations disagree on chain,
pool, timestamp, or event direction, the fused candidate is marked degraded
and entry is blocked.

## Components

### `GeckoTerminalSource`

An asynchronous HTTP source using `httpx.AsyncClient` and the configured local
proxy. It queries the network pool listing and normalizes only validated JSON
fields:

- network identifier;
- pool address;
- DEX identifier;
- base and quote token addresses;
- pool creation time;
- price, liquidity, volume, and transaction counters;
- response timestamp.

Discovery results are cached for 60 seconds. Connection and read timeouts are
10 seconds with at most three exponential-backoff retries. A failed refresh
keeps the last valid cache for observation only and never creates an empty or
synthetic market event.

### `EvmMarketCollector`

The collector uses the existing EVM adapter and polls `eth_blockNumber` and
`eth_getLogs`. Each candidate pool has an independent block cursor. Queries
are bounded to a configured maximum block span; a large gap is split into
sequential ranges. The collector validates that the observed chain ID matches
the configured chain ID before accepting logs.

The decoder supports the standard event signatures used by Uniswap/PancakeSwap
V2 and V3 pools. V2 logs include `Swap`, `Sync`, `Mint`, and `Burn`; V3 logs
include `Swap`, `Mint`, and `Burn`. Unknown DEX or event formats are retained as
observation-only raw source health, not converted into guessed swaps.

Each decoded event has a stable deduplication key composed of chain, transaction
hash, and log index. Replaying a block range therefore cannot create duplicate
strategy inputs or paper fills.

### `MarketFusion`

Fusion joins discovery records and RPC observations by normalized lowercase
chain/pool/token address. A candidate is `ready` only when:

1. the API record is within its 60-second freshness window;
2. the RPC chain ID and pool contract are valid;
3. the pool has a supported decoded event or a recent verified state update;
4. the API and RPC pool addresses and token identities agree; and
5. no required security or liquidity value is stale or conflicting.

Otherwise the candidate remains visible for diagnostics but is marked
`observation_only` or `degraded` and cannot create a new position.

## Normalized Events

The existing event repository remains the persistence boundary. The event model
will gain an optional source-event identifier and source metadata needed for
deduplication and audit. The collector emits:

- `PriceTick` from a fresh pool state/reference price associated with a
  verified pool;
- `Swap` from decoded V2/V3 logs, including the initiating wallet, direction,
  amount, and event timestamp;
- `LiquidityChange` from `Sync`, `Mint`, or `Burn` state changes.

No holder, dev, security, or social event is fabricated by this source. Those
signals remain separate inputs and their absence continues to be a strategy
veto where required.

## Configuration

The network registry remains the source of chain identity and endpoint
configuration. Market-source settings will be explicit and environment
overridable:

- `MARKET_PROXY_URL`, defaulting to `http://127.0.0.1:7890`;
- discovery network IDs `bsc` and `robinhood`;
- discovery refresh interval, default 60 seconds;
- RPC log poll interval, default 5 seconds;
- maximum log block span;
- maximum candidate pools per chain;
- HTTP timeout and retry limits.

No DEX factory or router address is hardcoded as a prerequisite. Discovery
returns concrete pool addresses and DEX identifiers. This avoids assuming a
single Robinhood deployment while still allowing a future verified static
allowlist to reduce discovery scope.

## Health and Failure Handling

Health status is explicit:

- `ready`: discovery and RPC validation are fresh and compatible;
- `observation_only`: a source is reachable but not sufficient for entry;
- `degraded`: a previously valid source failed or produced conflicting data;
- `unavailable`: no usable source has been established.

The runtime continues polling independent chains when one chain fails. It does
not advance a block cursor past a failed or undecodable range. It records source
errors and preserves the last valid event timestamp. New buys are blocked when
required data is stale, unavailable, conflicting, or security-gated; exits can
still be processed by the existing pause/risk controls.

## Testing and Verification

Tests will not depend on public network availability. They will use recorded
JSON fixtures and deterministic fake RPC responses for:

- BNB and Robinhood discovery parsing;
- proxy and timeout configuration;
- V2 and V3 topic decoding;
- block cursor advancement and range splitting;
- duplicate log suppression;
- API/RPC identity conflicts;
- stale cache and retry behavior;
- independent two-chain health and event isolation;
- paper strategy entry being blocked when security or source freshness is
  insufficient;
- valid normalized events reaching the existing PaperBroker without loading a
  signer.

A separate read-only smoke command will run through the configured proxy and
report discovered pools, RPC chain IDs, latest blocks, source health, and event
counts. It will never broadcast or load a private key.

## Rollout

1. Start in read-only collection mode and verify both chain IDs and source
   health.
2. Enable the paper runtime with automatic event collection and paper fills.
3. Review persisted events, source conflicts, paper PnL, and drawdown.
4. Keep approval/auto live execution disabled until the paper validation gate
   and explicit human review pass.

The existing live execution gates remain unchanged. This feature cannot enable
live signing as a side effect.
