from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.chains.base import SimulationResult
from app.execution.orders import Order
from app.risk.circuit_breaker import CircuitBreaker
from app.risk.limits import AccountSnapshot, MarketSnapshot, RiskEngine


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    code: str = "allowed"


class TransactionGuard:
    def __init__(
        self,
        validation_approved: bool,
        max_slippage_percent: float = 1.5,
        max_gas_wei: int | None = None,
        risk_engine: RiskEngine | None = None,
        account_provider: Callable[[], AccountSnapshot] | None = None,
        market_provider: Callable[[Order], MarketSnapshot] | None = None,
    ) -> None:
        self.validation_approved = validation_approved
        self.max_slippage_percent = max_slippage_percent
        self.max_gas_wei = max_gas_wei
        self.risk_engine = risk_engine
        self.account_provider = account_provider
        self.market_provider = market_provider

    def validate(
        self,
        order: Order,
        simulation: SimulationResult | None,
        breaker: CircuitBreaker | None = None,
    ) -> GuardDecision:
        if not self.validation_approved:
            return GuardDecision(False, "validation_gate_required")
        if breaker is not None and breaker.status().paused:
            return GuardDecision(False, "paused")
        if simulation is None:
            return GuardDecision(False, "simulation_required")
        if not simulation.ok:
            return GuardDecision(False, "simulation_failed")
        slippage_limit = min(self.max_slippage_percent, order.max_slippage_percent)
        if simulation.price_impact_percent > slippage_limit:
            return GuardDecision(False, "slippage_limit")
        if self.max_gas_wei is not None and simulation.gas_wei > self.max_gas_wei:
            return GuardDecision(False, "gas_limit")
        if self.risk_engine and self.account_provider and self.market_provider:
            decision = self.risk_engine.check(
                order, self.account_provider(), self.market_provider(order)
            )
            if not decision.allowed:
                return GuardDecision(False, decision.code)
        return GuardDecision(True)
