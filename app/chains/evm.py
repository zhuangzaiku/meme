from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from web3 import AsyncHTTPProvider, AsyncWeb3

from app.chains.base import ChainEvent, OrderIntent, Quote, SimulationResult


class EvmChainAdapter:
    def __init__(self, chain: str, rpc_http: str | None, proxy_url: str | None = None) -> None:
        if not rpc_http:
            raise ValueError(f"RPC endpoint is not configured for {chain}")
        self.chain = chain
        request_kwargs = {"proxy": proxy_url} if proxy_url else None
        self.web3 = AsyncWeb3(AsyncHTTPProvider(rpc_http, request_kwargs=request_kwargs))

    async def get_latest_block(self) -> int:
        return await self.web3.eth.block_number

    async def get_chain_id(self) -> int:
        return await self.web3.eth.chain_id

    async def get_balance(self, address: str) -> int:
        checksum_address = self.web3.to_checksum_address(address)
        return await self.web3.eth.get_balance(checksum_address)

    async def get_code(self, address: str) -> str:
        checksum_address = self.web3.to_checksum_address(address)
        return (await self.web3.eth.get_code(checksum_address)).hex()

    async def get_pool_token0(self, address: str) -> str:
        checksum_address = self.web3.to_checksum_address(address)
        selector = self.web3.keccak(text="token0()")[:4]
        result = await self.web3.eth.call({"to": checksum_address, "data": selector})
        return self.web3.to_checksum_address("0x" + bytes(result)[-20:].hex()).lower()

    async def get_logs(
        self, address: str, topics: list[str], from_block: int, to_block: int
    ) -> list[dict[str, object]]:
        logs = await self.web3.eth.get_logs(
            {
                "address": self.web3.to_checksum_address(address),
                "topics": [[topic if topic.startswith("0x") else f"0x{topic}" for topic in topics]],
                "fromBlock": from_block,
                "toBlock": to_block,
            }
        )
        return [dict(log) for log in logs]

    async def get_block_timestamp(self, block_number: int) -> datetime:
        block = await self.web3.eth.get_block(block_number)
        return datetime.fromtimestamp(int(block["timestamp"]), UTC)

    async def get_quote(self, token: str, amount: int, side: str) -> Quote:
        raise NotImplementedError(f"No DEX quote source configured for {self.chain}")

    async def simulate_swap(self, order: OrderIntent) -> SimulationResult:
        return SimulationResult(ok=False, error="no DEX route configured")

    def subscribe_events(self) -> AsyncIterator[ChainEvent]:
        raise NotImplementedError("WebSocket event subscription is not configured")
