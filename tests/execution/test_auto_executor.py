from app.chains.base import SimulationResult
from app.execution.auto_executor import AutoExecutor
from app.execution.orders import Order
from app.risk.circuit_breaker import CircuitBreaker


def make_order() -> Order:
    return Order("o1", "bnb", "0x1", "buy", 100, 1.5)


def test_auto_executor_rejects_without_validation_gate() -> None:
    result = AutoExecutor(validation_approved=False).execute(make_order())
    assert result.status == "rejected"
    assert result.code == "validation_gate_required"


def test_auto_executor_rejects_excessive_slippage() -> None:
    executor = AutoExecutor(validation_approved=True, max_slippage_percent=1.5)
    simulation = SimulationResult(ok=True, price_impact_percent=2.0)
    result = executor.execute(make_order(), simulation=simulation)
    assert result.status == "rejected"
    assert result.code == "slippage_limit"


def test_pause_prevents_broadcast() -> None:
    breaker = CircuitBreaker()
    breaker.pause("manual pause")
    result = AutoExecutor(validation_approved=True).execute(make_order(), breaker=breaker)
    assert result.status == "rejected"
    assert result.code == "paused"
