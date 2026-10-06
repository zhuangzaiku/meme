from __future__ import annotations

import argparse

from fastapi import FastAPI

from app.api.audit import AuditLog
from app.api.routes import ControlState, create_router
from app.api.websocket import create_websocket_router
from app.config import load_settings


def create_app() -> FastAPI:
    settings = load_settings()
    state = ControlState(execution_mode=settings.execution_mode)
    audit = AuditLog()
    application = FastAPI(title="Meme Agent")
    application.include_router(create_router(state, audit))
    application.include_router(create_websocket_router(state))
    application.state.control = state
    application.state.audit = audit
    return application


def main() -> None:
    parser = argparse.ArgumentParser(description="Realtime Meme agent")
    parser.add_argument("--mode", choices=["paper", "approval", "auto"], default=None)
    parser.add_argument("--check-connectors", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    settings = load_settings()
    mode = args.mode or settings.execution_mode
    if args.check_connectors:
        for name, chain in settings.chains.items():
            status = (
                "configured" if chain.rpc_http and chain.chain_id is not None else "unavailable"
            )
            print(f"{name}: {status}")
        return
    if args.dry_run and mode == "approval":
        print("approval dry-run; no private key loaded and no transaction broadcast")
        return
    if args.dry_run and mode == "auto":
        print("auto dry-run rejected: live broadcast is disabled")
        return
    if mode != "paper" or not args.dry_run:
        print(f"meme-agent mode={mode}; runtime loop is not enabled yet")
        return
    print("meme-agent mode=paper; dry-run only")


if __name__ == "__main__":
    main()
