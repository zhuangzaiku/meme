from app.strategy.state_machine import StrategyEngine
from tests.strategy.test_state_machine import armed_snapshot


def test_vertical_pump_is_not_a_trade_shape() -> None:
    snapshot = armed_snapshot()
    snapshot.trade_shape = "vertical_pump"
    decision = StrategyEngine().evaluate(snapshot)
    assert decision.action == "WATCH"


def test_confirmation_adds_only_after_valid_pullback() -> None:
    snapshot = armed_snapshot()
    snapshot.current_state = "PROBE"
    snapshot.trade_shape = "migration_pullback"
    decision = StrategyEngine().evaluate(snapshot)
    assert decision.state == "CONFIRMED"
    assert decision.action == "ADD_CONFIRMATION"
