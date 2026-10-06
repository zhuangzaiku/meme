from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest

from app.chains.solana import SolanaSignature
from app.data.events import LiquidityChange, PriceTick, Swap, TokenSecurityUpdate
from app.data.sources.models import PoolCandidate
from app.data.sources.solana_market import SolanaMarketCollector

POOL = "So11111111111111111111111111111111111111112"
BASE_TOKEN = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
TRADER = "Trader111111111111111111111111111111111111111"


def solana_candidate() -> PoolCandidate:
    return PoolCandidate(
        chain="sol",
        network_id="solana",
        pool_address=POOL,
        dex_id="raydium",
        base_token=BASE_TOKEN,
        quote_token=POOL,
        price_usd=1.25,
        reserve_usd=150000,
        observed_at=datetime.now(UTC),
    )


def parsed_transaction(candidate: PoolCandidate, delta: float = 2.0) -> Mapping[str, Any]:
    before = 1.0
    after = before + delta
    return {
        "slot": 9,
        "blockTime": 1791331200,
        "transaction": {
            "message": {
                "accountKeys": [
                    {"pubkey": TRADER, "signer": True},
                    {"pubkey": candidate.pool_address, "signer": False},
                ]
            }
        },
        "meta": {
            "err": None,
            "preTokenBalances": [
                {
                    "mint": candidate.base_token,
                    "owner": TRADER,
                    "uiTokenAmount": {"uiAmount": before},
                }
            ],
            "postTokenBalances": [
                {
                    "mint": candidate.base_token,
                    "owner": TRADER,
                    "uiTokenAmount": {"uiAmount": after},
                }
            ],
        },
    }


class FakeSolanaRpc:
    def __init__(
        self,
        *,
        signatures: list[SolanaSignature] | None = None,
        transactions: dict[str, Mapping[str, Any]] | None = None,
        mint_info: Mapping[str, Any] | None = None,
        transaction_error: Exception | None = None,
    ) -> None:
        self.signatures = signatures or []
        self.transactions = transactions or {}
        self.mint_info = mint_info or {
            "data": {
                "parsed": {
                    "info": {"mintAuthority": None, "freezeAuthority": None}
                }
            }
        }
        self.transaction_error = transaction_error

    async def get_account_info(self, address: str) -> Mapping[str, Any] | None:
        if address == BASE_TOKEN:
            return self.mint_info
        return {"owner": "raydium", "data": {"parsed": {"info": {}}}}

    async def get_signatures_for_address(
        self, address: str, limit: int, until: str | None
    ) -> list[SolanaSignature]:
        return self.signatures[:limit]

    async def get_transaction(self, signature: str) -> Mapping[str, Any] | None:
        if self.transaction_error is not None:
            raise self.transaction_error
        return self.transactions.get(signature)


@pytest.mark.asyncio
async def test_solana_collector_emits_verified_buy_context() -> None:
    candidate = solana_candidate()
    signature = SolanaSignature("sig-1", 9, datetime(2026, 10, 7, tzinfo=UTC))
    rpc = FakeSolanaRpc(
        signatures=[signature],
        transactions={"sig-1": parsed_transaction(candidate)},
    )

    events = await SolanaMarketCollector(rpc).collect([candidate])

    assert any(isinstance(event, PriceTick) for event in events)
    assert any(isinstance(event, LiquidityChange) for event in events)
    assert any(isinstance(event, TokenSecurityUpdate) and event.passed for event in events)
    swaps = [event for event in events if isinstance(event, Swap)]
    assert len(swaps) == 1
    assert swaps[0].side == "buy"
    assert swaps[0].wallet == TRADER


@pytest.mark.asyncio
async def test_solana_collector_parses_sell_and_deduplicates_signature() -> None:
    candidate = solana_candidate()
    signature = SolanaSignature("sig-1", 9, datetime(2026, 10, 7, tzinfo=UTC))
    rpc = FakeSolanaRpc(
        signatures=[signature],
        transactions={"sig-1": parsed_transaction(candidate, delta=-0.5)},
    )
    collector = SolanaMarketCollector(rpc)

    first = await collector.collect([candidate])
    second = await collector.collect([candidate])

    assert [event.side for event in first if isinstance(event, Swap)] == ["sell"]
    assert [event for event in second if isinstance(event, Swap)] == []
    assert collector.cursor("sol", candidate.pool_address) == "sig-1"


@pytest.mark.asyncio
async def test_active_freeze_authority_emits_blocking_security_event() -> None:
    candidate = solana_candidate()
    rpc = FakeSolanaRpc(
        mint_info={
            "data": {
                "parsed": {
                    "info": {
                        "mintAuthority": None,
                        "freezeAuthority": "Authority111111111111111111111111111111111111",
                    }
                }
            }
        }
    )

    events = await SolanaMarketCollector(rpc).collect([candidate])

    security = [event for event in events if isinstance(event, TokenSecurityUpdate)]
    assert security and security[-1].passed is False
    assert "freeze_authority" in security[-1].indicators


@pytest.mark.asyncio
async def test_transaction_failure_does_not_advance_signature_cursor() -> None:
    candidate = solana_candidate()
    signature = SolanaSignature("sig-1", 9, datetime.now(UTC))
    rpc = FakeSolanaRpc(
        signatures=[signature],
        transaction_error=ConnectionError("rpc failed"),
    )
    collector = SolanaMarketCollector(rpc)

    assert await collector.collect([candidate]) == []
    assert collector.cursor("sol", candidate.pool_address) is None
