from __future__ import annotations

from datetime import UTC, datetime

import pytest
from eth_abi import encode

from app.data.sources.evm_logs import V2_SWAP_TOPIC
from app.data.sources.evm_market import EvmMarketCollector
from app.data.sources.models import PoolCandidate

NOW = datetime.now(UTC)


def candidate() -> PoolCandidate:
    return PoolCandidate(
        chain="bnb",
        network_id="bsc",
        pool_address="0x00000000000000000000000000000000000000aa",
        dex_id="pancakeswap-v2",
        base_token="0x00000000000000000000000000000000000000bb",
        quote_token="0x00000000000000000000000000000000000000cc",
        base_is_token0=True,
        observed_at=NOW,
    )


class FakeRpc:
    def __init__(self, latest_block: int = 120, fail_from: int | None = None) -> None:
        self.latest_block = latest_block
        self.fail_from = fail_from
        self.calls: list[tuple[int, int]] = []
        self.code_calls: list[str] = []
        self.token0_calls: list[str] = []

    async def get_chain_id(self) -> int:
        return 56

    async def get_latest_block(self) -> int:
        return self.latest_block

    async def get_code(self, address: str) -> str:
        self.code_calls.append(address)
        return "0x1234"

    async def get_pool_token0(self, address: str) -> str:
        self.token0_calls.append(address)
        return candidate().base_token

    async def get_logs(
        self, address: str, topics: list[str], from_block: int, to_block: int
    ) -> list[dict[str, object]]:
        self.calls.append((from_block, to_block))
        if self.fail_from == from_block:
            raise ConnectionError("rpc log failure")
        return [
            {
                "topics": [V2_SWAP_TOPIC],
                "data": "0x" + encode(["uint256"] * 4, [0, 1_000_000, 500_000, 0]).hex(),
                "transactionHash": "0xabc",
                "logIndex": "0x3",
                "blockNumber": hex(to_block),
            }
        ]

    async def get_block_timestamp(self, block_number: int) -> datetime:
        return NOW


@pytest.mark.asyncio
async def test_collector_uses_bounded_initial_range_and_advances_cursor() -> None:
    rpc = FakeRpc(latest_block=120)
    collector = EvmMarketCollector(rpc, expected_chain_id=56, max_log_block_span=50)

    events = await collector.collect([candidate()])

    assert rpc.calls == [(71, 120)]
    assert collector.cursor("bnb", candidate().pool_address) == 120
    assert len(events) == 1
    assert events[0].pool_address == candidate().pool_address


@pytest.mark.asyncio
async def test_collector_does_not_advance_cursor_after_failed_range() -> None:
    rpc = FakeRpc(latest_block=120, fail_from=71)
    collector = EvmMarketCollector(rpc, expected_chain_id=56, max_log_block_span=50)

    events = await collector.collect([candidate()])

    assert events == []
    assert collector.cursor("bnb", candidate().pool_address) == 70


@pytest.mark.asyncio
async def test_collector_caches_pool_validation_and_reads_only_new_blocks() -> None:
    rpc = FakeRpc(latest_block=120)
    pool = candidate().model_copy(update={"base_is_token0": None})
    collector = EvmMarketCollector(rpc, expected_chain_id=56, max_log_block_span=50)

    await collector.collect([pool])
    rpc.latest_block = 125
    await collector.collect([pool])

    assert rpc.calls == [(71, 120), (121, 125)]
    assert rpc.code_calls == [pool.pool_address]
    assert rpc.token0_calls == [pool.pool_address]


@pytest.mark.asyncio
async def test_collector_limits_pools_per_cycle() -> None:
    rpc = FakeRpc(latest_block=120)
    first = candidate()
    second = first.model_copy(
        update={"pool_address": "0x00000000000000000000000000000000000000dd"}
    )
    collector = EvmMarketCollector(
        rpc,
        expected_chain_id=56,
        max_log_block_span=50,
        max_pools=1,
    )

    await collector.collect([first, second])

    assert rpc.code_calls == [first.pool_address]
    assert rpc.calls == [(71, 120)]
