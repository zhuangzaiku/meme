from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.data.connector_health import ConnectorStatus
from app.data.events import ExternalSignal
from app.data.sources.models import PoolCandidate, SourceHealth

TOPIC_KEYWORDS = {
    "ai": ("ai", "agent", "gpt", "llm"),
    "animal": ("dog", "cat", "inu", "frog", "pepe"),
    "community": ("community", "cult", "army", "movement"),
    "gaming": ("game", "gaming", "play", "metaverse"),
    "politics": ("president", "politics", "maga", "election"),
    "rwa": ("rwa", "real world", "yield"),
}


def build_signature(sk: str, ak: str, timestamp: str, path: str, body: str) -> str:
    payload = ak + timestamp + "POST" + path + "" + body
    return hmac.new(sk.encode(), payload.encode(), hashlib.sha256).hexdigest()


class GmgnCalloutSource:
    """Read-only GMGN token callout enrichment for supported chains."""

    def __init__(
        self,
        ak: str | None,
        sk: str | None,
        proxy_url: str,
        base_url: str = "https://papi.gmgn.ai/callout/openapi/v1",
        timeout_seconds: float = 10.0,
        max_retries: int = 2,
        max_tokens: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        self.ak = ak
        self.sk = sk
        self.proxy_url = proxy_url
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.max_tokens = max_tokens
        self.transport = transport
        self.health = SourceHealth(name="gmgn:callout", status="unavailable")

    async def collect(self, candidates: list[PoolCandidate]) -> list[ExternalSignal]:
        now = datetime.now(UTC)
        if not self.ak or not self.sk:
            self.health = SourceHealth(
                name="gmgn:callout",
                status="unavailable",
                error="GMGN AK/SK credentials are not configured",
                observed_at=now,
            )
            return []

        selected = [candidate for candidate in candidates if candidate.chain == "bnb"][
            : self.max_tokens
        ]
        if not selected:
            self.health = SourceHealth(
                name="gmgn:callout", status="observation_only", observed_at=now
            )
            return []

        signals: list[ExternalSignal] = []
        errors: list[str] = []
        for candidate in selected:
            try:
                payload = await self._request_token(candidate)
                signal = self._parse_signal(candidate, payload, now)
                if signal is not None:
                    signals.append(signal)
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                errors.append(str(exc))

        status: ConnectorStatus
        if errors and not signals:
            status = "degraded"
        elif signals:
            status = "ready"
        else:
            status = "observation_only"
        self.health = SourceHealth(
            name="gmgn:callout",
            status=status,
            error="; ".join(errors) if errors else None,
            observed_at=now,
        )
        return signals

    async def _request_token(self, candidate: PoolCandidate) -> Mapping[str, Any]:
        chain = "bsc" if candidate.chain == "bnb" else candidate.network_id
        payload = {"chain": chain, "call_token": candidate.base_token, "limit": 50}
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        path = "/callout/openapi/v1/token"
        url = f"{self.base_url}/token"
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            timestamp = str(int(time.time() * 1000))
            headers = {
                "Content-Type": "application/json",
                "X-Ak": self.ak or "",
                "X-Timestamp": timestamp,
                "X-Signature": build_signature(self.sk or "", self.ak or "", timestamp, path, body),
            }
            client_kwargs: dict[str, Any] = {
                "timeout": self.timeout_seconds,
                "transport": self.transport,
            }
            if self.transport is None:
                client_kwargs["proxy"] = self.proxy_url
            try:
                async with httpx.AsyncClient(**client_kwargs) as client:
                    response = await client.post(url, content=body, headers=headers)
                if response.status_code >= 500:
                    response.raise_for_status()
                response.raise_for_status()
                result = response.json()
                if not isinstance(result, Mapping) or result.get("code") != 0:
                    raise ValueError(f"GMGN API error: {result}")
                data = result.get("data")
                if not isinstance(data, Mapping):
                    raise ValueError("GMGN response data is not an object")
                return data
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise
        raise RuntimeError("GMGN request failed") from last_error

    def _parse_signal(
        self,
        candidate: PoolCandidate,
        data: Mapping[str, Any],
        observed_at: datetime,
    ) -> ExternalSignal | None:
        raw_messages = data.get("messages", [])
        if not isinstance(raw_messages, list):
            raise ValueError("GMGN messages is not a list")
        messages = [message for message in raw_messages if isinstance(message, Mapping)]
        if not messages:
            return None
        wallets = {
            str(message["wallet_address"]).lower()
            for message in messages
            if message.get("wallet_address")
        }
        multipliers: list[Decimal] = []
        for message in messages:
            value = self._decimal(message.get("multiplier"))
            if value is not None:
                multipliers.append(value)
        positive_ratio = (
            sum(value > Decimal("1") for value in multipliers) / len(multipliers)
            if multipliers
            else 0.0
        )
        max_multiplier = max(multipliers, default=Decimal("0"))
        topics = self._topics(messages)
        authors = {
            str(message.get("username") or message.get("display_name"))
            for message in messages
            if message.get("username") or message.get("display_name")
        }
        followers = sum(self._int_value(message.get("follower_count")) for message in messages)
        interactions = sum(
            self._int_value(message.get("like_count"))
            + self._int_value(message.get("reply_count"))
            for message in messages
        )
        smart_money_score = min(
            100.0,
            min(40.0, len(wallets) * 20.0)
            + positive_ratio * 35.0
            + min(25.0, float(max_multiplier) * 5.0),
        )
        narrative_score = min(
            100.0,
            (30.0 if topics else 0.0)
            + min(40.0, len(topics) * 20.0)
            + min(30.0, len(messages) * 10.0),
        )
        social_score = min(
            100.0,
            min(40.0, len(authors) * 20.0)
            + min(35.0, followers / 1000.0)
            + min(25.0, interactions * 2.0),
        )
        ids = sorted(
            str(message.get("ulid") or message.get("id"))
            for message in messages
            if message.get("ulid") or message.get("id")
        )
        digest = hashlib.sha256("|".join(ids).encode()).hexdigest()[:16]
        return ExternalSignal(
            chain=candidate.chain,
            token=candidate.base_token,
            timestamp=observed_at,
            source="gmgn:callout",
            source_event_id=f"gmgn:{candidate.chain}:{candidate.base_token}:{digest}",
            pool_address=candidate.pool_address,
            smart_money_score=smart_money_score,
            narrative_score=narrative_score,
            social_score=social_score,
            unique_callout_wallets=len(wallets),
            callout_count=len(messages),
            kol_count=0,
            topic_tags=topics,
            evidence=[
                f"gmgn_callouts={len(messages)}",
                f"gmgn_unique_wallets={len(wallets)}",
                f"gmgn_topics={','.join(topics) or 'none'}",
            ],
        )

    @staticmethod
    def _topics(messages: list[Mapping[str, Any]]) -> list[str]:
        text = " ".join(str(message.get("content", "")) for message in messages).lower()
        return [
            topic
            for topic, keywords in TOPIC_KEYWORDS.items()
            if any(re.search(rf"\b{re.escape(keyword)}\b", text) for keyword in keywords)
        ]

    @staticmethod
    def _decimal(value: object) -> Decimal | None:
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def _int_value(value: object) -> int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float, str)):
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                return 0
        return 0
