from __future__ import annotations

import json

import httpx
import pytest

from app.chains.solana import SolanaRpcAdapter

SOL_ADDRESS = "So11111111111111111111111111111111111111112"


@pytest.mark.asyncio
async def test_solana_rpc_sends_confirmed_json_rpc_requests() -> None:
    calls: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if body["method"] == "getAccountInfo":
            result: object = {"value": {"data": "ok"}}
        elif body["method"] == "getSignaturesForAddress":
            result = []
        else:
            result = None
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": body["id"], "result": result},
        )

    rpc = SolanaRpcAdapter(
        "https://api.mainnet.solana.com",
        "http://127.0.0.1:7890",
        timeout_seconds=20,
        transport=httpx.MockTransport(handler),
    )

    assert await rpc.get_account_info(SOL_ADDRESS) == {"data": "ok"}
    await rpc.get_signatures_for_address(SOL_ADDRESS, 20, None)
    await rpc.get_transaction("signature-1")

    assert calls[0]["method"] == "getAccountInfo"
    assert calls[0]["params"][1]["commitment"] == "confirmed"
    assert calls[1]["method"] == "getSignaturesForAddress"
    assert calls[1]["params"][1]["limit"] == 20
    assert calls[2]["method"] == "getTransaction"
    assert calls[2]["params"][1]["encoding"] == "jsonParsed"


@pytest.mark.asyncio
async def test_solana_rpc_retries_http_429_then_returns_signature() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, text="rate limited")
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": [
                    {
                        "signature": "sig",
                        "slot": 7,
                        "blockTime": 1700000000,
                        "err": None,
                    }
                ],
            },
        )

    rpc = SolanaRpcAdapter(
        "https://api.mainnet.solana.com",
        "http://127.0.0.1:7890",
        max_retries=1,
        retry_base_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    signatures = await rpc.get_signatures_for_address(SOL_ADDRESS, 20, None)

    assert attempts == 2
    assert signatures[0].signature == "sig"
    assert signatures[0].block_time is not None


@pytest.mark.asyncio
async def test_solana_rpc_rejects_rpc_error_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32000, "message": "node unavailable"},
            },
        )

    rpc = SolanaRpcAdapter(
        "https://api.mainnet.solana.com",
        "http://127.0.0.1:7890",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ConnectionError, match="node unavailable"):
        await rpc.get_transaction("signature-1")
