from app.intelligence.wallet_graph import WalletGraph, WalletSnapshot


def test_funded_by_same_source_wallets_are_not_independent() -> None:
    snapshots = [
        WalletSnapshot(wallet="0x1", funder="0xfunder"),
        WalletSnapshot(wallet="0x2", funder="0xfunder"),
    ]
    assert WalletGraph().are_independent(snapshots) is False


def test_wallets_with_different_funders_are_independent() -> None:
    snapshots = [
        WalletSnapshot(wallet="0x1", funder="0xfunder1"),
        WalletSnapshot(wallet="0x2", funder="0xfunder2"),
    ]
    assert WalletGraph().are_independent(snapshots) is True
