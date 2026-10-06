from app.risk.circuit_breaker import CircuitBreaker


def test_three_consecutive_losses_pause_trading() -> None:
    breaker = CircuitBreaker(max_consecutive_losses=3)
    for _ in range(3):
        breaker.record("loss")
    assert breaker.status().paused is True


def test_win_resets_consecutive_losses() -> None:
    breaker = CircuitBreaker(max_consecutive_losses=3)
    breaker.record("loss")
    breaker.record("win")
    assert breaker.status().consecutive_losses == 0
