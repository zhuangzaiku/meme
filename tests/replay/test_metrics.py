from app.replay.metrics import FillRecord, calculate_metrics


def test_metrics_include_costs_and_max_drawdown() -> None:
    fills = [
        FillRecord(pnl=12, costs=2, chain="bnb", strategy_shape="early_convergence"),
        FillRecord(pnl=-4, costs=1, chain="bnb", strategy_shape="migration_pullback"),
    ]
    metrics = calculate_metrics(fills, [1000, 1010, 1005])
    assert metrics.net_pnl == metrics.gross_pnl - metrics.total_costs
    assert metrics.max_drawdown >= 0
