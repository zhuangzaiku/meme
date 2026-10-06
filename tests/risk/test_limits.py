from app.execution.orders import Order
from app.risk.limits import AccountSnapshot, MarketSnapshot, RiskEngine


def test_daily_loss_limit_blocks_new_entries() -> None:
    risk_engine = RiskEngine()
    account = AccountSnapshot(
        equity=10_000,
        cash=8_000,
        daily_pnl=-150,
        consecutive_losses=0,
        open_positions=0,
        narrative_exposure=0,
    )
    order = Order(
        order_id="o1",
        chain="bnb",
        token="0x1",
        side="buy",
        amount=100,
        max_slippage_percent=1.5,
    )
    decision = risk_engine.check(order, account, MarketSnapshot(price=1.0))
    assert decision.allowed is False
    assert decision.code == "daily_loss_limit"
