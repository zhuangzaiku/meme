from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from web3 import Web3

ExecutionMode = Literal["paper", "approval", "auto"]


class RiskSettings(BaseModel):
    risk_per_trade: float = 0.0025
    max_position_percent: float = 0.03
    max_concurrent_positions: int = 5
    max_narrative_exposure: float = 0.08
    max_slippage_percent: float = 1.5
    daily_loss_limit: float = 0.015
    max_consecutive_losses: int = 3
    reserve_balance_percent: float = 20.0
    cooldown_after_exit_minutes: int = 30
    allow_averaging_down: bool = False


class MarketChainSettings(BaseModel):
    poll_interval_seconds: float = 5.0
    collection_timeout_seconds: float = 10.0


class MarketSourceSettings(BaseModel):
    proxy_url: str = "http://127.0.0.1:7890"
    discovery_interval_seconds: int = 60
    max_pools_per_chain: int = 2
    max_log_block_span: int = 25
    http_timeout_seconds: float = 10.0
    collection_timeout_seconds: float = 10.0
    max_retries: int = 3
    per_chain: dict[str, MarketChainSettings] = Field(
        default_factory=lambda: {
            "bnb": MarketChainSettings(),
            "robinhood": MarketChainSettings(
                poll_interval_seconds=15.0,
                collection_timeout_seconds=30.0,
            ),
        }
    )


class ExternalSignalSettings(BaseModel):
    enabled: bool = True
    gmgn_base_url: str = "https://papi.gmgn.ai/callout/openapi/v1"
    gmgn_ak_env: str = "GMGN_AK"
    gmgn_sk_env: str = "GMGN_SK"
    max_tokens_per_cycle: int = 2


NativeEventKind = Literal["v2_pair_created", "v3_pool_created", "four_meme"]


class NativeProtocolSettings(BaseModel):
    enabled: bool = True
    chain: str = "bnb"
    contract_address: str | None = None
    event_kind: NativeEventKind
    dex_id: str

    @field_validator("contract_address")
    @classmethod
    def validate_contract_address(cls, value: str | None) -> str | None:
        if value is not None:
            if not Web3.is_address(value):
                raise ValueError("contract_address must be a valid EVM address")
            return value.lower()
        return None

    @model_validator(mode="after")
    def enabled_protocol_requires_address(self) -> NativeProtocolSettings:
        if self.enabled and self.contract_address is None:
            raise ValueError("enabled native protocol requires contract_address")
        return self


class NativeDiscoverySettings(BaseModel):
    enabled: bool = True
    initial_backfill_blocks: int = Field(default=500, gt=0)
    max_log_block_span: int = Field(default=1000, gt=0)
    max_pools_per_protocol: int = Field(default=50, gt=0)
    stale_cache_seconds: int = Field(default=300, gt=0)
    protocols: dict[str, NativeProtocolSettings] = Field(
        default_factory=lambda: {
            "pancakeswap_v2": NativeProtocolSettings(
                contract_address="0xca143ce32fe78f1f7019d7d551a6402fc5350c73",
                event_kind="v2_pair_created",
                dex_id="pancakeswap-v2",
            ),
            "pancakeswap_v3": NativeProtocolSettings(
                contract_address="0x0bfbcf9fa4f9c56b0f40a671ad40e0805a091865",
                event_kind="v3_pool_created",
                dex_id="pancakeswap-v3",
            ),
        }
    )


class ChainSettings(BaseModel):
    name: str
    chain_id: int | None = None
    rpc_http: str | None = None
    rpc_ws: str | None = None
    native_symbol: str | None = None


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_mode: ExecutionMode = "paper"
    risk: RiskSettings = Field(default_factory=RiskSettings)
    market: MarketSourceSettings = Field(default_factory=MarketSourceSettings)
    external: ExternalSignalSettings = Field(default_factory=ExternalSignalSettings)
    native_discovery: NativeDiscoverySettings = Field(default_factory=NativeDiscoverySettings)
    chains: dict[str, ChainSettings]


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _apply_network_registry(raw: dict[str, Any], project_root: Path) -> None:
    registry = _read_yaml(project_root / "configs" / "networks.yaml")
    chains = raw.setdefault("chains", {})
    for name, metadata in registry.items():
        if not isinstance(metadata, dict):
            continue
        chain = chains.setdefault(name, {})
        for field in ("chain_id", "native_symbol"):
            if chain.get(field) is None and metadata.get(field) is not None:
                chain[field] = metadata[field]
        rpc_reference = metadata.get("rpc_env")
        if chain.get("rpc_http") is None and isinstance(rpc_reference, str):
            if rpc_reference.startswith(("http://", "https://")):
                chain["rpc_http"] = rpc_reference
            elif os.getenv(rpc_reference):
                chain["rpc_http"] = os.environ[rpc_reference]


def load_settings(path: Path | None = None) -> Settings:
    project_root = Path(__file__).resolve().parent.parent
    default_path = project_root / "configs" / "default.yaml"
    raw = _merge(_read_yaml(default_path), _read_yaml(path) if path else {})
    _apply_network_registry(raw, project_root)

    chains = raw.setdefault("chains", {})
    for key, env_name in (("bnb", "BNB_RPC_URL"), ("robinhood", "ROBINHOOD_RPC_URL")):
        if os.getenv(env_name):
            chains.setdefault(key, {})["rpc_http"] = os.environ[env_name]

    try:
        return Settings.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
