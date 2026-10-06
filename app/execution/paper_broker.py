from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.chains.base import Quote
from app.execution.orders import Order


@dataclass(frozen=True)
class Fees:
    trading: float
    gas: float

    @property
    def total(self) -> float:
        return self.trading + self.gas


@dataclass(frozen=True)
class OrderResult:
    order_id: str
    status: str
    fill_price: float | None = None
    filled_amount: float = 0.0
    fees: Fees = Fees(0.0, 0.0)
    reason: str | None = None


@dataclass
class Position:
    chain: str
    token: str
    amount: float
    average_price: float


class PaperBroker:
    def __init__(
        self,
        quote_provider: Callable[[Order], Quote],
        initial_cash: float,
        fee_rate: float = 0.01,
        gas_fee: float = 0.0,
    ) -> None:
        self.quote_provider = quote_provider
        self.cash = initial_cash
        self.initial_cash = initial_cash
        self.fee_rate = fee_rate
        self.gas_fee = gas_fee
        self._positions: dict[tuple[str, str], Position] = {}

    def submit(self, order: Order) -> OrderResult:
        quote = self.quote_provider(order)
        fill_price = quote.executable_price
        slippage = abs(fill_price - quote.mid_price) / quote.mid_price * 100
        if slippage > order.max_slippage_percent:
            return OrderResult(order.order_id, "rejected", reason="slippage_limit")
        notional = order.amount * fill_price
        fees = Fees(notional * self.fee_rate, self.gas_fee)
        key = (order.chain, order.token)
        if order.side == "buy":
            if self.cash < notional + fees.total:
                return OrderResult(order.order_id, "rejected", reason="insufficient_cash")
            self.cash -= notional + fees.total
            position = self._positions.get(key)
            if position is None:
                self._positions[key] = Position(order.chain, order.token, order.amount, fill_price)
            else:
                total_amount = position.amount + order.amount
                position.average_price = (
                    position.amount * position.average_price + order.amount * fill_price
                ) / total_amount
                position.amount = total_amount
        else:
            position = self._positions.get(key)
            if position is None or position.amount < order.amount:
                return OrderResult(order.order_id, "rejected", reason="insufficient_position")
            position.amount -= order.amount
            self.cash += notional - fees.total
            if position.amount == 0:
                del self._positions[key]
        return OrderResult(order.order_id, "filled", fill_price, order.amount, fees)

    def positions(self) -> list[Position]:
        return list(self._positions.values())

    def equity(self) -> float:
        positions_value = sum(
            position.amount * position.average_price for position in self._positions.values()
        )
        return self.cash + positions_value
