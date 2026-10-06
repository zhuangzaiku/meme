from app.data.connector_health import ConnectorHealth


def test_connector_is_not_trade_ready_when_observation_only() -> None:
    health = ConnectorHealth(name="gmgn", status="observation_only")
    assert health.trade_ready is False


def test_ready_connector_is_trade_ready() -> None:
    health = ConnectorHealth(name="rpc", status="ready")
    assert health.trade_ready is True
