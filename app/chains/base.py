from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class Quote:
    token: str
    side: Literal["buy", "sell"]
    amount: int
    mid_price: float
    executable_price: float
    liquidity: float | None = None
    timestamp: datetime | None = None


@dataclass(frozen=True)
class OrderIntent:
    chain: str
    token: str
    side: Literal["buy", "sell"]
    amount: int
    max_slippage_percent: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SimulationResult:
    ok: bool
    expected_price: float | None = None
    gas_wei: int = 0
    price_impact_percent: float = 0.0
    error: str | None = None


@dataclass(frozen=True)
class ChainEvent:
    chain: str
    kind: str
    block_number: int
    timestamp: datetime
    payload: dict[str, Any] = field(default_factory=dict)


class ChainAdapter(Protocol):
    async def get_latest_block(self) -> int: ...

    async def get_chain_id(self) -> int: ...

    async def get_balance(self, address: str) -> int: ...

    async def get_quote(self, token: str, amount: int, side: str) -> Quote: ...

    async def simulate_swap(self, order: OrderIntent) -> SimulationResult: ...

    def subscribe_events(self) -> AsyncIterator[ChainEvent]: ...
