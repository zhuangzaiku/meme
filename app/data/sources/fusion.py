from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.data.connector_health import ConnectorStatus
from app.data.events import MarketEvent
from app.data.sources.models import PoolCandidate


@dataclass(frozen=True)
class FusionResult:
    events: list[MarketEvent] = field(default_factory=list)
    status: ConnectorStatus = "observation_only"
    reasons: list[str] = field(default_factory=list)


class MarketFusion:
    def __init__(self, max_age_seconds: int = 60) -> None:
        self.max_age_seconds = max_age_seconds

    def fuse(
        self,
        candidate: PoolCandidate,
        events: list[MarketEvent],
        now: datetime,
    ) -> FusionResult:
        if not self._fresh(candidate.observed_at, now):
            return FusionResult(status="observation_only", reasons=["candidate data is stale"])
        for event in events:
            if event.chain != candidate.chain or event.token not in {
                candidate.base_token,
                candidate.quote_token,
            }:
                return FusionResult(status="degraded", reasons=["token identity conflict"])
            if event.pool_address != candidate.pool_address:
                return FusionResult(status="degraded", reasons=["pool identity conflict"])
            if not self._fresh(event.timestamp, now):
                return FusionResult(status="observation_only", reasons=["market event is stale"])
        if not events:
            return FusionResult(status="observation_only", reasons=["no verified market events"])
        return FusionResult(events=events, status="ready")

    def _fresh(self, timestamp: datetime, now: datetime) -> bool:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            return False
        age = now.astimezone(UTC) - timestamp.astimezone(UTC)
        return 0 <= age.total_seconds() <= self.max_age_seconds
