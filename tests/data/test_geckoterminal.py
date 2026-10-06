from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.data.sources.geckoterminal import GeckoTerminalSource

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures"


def fixture_transport(name: str) -> httpx.MockTransport:
    payload = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    return httpx.MockTransport(handler)


def timeout_transport(calls: list[int]) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ReadTimeout("timeout", request=request)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_discovery_parses_bsc_and_keeps_base_token() -> None:
    source = GeckoTerminalSource(
        "bsc",
        "http://127.0.0.1:7890",
        transport=fixture_transport("geckoterminal_bsc_pools.json"),
    )

    pools = await source.discover_pools()

    assert pools[0].chain == "bnb"
    assert pools[0].network_id == "bsc"
    assert pools[0].base_token == "0x00000000000000000000000000000000000000bb"
    assert source.health.status == "ready"


@pytest.mark.asyncio
async def test_discovery_retries_then_marks_degraded() -> None:
    calls: list[int] = []
    source = GeckoTerminalSource(
        "robinhood",
        "http://127.0.0.1:7890",
        max_retries=2,
        retry_base_seconds=0,
        transport=timeout_transport(calls),
    )

    assert await source.discover_pools() == []
    assert len(calls) == 3
    assert source.health.status == "degraded"
