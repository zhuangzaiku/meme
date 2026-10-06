from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field

from app.chains.evm import EvmChainAdapter
from app.config import Settings, load_settings
from app.data.connector_health import ConnectorStatus
from app.data.sources.evm_market import EvmMarketCollector
from app.data.sources.geckoterminal import GeckoTerminalSource


@dataclass(frozen=True)
class MarketSmokeResult:
    chain: str
    status: ConnectorStatus
    chain_id: int | None
    latest_block: int | None
    discovered_pools: int
    events: int
    reasons: list[str] = field(default_factory=list)
    broadcasted: bool = False


async def run_market_smoke(
    settings: Settings,
    max_pools: int | None = None,
    max_log_block_span: int | None = None,
) -> list[MarketSmokeResult]:
    results: list[MarketSmokeResult] = []
    for name, chain in settings.chains.items():
        if chain.rpc_http is None or chain.chain_id is None:
            results.append(
                MarketSmokeResult(name, "unavailable", None, None, 0, 0, ["RPC is not configured"])
            )
            continue
        adapter = EvmChainAdapter(
            name,
            chain.rpc_http,
            settings.market.proxy_url,
            settings.market.http_timeout_seconds,
        )
        discovery = GeckoTerminalSource(
            "bsc" if name == "bnb" else name,
            settings.market.proxy_url,
            timeout_seconds=settings.market.http_timeout_seconds,
            max_retries=settings.market.max_retries,
            max_pools=max_pools or settings.market.max_pools_per_chain,
        )
        try:
            observed_chain_id = await adapter.get_chain_id()
            latest_block = await adapter.get_latest_block()
            if observed_chain_id != chain.chain_id:
                results.append(
                    MarketSmokeResult(
                        name,
                        "degraded",
                        observed_chain_id,
                        latest_block,
                        0,
                        0,
                        [f"chain id mismatch: expected {chain.chain_id}"],
                    )
                )
                continue
            candidates = await discovery.discover_pools()
            collector = EvmMarketCollector(
                adapter,
                expected_chain_id=chain.chain_id,
                max_log_block_span=max_log_block_span or settings.market.max_log_block_span,
            )
            events = await collector.collect(candidates)
            status: ConnectorStatus = "ready" if events else "observation_only"
            reasons = [] if events else ["no verified events in scan window"]
            if discovery.health.status == "degraded":
                status = "degraded"
                reasons = [discovery.health.error or "discovery source degraded"]
            results.append(
                MarketSmokeResult(
                    name,
                    status,
                    observed_chain_id,
                    latest_block,
                    len(candidates),
                    len(events),
                    reasons,
                )
            )
        except Exception as exc:
            results.append(MarketSmokeResult(name, "degraded", None, None, 0, 0, [str(exc)]))
        finally:
            await adapter.web3.provider.disconnect()
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only market source smoke check")
    parser.add_argument("--chains", default="bnb,robinhood")
    parser.add_argument("--max-pools", type=int, default=5)
    parser.add_argument("--max-log-span", type=int, default=25)
    args = parser.parse_args()
    settings = load_settings()
    selected = {name.strip() for name in args.chains.split(",") if name.strip()}
    settings = settings.model_copy(
        update={"chains": {k: v for k, v in settings.chains.items() if k in selected}}
    )
    for result in asyncio.run(
        run_market_smoke(
            settings,
            max_pools=args.max_pools,
            max_log_block_span=args.max_log_span,
        )
    ):
        print(
            f"{result.chain}: status={result.status} chain_id={result.chain_id} "
            f"latest_block={result.latest_block} pools={result.discovered_pools} "
            f"events={result.events} broadcasted={result.broadcasted} "
            f"reasons={'; '.join(result.reasons) or 'none'}"
        )


if __name__ == "__main__":
    main()
