from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from web3 import Web3

from app.data.connector_health import ConnectorStatus

SOLANA_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


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

    @model_validator(mode="after")
    def validate_addresses(self) -> PoolCandidate:
        addresses = (self.pool_address, self.base_token, self.quote_token)
        if self.chain == "sol":
            if any(not _is_solana_public_key(value) for value in addresses):
                raise ValueError("invalid Solana public key")
            return self
        if any(not Web3.is_address(value) for value in addresses):
            raise ValueError("invalid EVM address")
        self.pool_address = self.pool_address.lower()
        self.base_token = self.base_token.lower()
        self.quote_token = self.quote_token.lower()
        return self

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


def _is_solana_public_key(value: str) -> bool:
    if not value or any(character not in SOLANA_BASE58_ALPHABET for character in value):
        return False
    number = 0
    for character in value:
        number = number * 58 + SOLANA_BASE58_ALPHABET.index(character)
    decoded = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    leading_zeroes = len(value) - len(value.lstrip("1"))
    return len(b"\x00" * leading_zeroes + decoded) == 32
