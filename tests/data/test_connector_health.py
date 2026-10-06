from app.data.collectors import Collector
from app.data.connector_health import ConnectorHealth
from app.storage.repository import EventRepository


def test_connector_is_not_trade_ready_when_observation_only() -> None:
    health = ConnectorHealth(name="gmgn", status="observation_only")
    assert health.trade_ready is False


def test_ready_connector_is_trade_ready() -> None:
    health = ConnectorHealth(name="rpc", status="ready")
    assert health.trade_ready is True


def test_observation_only_collector_stays_out_of_trade_path(tmp_path) -> None:
    async def source() -> list[object]:
        return []

    collector = Collector(
        "rpc",
        source,
        EventRepository(f"sqlite:///{tmp_path / 'events.sqlite3'}"),
        empty_status="observation_only",
    )

    import asyncio

    asyncio.run(collector.run_once())

    assert collector.health.trade_ready is False
