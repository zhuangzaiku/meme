from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from eth_abi.abi import decode
from web3 import Web3

from app.data.connector_health import ConnectorStatus
from app.data.sources.models import PoolCandidate, SourceHealth

NativeEventKind = Literal["v2_pair_created", "v3_pool_created", "four_meme"]

V2_PAIR_CREATED_TOPIC = Web3.keccak(
    text="PairCreated(address,address,address,uint256)"
).hex()
V3_POOL_CREATED_TOPIC = Web3.keccak(
    text="PoolCreated(address,address,uint24,int24,address)"
).hex()


class BscDiscoveryRpc(Protocol):
    async def get_latest_block(self) -> int: ...

    async def get_logs(
        self, address: str, topics: list[str], from_block: int, to_block: int
    ) -> list[dict[str, object]]: ...

    async def get_block_timestamp(self, block_number: int) -> datetime: ...


@dataclass(frozen=True)
class ProtocolSpec:
    name: str
    contract_address: str
    event_kind: NativeEventKind
    dex_id: str
    enabled: bool = True

    def __post_init__(self) -> None:
        if not Web3.is_address(self.contract_address):
            raise ValueError("protocol contract address must be a valid EVM address")
        object.__setattr__(self, "contract_address", self.contract_address.lower())


class BscPoolDiscovery:
    def __init__(
        self,
        rpc: BscDiscoveryRpc,
        specs: list[ProtocolSpec],
        initial_backfill_blocks: int,
        max_log_block_span: int,
        max_pools_per_protocol: int,
        stale_cache_seconds: int,
    ) -> None:
        if initial_backfill_blocks < 1:
            raise ValueError("initial_backfill_blocks must be positive")
        if max_log_block_span < 1:
            raise ValueError("max_log_block_span must be positive")
        if max_pools_per_protocol < 1:
            raise ValueError("max_pools_per_protocol must be positive")
        if stale_cache_seconds < 1:
            raise ValueError("stale_cache_seconds must be positive")
        self.rpc = rpc
        self.specs = tuple(spec for spec in specs if spec.enabled)
        self.initial_backfill_blocks = initial_backfill_blocks
        self.max_log_block_span = max_log_block_span
        self.max_pools_per_protocol = max_pools_per_protocol
        self.stale_cache_seconds = stale_cache_seconds
        self._cursors: dict[str, int] = {}
        self._cache: dict[str, tuple[datetime, list[PoolCandidate]]] = {}
        self._seen_logs: set[tuple[str, str]] = set()
        self.health = SourceHealth(name="bsc:native", status="unavailable")

    def cursor(self, protocol_name: str) -> int:
        return self._cursors.get(protocol_name, 0)

    async def discover_pools(self) -> list[PoolCandidate]:
        observed_at = datetime.now(UTC)
        if not self.specs:
            self.health = SourceHealth(
                name="bsc:native",
                status="observation_only",
                error="no verified BSC protocols are enabled",
                observed_at=observed_at,
            )
            return []
        try:
            latest_block = await self.rpc.get_latest_block()
        except Exception as exc:
            return self._use_cache_or_degrade(observed_at, [str(exc)])

        candidates: list[PoolCandidate] = []
        errors: list[str] = []
        successful_protocols = 0
        for spec in self.specs:
            topic = _topic_for(spec.event_kind)
            if topic is None:
                errors.append(f"{spec.name}: event schema is not configured")
                continue
            try:
                protocol_candidates = await self._scan_protocol(spec, topic, latest_block)
                candidates.extend(protocol_candidates)
                successful_protocols += 1
            except Exception as exc:
                cached = self._cached_candidates(spec.name, observed_at)
                if cached is None:
                    errors.append(f"{spec.name}: {exc}")
                else:
                    candidates.extend(cached)
                    errors.append(f"{spec.name}: {exc}; using cached pools")

        if candidates:
            status: ConnectorStatus = "observation_only" if errors else "ready"
        elif errors and successful_protocols == 0:
            status = "degraded"
        else:
            status = "observation_only"
        self.health = SourceHealth(
            name="bsc:native",
            status=status,
            error="; ".join(errors) if errors else None,
            observed_at=observed_at,
        )
        return _deduplicate_candidates(candidates)

    async def _scan_protocol(
        self, spec: ProtocolSpec, topic: str, latest_block: int
    ) -> list[PoolCandidate]:
        previous_cursor = self._cursors.get(spec.name)
        start = (
            previous_cursor + 1
            if previous_cursor is not None
            else max(0, latest_block - self.initial_backfill_blocks + 1)
        )
        protocol_candidates: list[PoolCandidate] = []
        scanned_log_keys: set[tuple[str, str]] = set()
        for from_block in range(start, latest_block + 1, self.max_log_block_span):
            to_block = min(from_block + self.max_log_block_span - 1, latest_block)
            logs = await self.rpc.get_logs(
                spec.contract_address,
                [topic],
                from_block,
                to_block,
            )
            for log in logs:
                key = (spec.name, _log_identity(log))
                if key in self._seen_logs or key in scanned_log_keys:
                    continue
                candidate = await self._decode_log(spec, log)
                if candidate is None:
                    continue
                scanned_log_keys.add(key)
                if len(protocol_candidates) < self.max_pools_per_protocol:
                    protocol_candidates.append(candidate)
        self._cursors[spec.name] = latest_block
        self._seen_logs.update(scanned_log_keys)
        self._cache[spec.name] = (datetime.now(UTC), protocol_candidates)
        return protocol_candidates

    async def _decode_log(
        self, spec: ProtocolSpec, log: Mapping[str, object]
    ) -> PoolCandidate | None:
        block_number = _as_int(log.get("blockNumber"))
        if block_number is None:
            return None
        timestamp = await self.rpc.get_block_timestamp(block_number)
        if spec.event_kind == "v2_pair_created":
            decoded = _decode_v2_pair(log)
        elif spec.event_kind == "v3_pool_created":
            decoded = _decode_v3_pool(log)
        else:
            return None
        if decoded is None:
            return None
        pool_address, token0, token1 = decoded
        try:
            return PoolCandidate(
                chain="bnb",
                network_id="bsc",
                pool_address=pool_address,
                dex_id=spec.dex_id,
                base_token=token0,
                quote_token=token1,
                observed_at=timestamp,
            )
        except ValueError:
            return None

    def _cached_candidates(
        self, protocol_name: str, now: datetime
    ) -> list[PoolCandidate] | None:
        cached = self._cache.get(protocol_name)
        if cached is None:
            return None
        cached_at, candidates = cached
        if (now - cached_at).total_seconds() > self.stale_cache_seconds:
            return None
        return list(candidates)

    def _use_cache_or_degrade(
        self, observed_at: datetime, errors: list[str]
    ) -> list[PoolCandidate]:
        candidates: list[PoolCandidate] = []
        for spec in self.specs:
            candidates.extend(self._cached_candidates(spec.name, observed_at) or [])
        status: ConnectorStatus = "observation_only" if candidates else "degraded"
        self.health = SourceHealth(
            name="bsc:native",
            status=status,
            error="; ".join(errors) if errors else None,
            observed_at=observed_at,
        )
        return _deduplicate_candidates(candidates)


