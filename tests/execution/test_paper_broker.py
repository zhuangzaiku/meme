from app.chains.base import Quote
from app.execution.orders import Order
from app.execution.paper_broker import PaperBroker


def test_paper_fill_includes_slippage_and_gas() -> None:
    quote = Quote(
        token="0x1",
        side="buy",
        amount=100,
        mid_price=1.0,
        executable_price=1.02,
        timestamp=None,
    )
    broker = PaperBroker(lambda _: quote, initial_cash=1_000, fee_rate=0.01, gas_fee=2)
    order = Order(
        order_id="o1",
        chain="bnb",
        token="0x1",
        side="buy",
        amount=100,
        max_slippage_percent=3,
    )
    result = broker.submit(order)
    assert result.status == "filled"
    assert result.fill_price != quote.mid_price
    assert result.fees.total > 0
