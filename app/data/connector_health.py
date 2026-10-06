from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

ConnectorStatus = Literal["ready", "degraded", "unavailable", "observation_only"]


@dataclass
class ConnectorHealth:
    name: str
    status: ConnectorStatus
    last_event_at: datetime | None = None
    error: str | None = None

    @property
    def trade_ready(self) -> bool:
        return self.status == "ready"