def _topic_for(event_kind: NativeEventKind) -> str | None:
    if event_kind == "v2_pair_created":
        return V2_PAIR_CREATED_TOPIC
    if event_kind == "v3_pool_created":
        return V3_POOL_CREATED_TOPIC
    return None


def _decode_v2_pair(log: Mapping[str, object]) -> tuple[str, str, str] | None:
    if _topic(log) != V2_PAIR_CREATED_TOPIC:
        return None
    topics = log.get("topics")
    if not isinstance(topics, list) or len(topics) < 3:
        return None
    token0 = _indexed_address(topics[1])
    token1 = _indexed_address(topics[2])
    values = _decode_data(log, ["address", "uint256"])
    if token0 is None or token1 is None or values is None:
        return None
    pair = values[0]
    if not isinstance(pair, str):
        return None
    return pair, token0, token1


def _decode_v3_pool(log: Mapping[str, object]) -> tuple[str, str, str] | None:
    if _topic(log) != V3_POOL_CREATED_TOPIC:
        return None
    topics = log.get("topics")
    if not isinstance(topics, list) or len(topics) < 4:
        return None
    token0 = _indexed_address(topics[1])
    token1 = _indexed_address(topics[2])
    values = _decode_data(log, ["int24", "address"])
    if token0 is None or token1 is None or values is None:
        return None
    pool = values[1]
    if not isinstance(pool, str):
        return None
    return pool, token0, token1


def _deduplicate_candidates(candidates: list[PoolCandidate]) -> list[PoolCandidate]:
    unique: dict[str, PoolCandidate] = {}
    for candidate in candidates:
        unique.setdefault(candidate.pool_address.lower(), candidate)
    return list(unique.values())


def _log_identity(log: Mapping[str, object]) -> str:
    transaction_hash = _as_hex(log.get("transactionHash"))
    log_index = _as_int(log.get("logIndex"))
    if transaction_hash is not None and log_index is not None:
        return f"{transaction_hash}:{log_index}"
    encoded = json.dumps(log, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _topic(log: Mapping[str, object]) -> str | None:
    topics = log.get("topics")
    if not isinstance(topics, list) or not topics:
        return None
    return _as_hex(topics[0])


def _indexed_address(value: object) -> str | None:
    encoded = _as_hex(value)
    if encoded is None or len(encoded) < 40:
        return None
    return "0x" + encoded[-40:]


def _decode_data(log: Mapping[str, object], types: list[str]) -> tuple[object, ...] | None:
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
