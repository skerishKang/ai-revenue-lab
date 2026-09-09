"""httpx Drive read port for the Engine Worker (WO-10 PR-C2, D28).

The Engine runs as a Python Worker (Pyodide) where there is no socket and
``urllib.request`` is unavailable, so every outbound HTTP call is async
through ``httpx``. This module owns the OAuth token refresh and the bounded
provider GET; the trusted :class:`padiem_ai_core.drive_capability.DriveReadPort`
contract is implemented here, not in Padiem AI Core.

Secrets are injected, never stored. The three OAuth credentials (client id,
client secret, refresh token) come from Worker secrets; the grant facts
(grant references only) come from the D1-backed store in
``app/connector_grants_d1.py``.
"""

from __future__ import annotations

import json
import time
from typing import Any, Awaitable, Callable
from urllib.parse import urlencode

import httpx

from padiem_ai_core.drive_capability import (
    DRIVE_BASE_URL,
    DRIVE_READONLY_SCOPE,
    DriveReadPort,
)

# Worker secret names. The values themselves are never written to source,
# logs, error messages, or D1 — only the names are declared here so callers
# know which env vars to inject.
ENGINE_GOOGLE_OAUTH_CLIENT_ID = "ENGINE_GOOGLE_OAUTH_CLIENT_ID"
ENGINE_GOOGLE_OAUTH_CLIENT_SECRET = "ENGINE_GOOGLE_OAUTH_CLIENT_SECRET"
ENGINE_GOOGLE_OAUTH_REFRESH_TOKEN = "ENGINE_GOOGLE_OAUTH_REFRESH_TOKEN"

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
ALLOWED_DRIVE_HOSTS = frozenset({"www.googleapis.com", "oauth2.googleapis.com"})
DRIVE_API_HOST = "www.googleapis.com"
TOKEN_REFRESH_SKEW_SECONDS = 60
MAX_TOKEN_RESPONSE_BYTES = 64_000
DEFAULT_MAX_RESPONSE_BYTES = 2_000_000
MAX_GOOGLE_API_RESPONSE_BYTES = 4_000_000


