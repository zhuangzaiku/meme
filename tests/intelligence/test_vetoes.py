from app.intelligence.token_risk import TokenRisk, TokenRiskSnapshot


def test_dev_distribution_is_a_hard_veto() -> None:
    snapshot = TokenRiskSnapshot(dev_selling=True)
    decision = TokenRisk().evaluate(snapshot)
    assert decision.action == "BLOCK"
    assert "dev" in decision.reasons[0].lower()


def test_safe_snapshot_is_allowed() -> None:
    decision = TokenRisk().evaluate(TokenRiskSnapshot())
    assert decision.action == "ALLOW"
