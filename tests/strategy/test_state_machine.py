from datetime import UTC, datetime

from app.intelligence.scoring import CandidateSnapshot, ScoreResult
from app.intelligence.token_risk import RiskDecision
from app.strategy.signals import StrategySnapshot
from app.strategy.state_machine import StrategyEngine


def armed_snapshot() -> StrategySnapshot:
    candidate = CandidateSnapshot(
        wallet_quality=25,
        contract_distribution=30,
        capital_flow=25,
        narrative_social=10,
        market_position=10,
        independent_wallets=3,
        confirmation_signals=2,
        risk_decision=RiskDecision.allow(),
    )
    return StrategySnapshot(
        score_result=ScoreResult("ARMED", 100, ["test"], []),
        candidate=candidate,
        trade_shape="early_convergence",
        quote_fresh=True,
        security_fresh=True,
        structure_valid=True,
        capital_flow_positive=True,
        holder_growth=True,
        smart_money_distributing=False,
        now=datetime.now(UTC),
    )


def test_three_independent_wallets_and_two_confirmations_arm() -> None:
    decision = StrategyEngine().evaluate(armed_snapshot())
    assert decision.state == "ARMED"
    assert decision.action == "BUY_PROBE"


def test_stale_quote_blocks_new_position() -> None:
    snapshot = armed_snapshot()
    snapshot.quote_fresh = False
    decision = StrategyEngine().evaluate(snapshot)
    assert decision.state == "BLOCK"
    assert decision.action == "BLOCK"


def test_blocked_candidate_cannot_be_armed() -> None:
    snapshot = armed_snapshot()
    snapshot.candidate = CandidateSnapshot(
        wallet_quality=25,
        contract_distribution=30,
        capital_flow=25,
        narrative_social=10,
        market_position=10,
        independent_wallets=3,
        confirmation_signals=2,
        risk_decision=RiskDecision.block("honeypot"),
    )
    decision = StrategyEngine().evaluate(snapshot)
    assert decision.state == "BLOCK"
