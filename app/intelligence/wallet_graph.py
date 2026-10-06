from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WalletSnapshot:
    wallet: str
    funder: str | None = None


class WalletGraph:
    def are_independent(self, wallets: list[WalletSnapshot]) -> bool:
        addresses = {snapshot.wallet.lower() for snapshot in wallets}
        if len(addresses) != len(wallets):
            return False
        funders = [snapshot.funder.lower() for snapshot in wallets if snapshot.funder]
        return len(funders) == len(set(funders))
