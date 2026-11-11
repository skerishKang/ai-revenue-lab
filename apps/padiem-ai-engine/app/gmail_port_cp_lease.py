from __future__ import annotations

import json
import re
from typing import Any, Awaitable

import httpx

from padiem_ai_core.connectors import (
    GMAIL_COMPOSE_SCOPE,
    GMAIL_READONLY_SCOPE,
    GmailDraftPort,
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


_ALLOWED_REQUIRED_SCOPE_TUPLES = frozenset(
    {
        (GMAIL_READONLY_SCOPE,),
        (GMAIL_COMPOSE_SCOPE,),
    }
)
_DRAFT_DELETE_PATH_RE = re.compile(r"\A/users/me/drafts/[A-Za-z0-9._:@+\-%]{1,256}\Z")


class ControlPlaneLeaseGmailReadPort(GmailReadPort, GmailDraftPort):
    """Gmail READ + draft create/delete port using short-lived CP access leases.

    This is the canonical Production path. It receives only the server-derived
    Gmail binding/actor references and a short-lived access lease. Client
    secrets and long-lived refresh credentials never enter this port. Mail send
    endpoints remain strictly forbidden (#7088).
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
        normalized_required = tuple(required_scopes)
        if normalized_required not in _ALLOWED_REQUIRED_SCOPE_TUPLES:
            raise _lease_mismatch("Gmail scope is not in the reviewed readonly/compose set.")
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
        lease_scope_set = set(lease.scopes)
        if not lease_scope_set <= {GMAIL_READONLY_SCOPE, GMAIL_COMPOSE_SCOPE}:
            raise _lease_mismatch("Gmail access lease scope mismatch.")
        if not set(normalized_required) <= lease_scope_set:
            raise _lease_mismatch("Gmail access lease lacks the required scope.")
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
        timeout_seconds: int | None,
        max_response_bytes: int,
    ) -> tuple[int, bytes]:
        if (
            isinstance(max_response_bytes, bool)
            or not isinstance(max_response_bytes, int)
            or not 1 <= max_response_bytes <= MAX_GOOGLE_API_RESPONSE_BYTES
        ):
            raise _provider_unavailable("Gmail response bound is invalid.")
        if (
            timeout_seconds is not None
            and (
                isinstance(timeout_seconds, bool)
                or not isinstance(timeout_seconds, int)
                or not 1 <= timeout_seconds <= 60
            )
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
        timeout_seconds: int | None,
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

    async def _request_bytes(
        self,
        *,
        method: str,
        token: str,
        url: str,
        json_body: dict[str, Any] | None,
        timeout_seconds: int | None,
        max_response_bytes: int,
    ) -> tuple[int, bytes]:
        if (
            isinstance(max_response_bytes, bool)
            or not isinstance(max_response_bytes, int)
            or not 1 <= max_response_bytes <= MAX_GOOGLE_API_RESPONSE_BYTES
        ):
            raise _provider_unavailable("Gmail response bound is invalid.")
        if (
            timeout_seconds is not None
            and (
                isinstance(timeout_seconds, bool)
                or not isinstance(timeout_seconds, int)
                or not 1 <= timeout_seconds <= 60
            )
        ):
            raise _provider_unavailable("Gmail timeout is invalid.")
        headers = {"Authorization": f"Bearer {token}"}
        content_bytes: bytes | None = None
        if json_body is not None:
            headers["Content-Type"] = "application/json"
            content_bytes = json.dumps(json_body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=timeout_seconds,
                follow_redirects=False,
            ) as client:
                async with client.stream(
                    method,
                    url,
                    headers=headers,
                    content=content_bytes,
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

    async def post_json(
        self,
        *,
        binding_ref: str,
        actor_ref: str,
        required_scopes: tuple[str, ...],
        base_url: str,
        path: str,
        json_body: dict[str, Any],
        timeout_seconds: int | None,
        max_response_bytes: int,
    ) -> dict[str, Any]:
        # Hard endpoint allowlist: draft creation ONLY. Mail/draft send is forbidden.
        if path != "/users/me/drafts":
            raise _provider_unavailable("Gmail POST is restricted to /users/me/drafts.")
        if not isinstance(json_body, dict):
            raise _provider_unavailable("Gmail draft payload must be an object.")
        url = self._url(base_url=base_url, path=path)
        for attempt in range(2):
            lease = await self._lease_for(
                binding_ref=binding_ref,
                actor_ref=actor_ref,
                required_scopes=required_scopes,
            )
            status, body = await self._request_bytes(
                method="POST",
                token=lease.access_token,
                url=url,
                json_body=json_body,
                timeout_seconds=timeout_seconds,
                max_response_bytes=max_response_bytes,
            )
            if status == 401 and attempt == 0:
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

    async def delete(
        self,
        *,
        binding_ref: str,
        actor_ref: str,
        required_scopes: tuple[str, ...],
        base_url: str,
        path: str,
        timeout_seconds: int | None,
        max_response_bytes: int,
    ) -> None:
        if not isinstance(path, str) or _DRAFT_DELETE_PATH_RE.fullmatch(path) is None:
            raise _provider_unavailable("Gmail DELETE is restricted to /users/me/drafts/{id}.")
        url = self._url(base_url=base_url, path=path)
        for attempt in range(2):
            lease = await self._lease_for(
                binding_ref=binding_ref,
                actor_ref=actor_ref,
                required_scopes=required_scopes,
            )
            status, _body = await self._request_bytes(
                method="DELETE",
                token=lease.access_token,
                url=url,
                json_body=None,
                timeout_seconds=timeout_seconds,
                max_response_bytes=max_response_bytes,
            )
            if status == 401 and attempt == 0:
                continue
            if status < 200 or status >= 300:
                raise _provider_unavailable(f"Gmail provider returned HTTP {status}.")
            return
        raise _provider_credential_rejected(
            "Gmail provider rejected refreshed access credentials."
        )


RAW_REFRESH_TOKEN_ACCEPTED = False
ACCESS_TOKEN_CACHED = False
GMAIL_WRITE = False
GMAIL_CREATE_DRAFT = True
GMAIL_DELETE_DRAFT = True
GMAIL_SEND = False
