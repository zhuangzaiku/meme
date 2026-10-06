from app.execution.approval_executor import ApprovalExecutor
from app.execution.orders import Order
from app.execution.wallet import WalletManager
from app.risk.limits import AccountSnapshot, MarketSnapshot, RiskEngine


def test_approval_request_contains_cost_and_risk_fields() -> None:
    executor = ApprovalExecutor(
        risk_engine=RiskEngine(),
        account_provider=lambda: AccountSnapshot(10_000, 8_000, 0, 0, 0, 0),
        market_provider=lambda _: MarketSnapshot(price=1.0),
        wallet_manager=WalletManager(),
    )
    order = Order(
        order_id="o1",
        chain="bnb",
        token="0x1",
        side="buy",
        amount=100,
        max_slippage_percent=1.5,
    )
    request = executor.prepare(order)
    assert request.chain == order.chain
    assert request.max_slippage_percent is not None
    assert request.risk_decision.allowed is True
