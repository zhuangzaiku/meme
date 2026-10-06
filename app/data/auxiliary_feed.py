from __future__ import annotations

import json
from collections.abc import Mapping

from app.data.collectors import normalize_swap
from app.data.events import MarketEvent


class AuxiliaryFeed:
    """Parse authorized structured wallet feeds without scraping platform HTML."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.observation_only = True

    def parse(self, payload: str | Mapping[str, object]) -> list[MarketEvent]:
        value = json.loads(payload) if isinstance(payload, str) else dict(payload)
        records = value.get("events", [value])
        if not isinstance(records, list):
            raise ValueError("auxiliary feed events must be a list")
        events: list[MarketEvent] = []
        for record in records:
            if not isinstance(record, Mapping):
                raise ValueError("auxiliary feed event must be an object")
            event_type = record.get("type", "swap")
            if event_type != "swap":
                raise ValueError(f"unsupported auxiliary event type: {event_type}")
            events.append(normalize_swap(record))
        return events
