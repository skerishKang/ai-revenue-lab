from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from typing import Any, Protocol

import httpx


@dataclass(frozen=True, slots=True)
class B14TransportResponse:
    status_code: int
    body: bytes

    def __post_init__(self) -> None:
        if isinstance(self.status_code, bool) or not isinstance(self.status_code, int):
            raise ValueError("status_code must be an integer")
        if not 100 <= self.status_code <= 599:
            raise ValueError("status_code must be a valid HTTP status")
        if not isinstance(self.body, (bytes, bytearray)):
            raise ValueError("body must be bytes")
        object.__setattr__(self, "body", bytes(self.body))


class B14Transport(Protocol):
    async def post_json(self, url: str, payload: dict[str, Any]) -> B14TransportResponse: ...


class B14PostJSONTransport(httpx.AsyncBaseTransport):
    """Bridge a product-neutral post_json transport into Core's HTTP execution path.

    Business 14 status classification, response-size enforcement, JSON parsing and
    route metadata parsing remain owned by B14ExecutionClient. This adapter only
    translates the transport boundary and never retries.
    """

    def __init__(self, transport: B14Transport, *, timeout_seconds: float = 20.0) -> None:
        if transport is None:
            raise ValueError("transport is required")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 1 <= float(timeout_seconds) <= 60
        ):
            raise ValueError("timeout_seconds must be between 1 and 60")
        self._transport = transport
        self._timeout_seconds = float(timeout_seconds)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        try:
            body = await request.aread()
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise httpx.TransportError("invalid Core request payload", request=request) from exc
        if not isinstance(payload, dict):
            raise httpx.TransportError("invalid Core request payload", request=request)

        try:
            response = await asyncio.wait_for(
                self._transport.post_json(str(request.url), payload),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as exc:
            raise httpx.ReadTimeout("B14 transport timed out", request=request) from exc
        except httpx.HTTPError:
            raise
        except Exception as exc:
            raise httpx.TransportError("B14 transport unavailable", request=request) from exc

        if not isinstance(response, B14TransportResponse):
            raise httpx.TransportError("invalid B14 transport response", request=request)
        return httpx.Response(
            status_code=response.status_code,
            content=response.body,
            request=request,
        )
