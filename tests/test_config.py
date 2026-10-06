from pathlib import Path

from app.config import load_settings


def test_default_mode_is_paper(tmp_path: Path) -> None:
    settings = load_settings(tmp_path / "missing.yaml")
    assert settings.execution_mode == "paper"
    assert settings.risk.risk_per_trade == 0.0025
    assert settings.market.proxy_url == "http://127.0.0.1:7890"
    assert settings.market.discovery_interval_seconds == 60
    assert settings.market.collection_timeout_seconds == 10.0
    assert settings.market.per_chain["bnb"].poll_interval_seconds == 5.0
    assert settings.market.per_chain["bnb"].collection_timeout_seconds == 10.0
    assert settings.market.per_chain["robinhood"].poll_interval_seconds == 15.0
    assert settings.market.per_chain["robinhood"].collection_timeout_seconds == 30.0


def test_chain_endpoints_are_loaded_from_environment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BNB_RPC_URL", "https://bnb.example")
    monkeypatch.setenv("ROBINHOOD_RPC_URL", "https://robinhood.example")
    settings = load_settings(tmp_path / "missing.yaml")
    assert settings.chains["bnb"].rpc_http == "https://bnb.example"
    assert settings.chains["robinhood"].rpc_http == "https://robinhood.example"


def test_network_registry_provides_verified_defaults(tmp_path: Path) -> None:
    settings = load_settings(tmp_path / "missing.yaml")

    assert settings.chains["bnb"].rpc_http == "https://bsc-dataseed.bnbchain.org"
    assert settings.chains["robinhood"].chain_id == 4663
    assert settings.chains["robinhood"].rpc_http == "https://rpc.mainnet.chain.robinhood.com/"


def test_invalid_mode_is_rejected(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("execution_mode: unsafe\n", encoding="utf-8")
    try:
        load_settings(config)
    except ValueError as exc:
        assert "execution_mode" in str(exc)
    else:
        raise AssertionError("invalid mode was accepted")
