from __future__ import annotations

ALLOWED_TRADE_SHAPES = frozenset(
    {"early_convergence", "migration_pullback", "second_leg_restart"}
)


def is_allowed_trade_shape(value: str | None) -> bool:
    return value in ALLOWED_TRADE_SHAPES
