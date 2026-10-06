from __future__ import annotations

from datetime import UTC, datetime, timedelta

DEFAULT_MAX_AGE_SECONDS = {
    "quote": 15,
    "liquidity": 60,
    "holder_snapshot": 120,
    "security": 300,
    "social": 600,
}


class FreshnessPolicy:
    def __init__(self, max_age_seconds: dict[str, int] | None = None) -> None:
        self.max_age_seconds = max_age_seconds or DEFAULT_MAX_AGE_SECONDS.copy()

    def is_fresh(self, kind: str, timestamp: datetime, now: datetime) -> bool:
        max_age = self.max_age_seconds.get(kind)
        if max_age is None:
            return False
        timestamp = self._as_utc(timestamp)
        now = self._as_utc(now)
        age = now - timestamp
        return timedelta(0) <= age <= timedelta(seconds=max_age)

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value.astimezone(UTC)
