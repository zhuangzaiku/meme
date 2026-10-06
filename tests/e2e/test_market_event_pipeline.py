from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from app.chains.evm import EvmChainAdapter
from app.config import load_settings
from app.data.collectors import Collector
from app.data.events import Swap
from app.data.sources.fusion import MarketFusion
from app.data.sources.models import PoolCandidate, SourceHealth
from app.data.sources.pipeline import LiveMarketSource
from app.data.sources.solana_market import SolanaMarketCollector
from app.execution.paper_broker import PaperBroker
from app.main import build_market_source, build_native_discovery
from app.runtime import PaperRuntime
from app.storage.repository import EventRepository


def candidate(chain: str, network_id: str, pool: str) -> PoolCandidate:
    now = datetime.now(UTC)
    return PoolCandidate(
        chain=chain,
        network_id=network_id,
        pool_address=pool,
        dex_id="pancakeswap-v2",
        base_token="0x00000000000000000000000000000000000000bb",
        quote_token="0x00000000000000000000000000000000000000cc",
        base_is_token0=True,
        observed_at=now,
    )


def test_bnb_builds_native_discovery_when_enabled(tmp_path: Path) -> None:
    settings = load_settings(tmp_path / "missing.yaml")

    source = build_native_discovery(settings, cast(EvmChainAdapter, object()))

    assert source is not None
    assert {spec.name for spec in source.specs} == {"pancakeswap_v2", "pancakeswap_v3"}


def test_sol_builds_a_solana_collector(tmp_path: Path) -> None:
    settings = load_settings(tmp_path / "missing.yaml")
    repository = EventRepository(f"sqlite:///{tmp_path / 'events.sqlite3'}")

    collector = build_market_source(settings, "sol", repository)

    assert collector.source_name == "sol"
    assert hasattr(collector.event_source, "__self__")
    live_source = collector.event_source.__self__
    assert isinstance(live_source.collector, SolanaMarketCollector)


class FakeDiscovery:
    def __init__(self, pool: PoolCandidate) -> None:
        self.pool = pool
        self.health = SourceHealth(name=f"gecko:{pool.chain}", status="ready")

    async def discover_pools(self) -> list[PoolCandidate]:
        return [self.pool]


class FakeMarketCollector:
    def __init__(self, pool: PoolCandidate) -> None:
        self.pool = pool

    async def collect(self, candidates: list[PoolCandidate]) -> list[Swap]:
        return [
            Swap(
                chain=self.pool.chain,
                token=self.pool.base_token,
                wallet="0x00000000000000000000000000000000000000dd",
                side="buy",
                amount=1,
                price=1,
                timestamp=datetime.now(UTC),
                pool_address=self.pool.pool_address,
                source_event_id=f"{self.pool.chain}:0xabc:1",
            )
        ]


@pytest.mark.asyncio
async def test_runtime_collects_independent_chains_concurrently(tmp_path) -> None:
    repository = EventRepository(f"sqlite:///{tmp_path / 'events.sqlite3'}")
    started: set[str] = set()

    async def source(name: str) -> list[Swap]:
        started.add(name)
        while len(started) < 2:
            await asyncio.sleep(0)
        return []

    collectors = {
        name: Collector(name, lambda name=name: source(name), repository)
    for name in ("bnb", "robinhood", "sol")
    }
    runtime = PaperRuntime(
        collectors,
        PaperBroker(lambda _: None, initial_cash=100_000),
        repository=repository,
        initial_cash=100_000,
    )

    report = await asyncio.wait_for(runtime.run_once(), timeout=0.2)

    assert report.events_seen == 0
    assert set(report.health) == {"bnb", "robinhood", "sol"}


@pytest.mark.asyncio
async def test_runtime_marks_slow_source_degraded_after_timeout(tmp_path) -> None:
    repository = EventRepository(f"sqlite:///{tmp_path / 'events.sqlite3'}")

    async def slow_source() -> list[Swap]:
        await asyncio.sleep(1)
        return []

    collector = Collector("bnb", slow_source, repository)
    runtime = PaperRuntime(
        {"bnb": collector},
        PaperBroker(lambda _: None, initial_cash=100_000),
        repository=repository,
        initial_cash=100_000,
    )

    report = await runtime.run_once(collection_timeout_seconds=0.01)

    assert report.events_seen == 0
    assert report.health["bnb"].status == "degraded"
    assert "timed out" in (report.health["bnb"].error or "")


