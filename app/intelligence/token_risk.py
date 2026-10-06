from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RiskDecision:
    action: str
    reasons: list[str] = field(default_factory=list)

    @classmethod
    def allow(cls) -> RiskDecision:
        return cls("ALLOW")

    @classmethod
    def block(cls, reason: str) -> RiskDecision:
        return cls("BLOCK", [reason])


@dataclass(frozen=True)
class TokenRiskSnapshot:
    mint_authority_risky: bool = False
    freeze_authority_risky: bool = False
    blacklist_risky: bool = False
    honeypot_risk: bool = False
    dev_selling: bool = False
    lp_removed: bool = False
    liquidity_ok: bool = True
    insider_concentration_high: bool = False
    bundler_concentration_high: bool = False
    sniper_concentration_high: bool = False
    coordinated_wallets: bool = False
    data_fresh: bool = True
    quote_slippage_percent: float | None = None
    max_slippage_percent: float = 1.5


class TokenRisk:
    def evaluate(self, snapshot: TokenRiskSnapshot) -> RiskDecision:
        checks = (
            (snapshot.mint_authority_risky, "mint authority risk"),
            (snapshot.freeze_authority_risky, "freeze authority risk"),
            (snapshot.blacklist_risky, "blacklist risk"),
            (snapshot.honeypot_risk, "honeypot risk"),
            (snapshot.dev_selling, "dev distribution"),
            (snapshot.lp_removed, "LP removed"),
            (not snapshot.liquidity_ok, "liquidity below minimum"),
            (snapshot.insider_concentration_high, "insider concentration"),
            (snapshot.bundler_concentration_high, "bundler concentration"),
            (snapshot.sniper_concentration_high, "sniper concentration"),
            (snapshot.coordinated_wallets, "wallet coordination"),
            (not snapshot.data_fresh, "stale security data"),
            (
                snapshot.quote_slippage_percent is not None
                and snapshot.quote_slippage_percent > snapshot.max_slippage_percent,
                "quote slippage limit",
            ),
        )
        reasons = [reason for failed, reason in checks if failed]
        return RiskDecision("BLOCK", reasons) if reasons else RiskDecision.allow()
