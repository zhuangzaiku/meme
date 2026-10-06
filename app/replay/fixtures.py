from __future__ import annotations

from collections.abc import Iterable

from app.replay.metrics import FillRecord


def synthetic_fills(count: int, chains: Iterable[str]) -> list[FillRecord]:
    chain_list = list(chains)
    if not chain_list:
        raise ValueError("at least one chain is required")
    shapes = ("early_convergence", "migration_pullback", "second_leg_restart")
    return [
        FillRecord(
            pnl=4.0 if index % 3 else -2.0,
            costs=0.5,
            chain=chain_list[index % len(chain_list)],
            strategy_shape=shapes[index % len(shapes)],
        )
        for index in range(count)
    ]
