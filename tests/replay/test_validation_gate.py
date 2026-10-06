from app.replay.metrics import PerformanceMetrics
from app.replay.runner import ValidationGate


def test_validation_gate_requires_one_hundred_virtual_trades() -> None:
    metrics = PerformanceMetrics(
        trade_count=99,
        win_rate=0.5,
        gross_pnl=10,
        total_costs=1,
        net_pnl=9,
        expectancy=0.09,
        max_drawdown=0.05,
        max_consecutive_losses=2,
        data_source_verified=True,
        circuit_breakers_passed=True,
    )
    result = ValidationGate().evaluate(metrics)
    assert result.approved_for_live is False
    assert "100" in result.reasons[0]
