from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.data.events import MarketEvent
from app.data.sources.evm_logs import (
    V2_BURN_TOPIC,
    V2_MINT_TOPIC,
    V2_SWAP_TOPIC,
    V2_SYNC_TOPIC,
    V3_BURN_TOPIC,
    V3_MINT_TOPIC,
    V3_SWAP_TOPIC,
    decode_sync_or_liquidity,
    decode_v2_swap,
    decode_v3_swap,
)
from app.data.sources.models import PoolCandidate

SUPPORTED_TOPICS = [
    V2_SWAP_TOPIC,
    V2_SYNC_TOPIC,
    V2_MINT_TOPIC,
    V2_BURN_TOPIC,
    V3_SWAP_TOPIC,
    V3_MINT_TOPIC,
    V3_BURN_TOPIC,
]


class MarketRpc(Protocol):
    async def get_chain_id(self) -> int: ...

    async def get_latest_block(self) -> int: ...

    async def get_code(self, address: str) -> str: ...

    async def get_pool_token0(self, address: str) -> str: ...

    async def get_logs(
        self, address: str, topics: list[str], from_block: int, to_block: int
    ) -> list[dict[str, object]]: ...

    async def get_block_timestamp(self, block_number: int) -> datetime: ...


class EvmMarketCollector:
    def __init__(
        self,
        adapter: MarketRpc,
        expected_chain_id: int,
        max_log_block_span: int = 1000,
    ) -> None:
        if max_log_block_span < 1:
            raise ValueError("max_log_block_span must be positive")
        self.adapter = adapter
        self.expected_chain_id = expected_chain_id
        self.max_log_block_span = max_log_block_span
        self._cursors: dict[tuple[str, str], int] = {}
        self._seen_event_ids: set[str] = set()

    async def collect(self, candidates: list[PoolCandidate]) -> list[MarketEvent]:
        chain_id = await self.adapter.get_chain_id()
        if chain_id != self.expected_chain_id:
            raise ConnectionError(
                f"chain id mismatch: expected {self.expected_chain_id}, got {chain_id}"
            )
        latest_block = await self.adapter.get_latest_block()
        collected: list[MarketEvent] = []
        for candidate in candidates:
            key = (candidate.chain, candidate.pool_address)
            code = await self.adapter.get_code(candidate.pool_address)
            if not code or code in {"0x", "0x0"}:
                continue
            if candidate.base_is_token0 is None:
                token0 = await self.adapter.get_pool_token0(candidate.pool_address)
                candidate = candidate.model_copy(
                    update={"base_is_token0": token0.lower() == candidate.base_token}
                )
            initial_cursor = max(0, latest_block - self.max_log_block_span)
            cursor = self._cursors.setdefault(key, initial_cursor)
            next_events: list[MarketEvent] = []
            try:
                for start in range(cursor + 1, latest_block + 1, self.max_log_block_span):
                    end = min(start + self.max_log_block_span - 1, latest_block)
                    logs = await self.adapter.get_logs(
                        candidate.pool_address,
                        SUPPORTED_TOPICS,
                        start,
                        end,
                    )
                    next_events.extend(await self._decode_logs(logs, candidate))
            except Exception:
                continue
            self._cursors[key] = latest_block
            for event in next_events:
                if (
                    event.source_event_id is None
                    or event.source_event_id not in self._seen_event_ids
                ):
                    if event.source_event_id is not None:
                        self._seen_event_ids.add(event.source_event_id)
                    collected.append(event)
        return collected

    def cursor(self, chain: str, pool_address: str) -> int:
        return self._cursors.get(
            (chain, pool_address.lower()),
            0,
        )

    async def _decode_logs(
        self, logs: list[dict[str, object]], candidate: PoolCandidate
    ) -> list[MarketEvent]:
        decoded: list[MarketEvent] = []
        is_v3 = "v3" in candidate.dex_id.lower()
        for log in logs:
            block_number = _int_value(log.get("blockNumber"))
            if block_number is None:
                continue
            timestamp = await self.adapter.get_block_timestamp(block_number)
            event: MarketEvent | None = (
                decode_v3_swap(log, candidate, timestamp)
                if is_v3
                else decode_v2_swap(log, candidate, timestamp)
            )
            if event is None and not is_v3:
                event = decode_sync_or_liquidity(log, candidate, timestamp)
            if event is not None:
                decoded.append(event)
        return decoded


def _int_value(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 16) if value.startswith("0x") else int(value)
        except ValueError:
            return None
    return None
