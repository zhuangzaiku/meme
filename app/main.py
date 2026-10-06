from __future__ import annotations

import argparse
import asyncio
import os
from collections.abc import Awaitable, Callable, Iterable

from fastapi import FastAPI

from app.api.audit import AuditLog
from app.api.routes import ControlState, create_router
from app.api.websocket import create_websocket_router
from app.chains.base import Quote
from app.chains.evm import EvmChainAdapter
from app.config import Settings, load_settings
from app.data.collectors import Collector
from app.data.events import MarketEvent
from app.execution.paper_broker import PaperBroker
from app.runtime import PaperRuntime, RuntimeReport
from app.storage.repository import EventRepository


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
            duration_seconds=args.duration,
        )
    )


async def run_paper(
    settings: Settings,
    *,
    once: bool = False,
    interval_seconds: float = 5.0,
    duration_seconds: float | None = None,
) -> None:
    database_url = os.getenv("MEME_AGENT_DATABASE_URL", "sqlite:///meme_agent.sqlite3")
    repository = EventRepository(database_url)
    initial_cash = 100_000.0
    broker = PaperBroker(lambda _: _unreachable_quote(), initial_cash=initial_cash)
    collectors = {
        name: Collector(
            name,
            _rpc_heartbeat_source(name, chain.rpc_http, chain.chain_id),
            repository,
            empty_status="observation_only",
        )
        for name, chain in settings.chains.items()
    }
    runtime = PaperRuntime.from_risk_settings(
        collectors,
        broker,
        repository=repository,
        initial_cash=initial_cash,
        risk=settings.risk,
    )

    async def report(report: RuntimeReport) -> None:
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


def _rpc_heartbeat_source(
    name: str, rpc_http: str | None, expected_chain_id: int | None
) -> Callable[[], Awaitable[Iterable[MarketEvent]]]:
    if rpc_http:
        adapter = EvmChainAdapter(name, rpc_http)

        async def source() -> Iterable[MarketEvent]:
            try:
                observed_chain_id = await adapter.get_chain_id()
                if expected_chain_id is None or observed_chain_id != expected_chain_id:
                    raise ConnectionError(
                        f"{name}: chain id mismatch, expected {expected_chain_id}, "
                        f"got {observed_chain_id}"
                    )
                await adapter.get_latest_block()
                return []
            finally:
                await adapter.web3.provider.disconnect()

        return source

    async def unavailable_source() -> Iterable[MarketEvent]:
        raise ConnectionError(f"{name}: RPC is not configured")

    return unavailable_source


def _unreachable_quote() -> Quote:
    raise RuntimeError("paper quote provider is replaced by PaperRuntime")


async def _stop_after(seconds: float, event: asyncio.Event) -> None:
    if seconds > 0:
        await asyncio.sleep(seconds)
    event.set()


if __name__ == "__main__":
    main()
