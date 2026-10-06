from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class FillRecord:
    pnl: float
    costs: float
    chain: str
    strategy_shape: str

    @property
    def net_pnl(self) -> float:
        return self.pnl - self.costs


@dataclass(frozen=True)
class PerformanceMetrics:
    trade_count: int
    win_rate: float
    gross_pnl: float
    total_costs: float
    net_pnl: float
    expectancy: float
    max_drawdown: float
    max_consecutive_losses: int
    data_source_verified: bool = False
    circuit_breakers_passed: bool = False


def _max_consecutive_losses(fills: Sequence[FillRecord]) -> int:
    current = 0
    maximum = 0
    for fill in fills:
        if fill.net_pnl < 0:
            current += 1
            maximum = max(maximum, current)
        else:
            current = 0
    return maximum


def _drawdown(equity_curve: Sequence[float]) -> float:
    peak = 0.0
    maximum = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        if peak > 0:
            maximum = max(maximum, (peak - equity) / peak)
    return maximum


def calculate_metrics(
    fills: Sequence[FillRecord], equity_curve: Sequence[float]
) -> PerformanceMetrics:
    trade_count = len(fills)
    gross_pnl = sum(fill.pnl for fill in fills)
    total_costs = sum(fill.costs for fill in fills)
    net_pnl = gross_pnl - total_costs
    wins = sum(fill.net_pnl > 0 for fill in fills)
    return PerformanceMetrics(
        trade_count=trade_count,
        win_rate=wins / trade_count if trade_count else 0.0,
        gross_pnl=gross_pnl,
        total_costs=total_costs,
        net_pnl=net_pnl,
        expectancy=net_pnl / trade_count if trade_count else 0.0,
        max_drawdown=_drawdown(equity_curve),
        max_consecutive_losses=_max_consecutive_losses(fills),
    )
