from app.execution.wallet import WalletManager


def test_paper_mode_does_not_load_signer() -> None:
    manager = WalletManager()
    assert manager.load_signer("bnb", "paper") is None
