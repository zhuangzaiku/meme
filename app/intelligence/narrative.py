from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class NarrativeEvidence:
    summary: str
    uncertainties: list[str]


class NarrativeAnalyzer:
    """Evidence summarizer with no order or risk authority."""

    def summarize(self, events: Iterable[Mapping[str, object]]) -> NarrativeEvidence:
        events = list(events)
        if not events:
            return NarrativeEvidence("no narrative evidence", ["no events supplied"])
        activities = [str(event.get("activity", "unknown")) for event in events]
        return NarrativeEvidence(
            summary=f"observed activities: {', '.join(activities[:5])}",
            uncertainties=["social evidence is non-authoritative"],
        )
