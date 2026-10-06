from __future__ import annotations

from app.strategy.rules import is_allowed_trade_shape
from app.strategy.signals import Decision, StrategySnapshot


class StrategyEngine:
    def evaluate(self, snapshot: StrategySnapshot) -> Decision:
        if (
            snapshot.score_result.action == "BLOCK"
            or snapshot.candidate.risk_decision.action == "BLOCK"
        ):
            vetoes = snapshot.candidate.risk_decision.reasons or snapshot.score_result.vetoes
            return Decision.from_snapshot("BLOCK", "BLOCK", snapshot, vetoes=vetoes)
        if not snapshot.quote_fresh or not snapshot.security_fresh:
            return Decision.from_snapshot(
                "BLOCK",
                "BLOCK",
                snapshot,
                vetoes=["required data is stale"],
            )

        if snapshot.current_state == "PROBE":
            if not snapshot.structure_valid or snapshot.smart_money_distributing:
                return Decision.from_snapshot("EXIT", "EXIT", snapshot)
            if snapshot.capital_flow_positive and snapshot.holder_growth:
                return Decision.from_snapshot("ADD_CONFIRMATION", "CONFIRMED", snapshot)
            return Decision.from_snapshot("WATCH", "PROBE", snapshot)

        if snapshot.current_state == "CONFIRMED":
            if not snapshot.structure_valid or snapshot.smart_money_distributing:
                return Decision.from_snapshot("EXIT", "EXIT", snapshot)
            return Decision.from_snapshot("HOLD", "HOLD", snapshot)

        if not is_allowed_trade_shape(snapshot.trade_shape):
            return Decision.from_snapshot("WATCH", "WATCH", snapshot)
        if snapshot.score_result.action == "ARMED":
            return Decision.from_snapshot("BUY_PROBE", "ARMED", snapshot)
        return Decision.from_snapshot("WATCH", "WATCH", snapshot)
