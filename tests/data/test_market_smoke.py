from app.data.sources.smoke import MarketSmokeResult


def test_smoke_result_never_reports_broadcasting() -> None:
    result = MarketSmokeResult(
        chain="bnb",
        status="ready",
        chain_id=56,
        latest_block=1,
        discovered_pools=1,
        events=2,
        reasons=[],
    )

    assert result.broadcasted is False
