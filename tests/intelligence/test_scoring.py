from app.intelligence.scoring import CandidateSnapshot, score_candidate
from app.intelligence.token_risk import RiskDecision


def test_candidate_needs_three_independent_wallets() -> None:
    candidate = CandidateSnapshot(
        wallet_quality=25,
        contract_distribution=30,
        capital_flow=25,
        narrative_social=10,
        market_position=10,
        independent_wallets=2,
        confirmation_signals=2,
        risk_decision=RiskDecision.allow(),
    )
    result = score_candidate(candidate)
    assert result.action == "WATCH"


def test_blocked_candidate_cannot_be_armed() -> None:
    candidate = CandidateSnapshot(
        wallet_quality=25,
        contract_distribution=30,
        capital_flow=25,
        narrative_social=10,
        market_position=10,
        independent_wallets=5,
        confirmation_signals=3,
        risk_decision=RiskDecision.block("dev distribution"),
    )
    result = score_candidate(candidate)
    assert result.action == "BLOCK"
