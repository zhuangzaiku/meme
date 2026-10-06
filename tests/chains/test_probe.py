import pytest

from app.chains.probe import NetworkProbe
from tests.chains.fakes import FakeAdapter


@pytest.mark.asyncio
async def test_probe_accepts_expected_chain_id() -> None:
    result = await NetworkProbe(FakeAdapter(chain_id=56)).verify(56)
    assert result.ok is True
    assert result.chain_id == 56


@pytest.mark.asyncio
async def test_probe_rejects_wrong_chain_id() -> None:
    result = await NetworkProbe(FakeAdapter(chain_id=56)).verify(999)
    assert result.ok is False
    assert "chain id" in result.errors[0].lower()