@pytest.mark.asyncio
async def test_run_forever_accepts_collection_timeout_separate_from_interval(tmp_path) -> None:
    repository = EventRepository(f"sqlite:///{tmp_path / 'events.sqlite3'}")

    async def slow_source() -> list[Swap]:
        await asyncio.sleep(0.02)
        return []

    runtime = PaperRuntime(
        {"bnb": Collector("bnb", slow_source, repository)},
        PaperBroker(lambda _: None, initial_cash=100_000),
        repository=repository,
        initial_cash=100_000,
    )
    stop_event = asyncio.Event()
    reports = []

    async def on_report(report) -> None:
        reports.append(report)
        if report.health["bnb"].status != "unavailable":
            stop_event.set()

    await runtime.run_forever(
        interval_seconds=0.1,
        collection_timeout_seconds=0.01,
        stop_event=stop_event,
        on_report=on_report,
    )

    assert reports[-1].health["bnb"].status == "degraded"


@pytest.mark.asyncio
async def test_run_forever_polls_chains_at_independent_intervals(tmp_path) -> None:
    repository = EventRepository(f"sqlite:///{tmp_path / 'events.sqlite3'}")
    counts = {"bnb": 0, "robinhood": 0, "sol": 0}

    async def source(name: str) -> list[Swap]:
        counts[name] += 1
        return []

    runtime = PaperRuntime(
        {
            name: Collector(name, lambda name=name: source(name), repository)
            for name in counts
        },
        PaperBroker(lambda _: None, initial_cash=100_000),
        repository=repository,
        initial_cash=100_000,
    )
    stop_event = asyncio.Event()
    report_count = 0

    async def on_report(report) -> None:
        nonlocal report_count
        report_count += 1
        if report_count >= 8:
            stop_event.set()

    await runtime.run_forever(
        interval_seconds=0.01,
        poll_intervals={"bnb": 0.02, "robinhood": 0.05, "sol": 0.03},
        collection_timeouts={"bnb": 0.01, "robinhood": 0.01, "sol": 0.01},
        stop_event=stop_event,
        on_report=on_report,
    )

    assert counts["bnb"] > counts["robinhood"]
    assert counts["sol"] > 0


@pytest.mark.asyncio
async def test_solana_degraded_does_not_degrade_bnb(tmp_path: Path) -> None:
    repository = EventRepository(f"sqlite:///{tmp_path / 'events.sqlite3'}")

    async def empty_source() -> list[Swap]:
        return []

    async def failing_source() -> list[Swap]:
        raise ConnectionError("solana unavailable")

    runtime = PaperRuntime(
        {
            "bnb": Collector("bnb", empty_source, repository, empty_status="observation_only"),
            "sol": Collector("sol", failing_source, repository),
        },
        PaperBroker(lambda _: None, initial_cash=100_000),
        repository=repository,
        initial_cash=100_000,
    )

    report = await runtime.run_once()

    assert report.health["sol"].status == "degraded"
    assert report.health["bnb"].status == "observation_only"


@pytest.mark.asyncio
async def test_verified_market_events_reach_two_chain_paper_runtime(tmp_path) -> None:
    repository = EventRepository(f"sqlite:///{tmp_path / 'events.sqlite3'}")
    collectors: dict[str, Collector] = {}
    for chain, network_id in (("bnb", "bsc"), ("robinhood", "robinhood")):
        pool = candidate(
            chain,
            network_id,
            f"0x00000000000000000000000000000000000000{len(collectors) + 1}a",
        )
        live_source = LiveMarketSource(
            FakeDiscovery(pool),
            FakeMarketCollector(pool),
            MarketFusion(),
        )
        collectors[chain] = Collector(chain, live_source.collect, repository)

    broker = PaperBroker(lambda _: None, initial_cash=100_000)
    runtime = PaperRuntime(
        collectors,
        broker,
        repository=repository,
        initial_cash=100_000,
    )

    report = await runtime.run_once()

    assert report.events_seen == 2
    assert set(report.health) == {"bnb", "robinhood"}
    assert all(health.status == "ready" for health in report.health.values())
    assert report.filled_orders == 0
    assert len(repository.list_events("bnb", "0x00000000000000000000000000000000000000bb", 10)) == 1
