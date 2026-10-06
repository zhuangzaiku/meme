from __future__ import annotations

from fastapi import APIRouter, WebSocket

from app.api.routes import ControlState


def create_websocket_router(state: ControlState) -> APIRouter:
    router = APIRouter()

    @router.websocket("/events")
    async def events(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_json(
            {
                "type": "status",
                "execution_mode": state.execution_mode,
                "paused": state.paused,
            }
        )
        await websocket.close()

    return router
