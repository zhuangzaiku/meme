from datetime import UTC, datetime, timedelta

from app.data.events import Swap
from app.data.sources.fusion import MarketFusion
from app.data.sources.models import PoolCandidate


def candidate(pool_address: str) -> PoolCandidate:
    return PoolCandidate(
        chain="bnb",
        network_id="bsc",
        pool_address=pool_address,
        dex_id="pancakeswap-v2",
        base_token="0x00000000000000000000000000000000000000bb",
        quote_token="0x00000000000000000000000000000000000000cc",
        base_is_token0=True,
        observed_at=datetime.now(UTC),
    )


def swap(pool_address: str) -> Swap:
    return Swap(
        chain="bnb",
        token="0x00000000000000000000000000000000000000bb",
        wallet="0x00000000000000000000000000000000000000dd",
        side="buy",
        amount=1,
        price=1,
        timestamp=datetime.now(UTC),
        pool_address=pool_address,
    )


def test_fusion_blocks_api_rpc_pool_mismatch() -> None:
    result = MarketFusion().fuse(
        candidate("0x00000000000000000000000000000000000000aa"),
        [swap("0x00000000000000000000000000000000000000bb")],
        datetime.now(UTC),
    )

    assert result.status == "degraded"
    assert "pool identity" in result.reasons[0]


def test_fusion_marks_old_event_observation_only() -> None:
    old = swap("0x00000000000000000000000000000000000000aa").model_copy(
        update={"timestamp": datetime.now(UTC) - timedelta(minutes=10)}
    )

    result = MarketFusion().fuse(
        candidate("0x00000000000000000000000000000000000000aa"),
        [old],
        datetime.now(UTC),
    )

    assert result.status == "observation_only"
