from datetime import UTC, datetime

import pytest

from app.data.sources.models import PoolCandidate


def test_pool_candidate_normalizes_addresses() -> None:
    candidate = PoolCandidate(
        chain="robinhood",
        network_id="robinhood",
        pool_address="0x0000000000000000000000000000000000000ABC",
        dex_id="uniswap-v3-robinhood",
        base_token="0x0000000000000000000000000000000000000DEF",
        quote_token="0x0000000000000000000000000000000000000123",
        observed_at=datetime.now(UTC),
    )

    assert candidate.pool_address == "0x0000000000000000000000000000000000000abc"
    assert candidate.base_token == "0x0000000000000000000000000000000000000def"


def test_pool_candidate_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone"):
        PoolCandidate(
            chain="bnb",
            network_id="bsc",
            pool_address="0x0000000000000000000000000000000000000abc",
            dex_id="pancakeswap",
            base_token="0x0000000000000000000000000000000000000def",
            quote_token="0x0000000000000000000000000000000000000123",
            observed_at=datetime(2026, 1, 1),
        )


def test_pool_candidate_accepts_solana_base58_addresses() -> None:
    candidate = PoolCandidate(
        chain="sol",
        network_id="solana",
        pool_address="So11111111111111111111111111111111111111112",
        dex_id="raydium",
        base_token="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        quote_token="So11111111111111111111111111111111111111112",
        observed_at=datetime.now(UTC),
    )

    assert candidate.pool_address == "So11111111111111111111111111111111111111112"
    assert candidate.base_token == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def test_pool_candidate_rejects_malformed_solana_address() -> None:
    with pytest.raises(ValueError, match="Solana"):
        PoolCandidate(
            chain="sol",
            network_id="solana",
            pool_address="not-a-public-key",
            dex_id="raydium",
            base_token="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            quote_token="So11111111111111111111111111111111111111112",
            observed_at=datetime.now(UTC),
        )
