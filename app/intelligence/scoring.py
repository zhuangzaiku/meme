from __future__ import annotations

from dataclasses import dataclass, replace

from app.intelligence.token_risk import RiskDecision

WEIGHTS = {
    "wallet_quality": 25,
    "contract_distribution": 30,
    "capital_flow": 25,
    "narrative_social": 10,
    "market_position": 10,
}


@dataclass(frozen=True)
class CandidateSnapshot:
    wallet_quality: float
    contract_distribution: float
    capital_flow: float
    narrative_social: float
    market_position: float
    independent_wallets: int
    confirmation_signals: int
    risk_decision: RiskDecision
    trade_shape: str | None = None

    def with_independent_wallets(self, count: int) -> CandidateSnapshot:
        return replace(self, independent_wallets=count)


@dataclass(frozen=True)
class ScoreResult:
    action: str
    score: float
    evidence: list[str]
    vetoes: list[str]


def _bounded(value: float, maximum: int) -> float:
    return max(0.0, min(float(value), float(maximum)))


def score_candidate(candidate: CandidateSnapshot) -> ScoreResult:
    if candidate.risk_decision.action == "BLOCK":
        return ScoreResult("BLOCK", 0.0, [], candidate.risk_decision.reasons)

    score = sum(
        _bounded(getattr(candidate, name), maximum) for name, maximum in WEIGHTS.items()
    )
    evidence = [f"score={score:.1f}", f"independent_wallets={candidate.independent_wallets}"]
    if candidate.independent_wallets < 3:
        return ScoreResult("WATCH", score, evidence, [])
    if candidate.confirmation_signals < 2:
        return ScoreResult("WATCH", score, evidence, [])
    if score >= 80:
        return ScoreResult("ARMED", score, evidence, [])
    if score >= 75:
        return ScoreResult("PROBE_ONLY", score, evidence, [])
    return ScoreResult("WATCH", score, evidence, [])
