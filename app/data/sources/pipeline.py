from __future__ import annotations

from collections.abc import Callable
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


class LiveMarketSource:
    def __init__(
        self,
        discovery: PoolDiscovery,
        collector: MarketCollector,
        fusion: MarketFusion,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.discovery = discovery
        self.collector = collector
        self.fusion = fusion
        self.clock = clock or (lambda: datetime.now(UTC))

    async def collect(self) -> list[MarketEvent]:
        candidates = await self.discovery.discover_pools()
        discovery_health = getattr(self.discovery, "health", None)
        if getattr(discovery_health, "status", None) == "degraded":
            error = getattr(discovery_health, "error", None) or "discovery source degraded"
            raise ConnectionError(error)
        events = await self.collector.collect(candidates)
        by_pool: dict[str, list[MarketEvent]] = {}
        for event in events:
            if event.pool_address is not None:
                by_pool.setdefault(event.pool_address.lower(), []).append(event)
        accepted: list[MarketEvent] = []
        now = self.clock()
        for candidate in candidates:
            result = self.fusion.fuse(
                candidate,
                by_pool.get(candidate.pool_address.lower(), []),
                now,
            )
            if result.status == "ready":
                accepted.extend(result.events)
        return accepted
