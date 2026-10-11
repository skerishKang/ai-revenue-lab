from __future__ import annotations

import json
from typing import Any, Awaitable

import httpx

from padiem_ai_core.connectors import (
    GMAIL_READONLY_SCOPE,
    GmailReadPort,
)
from padiem_ai_core.tool_runtime import ToolHandlerError

from app.google_oauth_access_lease import (
    CloudflareControlPlaneGoogleOAuthAccessLeaseClient,
    EngineGoogleOAuthAccessLease,
)
from app.service import ServiceContractError


GMAIL_API_HOST = "gmail.googleapis.com"
MAX_GOOGLE_API_RESPONSE_BYTES = 4_000_000


def _lease_mismatch(message: str) -> ToolHandlerError:
    return ToolHandlerError("gmail_access_lease_mismatch", message)


def _provider_unavailable(message: str) -> ToolHandlerError:
    return ToolHandlerError("gmail_provider_unavailable", message)


def _provider_credential_rejected(message: str) -> ToolHandlerError:
    return ToolHandlerError("gmail_provider_credential_rejected", message)


class ControlPlaneLeaseGmailReadPort(GmailReadPort):
    """Gmail READ port using short-lived access leases from Control Plane.

    This is the canonical Production path. It receives only the server-derived
    Gmail binding/actor references and a short-lived access lease. Client
    secrets and long-lived refresh credentials never enter this port.
    """

    def __init__(
        self,
        *,
        lease_client: CloudflareControlPlaneGoogleOAuthAccessLeaseClient,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not callable(getattr(lease_client, "issue_access_lease", None)):
            raise ValueError("lease_client must expose issue_access_lease")
        self._lease_client = lease_client
        self._transport = transport

    async def _lease_for(
        self,
        *,
        binding_ref: str,
        actor_ref: str,
        required_scopes: tuple[str, ...],
    ) -> EngineGoogleOAuthAccessLease:
        if tuple(required_scopes) != (GMAIL_READONLY_SCOPE,):
            raise _lease_mismatch("Gmail scope is not the reviewed readonly scope.")
        try:
            lease = await self._lease_client.issue_access_lease(
                binding_ref=binding_ref,
                connector_id="gmail",
            )
        except ServiceContractError as exc:
            raise ToolHandlerError(exc.code, exc.safe_message) from exc
        except Exception:
            raise ToolHandlerError(
                "google_oauth_access_lease_unavailable",
                "Control Plane Google OAuth access lease could not be issued.",
            ) from None
        if lease.binding_ref != binding_ref or lease.actor_ref != actor_ref:
            raise _lease_mismatch("Gmail access lease does not match the trusted grant.")
        if lease.scopes != (GMAIL_READONLY_SCOPE,):
            raise _lease_mismatch("Gmail access lease scope mismatch.")
        return lease

    @staticmethod
    def _url(*, base_url: str, path: str) -> str:
        if not isinstance(base_url, str) or not base_url.startswith("https://"):
            raise _provider_unavailable("Gmail base URL is invalid.")
        host = base_url.split("://", 1)[-1].split("/", 1)[0]
        if host != GMAIL_API_HOST:
            raise _provider_unavailable("Gmail host is not permitted.")
        if not isinstance(path, str) or not path.startswith("/"):
            raise _provider_unavailable("Gmail path is invalid.")
        return f"{base_url.rstrip('/')}{path}"

    async def _get_bytes(
        self,
        *,
        token: str,
        url: str,
        query: dict[str, str],
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> tuple[int, bytes]:
        if (
            isinstance(max_response_bytes, bool)
            or not isinstance(max_response_bytes, int)
            or not 1 <= max_response_bytes <= MAX_GOOGLE_API_RESPONSE_BYTES
        ):
            raise _provider_unavailable("Gmail response bound is invalid.")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or not 1 <= timeout_seconds <= 60
        ):
            raise _provider_unavailable("Gmail timeout is invalid.")
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=timeout_seconds,
                follow_redirects=False,
            ) as client:
                async with client.stream(
                    "GET",
                    url,
                    params=dict(query) or None,
                    headers={"Authorization": f"Bearer {token}"},
                ) as response:
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > max_response_bytes:
                            raise _provider_unavailable(
                                "Gmail response exceeded the trusted bound."
                            )
                    return response.status_code, bytes(chunks)
        except ToolHandlerError:
            raise
        except httpx.HTTPError:
            raise _provider_unavailable("Gmail provider request failed.") from None

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
        url = self._url(base_url=base_url, path=path)
        for attempt in range(2):
            lease = await self._lease_for(
                binding_ref=binding_ref,
                actor_ref=actor_ref,
                required_scopes=required_scopes,
            )
            status, body = await self._get_bytes(
                token=lease.access_token,
                url=url,
                query=query,
                timeout_seconds=timeout_seconds,
                max_response_bytes=max_response_bytes,
            )
            if status == 401 and attempt == 0:
                # Never cache the access token. Request one fresh CP lease and
                # retry the same bounded GET exactly once.
                continue
            if status < 200 or status >= 300:
                raise _provider_unavailable(f"Gmail provider returned HTTP {status}.")
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise _provider_unavailable("Gmail provider response is invalid JSON.") from None
            if not isinstance(payload, dict):
                raise _provider_unavailable("Gmail provider response must be an object.")
            return payload
        raise _provider_credential_rejected(
            "Gmail provider rejected refreshed access credentials."
        )


RAW_REFRESH_TOKEN_ACCEPTED = False
ACCESS_TOKEN_CACHED = False
GMAIL_WRITE = False
GMAIL_CREATE_DRAFT = False
GMAIL_SEND = False
