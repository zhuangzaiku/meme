from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.chains.solana import SolanaRpc, SolanaSignature
from app.data.events import LiquidityChange, MarketEvent, PriceTick, Swap, TokenSecurityUpdate
from app.data.sources.models import PoolCandidate

SUPPORTED_DEX_MARKERS = ("raydium", "meteora", "orca", "pump")


class SolanaMarketCollector:
    def __init__(
        self,
        rpc: SolanaRpc,
        max_pools: int = 3,
        max_signatures_per_pool: int = 20,
    ) -> None:
        if max_pools < 1:
            raise ValueError("max_pools must be positive")
        if max_signatures_per_pool < 1:
            raise ValueError("max_signatures_per_pool must be positive")
        self.rpc = rpc
        self.max_pools = max_pools
        self.max_signatures_per_pool = max_signatures_per_pool
        self._cursors: dict[tuple[str, str], str] = {}
        self._seen_signatures: set[str] = set()

    async def collect(self, candidates: list[PoolCandidate]) -> list[MarketEvent]:
        events: list[MarketEvent] = []
        for candidate in candidates[: self.max_pools]:
            try:
                events.extend(await self._collect_candidate(candidate))
            except Exception:
                continue
        return sorted(events, key=lambda event: event.timestamp)

    def cursor(self, chain: str, pool_address: str) -> str | None:
        return self._cursors.get((chain, pool_address))

    async def _collect_candidate(self, candidate: PoolCandidate) -> list[MarketEvent]:
        pool_account = await self.rpc.get_account_info(candidate.pool_address)
        if pool_account is None:
            return []
        key = (candidate.chain, candidate.pool_address)
        cursor = self._cursors.get(key)
        signatures = await self.rpc.get_signatures_for_address(
            candidate.pool_address,
            self.max_signatures_per_pool,
            cursor,
        )
        new_signatures = [
            signature
            for signature in signatures
            if signature.signature not in self._seen_signatures
        ]
        transactions: list[tuple[SolanaSignature, Mapping[str, Any]]] = []
        for signature in new_signatures:
            transaction = await self.rpc.get_transaction(signature.signature)
            if transaction is None:
                raise ConnectionError("Solana transaction is unavailable")
            transactions.append((signature, transaction))

        timestamp = _candidate_timestamp(candidate, signatures)
        events: list[MarketEvent] = []
        if candidate.price_usd is not None:
            events.append(
                PriceTick(
                    chain=candidate.chain,
                    token=candidate.base_token,
                    price=candidate.price_usd,
                    timestamp=timestamp,
                    source="geckoterminal:price",
                    pool_address=candidate.pool_address,
                )
            )
        if candidate.reserve_usd is not None:
            events.append(
                LiquidityChange(
                    chain=candidate.chain,
                    token=candidate.base_token,
                    liquidity=candidate.reserve_usd,
                    timestamp=timestamp,
                    source="geckoterminal:liquidity",
                    pool_address=candidate.pool_address,
                )
            )
        mint_account = await self.rpc.get_account_info(candidate.base_token)
        events.append(self._security_event(candidate, mint_account, timestamp))
        if _is_supported_dex(candidate.dex_id):
            for signature, transaction in transactions:
                swap = _parse_swap(candidate, signature, transaction)
                if swap is not None:
                    events.append(swap)
        if signatures:
            self._cursors[key] = signatures[0].signature
            self._seen_signatures.update(signature.signature for signature in signatures)
        return events

    @staticmethod
    def _security_event(
        candidate: PoolCandidate,
        mint_account: Mapping[str, Any] | None,
        timestamp: datetime,
    ) -> TokenSecurityUpdate:
        info = _parsed_info(mint_account)
        indicators: list[str] = []
        if info is None:
            indicators.append("missing_mint_account")
        else:
            if info.get("mintAuthority") is not None:
                indicators.append("mint_authority")
            if info.get("freezeAuthority") is not None:
                indicators.append("freeze_authority")
        return TokenSecurityUpdate(
            chain=candidate.chain,
            token=candidate.base_token,
            passed=not indicators,
            indicators=indicators,
            timestamp=timestamp,
            source="rpc:token-security",
            pool_address=candidate.pool_address,
        )


def _parse_swap(
    candidate: PoolCandidate,
    signature: SolanaSignature,
    transaction: Mapping[str, Any],
) -> Swap | None:
    meta = transaction.get("meta")
    message = _mapping_value(transaction.get("transaction"), "message")
    if (
        not isinstance(meta, Mapping)
        or meta.get("err") is not None
        or not isinstance(message, Mapping)
    ):
        return None
    signer = _signer(message.get("accountKeys"))
    if signer is None:
        return None
    before = _owner_balance(meta.get("preTokenBalances"), candidate.base_token, signer)
    after = _owner_balance(meta.get("postTokenBalances"), candidate.base_token, signer)
    delta = after - before
    if delta == 0:
        return None
    timestamp = _transaction_timestamp(transaction, signature)
    return Swap(
        chain=candidate.chain,
        token=candidate.base_token,
        wallet=signer,
        side="buy" if delta > 0 else "sell",
        amount=abs(delta),
        price=candidate.price_usd,
        timestamp=timestamp,
        source="rpc:solana-swap",
        source_event_id=f"solana:{signature.signature}",
        block_number=signature.slot,
        transaction_hash=signature.signature,
        pool_address=candidate.pool_address,
    )


def _owner_balance(entries: object, token: str, owner: str) -> float:
    if not isinstance(entries, list):
        return 0.0
    total = 0.0
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        if entry.get("mint") != token or entry.get("owner") != owner:
            continue
        amount = _mapping_value(entry.get("uiTokenAmount"), "uiAmount")
        if isinstance(amount, (int, float)) and not isinstance(amount, bool):
            total += float(amount)
            continue
        raw_amount = _mapping_value(entry.get("uiTokenAmount"), "uiAmountString")
        if isinstance(raw_amount, str):
            try:
                total += float(raw_amount)
            except ValueError:
                continue
    return total


def _signer(account_keys: object) -> str | None:
    if not isinstance(account_keys, list):
        return None
    for account in account_keys:
        if isinstance(account, Mapping) and account.get("signer") is True:
            public_key = account.get("pubkey")
            if isinstance(public_key, str):
                return public_key
    return None


def _parsed_info(account: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    parsed = _mapping_value(account.get("data") if account else None, "parsed")
    info = _mapping_value(parsed, "info")
    return info if isinstance(info, Mapping) else None


def _mapping_value(value: object, key: str) -> object:
    return value.get(key) if isinstance(value, Mapping) else None


def _candidate_timestamp(candidate: PoolCandidate, signatures: list[SolanaSignature]) -> datetime:
    if signatures and signatures[0].block_time:
        return signatures[0].block_time
    return candidate.observed_at


def _transaction_timestamp(
    transaction: Mapping[str, Any], signature: SolanaSignature
) -> datetime:
    block_time = transaction.get("blockTime")
    if isinstance(block_time, (int, float)) and not isinstance(block_time, bool):
        return datetime.fromtimestamp(block_time, UTC)
    return signature.block_time or datetime.now(UTC)


def _is_supported_dex(dex_id: str) -> bool:
    name = dex_id.lower()
    return any(marker in name for marker in SUPPORTED_DEX_MARKERS)
