import hashlib
import hmac
import json
from datetime import UTC, datetime

import httpx
import pytest

from app.data.sources.gmgn import GmgnCalloutSource, build_signature
from app.data.sources.models import PoolCandidate


def candidate() -> PoolCandidate:
    return PoolCandidate(
        chain="bnb",
        network_id="bsc",
        pool_address="0x00000000000000000000000000000000000000aa",
        dex_id="pancakeswap-v2",
        base_token="0x00000000000000000000000000000000000000bb",
        quote_token="0x00000000000000000000000000000000000000cc",
        observed_at=datetime.now(UTC),
    )


def test_gmgn_signature_covers_exact_request_body() -> None:
    body = '{"chain":"bsc","call_token":"0xabc"}'
    payload = "ak123" + "1700000000000" + "POST" + "/callout/openapi/v1/token" + "" + body

    assert build_signature(
        "secret", "ak123", "1700000000000", "/callout/openapi/v1/token", body
    ) == hmac.new(b"secret", payload.encode(), hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_gmgn_token_callouts_normalize_external_signal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/callout/openapi/v1/token"
        assert request.headers["X-Ak"] == "ak"
        payload = json.loads(request.content)
        assert payload == {"chain": "bsc", "call_token": candidate().base_token, "limit": 50}
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "messages": [
                        {
                            "ulid": "01one",
                            "wallet_address": "0xwallet1",
                            "content": "AI agent meme narrative",
                            "follower_count": 1200,
                            "like_count": 20,
                            "reply_count": 4,
                            "multiplier": "2.5",
                            "created_at": "2026-10-07T00:00:00Z",
                        },
                        {
                            "ulid": "01two",
                            "wallet_address": "0xwallet2",
                            "content": "AI community is growing",
                            "follower_count": 800,
                            "like_count": 10,
                            "reply_count": 2,
                            "multiplier": "1.4",
                            "created_at": "2026-10-07T00:00:00Z",
                        },
                    ],
                    "has_more": False,
                },
            },
        )

    source = GmgnCalloutSource(
        ak="ak",
        sk="sk",
        proxy_url="http://127.0.0.1:7890",
        transport=httpx.MockTransport(handler),
    )

    signals = await source.collect([candidate()])

    assert len(signals) == 1
    assert signals[0].chain == "bnb"
    assert signals[0].token == candidate().base_token
    assert signals[0].unique_callout_wallets == 2
    assert signals[0].callout_count == 2
    assert signals[0].smart_money_score > 0
    assert signals[0].narrative_score > 0
    assert signals[0].social_score > 0


@pytest.mark.asyncio
async def test_gmgn_without_credentials_is_unavailable_and_emits_nothing() -> None:
    source = GmgnCalloutSource(ak=None, sk=None, proxy_url="http://127.0.0.1:7890")

    assert await source.collect([candidate()]) == []
    assert source.health.status == "unavailable"
