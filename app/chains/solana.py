from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx


@dataclass(frozen=True)
class SolanaSignature:
    signature: str
    slot: int
    block_time: datetime | None


class SolanaRpc(Protocol):
    async def get_account_info(self, address: str) -> Mapping[str, Any] | None: ...

    async def get_signatures_for_address(
        self, address: str, limit: int, until: str | None
    ) -> list[SolanaSignature]: ...

    async def get_transaction(self, signature: str) -> Mapping[str, Any] | None: ...


class SolanaRpcAdapter:
    def __init__(
        self,
        rpc_http: str,
        proxy_url: str | None = None,
        timeout_seconds: float = 20.0,
        max_retries: int = 3,
        commitment: str = "confirmed",
        transport: httpx.AsyncBaseTransport | None = None,
        retry_base_seconds: float = 0.25,
    ) -> None:
        if not rpc_http:
            raise ValueError("Solana RPC endpoint is required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if retry_base_seconds < 0:
            raise ValueError("retry_base_seconds must be non-negative")
        self.rpc_http = rpc_http
        self.proxy_url = proxy_url
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.commitment = commitment
        self.transport = transport
        self.retry_base_seconds = retry_base_seconds
        self._request_id = 0

    async def get_account_info(self, address: str) -> Mapping[str, Any] | None:
        result = await self._request(
            "getAccountInfo",
            [address, {"encoding": "jsonParsed", "commitment": self.commitment}],
        )
        if not isinstance(result, Mapping):
            raise ConnectionError("Solana getAccountInfo result is malformed")
        value = result.get("value")
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise ConnectionError("Solana account value is malformed")
        return value

    async def get_signatures_for_address(
        self, address: str, limit: int, until: str | None
    ) -> list[SolanaSignature]:
        if limit < 1:
            raise ValueError("signature limit must be positive")
        options: dict[str, Any] = {"limit": limit, "commitment": self.commitment}
        if until is not None:
            options["until"] = until
        result = await self._request("getSignaturesForAddress", [address, options])
        if not isinstance(result, list):
            raise ConnectionError("Solana signature result is malformed")
        signatures: list[SolanaSignature] = []
        for item in result:
            if not isinstance(item, Mapping) or item.get("err") is not None:
                continue
            signature = item.get("signature")
            slot = item.get("slot")
            if not isinstance(signature, str) or not isinstance(slot, int):
                raise ConnectionError("Solana signature item is malformed")
            block_time = item.get("blockTime")
            if block_time is not None and not isinstance(block_time, (int, float)):
                raise ConnectionError("Solana blockTime is malformed")
            signatures.append(
                SolanaSignature(
                    signature=signature,
                    slot=slot,
                    block_time=(
                        datetime.fromtimestamp(block_time, UTC)
                        if block_time is not None
                        else None
                    ),
                )
            )
        return signatures

    async def get_transaction(self, signature: str) -> Mapping[str, Any] | None:
        result = await self._request(
            "getTransaction",
            [
                signature,
                {
                    "encoding": "jsonParsed",
                    "commitment": self.commitment,
                    "maxSupportedTransactionVersion": 0,
                },
            ],
        )
        if result is None:
            return None
        if not isinstance(result, Mapping):
            raise ConnectionError("Solana transaction result is malformed")
        return result

    async def _request(self, method: str, params: list[object]) -> object:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._request_id += 1
            payload = {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": method,
                "params": params,
            }
            client_kwargs: dict[str, Any] = {
                "timeout": self.timeout_seconds,
                "transport": self.transport,
            }
            if self.transport is None and self.proxy_url:
                client_kwargs["proxy"] = self.proxy_url
            try:
                async with httpx.AsyncClient(**client_kwargs) as client:
                    response = await client.post(self.rpc_http, json=payload)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, Mapping):
                    raise ConnectionError("Solana JSON-RPC response is malformed")
                error = data.get("error")
                if isinstance(error, Mapping):
                    raise ConnectionError(str(error.get("message", error)))
                if "result" not in data:
                    raise ConnectionError("Solana JSON-RPC response has no result")
                return data["result"]
            except ConnectionError:
                raise
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
                status_code = (
                    exc.response.status_code
                    if isinstance(exc, httpx.HTTPStatusError)
                    else None
                )
                retryable = status_code == 429 or status_code is None or status_code >= 500
                if not retryable or attempt >= self.max_retries:
                    raise
                await asyncio.sleep(self.retry_base_seconds * (2**attempt))
        raise ConnectionError("Solana RPC request failed") from last_error
