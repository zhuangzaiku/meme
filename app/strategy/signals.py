from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from app.intelligence.scoring import CandidateSnapshot, ScoreResult

StrategyState = Literal[
    "WATCH",
    "ARMED",
    "PROBE",
    "CONFIRMED",
    "HOLD",
    "REDUCE",
    "EXIT",
    "BLOCK",
    "PAUSE",
]


@dataclass
class StrategySnapshot:
    score_result: ScoreResult
    candidate: CandidateSnapshot
    trade_shape: str | None
    quote_fresh: bool
    security_fresh: bool
    structure_valid: bool
    capital_flow_positive: bool
    holder_growth: bool
    smart_money_distributing: bool
    now: datetime
    current_state: StrategyState = "WATCH"


@dataclass(frozen=True)
class Decision:
    action: str
    state: StrategyState
    score: float
    evidence: list[str]
    vetoes: list[str]
    expiry: datetime | None = None

    @classmethod
    def from_snapshot(
        cls,
        action: str,
        state: StrategyState,
        snapshot: StrategySnapshot,
        evidence: list[str] | None = None,
        vetoes: list[str] | None = None,
    ) -> Decision:
        return cls(
            action=action,
            state=state,
            score=snapshot.score_result.score,
            evidence=evidence or snapshot.score_result.evidence,
            vetoes=vetoes or snapshot.score_result.vetoes,
            expiry=snapshot.now + timedelta(minutes=5),
        )
