# BSC Native Meme Pool Discovery Design

**Date:** 2026-10-07  
**Status:** Approved direction, pending written-spec review

## Goal

Reduce dependence on GeckoTerminal rate limits by discovering BSC Meme pools
directly from verified on-chain factory and launchpad events, while keeping
the existing RPC-verified event collector, GMGN enrichment, paper broker, and
no-private-key safety boundary unchanged.

## Scope

The first implementation covers:

- PancakeSwap V2 pair discovery through `PairCreated` events.
- PancakeSwap V3 pool discovery through `PoolCreated` events.
- Four.meme launch and/or migration discovery only when its official BSC
  contract address and event ABI are verified before enabling the adapter.
- BSC-only native discovery; Robinhood continues using its existing discovery
  path until a separate verified protocol registry exists.
- Incremental block cursors, bounded `eth_getLogs` ranges, event deduplication,
  contract validation, and candidate normalization into `PoolCandidate`.
- GeckoTerminal as a supplementary discovery source and fallback for protocols
  not covered by the native registry.

This feature remains read-only. It does not load a wallet private key, sign a
transaction, or broadcast a transaction in paper, approval, or auto modes.

## Data Flow

```text
BSC RPC eth_getLogs
        |
        +--> Pancake V2/V3 factory adapters
        |
        +--> Four.meme adapter when verified and enabled
        v
  verified PoolCandidate registry
        |
        +--> pool contract code/token identity checks
        +--> EVM Swap/Mint/Burn/Sync collector
        +--> GeckoTerminal metadata fallback/enrichment
        v
  MarketFusion -> ExternalSignal(GMGN) -> strategy/risk -> PaperBroker
```

Native discovery is authoritative for the existence of a newly created pool,
but not for social or narrative quality. GMGN and future social sources remain
responsible for external smart-money, narrative, and social scores.

## Components

### `BscPoolDiscovery`

An asynchronous source implementing the existing `PoolDiscovery` protocol. It
holds one cursor per protocol and scans only configured factory or launchpad
addresses. Each scan:

1. reads the current BSC block;
2. splits the cursor-to-head interval into bounded block windows;
3. calls `eth_getLogs` for the protocol's creation topics;
4. decodes the indexed and data fields into normalized pool candidates;
5. validates addresses and retains only candidates from the expected chain;
6. advances a protocol cursor only after its complete scan succeeds.

Pancake V2 candidates use the pair address and token0/token1 emitted by
`PairCreated`, with `dex_id="pancakeswap-v2"`. Pancake V3 candidates use the
pool address and token0/token1/fee emitted by `PoolCreated`, with a stable V3
DEX identifier. Four.meme candidates use the official event fields for the
token, launch pool, and migration target; unsupported event shapes are
ignored rather than guessed.

### Protocol registry

Protocol addresses, event signatures, and decode metadata live in a verified
configuration registry, not scattered through the collector. An entry is
enabled only when its chain ID, contract address, event topic, and decode
schema are present. The registry must not invent Four.meme values; an absent
or invalid entry produces `observation_only` health and leaves GeckoTerminal
available as fallback.

### Candidate merge and deduplication

Native and GeckoTerminal candidates are merged by lowercase pool address. A
native candidate wins identity fields because its factory event is authoritative;
GeckoTerminal may fill non-authoritative context such as price or reserve. A
pool is emitted once per source event, keyed by chain, transaction hash, and
log index. Replayed ranges cannot create duplicate candidates or paper events.

## Failure Handling

- A failed RPC range does not advance its cursor.
- A rate-limited or timed-out protocol keeps its last verified candidates for
  a bounded stale-cache window and reports `observation_only`.
- No cache and no successful scan reports `degraded` for that protocol.
- One protocol or chain failing does not stop the other chain's scan.
- Candidate discovery never bypasses existing pool identity, chain ID,
  liquidity, freshness, security, or risk gates.
- GeckoTerminal 429 responses remain diagnosable and may provide fallback
  candidates; they are not converted into synthetic market events.

## Configuration

The implementation adds BSC native-discovery settings for:

- enable/disable native BSC discovery;
- protocol registry entries and enabled protocol names;
- discovery poll interval and maximum block span;
- maximum candidates per protocol and stale-cache duration;
- independent RPC timeout/retry limits.

Existing `configs/networks.yaml` remains user-owned and is not overwritten.
Protocol metadata is additive and validated at startup. All HTTP requests,
including optional GeckoTerminal and GMGN requests, continue to use the local
proxy at `http://127.0.0.1:7890`.

## Testing

Tests use deterministic fake RPC responses and recorded logs. They cover:

- V2 `PairCreated` decoding;
- V3 `PoolCreated` decoding;
- Four.meme adapter enablement only with verified metadata;
- bounded ranges and per-protocol cursor advancement;
- failed-range cursor preservation;
- duplicate log/candidate suppression;
- native-plus-Gecko candidate merge precedence;
- stale-cache behavior under RPC timeout or rate limiting;
- independent BNB/Robinhood health and poll intervals;
- end-to-end verified candidates reaching the existing paper runtime without a
  signer.

No test depends on public RPC availability. A separate read-only smoke command
may exercise the configured BSC RPC and prints discovery health, block ranges,
candidate counts, and event counts without broadcasting.

## Rollout

1. Validate the BSC RPC and protocol registry with a bounded read-only smoke
   run.
2. Enable native Pancake discovery in paper mode while keeping GeckoTerminal
   as fallback.
3. Enable Four.meme only after its official address and ABI metadata pass the
   registry validation and fixture tests.
4. Compare native and Gecko candidate counts, event freshness, and paper
   decisions before changing any live execution setting.

