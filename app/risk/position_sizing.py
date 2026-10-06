from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SizeResult:
    units: float
    notional: float
    max_loss: float


class PositionSizer:
    def __init__(self, risk_per_trade: float = 0.0025, max_position_percent: float = 0.03) -> None:
        self.risk_per_trade = risk_per_trade
        self.max_position_percent = max_position_percent

    def size(
        self,
        account_equity: float,
        entry: float,
        invalidation: float,
        costs_per_unit: float = 0.0,
    ) -> SizeResult:
        if account_equity <= 0 or entry <= 0 or entry == invalidation:
            return SizeResult(0.0, 0.0, 0.0)
        risk_budget = account_equity * self.risk_per_trade
        loss_per_unit = abs(entry - invalidation) + max(costs_per_unit, 0.0)
        units_by_risk = risk_budget / loss_per_unit
        units_by_position = account_equity * self.max_position_percent / entry
        units = min(units_by_risk, units_by_position)
        return SizeResult(units, units * entry, units * loss_per_unit)
