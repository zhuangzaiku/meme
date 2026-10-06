from __future__ import annotations

from datetime import UTC, datetime

import pytest
from eth_abi import encode
from web3 import Web3

from app.data.sources.bsc_discovery import BscPoolDiscovery, ProtocolSpec

NOW = datetime.now(UTC)
V2_FACTORY = "0xca143ce32fe78f1f7019d7d551a6402fc5350c73"
V3_FACTORY = "0x0bfbcf9fa4f9c56b0f40a671ad40e0805a091865"
TOKEN0 = "0x00000000000000000000000000000000000000bb"
TOKEN1 = "0x00000000000000000000000000000000000000cc"
PAIR = "0x00000000000000000000000000000000000000aa"
POOL = "0x00000000000000000000000000000000000000dd"


def _indexed_address(value: str) -> str:
    return "0x" + value[2:].rjust(64, "0")


def v2_pair_created_log() -> dict[str, object]:
    return {
        "topics": [
            Web3.keccak(text="PairCreated(address,address,address,uint256)").hex(),
            _indexed_address(TOKEN0),
            _indexed_address(TOKEN1),
        ],
        "data": "0x" + encode(["address", "uint256"], [PAIR, 1]).hex(),
        "blockNumber": hex(100),
        "transactionHash": "0x" + "ab" * 32,
        "logIndex": "0x3",
    }


def v3_pool_created_log() -> dict[str, object]:
    return {
        "topics": [
            Web3.keccak(text="PoolCreated(address,address,uint24,int24,address)").hex(),
            _indexed_address(TOKEN0),
            _indexed_address(TOKEN1),
            "0x" + (500).to_bytes(32, "big").hex(),
        ],
        "data": "0x" + encode(["int24", "address"], [60, POOL]).hex(),
        "blockNumber": hex(100),
        "transactionHash": "0x" + "cd" * 32,
        "logIndex": "0x4",
    }


def v2_spec() -> ProtocolSpec:
    return ProtocolSpec(
        name="pancakeswap_v2",
        contract_address=V2_FACTORY,
        event_kind="v2_pair_created",
        dex_id="pancakeswap-v2",
    )


def v3_spec() -> ProtocolSpec:
    return ProtocolSpec(
        name="pancakeswap_v3",
        contract_address=V3_FACTORY,
        event_kind="v3_pool_created",
        dex_id="pancakeswap-v3",
    )


class FakeDiscoveryRpc:
    def __init__(
        self,
        logs: list[dict[str, object]] | None = None,
        latest_block: int = 100,
        fail: bool = False,
    ) -> None:
        self.logs = logs or []
        self.latest_block = latest_block
        self.fail = fail
        self.calls: list[tuple[str, int, int]] = []

    async def get_latest_block(self) -> int:
        return self.latest_block

    async def get_logs(
        self, address: str, topics: list[str], from_block: int, to_block: int
    ) -> list[dict[str, object]]:
        self.calls.append((address, from_block, to_block))
        if self.fail:
            raise ConnectionError("rpc log failure")
        return self.logs

    async def get_block_timestamp(self, block_number: int) -> datetime:
        return NOW


@pytest.mark.asyncio
async def test_discovery_decodes_v2_pair_created_and_advances_cursor() -> None:
    rpc = FakeDiscoveryRpc(logs=[v2_pair_created_log()])
    source = BscPoolDiscovery(rpc, [v2_spec()], 100, 50, 10, 300)

    pools = await source.discover_pools()

    assert pools[0].dex_id == "pancakeswap-v2"
    assert pools[0].pool_address == PAIR
    assert pools[0].base_token == TOKEN0
    assert source.cursor("pancakeswap_v2") == 100
    assert rpc.calls == [(V2_FACTORY, 1, 50), (V2_FACTORY, 51, 100)]


@pytest.mark.asyncio
async def test_discovery_decodes_v3_pool_created() -> None:
    source = BscPoolDiscovery(
        FakeDiscoveryRpc(logs=[v3_pool_created_log()]), [v3_spec()], 100, 50, 10, 300
    )

    pools = await source.discover_pools()

    assert pools[0].dex_id == "pancakeswap-v3"
    assert pools[0].pool_address == POOL
    assert pools[0].base_token == TOKEN0
    assert pools[0].quote_token == TOKEN1


@pytest.mark.asyncio
async def test_failed_range_does_not_advance_cursor_or_emit_candidates() -> None:
    rpc = FakeDiscoveryRpc(fail=True)
    source = BscPoolDiscovery(rpc, [v2_spec()], 100, 50, 10, 300)

    assert await source.discover_pools() == []
    assert source.cursor("pancakeswap_v2") == 0
    assert source.health.status == "degraded"


@pytest.mark.asyncio
async def test_duplicate_factory_logs_are_emitted_once() -> None:
    log = v2_pair_created_log()
    source = BscPoolDiscovery(
        FakeDiscoveryRpc(logs=[log, log]), [v2_spec()], 100, 50, 10, 300
    )

    pools = await source.discover_pools()

    assert len(pools) == 1


@pytest.mark.asyncio
async def test_candidate_limit_does_not_skip_later_ranges() -> None:
    rpc = FakeDiscoveryRpc(logs=[v2_pair_created_log()])
    source = BscPoolDiscovery(rpc, [v2_spec()], 100, 50, 1, 300)

    await source.discover_pools()

    assert rpc.calls == [(V2_FACTORY, 1, 50), (V2_FACTORY, 51, 100)]
