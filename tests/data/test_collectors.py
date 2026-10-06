from app.data.collectors import normalize_swap


def test_swap_normalization_preserves_chain_and_token() -> None:
    event = normalize_swap({"chain": "bnb", "token": "0x1", "amount": "2.5"})
    assert event.chain == "bnb"
    assert event.token == "0x1"
    assert event.amount == 2.5
