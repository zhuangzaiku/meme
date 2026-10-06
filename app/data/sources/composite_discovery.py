from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.data.connector_health import ConnectorStatus
from app.data.sources.models import PoolCandidate, SourceHealth
from app.data.sources.pipeline import PoolDiscovery


class CompositePoolDiscovery:
    def __init__(self, sources: list[PoolDiscovery]) -> None:
        if not sources:
            raise ValueError("at least one discovery source is required")
        self.sources = tuple(sources)
        self.health = SourceHealth(name="composite:pool-discovery", status="unavailable")

    async def discover_pools(self) -> list[PoolCandidate]:
        observed_at = datetime.now(UTC)
        ordered_sources = sorted(
            self.sources,
            key=lambda source: 0
            if getattr(source.health, "name", "").startswith("bsc:native")
            else 1,
        )
        results = await asyncio.gather(
            *(source.discover_pools() for source in ordered_sources),
            return_exceptions=True,
        )
        merged: dict[str, PoolCandidate] = {}
        errors: list[str] = []
        successful_sources = 0
        for source, result in zip(ordered_sources, results, strict=True):
            if isinstance(result, BaseException):
                errors.append(f"{source.health.name}: {result}")
                continue
            successful_sources += 1
            if source.health.error:
                errors.append(f"{source.health.name}: {source.health.error}")
            for candidate in result:
                key = candidate.pool_address.lower()
                previous = merged.get(key)
                if previous is None:
                    merged[key] = candidate
                else:
                    merged[key] = _merge_candidates(previous, candidate)

        status: ConnectorStatus
        if merged:
            status = "ready"
        elif successful_sources > 0:
            status = "observation_only"
        else:
            status = "degraded"
        self.health = SourceHealth(
            name="composite:pool-discovery",
            status=status,
            error="; ".join(errors) if errors else None,
            observed_at=observed_at,
        )
        return list(merged.values())


def _merge_candidates(
    authoritative: PoolCandidate, metadata: PoolCandidate
) -> PoolCandidate:
    updates: dict[str, object] = {}
    if authoritative.price_usd is None and metadata.price_usd is not None:
        updates["price_usd"] = metadata.price_usd
    if authoritative.reserve_usd is None and metadata.reserve_usd is not None:
        updates["reserve_usd"] = metadata.reserve_usd
    return authoritative.model_copy(update=updates) if updates else authoritative
