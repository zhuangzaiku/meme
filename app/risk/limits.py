from __future__ import annotations

from dataclasses import dataclass

from app.execution.orders import Order


@dataclass(frozen=True)
class AccountSnapshot:
    equity: float
    cash: float
    daily_pnl: float
    consecutive_losses: int
    open_positions: int
    narrative_exposure: float


@dataclass(frozen=True)
class MarketSnapshot:
    price: float
    quote_fresh: bool = True
    slippage_percent: float = 0.0


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    code: str = "allowed"
    reasons: list[str] | None = None


class RiskEngine:
    def __init__(
        self,
        risk_per_trade: float = 0.0025,
        max_position_percent: float = 0.03,
        max_concurrent_positions: int = 5,
        max_narrative_exposure: float = 0.08,
        max_slippage_percent: float = 1.5,
        daily_loss_limit: float = 0.015,
        max_consecutive_losses: int = 3,
        reserve_balance_percent: float = 20.0,
    ) -> None:
        self.risk_per_trade = risk_per_trade
        self.max_position_percent = max_position_percent
        self.max_concurrent_positions = max_concurrent_positions
        self.max_narrative_exposure = max_narrative_exposure
        self.max_slippage_percent = max_slippage_percent
        self.daily_loss_limit = daily_loss_limit
        self.max_consecutive_losses = max_consecutive_losses
        self.reserve_balance_percent = reserve_balance_percent

    def check(
        self, order: Order, account: AccountSnapshot, market: MarketSnapshot
    ) -> RiskDecision:
        if account.equity <= 0:
            return RiskDecision(False, "invalid_equity", ["equity must be positive"])
        if order.side == "buy" and account.daily_pnl <= -account.equity * self.daily_loss_limit:
            return RiskDecision(False, "daily_loss_limit", ["daily loss limit reached"])
        if order.side == "buy" and account.consecutive_losses >= self.max_consecutive_losses:
            return RiskDecision(False, "consecutive_loss_limit", ["consecutive loss limit reached"])
        if order.side == "buy" and account.open_positions >= self.max_concurrent_positions:
            return RiskDecision(False, "position_limit", ["maximum open positions reached"])
        if order.side == "buy" and account.narrative_exposure >= self.max_narrative_exposure:
            return RiskDecision(False, "narrative_exposure", ["narrative exposure limit reached"])
        if not market.quote_fresh:
            return RiskDecision(False, "stale_quote", ["quote is stale"])
        if market.slippage_percent > min(order.max_slippage_percent, self.max_slippage_percent):
            return RiskDecision(False, "slippage_limit", ["slippage limit exceeded"])
        if order.side == "buy":
            notional = order.amount * market.price
            if notional > account.equity * self.max_position_percent:
                return RiskDecision(False, "position_size", ["position size limit exceeded"])
            reserve = account.equity * self.reserve_balance_percent / 100
            if account.cash - notional < reserve:
                return RiskDecision(False, "balance_reserve", ["balance reserve would be breached"])
        return RiskDecision(True)
