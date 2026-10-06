from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.replay.metrics import FillRecord, PerformanceMetrics, calculate_metrics


@dataclass(frozen=True)
class ReplayResult:
    fills: list[FillRecord]
    equity_curve: list[float]
    metrics: PerformanceMetrics


class ReplayRunner:
    def run(self, events: Iterable[FillRecord], initial_equity: float = 1_000) -> ReplayResult:
        fills = list(events)
        equity_curve = [initial_equity]
        equity = initial_equity
        for fill in fills:
            equity += fill.net_pnl
            equity_curve.append(equity)
        metrics = calculate_metrics(fills, equity_curve)
        return ReplayResult(fills, equity_curve, metrics)


@dataclass(frozen=True)
class ValidationResult:
    approved_for_live: bool
    reasons: list[str]


class ValidationGate:
    def __init__(self, max_drawdown: float = 0.20) -> None:
        self.max_drawdown = max_drawdown

    def evaluate(self, metrics: PerformanceMetrics) -> ValidationResult:
        reasons: list[str] = []
        if metrics.trade_count < 100:
            reasons.append("at least 100 virtual trades are required")
        if metrics.expectancy <= 0:
            reasons.append("net expectancy after costs must be positive")
        if metrics.max_drawdown > self.max_drawdown:
            reasons.append("maximum drawdown exceeds the validation limit")
        if not metrics.data_source_verified:
            reasons.append("authoritative live data source is not verified")
        if not metrics.circuit_breakers_passed:
            reasons.append("circuit breaker validation has not passed")
        return ValidationResult(not reasons, reasons)