class HttpxDriveReadPort(DriveReadPort):
    """Fetch-based Drive read port over httpx with OAuth refresh.

    Constructed only when all three Worker secrets are present; the
    composition root (``worker_identity._drive_port_for_env``) refuses to
    build the port otherwise, keeping Production fail-closed.
    """

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._transport = transport
        self._clock = clock
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    # --- token refresh ---------------------------------------------------

    async def _refresh(self) -> str:
        # OAuth token requests are application/x-www-form-urlencoded. Always
        # percent-encode credential values rather than concatenating them: real
        # secrets may legally contain '&', '=', '+', '%' and other reserved
        # characters that would otherwise change field boundaries or values.
        data = urlencode(
            {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            }
        )
        status = 0
        body = b""
        async with httpx.AsyncClient(
            transport=self._transport, follow_redirects=False
        ) as client:
            async with client.stream(
                "POST",
                GOOGLE_TOKEN_URL,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                content=data,
            ) as response:
                status = response.status_code
                chunks = bytearray()
                async for chunk in response.aiter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > MAX_TOKEN_RESPONSE_BYTES:
                        raise ValueError("provider_token_response_too_large")
                body = bytes(chunks)
        if status != 200:
            raise ValueError(f"provider_token_http_{status}")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("provider_token_invalid") from exc
        access_token = payload.get("access_token")
        expires_in = payload.get("expires_in")
        if not isinstance(access_token, str) or not access_token:
            raise ValueError("provider_token_invalid")
        if not isinstance(expires_in, (int, float)) or expires_in <= 0:
            raise ValueError("provider_token_invalid")
        # The granted scope must include the reviewed readonly scope.
        returned_scopes = payload.get("scope")
        if (
            not isinstance(returned_scopes, str)
            or DRIVE_READONLY_SCOPE not in returned_scopes.split()
        ):
            raise ValueError("scope_not_granted")
        self._access_token = access_token
        self._token_expires_at = self._clock() + float(expires_in) - TOKEN_REFRESH_SKEW_SECONDS
        return access_token

    async def _access_token_for(self) -> str:
        if (
            self._access_token is not None
            and self._clock() < self._token_expires_at
        ):
            return self._access_token
        return await self._refresh()

    # --- bounded provider GET -------------------------------------------

    async def _stream_get(
        self,
        *,
        token: str,
        url: str,
        params: dict[str, str] | None,
        max_response_bytes: int,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(
            transport=self._transport, timeout=timeout_seconds, follow_redirects=False
        ) as client:
            async with client.stream(
                "GET",
                url,
                params=params or None,
                headers={"Authorization": f"Bearer {token}"},
            ) as response:
                status = response.status_code
                if status < 200 or status >= 300:
                    raise ValueError(f"provider_http_{status}")
                chunks = bytearray()
                async for chunk in response.aiter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > max_response_bytes:
                        raise ValueError("response_too_large")
                body = bytes(chunks)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("provider_response_invalid") from exc
        if not isinstance(payload, dict):
            raise ValueError("provider_response_invalid")
        return payload

    async def _stream_get_text(
        self,
        *,
        token: str,
        url: str,
        params: dict[str, str] | None,
        max_response_bytes: int,
        timeout_seconds: int,
    ) -> str:
        async with httpx.AsyncClient(
            transport=self._transport, timeout=timeout_seconds, follow_redirects=False
        ) as client:
            async with client.stream(
                "GET",
                url,
                params=params or None,
                headers={"Authorization": f"Bearer {token}"},
            ) as response:
                status = response.status_code
                if status < 200 or status >= 300:
                    raise ValueError(f"provider_http_{status}")
                chunks = bytearray()
                async for chunk in response.aiter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > max_response_bytes:
                        raise ValueError("response_too_large")
                body = bytes(chunks)
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("provider_response_invalid") from exc
        if not isinstance(text, str):
            raise ValueError("provider_response_invalid")
        return text

    # --- DriveReadPort --------------------------------------------------

    async def get_json(
        self,
        *,
        binding_ref: str,
        actor_ref: str,
        required_scopes: tuple[str, ...],
        base_url: str,
        path: str,
        query: dict[str, str],
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> dict[str, Any] | Awaitable[dict[str, Any]]:
        # (1) Scope gate: the port only ever runs the reviewed readonly scope.
        if not set(required_scopes) <= {DRIVE_READONLY_SCOPE}:
            raise ValueError("scope_not_permitted")
        # (2) Host gate: the port only talks to the allowed Google API host.
        host = base_url.split("://", 1)[-1].split("/", 1)[0]
        if host != DRIVE_API_HOST:
            raise ValueError("host_not_permitted")
        # (3) Refresh the OAuth token, then GET the bounded provider body.
        url = f"{base_url.rstrip('/')}{path}"
        params = {key: value for key, value in query.items()}
        token = await self._access_token_for()
        for attempt in range(2):
            try:
                return await self._stream_get(
                    token=token,
                    url=url,
                    params=params,
                    max_response_bytes=max_response_bytes,
                    timeout_seconds=timeout_seconds,
                )
            except ValueError as exc:
                if str(exc) == "provider_http_401" and attempt == 0:
                    self._access_token = None
                    token = await self._access_token_for()
                    continue
                raise
        raise ValueError("provider_http_401")

    async def get_text(
        self,
        *,
        binding_ref: str,
        actor_ref: str,
        required_scopes: tuple[str, ...],
        base_url: str,
        path: str,
        query: dict[str, str],
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> str | Awaitable[str]:
        # (1) Scope gate.
        if not set(required_scopes) <= {DRIVE_READONLY_SCOPE}:
            raise ValueError("scope_not_permitted")
        # (2) Host gate.
        host = base_url.split("://", 1)[-1].split("/", 1)[0]
        if host != DRIVE_API_HOST:
            raise ValueError("host_not_permitted")
        # (3) Refresh the OAuth token, then GET the bounded provider body.
        url = f"{base_url.rstrip('/')}{path}"
        params = {key: value for key, value in query.items()}
        token = await self._access_token_for()
        for attempt in range(2):
            try:
                return await self._stream_get_text(
                    token=token,
                    url=url,
                    params=params,
                    max_response_bytes=max_response_bytes,
                    timeout_seconds=timeout_seconds,
                )
            except ValueError as exc:
                if str(exc) == "provider_http_401" and attempt == 0:
                    self._access_token = None
                    token = await self._access_token_for()
                    continue
                raise
        raise ValueError("provider_http_401")


__all__ = [
    "ENGINE_GOOGLE_OAUTH_CLIENT_ID",
    "ENGINE_GOOGLE_OAUTH_CLIENT_SECRET",
    "ENGINE_GOOGLE_OAUTH_REFRESH_TOKEN",
    "HttpxDriveReadPort",
    "DriveReadPort",
]
