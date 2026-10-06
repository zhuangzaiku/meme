from __future__ import annotations

from collections.abc import AsyncIterator

from web3 import AsyncHTTPProvider, AsyncWeb3

from app.chains.base import ChainEvent, OrderIntent, Quote, SimulationResult


class EvmChainAdapter:
    def __init__(self, chain: str, rpc_http: str | None) -> None:
        if not rpc_http:
            raise ValueError(f"RPC endpoint is not configured for {chain}")
        self.chain = chain
        self.web3 = AsyncWeb3(AsyncHTTPProvider(rpc_http))

    async def get_latest_block(self) -> int:
        return await self.web3.eth.block_number

    async def get_chain_id(self) -> int:
        return await self.web3.eth.chain_id

    async def get_balance(self, address: str) -> int:
        checksum_address = self.web3.to_checksum_address(address)
        return await self.web3.eth.get_balance(checksum_address)

    async def get_quote(self, token: str, amount: int, side: str) -> Quote:
        raise NotImplementedError(f"No DEX quote source configured for {self.chain}")

    async def simulate_swap(self, order: OrderIntent) -> SimulationResult:
        return SimulationResult(ok=False, error="no DEX route configured")

    def subscribe_events(self) -> AsyncIterator[ChainEvent]:
        raise NotImplementedError("WebSocket event subscription is not configured")
