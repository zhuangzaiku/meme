from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.data.sources.composite_discovery import CompositePoolDiscovery
from app.data.sources.models import PoolCandidate, SourceHealth

NOW = datetime.now(UTC)
POOL = "0x00000000000000000000000000000000000000aa"
TOKEN0 = "0x00000000000000000000000000000000000000bb"
TOKEN1 = "0x00000000000000000000000000000000000000cc"


def native_candidate() -> PoolCandidate:
    return PoolCandidate(
        chain="bnb",
        network_id="bsc",
        pool_address=POOL,
        dex_id="pancakeswap-v2",
        base_token=TOKEN0,
        quote_token=TOKEN1,
        base_is_token0=True,
        observed_at=NOW,
    )


def gecko_candidate() -> PoolCandidate:
    return PoolCandidate(
        chain="bnb",
        network_id="bsc",
        pool_address=POOL,
        dex_id="gecko-pool",
        base_token=TOKEN0,
        quote_token=TOKEN1,
        price_usd=0.12,
        reserve_usd=1234.0,
        observed_at=NOW,
    )


class FakeSource:
    def __init__(self, name: str, candidates: list[PoolCandidate]) -> None:
        self.health = SourceHealth(name=name, status="ready")
        self.candidates = candidates

    async def discover_pools(self) -> list[PoolCandidate]:
        return self.candidates


class FailingSource:
    def __init__(self, name: str) -> None:
        self.health = SourceHealth(name=name, status="unavailable")

    async def discover_pools(self) -> list[PoolCandidate]:
        raise ConnectionError("source unavailable")


@pytest.mark.asyncio
async def test_native_identity_wins_and_gecko_metadata_is_retained() -> None:
    source = CompositePoolDiscovery(
        [
            FakeSource("bsc:native", [native_candidate()]),
            FakeSource("gecko:bsc", [gecko_candidate()]),
        ]
    )

    pools = await source.discover_pools()

    assert len(pools) == 1
    assert pools[0].dex_id == "pancakeswap-v2"
    assert pools[0].reserve_usd == 1234.0
    assert pools[0].price_usd == 0.12


@pytest.mark.asyncio
async def test_one_failed_source_does_not_block_healthy_source() -> None:
    source = CompositePoolDiscovery(
        [FailingSource("bsc:native"), FakeSource("gecko:bsc", [gecko_candidate()])]
    )

    pools = await source.discover_pools()

    assert len(pools) == 1
    assert source.health.status in {"ready", "observation_only"}
    assert "source unavailable" in (source.health.error or "")
