from __future__ import annotations

import argparse
import asyncio
import os
from collections.abc import Iterable
from dataclasses import dataclass

from fastapi import FastAPI

from app.api.audit import AuditLog
from app.api.routes import ControlState, create_router
from app.api.websocket import create_websocket_router
from app.chains.base import Quote
from app.chains.evm import EvmChainAdapter
from app.config import MarketChainSettings, Settings, load_settings
from app.data.collectors import Collector
from app.data.events import MarketEvent
from app.data.sources.bsc_discovery import BscPoolDiscovery, ProtocolSpec
from app.data.sources.composite_discovery import CompositePoolDiscovery
from app.data.sources.evm_market import EvmMarketCollector
from app.data.sources.fusion import MarketFusion
from app.data.sources.geckoterminal import GeckoTerminalSource
from app.data.sources.gmgn import GmgnCalloutSource
from app.data.sources.pipeline import LiveMarketSource, PoolDiscovery
from app.execution.paper_broker import PaperBroker
from app.runtime import PaperRuntime, RuntimeReport
from app.storage.repository import EventRepository


@dataclass
class ReportGate:
    interval_seconds: float
    _last_report_at: float | None = None

    def should_report(self, now: float) -> bool:
        if self.interval_seconds <= 0:
            raise ValueError("report interval must be positive")
        if self._last_report_at is not None and now - self._last_report_at < self.interval_seconds:
            return False
        self._last_report_at = now
        return True


def create_app() -> FastAPI:
    settings = load_settings()
    state = ControlState(execution_mode=settings.execution_mode)
    audit = AuditLog()
    application = FastAPI(title="Meme Agent")
    application.include_router(create_router(state, audit))
    application.include_router(create_websocket_router(state))
    application.state.control = state
    application.state.audit = audit
    return application


