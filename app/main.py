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
from app.config import Settings, load_settings
from app.data.collectors import Collector
from app.data.events import MarketEvent
from app.data.sources.evm_market import EvmMarketCollector
from app.data.sources.fusion import MarketFusion
from app.data.sources.geckoterminal import GeckoTerminalSource
from app.data.sources.pipeline import LiveMarketSource
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
        discovery = GeckoTerminalSource(
            network_id,
            settings.market.proxy_url,
            timeout_seconds=settings.market.http_timeout_seconds,
            max_retries=settings.market.max_retries,
            max_pools=settings.market.max_pools_per_chain,
        )
        adapter = EvmChainAdapter(
            name,
            chain.rpc_http,
            settings.market.proxy_url,
            settings.market.http_timeout_seconds,
        )
        market_collector = EvmMarketCollector(
            adapter,
            expected_chain_id=chain.chain_id,
            max_log_block_span=settings.market.max_log_block_span,
        )
        source = LiveMarketSource(discovery, market_collector, MarketFusion())
        return Collector(name, source.collect, repository, empty_status="observation_only")

    async def unavailable_source() -> Iterable[MarketEvent]:
        raise ConnectionError(f"{name}: RPC is not configured")

    return Collector(name, unavailable_source, repository, empty_status="observation_only")


def _unreachable_quote() -> Quote:
    raise RuntimeError("paper quote provider is replaced by PaperRuntime")


async def _stop_after(seconds: float, event: asyncio.Event) -> None:
    if seconds > 0:
        await asyncio.sleep(seconds)
    event.set()


if __name__ == "__main__":
    main()
