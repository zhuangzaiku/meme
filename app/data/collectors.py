from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping
from datetime import UTC, datetime

from app.data.connector_health import ConnectorHealth
from app.data.events import MarketEvent, Swap
from app.storage.repository import EventRepository


def _parse_timestamp(value: object) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise ValueError("event timestamp must be an ISO string or datetime")


def _as_float(value: object) -> float:
    if isinstance(value, (float, int, str)):
        return float(value)
    raise ValueError("numeric event field is invalid")


def normalize_swap(raw: Mapping[str, object]) -> Swap:
    return Swap(
        chain=str(raw["chain"]),
        token=str(raw["token"]),
        wallet=str(raw.get("wallet", "unknown")),
        side=str(raw.get("side", "buy")),
        amount=_as_float(raw["amount"]),
        price=_as_float(raw["price"]) if raw.get("price") is not None else None,
        source=str(raw.get("source", "unknown")),
        timestamp=_parse_timestamp(raw.get("timestamp")),
    )


class Collector:
    def __init__(
        self,
        source_name: str,
        event_source: Callable[[], Awaitable[Iterable[MarketEvent]]],
        repository: EventRepository,
    ) -> None:
        self.source_name = source_name
        self.event_source = event_source
        self.repository = repository
        self.health = ConnectorHealth(source_name, "unavailable")

    async def run_once(self) -> list[MarketEvent]:
        try:
            events = list(await self.event_source())
        except Exception as exc:  # connector failures become health state
            self.health = ConnectorHealth(self.source_name, "degraded", error=str(exc))
            return []
        for event in events:
            self.repository.save_event(event)
        self.health = ConnectorHealth(
            self.source_name,
            "ready",
            last_event_at=events[-1].timestamp if events else None,
        )
        return events

    async def stream(self, source: AsyncIterator[MarketEvent]) -> AsyncIterator[MarketEvent]:
        try:
            async for event in source:
                self.repository.save_event(event)
                self.health = ConnectorHealth(self.source_name, "ready", event.timestamp)
                yield event
        except Exception as exc:  # preserve the last good state and report failure
            self.health = ConnectorHealth(self.source_name, "degraded", error=str(exc))
