from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field

from app.chains.base import ChainAdapter
from app.chains.evm import EvmChainAdapter
from app.config import load_settings


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    chain_id: int | None = None
    errors: list[str] = field(default_factory=list)


class NetworkProbe:
    def __init__(self, adapter: ChainAdapter) -> None:
        self.adapter = adapter

    async def verify(self, expected_chain_id: int | None) -> ProbeResult:
        if expected_chain_id is None:
            return ProbeResult(False, errors=["expected chain id is not configured"])
        try:
            observed_chain_id = await self.adapter.get_chain_id()
        except Exception as exc:  # provider errors are reported, not hidden
            return ProbeResult(False, errors=[f"provider error: {exc}"])
        if observed_chain_id != expected_chain_id:
            return ProbeResult(
                False,
                chain_id=observed_chain_id,
                errors=[
                    f"chain id mismatch: expected {expected_chain_id}, got {observed_chain_id}"
                ],
            )
        return ProbeResult(True, chain_id=observed_chain_id)


async def _probe_network(network: str) -> int:
    settings = load_settings()
    chain = settings.chains.get(network)
    if chain is None:
        print(f"{network}: unavailable (unknown network)")
        return 1
    try:
        adapter = EvmChainAdapter(network, chain.rpc_http)
    except ValueError as exc:
        print(f"{network}: unavailable ({exc})")
        return 1
    result = await NetworkProbe(adapter).verify(chain.chain_id)
    if result.ok:
        print(f"{network}: OK chain_id={result.chain_id}")
        return 0
    print(f"{network}: unavailable ({'; '.join(result.errors)})")
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only EVM network probe")
    parser.add_argument("--network", choices=["bnb", "robinhood"], required=True)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_probe_network(args.network)))


if __name__ == "__main__":
    main()
