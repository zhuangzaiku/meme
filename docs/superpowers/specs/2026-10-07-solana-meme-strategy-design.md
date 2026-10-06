# Solana Meme Strategy Design

**Date:** 2026-10-07  
**Status:** Approved design, pending implementation-plan review

## Goal

Extend the paper-first Meme agent from BNB Smart Chain and Robinhood Chain to
three independently scheduled meme-market lanes: BNB, Robinhood, and Solana.
Solana must use `https://api.mainnet.solana.com` as its primary RPC, keep all
requests behind the local proxy, and feed only verified events into the
existing scoring, risk, and paper-execution pipeline.

## Scope

The first Solana implementation covers:

- Solana mainnet configuration and independent polling/timeout settings.
- Candidate-pool discovery through the existing GeckoTerminal HTTP pattern on
  the `solana` network, including cache reuse and rate-limit degradation.
- Solana JSON-RPC account checks, incremental transaction-signature polling,
  parsed transaction retrieval, and mint-account security checks.
- Candidate-driven parsing for known Raydium, Meteora, Orca, and Pump.fun
  identifiers when the transaction shape is supported.
- Normalized `PriceTick`, `Swap`, `LiquidityChange`, and
  `TokenSecurityUpdate` events compatible with the existing fusion, strategy,
  risk, repository, and `PaperBroker` components.
- Independent Solana health reporting. A Solana failure must not pause BNB or
  Robinhood collection, and vice versa.
- Paper mode only. No private-key loading, signing, or transaction broadcast.

The first implementation does not scan every Solana program globally. The
public RPC is used to validate and consume transactions for discovered
candidate pools. Unknown transaction formats remain observation-only rather
than being interpreted heuristically. Solana GMGN/FOMO enrichment is not
fabricated; a future compatible read-only enrichment source can be attached
through the existing external-signal boundary.

## Data Flow

```text
GeckoTerminal solana pool discovery
            |
            v
candidate pool cache (base58 addresses, DEX, price, liquidity, freshness)
            |
            +--> Solana RPC account validation
            |
            +--> getSignaturesForAddress per pool
                         |
                         v
                   getTransaction (jsonParsed)
                         |
                         v
       swap direction + wallet + token balance delta
                         |
                         +--> mint account authority checks
                         |
                         v
 normalized events -> MarketFusion -> existing score/risk -> PaperBroker
```

GeckoTerminal identifies candidate pools and supplies fresh reference price
and liquidity context. Solana RPC is authoritative for account existence,
transaction signatures, transaction timestamps, wallet-side token balance
changes, and mint/freeze authority state. A candidate without successful RPC
validation remains visible for diagnostics but cannot authorize a buy.

## Components

### Cross-chain candidate model

`PoolCandidate` will support two address encodings:

- BNB and Robinhood: lower-cased, validated EVM addresses.
- Solana: strict Base58 public keys for pool and token addresses.

The model will preserve the existing field names so the market fusion and
runtime interfaces remain stable. Composite discovery deduplication will use
`(chain, pool_address)` instead of only the pool address, preventing a
cross-chain collision.

### `SolanaRpcAdapter`

The adapter will use JSON-RPC over HTTP through the configured local proxy and
existing retry policy. It will expose the smallest interface required by the
collector:

- `get_account_info(address)` for pool and mint account existence/metadata;
- `get_signatures_for_address(address, limit, before)` for incremental polling;
- `get_transaction(signature)` with `jsonParsed` encoding and version support;
- the response slot and block time needed for event timestamps.

The adapter will use `confirmed` commitment, a 20-second default Solana
collection timeout, and explicit response-shape validation. RPC errors,
timeouts, HTTP 429 responses, and malformed responses become connector health
state rather than guessed events.

### `SolanaPoolDiscovery`

The discovery source will normalize GeckoTerminal's `solana` network records
into `PoolCandidate` objects. It will retain the existing bounded cache and
retry behavior, including returning recent cached pools as
`observation_only` after a rate limit. Discovery will cap the number of pools
per cycle to avoid exhausting the public RPC.

### `SolanaMarketCollector`

The collector will maintain independent signature cursors and seen-signature
sets per `(chain, pool_address)`:

1. Verify the candidate pool account exists through RPC.
2. Retrieve signatures newer than the stored cursor, with a bounded per-pool
   limit.
3. Fetch parsed transactions for those signatures.
4. Match token-balance changes for the candidate base token and identify the
   transaction signer.
5. Emit a buy when the signer receives base tokens and a sell when the signer
   gives up base tokens. If the signer or direction is ambiguous, skip the
   swap and record a diagnostic reason.
6. Emit a fresh price and liquidity event only when the candidate metadata is
   fresh and the pool account was RPC-verified.
7. Read the base-token mint account and emit a passing security event only
   when both mint and freeze authority are absent. Any remaining authority or
   unavailable mint data is a blocking security event.

The cursor advances only after the requested signature range has been handled
without a transport or response-shape failure. Replayed signatures are
deduplicated by the stable Solana signature identifier.

## Configuration

The network registry will add:

```yaml
sol:
  name: Solana Mainnet
  chain_id: null
  native_symbol: SOL
  rpc_env: https://api.mainnet.solana.com
```

`load_settings` will accept `SOLANA_RPC_URL` as an environment override. The
default market configuration will add:

```yaml
per_chain:
  sol:
    poll_interval_seconds: 10
    collection_timeout_seconds: 20
```

Solana-specific bounds will be explicit configuration values: three maximum
candidate pools, twenty signatures per pool per cycle, `confirmed` commitment,
and the existing proxy/retry settings. The default execution mode remains
`paper`.

## Health and Failure Handling

Health is reported independently for `bnb`, `robinhood`, and `sol`:

- `ready`: candidate and RPC observations are fresh and compatible;
- `observation_only`: the source is reachable but no verified trade event is
  available;
- `degraded`: a previously usable source failed, was rate-limited without a
  usable cache, or returned conflicting/malformed data;
- `unavailable`: the Solana RPC endpoint is not configured.

The runtime continues scheduling the other chains when Solana is degraded. No
new Solana entry is allowed when candidate freshness, pool existence, token
security, liquidity, or swap direction is missing. Existing exit/risk
handling remains governed by the current runtime and circuit-breaker rules.

## Testing and Verification

Tests will be deterministic and network-free:

- Base58 Solana candidate validation and EVM regression coverage;
- Solana RPC request payloads, proxy wiring, timeout, retry, and malformed
  response handling;
- signature cursor advancement, replay suppression, and failure retention;
- parsed token-balance changes to buy/sell events;
- missing or active mint/freeze authority blocking entry;
- GeckoTerminal Solana parsing and stale-cache behavior;
- three-chain configuration and independent scheduler timeouts;
- Solana events reaching `PaperRuntime` and `PaperBroker` without loading a
  signer or broadcasting a transaction.

The implementation is complete only when the full test suite, Ruff, mypy, and
`git diff --check` pass.

## Rollout

1. Run the read-only connector check and verify Solana RPC health through the
   configured proxy.
2. Start paper mode with BNB, Robinhood, and Solana enabled.
3. Review Solana candidate freshness, signature cursors, security vetoes,
   event counts, paper fills, and chain-specific degraded states.
4. Keep approval and automatic live execution disabled until the existing
   paper validation gate and explicit human review pass.

This design does not introduce a wallet private key, signing path, or live
execution permission.
