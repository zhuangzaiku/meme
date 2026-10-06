from datetime import UTC, datetime

from eth_abi import encode

from app.data.sources.evm_logs import (
    V2_SWAP_TOPIC,
    V3_SWAP_TOPIC,
    decode_v2_swap,
    decode_v3_swap,
    event_id,
)
from app.data.sources.models import PoolCandidate

NOW = datetime.now(UTC)


def bsc_candidate() -> PoolCandidate:
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


def topic_address(address: str) -> str:
    return "0x" + ("0" * 24) + address[2:]


def test_v2_swap_marks_base_token_buy_from_amount_out() -> None:
    log = {
        "topics": [
            V2_SWAP_TOPIC,
            topic_address("0x00000000000000000000000000000000000000dd"),
            topic_address("0x00000000000000000000000000000000000000ee"),
        ],
        "data": "0x" + encode(["uint256"] * 4, [0, 1_000_000, 500_000, 0]).hex(),
        "transactionHash": "0xabc",
        "logIndex": "0x3",
        "blockNumber": "0x10",
    }

    event = decode_v2_swap(log, bsc_candidate(), NOW)

    assert event is not None
    assert event.side == "buy"
    assert event.amount == 500_000
    assert event.source_event_id == "bnb:0xabc:3"
    assert event.block_number == 16


def test_v3_swap_marks_base_token_buy_from_signed_delta() -> None:
    log = {
        "topics": [
            V3_SWAP_TOPIC,
            topic_address("0x00000000000000000000000000000000000000dd"),
            topic_address("0x00000000000000000000000000000000000000ee"),
        ],
        "data": "0x"
        + encode(
            ["int256", "int256", "uint160", "uint128", "int24"],
            [-500_000, 1_000_000, 1, 1, 0],
        ).hex(),
        "transactionHash": "0xdef",
        "logIndex": "0x4",
        "blockNumber": "0x11",
    }
    candidate = bsc_candidate().model_copy(update={"dex_id": "uniswap-v3"})

    event = decode_v3_swap(log, candidate, NOW)

    assert event is not None
    assert event.side == "buy"
    assert event.amount == 500_000


def test_v3_unknown_topic_is_ignored() -> None:
    log = {"topics": ["0xdeadbeef"], "data": "0x"}
    assert decode_v3_swap(log, bsc_candidate(), NOW) is None


def test_event_id_requires_transaction_and_log_index() -> None:
    assert event_id({"transactionHash": "0xabc", "logIndex": "0x3"}, "bnb") == "bnb:0xabc:3"
    assert event_id({"transactionHash": "0xabc"}, "bnb") is None
