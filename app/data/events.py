from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MarketEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chain: str
    token: str
    timestamp: datetime
    source: str = "unknown"

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value


class PriceTick(MarketEvent):
    price: float = Field(gt=0)


class Swap(MarketEvent):
    wallet: str
    side: str
    amount: float = Field(gt=0)
    price: float | None = Field(default=None, gt=0)


class LiquidityChange(MarketEvent):
    liquidity: float = Field(ge=0)


class HolderSnapshot(MarketEvent):
    holder_count: int = Field(ge=0)


class WalletBuy(MarketEvent):
    wallet: str
    amount: float = Field(gt=0)


class WalletSell(MarketEvent):
    wallet: str
    amount: float = Field(gt=0)


class DevTransfer(MarketEvent):
    wallet: str
    amount: float = Field(ge=0)
    direction: str


class TokenSecurityUpdate(MarketEvent):
    passed: bool
    indicators: list[str] = Field(default_factory=list)


class SocialActivity(MarketEvent):
    activity: str
    metrics: dict[str, Any] = Field(default_factory=dict)
