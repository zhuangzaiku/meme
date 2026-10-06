from datetime import UTC, datetime, timedelta

import pytest

from app.data.collectors import Collector
from app.data.events import (
    LiquidityChange,
    PriceTick,
    SocialActivity,
    Swap,
    TokenSecurityUpdate,
)
from app.execution.paper_broker import PaperBroker
from app.runtime import PaperRuntime
from app.storage.repository import EventRepository


def _events() -> list[object]:
    now = datetime.now(UTC)
    return [
        PriceTick(chain="bnb", token="0x1", price=1.0, timestamp=now - timedelta(seconds=2)),
        PriceTick(chain="bnb", token="0x1", price=1.01, timestamp=now),
        Swap(
            chain="bnb",
            token="0x1",
            wallet="0xa",
            side="buy",
            amount=10,
            price=1.0,
            timestamp=now,
        ),
        Swap(
            chain="bnb",
            token="0x1",
            wallet="0xb",
            side="buy",
            amount=10,
            price=1.0,
            timestamp=now,
        ),
        Swap(
            chain="bnb",
            token="0x1",
            wallet="0xc",
            side="buy",
            amount=10,
            price=1.0,
            timestamp=now,
        ),
        TokenSecurityUpdate(
            chain="bnb", token="0x1", passed=True, timestamp=now, source="security"
        ),
        LiquidityChange(chain="bnb", token="0x1", liquidity=100_000, timestamp=now),
        SocialActivity(chain="bnb", token="0x1", activity="active", timestamp=now),
    ]


@pytest.mark.asyncio
async def test_paper_runtime_turns_valid_events_into_a_paper_fill(tmp_path) -> None:
    repository = EventRepository(f"sqlite:///{tmp_path / 'events.sqlite3'}")

    async def source() -> list[object]:
        return _events()

    collector = Collector("bnb", source, repository)
    broker = PaperBroker(lambda order: None, initial_cash=10_000)
    runtime = PaperRuntime(
        {"bnb": collector},
        broker,
        repository=repository,
        initial_cash=10_000,
    )

    report = await runtime.run_once()

    assert report.orders_submitted == 1
    assert report.filled_orders == 1
    assert report.decisions[0].action == "BUY_PROBE"
    assert broker.positions()[0].token == "0x1"


@pytest.mark.asyncio
async def test_paper_runtime_does_not_trade_when_source_is_unavailable(tmp_path) -> None:
    repository = EventRepository(f"sqlite:///{tmp_path / 'events.sqlite3'}")

    async def unavailable() -> list[object]:
        raise ConnectionError("rpc unavailable")

    collector = Collector("robinhood", unavailable, repository)
    broker = PaperBroker(lambda order: None, initial_cash=10_000)
    runtime = PaperRuntime(
        {"robinhood": collector},
        broker,
        repository=repository,
        initial_cash=10_000,
    )

    report = await runtime.run_once()

    assert report.orders_submitted == 0
    assert report.filled_orders == 0
    assert report.health["robinhood"].status == "degraded"
