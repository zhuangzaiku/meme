from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.audit import AuditLog

ExecutionMode = Literal["paper", "approval", "auto"]


@dataclass
class ControlState:
    execution_mode: ExecutionMode = "paper"
    paused: bool = False
    validation_approved: bool = False
    orders: dict[str, dict[str, object]] = field(default_factory=dict)
    positions: list[dict[str, object]] = field(default_factory=list)
    signals: list[dict[str, object]] = field(default_factory=list)


class ModeRequest(BaseModel):
    mode: ExecutionMode


class OrderRequest(BaseModel):
    chain: str = "bnb"
    token: str
    side: Literal["buy", "sell"]
    amount: float = Field(default=0.0, ge=0)
    max_slippage_percent: float = Field(default=1.5, ge=0)


def create_router(state: ControlState, audit: AuditLog) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/status")
    def status() -> dict[str, object]:
        return {
            "execution_mode": state.execution_mode,
            "paused": state.paused,
            "validation_approved": state.validation_approved,
        }

    @router.get("/positions")
    def positions() -> list[dict[str, object]]:
        return state.positions

    @router.get("/orders")
    def orders() -> list[dict[str, object]]:
        return list(state.orders.values())

    @router.get("/signals")
    def signals() -> list[dict[str, object]]:
        return state.signals

    @router.post("/orders", status_code=202)
    def submit_order(request: OrderRequest) -> dict[str, object]:
        if state.paused:
            raise HTTPException(status_code=423, detail="agent is paused")
        order_id = str(uuid4())
        order = {"id": order_id, **request.model_dump(), "status": "accepted"}
        state.orders[order_id] = order
        audit.record("order_submitted", order_id=order_id, mode=state.execution_mode)
        return order

    @router.post("/execution-mode")
    def set_execution_mode(request: ModeRequest) -> dict[str, object]:
        if request.mode == "auto" and not state.validation_approved:
            raise HTTPException(
                status_code=409, detail="validation gate has not approved auto mode"
            )
        previous = state.execution_mode
        state.execution_mode = request.mode
        audit.record("execution_mode_changed", previous=previous, current=request.mode)
        return status()

    @router.post("/pause")
    def pause() -> dict[str, object]:
        state.paused = True
        audit.record("paused")
        return status()

    @router.post("/resume")
    def resume() -> dict[str, object]:
        state.paused = False
        audit.record("resumed")
        return status()

    @router.post("/orders/{order_id}/approve")
    def approve_order(order_id: str) -> dict[str, object]:
        order = state.orders.get(order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="order not found")
        order["status"] = "approved"
        audit.record("order_approved", order_id=order_id)
        return order

    @router.post("/positions/{position_id}/exit")
    def exit_position(position_id: str) -> dict[str, str]:
        audit.record("position_exit_requested", position_id=position_id)
        return {"status": "exit_requested", "position_id": position_id}

    return router
