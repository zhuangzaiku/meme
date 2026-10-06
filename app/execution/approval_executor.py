from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.execution.orders import Order
from app.execution.wallet import WalletManager
from app.risk.limits import AccountSnapshot, MarketSnapshot, RiskDecision, RiskEngine


@dataclass(frozen=True)
class ApprovalRequest:
    request_id: str
    order: Order
    chain: str
    token: str
    side: str
    amount: float
    quote: float
    max_slippage_percent: float
    estimated_gas: int
    score: float
    evidence: list[str]
    vetoes: list[str]
    risk_decision: RiskDecision
    expires_at: datetime


@dataclass(frozen=True)
class BroadcastResult:
    status: str
    code: str
    tx_hash: str | None = None


class ApprovalExecutor:
    def __init__(
        self,
        risk_engine: RiskEngine,
        account_provider: Callable[[], AccountSnapshot],
        market_provider: Callable[[Order], MarketSnapshot],
        wallet_manager: WalletManager,
        transaction_builder: Callable[[Order, Any], dict[str, Any]] | None = None,
        broadcaster: Callable[[dict[str, Any], Any], str] | None = None,
    ) -> None:
        self.risk_engine = risk_engine
        self.account_provider = account_provider
        self.market_provider = market_provider
        self.wallet_manager = wallet_manager
        self.transaction_builder = transaction_builder
        self.broadcaster = broadcaster
        self._requests: dict[str, ApprovalRequest] = {}

    def prepare(self, order: Order) -> ApprovalRequest:
        market = self.market_provider(order)
        decision = self.risk_engine.check(order, self.account_provider(), market)
        request = ApprovalRequest(
            request_id=str(uuid4()),
            order=order,
            chain=order.chain,
            token=order.token,
            side=order.side,
            amount=order.amount,
            quote=market.price,
            max_slippage_percent=order.max_slippage_percent,
            estimated_gas=0,
            score=float(order.metadata.get("score", 0.0)),
            evidence=[str(item) for item in order.metadata.get("evidence", [])],
            vetoes=[str(item) for item in order.metadata.get("vetoes", [])],
            risk_decision=decision,
            expires_at=datetime.now(UTC) + timedelta(minutes=1),
        )
        self._requests[request.request_id] = request
        return request

    def approve(self, request_id: str) -> BroadcastResult:
        request = self._requests.get(request_id)
        if request is None:
            return BroadcastResult("rejected", "request_not_found")
        if datetime.now(UTC) >= request.expires_at:
            return BroadcastResult("rejected", "request_expired")
        market = self.market_provider(request.order)
        decision = self.risk_engine.check(request.order, self.account_provider(), market)
        if not decision.allowed:
            return BroadcastResult("rejected", decision.code)
        if self.transaction_builder is None or self.broadcaster is None:
            return BroadcastResult("rejected", "route_not_configured")
        try:
            signer = self.wallet_manager.load_signer(request.chain, "approval")
            assert signer is not None
            transaction = self.transaction_builder(request.order, signer)
            tx_hash = self.broadcaster(transaction, signer)
        except RuntimeError:
            return BroadcastResult("rejected", "signer_unavailable")
        except ValueError:
            return BroadcastResult("rejected", "invalid_transaction")
        return BroadcastResult("broadcast", "ok", tx_hash)