def main() -> None:
    parser = argparse.ArgumentParser(description="Realtime Meme agent")
    parser.add_argument("--mode", choices=["paper", "approval", "auto"], default=None)
    parser.add_argument("--check-connectors", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--once", action="store_true", help="run one paper cycle and exit")
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument(
        "--report-interval",
        type=float,
        default=None,
        help="status interval in seconds; defaults to the strategy interval",
    )
    parser.add_argument("--duration", type=float, default=None)
    args = parser.parse_args()

    settings = load_settings()
    mode = args.mode or settings.execution_mode
    if args.check_connectors:
        for name, chain in settings.chains.items():
            status = (
                "configured" if chain.rpc_http and chain.chain_id is not None else "unavailable"
            )
            print(f"{name}: {status}")
        return
    if args.dry_run and mode == "approval":
        print("approval dry-run; no private key loaded and no transaction broadcast")
        return
    if args.dry_run and mode == "auto":
        print("auto dry-run rejected: live broadcast is disabled")
        return
    if mode != "paper":
        print(f"meme-agent mode={mode}; live runtime is disabled in this build")
        return
    asyncio.run(
        run_paper(
            settings,
            once=args.once,
            interval_seconds=args.interval,
            report_interval_seconds=args.report_interval,
            duration_seconds=args.duration,
        )
    )


async def run_paper(
    settings: Settings,
    *,
    once: bool = False,
    interval_seconds: float = 5.0,
    report_interval_seconds: float | None = None,
    duration_seconds: float | None = None,
) -> None:
    database_url = os.getenv("MEME_AGENT_DATABASE_URL", "sqlite:///meme_agent.sqlite3")
    repository = EventRepository(database_url)
    initial_cash = 100_000.0
    broker = PaperBroker(lambda _: _unreachable_quote(), initial_cash=initial_cash)
    collectors = {
        name: build_market_source(settings, name, repository)
        for name, chain in settings.chains.items()
    }
    runtime = PaperRuntime.from_risk_settings(
        collectors,
        broker,
        repository=repository,
        initial_cash=initial_cash,
        risk=settings.risk,
    )
    report_gate = ReportGate(
        report_interval_seconds
        if report_interval_seconds is not None
        else interval_seconds
    )
    poll_intervals: dict[str, float] = {}
    collection_timeouts: dict[str, float] = {}
    for name in collectors:
        chain_market = settings.market.per_chain.get(
            name,
            MarketChainSettings(
                poll_interval_seconds=interval_seconds,
                collection_timeout_seconds=settings.market.collection_timeout_seconds,
            ),
        )
        poll_intervals[name] = chain_market.poll_interval_seconds
        collection_timeouts[name] = chain_market.collection_timeout_seconds

    async def report(report: RuntimeReport) -> None:
        if not once and not report_gate.should_report(asyncio.get_running_loop().time()):
            return
        statuses = ", ".join(
            f"{name}={health.status}" for name, health in report.health.items()
        )
        print(
            f"paper cycle events={report.events_seen} decisions={len(report.decisions)} "
            f"filled={report.filled_orders} equity={broker.equity():.2f} {statuses}"
        )

    if once:
        await report(await runtime.run_once())
        return

    stop_event = asyncio.Event()
    if duration_seconds is not None:
        if duration_seconds <= 0:
            raise ValueError("duration must be positive")
        asyncio.create_task(_stop_after(duration_seconds, stop_event))
    print("meme-agent mode=paper; signer=disabled; waiting for authoritative event sources")
    try:
        await runtime.run_forever(
            interval_seconds=interval_seconds,
            collection_timeout_seconds=settings.market.collection_timeout_seconds,
            poll_intervals=poll_intervals,
            collection_timeouts=collection_timeouts,
            stop_event=stop_event,
            on_report=report,
        )
    except KeyboardInterrupt:
        stop_event.set()
        print("meme-agent stopped")


def build_market_source(
    settings: Settings, name: str, repository: EventRepository
) -> Collector:
    chain = settings.chains[name]
    network_id = "bsc" if name == "bnb" else name
    if chain.rpc_http and chain.chain_id is not None:
        adapter = EvmChainAdapter(
            name,
            chain.rpc_http,
            settings.market.proxy_url,
            settings.market.http_timeout_seconds,
        )
        discovery: PoolDiscovery = GeckoTerminalSource(
            network_id,
            settings.market.proxy_url,
            timeout_seconds=settings.market.http_timeout_seconds,
            max_retries=settings.market.max_retries,
            max_pools=settings.market.max_pools_per_chain,
        )
        native_discovery = build_native_discovery(settings, adapter) if name == "bnb" else None
        if native_discovery is not None:
            discovery = CompositePoolDiscovery([native_discovery, discovery])
        market_collector = EvmMarketCollector(
            adapter,
            expected_chain_id=chain.chain_id,
            max_log_block_span=settings.market.max_log_block_span,
            max_pools=settings.market.max_pools_per_chain,
        )
        external_source = None
        if settings.external.enabled:
            external_source = GmgnCalloutSource(
                ak=os.getenv(settings.external.gmgn_ak_env),
                sk=os.getenv(settings.external.gmgn_sk_env),
                proxy_url=settings.market.proxy_url,
                base_url=settings.external.gmgn_base_url,
                timeout_seconds=settings.market.http_timeout_seconds,
                max_retries=settings.market.max_retries,
                max_tokens=settings.external.max_tokens_per_cycle,
            )
        source = LiveMarketSource(
            discovery,
            market_collector,
            MarketFusion(),
            external_source=external_source,
        )
        return Collector(name, source.collect, repository, empty_status="observation_only")

    async def unavailable_source() -> Iterable[MarketEvent]:
        raise ConnectionError(f"{name}: RPC is not configured")

    return Collector(name, unavailable_source, repository, empty_status="observation_only")


def build_native_discovery(
    settings: Settings, adapter: EvmChainAdapter
) -> BscPoolDiscovery | None:
    if not settings.native_discovery.enabled:
        return None
    specs = [
        ProtocolSpec(
            name=name,
            contract_address=protocol.contract_address,
            event_kind=protocol.event_kind,
            dex_id=protocol.dex_id,
            enabled=protocol.enabled and protocol.chain == "bnb",
        )
        for name, protocol in settings.native_discovery.protocols.items()
        if protocol.contract_address is not None
    ]
    if not specs:
        return None
    return BscPoolDiscovery(
        adapter,
        specs,
        initial_backfill_blocks=settings.native_discovery.initial_backfill_blocks,
        max_log_block_span=settings.native_discovery.max_log_block_span,
        max_pools_per_protocol=settings.native_discovery.max_pools_per_protocol,
        stale_cache_seconds=settings.native_discovery.stale_cache_seconds,
    )


def _unreachable_quote() -> Quote:
    raise RuntimeError("paper quote provider is replaced by PaperRuntime")


async def _stop_after(seconds: float, event: asyncio.Event) -> None:
    if seconds > 0:
        await asyncio.sleep(seconds)
    event.set()


if __name__ == "__main__":
    main()
