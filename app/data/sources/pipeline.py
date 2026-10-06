from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Protocol

from app.data.events import MarketEvent
from app.data.sources.fusion import MarketFusion
from app.data.sources.models import PoolCandidate, SourceHealth


class PoolDiscovery(Protocol):
    health: SourceHealth

    async def discover_pools(self) -> list[PoolCandidate]: ...


class MarketCollector(Protocol):
    async def collect(self, candidates: list[PoolCandidate]) -> list[MarketEvent]: ...


class ExternalSignalSource(Protocol):
    async def collect(self, candidates: list[PoolCandidate]) -> Iterable[MarketEvent]: ...


class LiveMarketSource:
    def __init__(
        self,
        discovery: PoolDiscovery,
        collector: MarketCollector,
        fusion: MarketFusion,
        external_source: ExternalSignalSource | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.discovery = discovery
        self.collector = collector
        self.fusion = fusion
        self.external_source = external_source
        self.clock = clock or (lambda: datetime.now(UTC))

    async def collect(self) -> list[MarketEvent]:
        candidates = await self.discovery.discover_pools()
        discovery_health = getattr(self.discovery, "health", None)
        if getattr(discovery_health, "status", None) == "degraded":
            error = getattr(discovery_health, "error", None) or "discovery source degraded"
            raise ConnectionError(error)
        events = await self.collector.collect(candidates)
        if self.external_source is not None:
            events.extend(await self.external_source.collect(candidates))
        by_pool: dict[tuple[str, str], list[MarketEvent]] = {}
        for event in events:
            if event.pool_address is not None:
                by_pool.setdefault(_pool_key(event.chain, event.pool_address), []).append(event)
        accepted: list[MarketEvent] = []
        now = self.clock()
        for candidate in candidates:
            result = self.fusion.fuse(
                candidate,
                by_pool.get(_pool_key(candidate.chain, candidate.pool_address), []),
                now,
            )
            if result.status == "ready":
                accepted.extend(result.events)
        return accepted


def _pool_key(chain: str, pool_address: str) -> tuple[str, str]:
    normalized = pool_address if chain == "sol" else pool_address.lower()
    return chain, normalized
