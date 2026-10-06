from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class AuditEvent:
    event: str
    details: dict[str, object]
    timestamp: datetime

    def as_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["timestamp"] = self.timestamp.isoformat()
        return value


class AuditLog:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, event: str, **details: object) -> AuditEvent:
        entry = AuditEvent(event, details, datetime.now(UTC))
        self.events.append(entry)
        return entry
