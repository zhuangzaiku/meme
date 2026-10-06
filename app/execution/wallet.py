from __future__ import annotations

from typing import Any, Literal, cast

import keyring
from eth_account import Account
from eth_account.signers.base import BaseAccount

ExecutionMode = Literal["paper", "approval", "auto"]


class WalletManager:
    def __init__(self, keyring_backend: Any = keyring, username: str = "private_key") -> None:
        self.keyring = keyring_backend
        self.username = username

    def load_signer(self, chain: str, mode: ExecutionMode) -> BaseAccount | None:
        if mode == "paper":
            return None
        if mode not in ("approval", "auto"):
            raise ValueError(f"unsupported execution mode: {mode}")
        private_key = self.keyring.get_password(f"meme-agent/{chain}", self.username)
        if not private_key:
            raise RuntimeError(f"no signer configured for {chain}")
        return cast(BaseAccount, Account.from_key(private_key))
