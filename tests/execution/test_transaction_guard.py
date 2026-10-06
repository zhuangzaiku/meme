from app.chains.base import SimulationResult
from app.execution.auto_executor import AutoExecutor
from app.execution.orders import Order


def test_failed_simulation_is_rejected() -> None:
    executor = AutoExecutor(validation_approved=True)
    result = executor.execute(
        Order("o1", "bnb", "0x1", "buy", 100, 1.5),
        simulation=SimulationResult(ok=False, error="revert"),
    )
    assert result.status == "rejected"
    assert result.code == "simulation_failed"
