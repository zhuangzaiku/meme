from datetime import UTC, datetime

import pytest

from app.data.events import PriceTick
from app.storage.repository import EventRepository


@pytest.fixture
def repository(tmp_path):
    return EventRepository(f"sqlite:///{tmp_path / 'events.sqlite3'}")


def test_price_tick_round_trips_through_repository(repository) -> None:
    event = PriceTick(
        chain="bnb",
        token="0x1",
        price=1.25,
        timestamp=datetime.now(UTC),
    )
    repository.save_event(event)
    events = repository.list_events("bnb", "0x1", 1)
    assert events[0].price == 1.25


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone"):
        PriceTick(chain="bnb", token="0x1", price=1.25, timestamp=datetime.now())
