from __future__ import annotations

import argparse

from app.config import load_settings


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
    if mode != "paper" or not args.dry_run:
        print(f"meme-agent mode={mode}; runtime loop is not enabled yet")
        return
    print("meme-agent mode=paper; dry-run only")


if __name__ == "__main__":
    main()
