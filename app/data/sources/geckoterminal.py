from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx

from app.data.connector_health import ConnectorStatus
from app.data.sources.models import PoolCandidate, SourceHealth


class GeckoTerminalSource:
    def __init__(
        self,
        network_id: str,
        proxy_url: str,
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
        max_pools: int = 50,
        transport: httpx.AsyncBaseTransport | None = None,
        retry_base_seconds: float = 0.25,
        cache_seconds: int = 60,
        stale_cache_seconds: int = 300,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if max_pools < 1:
            raise ValueError("max_pools must be positive")
        if stale_cache_seconds < cache_seconds:
            raise ValueError("stale_cache_seconds must be at least cache_seconds")
        self.network_id = network_id
        self.proxy_url = proxy_url
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.max_pools = max_pools
        self.transport = transport
        self.retry_base_seconds = retry_base_seconds
        self.cache_seconds = cache_seconds
        self.stale_cache_seconds = stale_cache_seconds
        self.health = SourceHealth(name=f"geckoterminal:{network_id}", status="unavailable")
        self._cache: list[PoolCandidate] = []
        self._cached_at: datetime | None = None

    async def discover_pools(self) -> list[PoolCandidate]:
        now = datetime.now(UTC)
        if (
            self._cached_at is not None
            and (now - self._cached_at).total_seconds() < self.cache_seconds
        ):
            self.health = self.health.model_copy(update={"observed_at": now})
            return list(self._cache)

        url = f"https://api.geckoterminal.com/api/v2/networks/{self.network_id}/pools?page=1"
        last_error = "source request failed"
        for attempt in range(self.max_retries + 1):
            try:
                client_kwargs: dict[str, Any] = {
                    "timeout": self.timeout_seconds,
                    "transport": self.transport,
                }
                if self.transport is None:
                    client_kwargs["proxy"] = self.proxy_url
                async with httpx.AsyncClient(**client_kwargs) as client:
                    response = await client.get(url)
                if 500 <= response.status_code:
                    response.raise_for_status()
                if 400 <= response.status_code:
                    response.raise_for_status()
                candidates = self._parse(response.json(), now)
                self._cache = candidates
                self._cached_at = now
                status: ConnectorStatus = "ready" if candidates else "observation_only"
                self.health = SourceHealth(
                    name=f"geckoterminal:{self.network_id}",
                    status=status,
                    observed_at=now,
                )
                return list(candidates)
            except httpx.HTTPStatusError as exc:
                last_error = f"http {exc.response.status_code}"
                if exc.response.status_code < 500:
                    break
            except (httpx.TimeoutException, httpx.TransportError, ValueError) as exc:
                last_error = str(exc)
            if attempt < self.max_retries:
                await asyncio.sleep(self.retry_base_seconds * (2**attempt))

        if self._cached_at is not None and (
            now - self._cached_at
        ).total_seconds() <= self.stale_cache_seconds:
            self.health = SourceHealth(
                name=f"geckoterminal:{self.network_id}",
                status="observation_only",
                error=f"{last_error}; using cached pools",
                observed_at=now,
            )
            return list(self._cache)
        self.health = SourceHealth(
            name=f"geckoterminal:{self.network_id}",
            status="degraded",
            error=last_error,
            observed_at=now,
        )
        return []

    def _parse(self, payload: object, observed_at: datetime) -> list[PoolCandidate]:
        if not isinstance(payload, dict):
            raise ValueError("GeckoTerminal response must be an object")
        raw_data = payload.get("data")
        if not isinstance(raw_data, list):
            raise ValueError("GeckoTerminal response data must be a list")
        candidates: list[PoolCandidate] = []
        chain = {"bsc": "bnb", "solana": "sol"}.get(self.network_id, self.network_id)
        for item in raw_data[: self.max_pools]:
            if not isinstance(item, dict):
                continue
            attributes = item.get("attributes")
            relationships = item.get("relationships")
            if not isinstance(attributes, dict) or not isinstance(relationships, dict):
                continue
            pool_address = attributes.get("address")
            base_token = self._relationship_address(relationships, "base_token")
            quote_token = self._relationship_address(relationships, "quote_token")
            dex_id = self._relationship_id(relationships, "dex")
            if not isinstance(pool_address, str):
                continue
            if not isinstance(base_token, str):
                continue
            if not isinstance(quote_token, str):
                continue
            if not isinstance(dex_id, str):
                continue
            try:
                candidates.append(
                    PoolCandidate(
                        chain=chain,
                        network_id=self.network_id,
                        pool_address=pool_address,
                        dex_id=dex_id,
                        base_token=base_token,
                        quote_token=quote_token,
                        price_usd=self._positive_float(attributes.get("base_token_price_usd")),
                        reserve_usd=self._non_negative_float(attributes.get("reserve_in_usd")),
                        observed_at=observed_at,
                    )
                )
            except ValueError:
                continue
        return candidates

    def _relationship_address(self, relationships: dict[str, Any], name: str) -> str | None:
        relationship = relationships.get(name)
        if not isinstance(relationship, dict):
            return None
        data = relationship.get("data")
        if not isinstance(data, dict):
            return None
        value = data.get("id")
        if not isinstance(value, str):
            return None
        prefix = f"{self.network_id}_"
        return value[len(prefix) :] if value.startswith(prefix) else None

    @staticmethod
    def _relationship_id(relationships: dict[str, Any], name: str) -> str | None:
        relationship = relationships.get(name)
        if not isinstance(relationship, dict):
            return None
        data = relationship.get("data")
        if not isinstance(data, dict):
            return None
        value = data.get("id")
        return value if isinstance(value, str) else None

    @staticmethod
    def _positive_float(value: object) -> float | None:
        if not isinstance(value, (float, int, str)) or isinstance(value, bool):
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _non_negative_float(value: object) -> float | None:
        if not isinstance(value, (float, int, str)) or isinstance(value, bool):
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed >= 0 else None
