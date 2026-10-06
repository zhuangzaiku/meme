from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
    chains: dict[str, ChainSettings]


def _merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_settings(path: Path | None = None) -> Settings:
    project_root = Path(__file__).resolve().parent.parent
    default_path = project_root / "configs" / "default.yaml"
    raw = _merge(_read_yaml(default_path), _read_yaml(path) if path else {})

    chains = raw.setdefault("chains", {})
    for key, env_name in (("bnb", "BNB_RPC_URL"), ("robinhood", "ROBINHOOD_RPC_URL")):
        if os.getenv(env_name):
            chains.setdefault(key, {})["rpc_http"] = os.environ[env_name]

    try:
        return Settings.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
