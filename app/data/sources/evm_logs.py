from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from eth_abi.abi import decode
from web3 import Web3

from app.data.events import LiquidityChange, Swap
from app.data.sources.models import PoolCandidate

V2_SWAP_TOPIC = Web3.keccak(
    text="Swap(address,uint256,uint256,uint256,uint256,address)"
).hex()
V3_SWAP_TOPIC = Web3.keccak(
    text="Swap(address,address,int256,int256,uint160,uint128,int24)"
).hex()
V2_SYNC_TOPIC = Web3.keccak(text="Sync(uint112,uint112)").hex()
V2_MINT_TOPIC = Web3.keccak(text="Mint(address,uint256,uint256)").hex()
V2_BURN_TOPIC = Web3.keccak(text="Burn(address,uint256,uint256,address)").hex()
V3_MINT_TOPIC = Web3.keccak(
    text="Mint(address,address,int24,int24,uint128,uint256,uint256)"
).hex()
V3_BURN_TOPIC = Web3.keccak(
    text="Burn(address,int24,int24,uint128,uint256,uint256)"
).hex()


def event_id(log: Mapping[str, object], chain: str) -> str | None:
    transaction_hash = log.get("transactionHash")
    log_index = log.get("logIndex")
    if transaction_hash is None or log_index is None:
        return None
    transaction = _as_hex(transaction_hash)
    index = _as_int(log_index)
    if transaction is None or index is None:
        return None
    return f"{chain}:0x{transaction}:{index}"


def decode_v2_swap(
    log: Mapping[str, object], candidate: PoolCandidate, block_timestamp: datetime
) -> Swap | None:
    if _topic(log) != V2_SWAP_TOPIC or candidate.base_is_token0 is None:
        return None
    values = _decode_data(log, ["uint256", "uint256", "uint256", "uint256"])
    if values is None:
        return None
    amount0_in, amount1_in, amount0_out, amount1_out = (int(value) for value in values)
    if candidate.base_is_token0:
        base_in, quote_in, base_out, quote_out = (
            amount0_in,
            amount1_in,
            amount0_out,
            amount1_out,
        )
    else:
        base_in, quote_in, base_out, quote_out = (
            amount1_in,
            amount0_in,
            amount1_out,
            amount0_out,
        )
    if base_out > 0 and quote_in > 0:
        side = "buy"
        amount = base_out
        price = quote_in / base_out
    elif base_in > 0 and quote_out > 0:
        side = "sell"
        amount = base_in
        price = quote_out / base_in
    else:
        return None
    return Swap(
        chain=candidate.chain,
        token=candidate.base_token,
        wallet=_indexed_address(log, 1) or "unknown",
        side=side,
        amount=float(amount),
        price=price,
        source="rpc:v2",
        timestamp=block_timestamp,
        source_event_id=event_id(log, candidate.chain),
        block_number=_as_int(log.get("blockNumber")),
        transaction_hash=_as_hex(log.get("transactionHash")),
    )


def decode_v3_swap(
    log: Mapping[str, object], candidate: PoolCandidate, block_timestamp: datetime
) -> Swap | None:
    if _topic(log) != V3_SWAP_TOPIC or candidate.base_is_token0 is None:
        return None
    values = _decode_data(log, ["int256", "int256", "uint160", "uint128", "int24"])
    if values is None:
        return None
    amount0, amount1 = int(values[0]), int(values[1])
    base_delta, quote_delta = (
        (amount0, amount1) if candidate.base_is_token0 else (amount1, amount0)
    )
    if base_delta < 0 and quote_delta > 0:
        side = "buy"
        amount = abs(base_delta)
        price = quote_delta / amount
    elif base_delta > 0 and quote_delta < 0:
        side = "sell"
        amount = base_delta
        price = abs(quote_delta) / amount
    else:
        return None
    return Swap(
        chain=candidate.chain,
        token=candidate.base_token,
        wallet=_indexed_address(log, 1) or "unknown",
        side=side,
        amount=float(amount),
        price=price,
        source="rpc:v3",
        timestamp=block_timestamp,
        source_event_id=event_id(log, candidate.chain),
        block_number=_as_int(log.get("blockNumber")),
        transaction_hash=_as_hex(log.get("transactionHash")),
    )


def decode_sync_or_liquidity(
    log: Mapping[str, object], candidate: PoolCandidate, block_timestamp: datetime
) -> LiquidityChange | None:
    topic = _topic(log)
    if topic == V2_SYNC_TOPIC:
        values = _decode_data(log, ["uint112", "uint112"])
        liquidity = float(sum(int(value) for value in values)) if values else None
    elif topic in {V2_MINT_TOPIC, V2_BURN_TOPIC}:
        values = _decode_data(log, ["uint256", "uint256"])
        liquidity = float(sum(int(value) for value in values)) if values else None
    else:
        return None
    if liquidity is None:
        return None
    return LiquidityChange(
        chain=candidate.chain,
        token=candidate.base_token,
        liquidity=liquidity,
        source="rpc:liquidity",
        timestamp=block_timestamp,
        source_event_id=event_id(log, candidate.chain),
        block_number=_as_int(log.get("blockNumber")),
        transaction_hash=_as_hex(log.get("transactionHash")),
    )


def _topic(log: Mapping[str, object]) -> str | None:
    topics = log.get("topics")
    if not isinstance(topics, list) or not topics:
        return None
    return _as_hex(topics[0])


def _indexed_address(log: Mapping[str, object], index: int) -> str | None:
    topics = log.get("topics")
    if not isinstance(topics, list) or len(topics) <= index:
        return None
    value = _as_hex(topics[index])
    return f"0x{value[-40:]}" if value and len(value) >= 40 else None


def _decode_data(log: Mapping[str, object], types: list[str]) -> tuple[Any, ...] | None:
    data = log.get("data")
    if not isinstance(data, str):
        return None
    try:
        return decode(types, bytes.fromhex(data.removeprefix("0x")))
    except (TypeError, ValueError):
        return None


def _as_hex(value: object) -> str | None:
    if isinstance(value, bytes):
        return value.hex()
    if not isinstance(value, str):
        return None
    return value.lower().removeprefix("0x")


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 16) if value.startswith("0x") else int(value)
        except ValueError:
            return None
    return None
