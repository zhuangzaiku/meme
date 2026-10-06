from datetime import UTC, datetime, timedelta

from app.data.freshness import FreshnessPolicy


def test_quote_older_than_fifteen_seconds_is_stale() -> None:
    now = datetime.now(UTC)
    policy = FreshnessPolicy()
    assert policy.is_fresh("quote", now - timedelta(seconds=16), now) is False


def test_unknown_event_kind_is_not_fresh() -> None:
    now = datetime.now(UTC)
    assert FreshnessPolicy().is_fresh("unknown", now, now) is False
