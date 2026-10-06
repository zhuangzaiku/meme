from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.chains.base import SimulationResult
from app.execution.approval_executor import BroadcastResult
from app.execution.orders import Order
from app.execution.transaction_guard import TransactionGuard
from app.execution.wallet import WalletManager
from app.risk.circuit_breaker import CircuitBreaker
from app.risk.limits import AccountSnapshot, MarketSnapshot, RiskEngine


class AutoExecutor:
    def __init__(
        self,
        validation_approved: bool = False,
        max_slippage_percent: float = 1.5,
        max_gas_wei: int | None = None,
        risk_engine: RiskEngine | None = None,
        account_provider: Callable[[], AccountSnapshot] | None = None,
        market_provider: Callable[[Order], MarketSnapshot] | None = None,
        wallet_manager: WalletManager | None = None,
        transaction_builder: Callable[[Order, Any], dict[str, Any]] | None = None,
        broadcaster: Callable[[dict[str, Any], Any], str] | None = None,
    ) -> None:
        self.guard = TransactionGuard(
            validation_approved=validation_approved,
            max_slippage_percent=max_slippage_percent,
            max_gas_wei=max_gas_wei,
            risk_engine=risk_engine,
            account_provider=account_provider,
            market_provider=market_provider,
        )
        self.wallet_manager = wallet_manager or WalletManager()
        self.transaction_builder = transaction_builder
        self.broadcaster = broadcaster

    def execute(
        self,
        order: Order,
        simulation: SimulationResult | None = None,
        breaker: CircuitBreaker | None = None,
    ) -> BroadcastResult:
        decision = self.guard.validate(order, simulation, breaker)
        if not decision.allowed:
            return BroadcastResult("rejected", decision.code)
        if self.transaction_builder is None or self.broadcaster is None:
            return BroadcastResult("rejected", "route_not_configured")
        try:
            signer = self.wallet_manager.load_signer(order.chain, "auto")
            assert signer is not None
            transaction = self.transaction_builder(order, signer)
            tx_hash = self.broadcaster(transaction, signer)
        except RuntimeError:
            return BroadcastResult("rejected", "signer_unavailable")
        except ValueError:
            return BroadcastResult("rejected", "invalid_transaction")
        return BroadcastResult("broadcast", "ok", tx_hash)
