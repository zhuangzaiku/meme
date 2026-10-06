from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from app.data.collectors import Collector
from app.data.events import Swap
from app.data.sources.fusion import MarketFusion
from app.data.sources.models import PoolCandidate, SourceHealth
from app.data.sources.pipeline import LiveMarketSource
from app.execution.paper_broker import PaperBroker
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
        for name in ("bnb", "robinhood")
    }
    runtime = PaperRuntime(
        collectors,
        PaperBroker(lambda _: None, initial_cash=100_000),
        repository=repository,
        initial_cash=100_000,
    )

    report = await asyncio.wait_for(runtime.run_once(), timeout=0.2)

    assert report.events_seen == 0
    assert set(report.health) == {"bnb", "robinhood"}


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
