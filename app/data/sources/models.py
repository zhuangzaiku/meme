from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator
from web3 import Web3

from app.data.connector_health import ConnectorStatus


class PoolCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chain: str
    network_id: str
    pool_address: str
    dex_id: str
    base_token: str
    quote_token: str
    base_is_token0: bool | None = None
    price_usd: float | None = Field(default=None, gt=0)
    reserve_usd: float | None = Field(default=None, ge=0)
    observed_at: datetime

    @field_validator("pool_address", "base_token", "quote_token")
    @classmethod
    def normalize_address(cls, value: str) -> str:
        if not Web3.is_address(value):
            raise ValueError("invalid EVM address")
        return value.lower()

    @field_validator("observed_at")
    @classmethod
    def timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value


class SourceHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: ConnectorStatus
    error: str | None = None
    observed_at: datetime | None = None
