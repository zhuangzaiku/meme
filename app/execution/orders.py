from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

OrderSide = Literal["buy", "sell"]


@dataclass(frozen=True)
class Order:
    order_id: str
    chain: str
    token: str
    side: OrderSide
    amount: float
    max_slippage_percent: float
    strategy_state: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
