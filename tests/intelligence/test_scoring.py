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


def test_external_callout_signal_increases_candidate_score() -> None:
    base = CandidateSnapshot(
        wallet_quality=10,
        contract_distribution=15,
        capital_flow=10,
        narrative_social=4,
        market_position=5,
        independent_wallets=3,
        confirmation_signals=2,
        risk_decision=RiskDecision.allow(),
    )
    enriched = CandidateSnapshot(
        **{
            **base.__dict__,
            "external_smart_money": 80,
            "external_narrative": 70,
            "external_social": 60,
        }
    )

    assert score_candidate(enriched).score > score_candidate(base).score
