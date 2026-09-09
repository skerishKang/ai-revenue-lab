from __future__ import annotations

import json
from typing import Any, Awaitable

import httpx

from padiem_ai_core.drive_capability import (
    DRIVE_READONLY_SCOPE,
    DriveReadPort,
)

from app.google_oauth_access_lease import (
    CloudflareControlPlaneGoogleOAuthAccessLeaseClient,
    EngineGoogleOAuthAccessLease,
)
from app.service import ServiceContractError


DRIVE_API_HOST = "www.googleapis.com"
MAX_GOOGLE_API_RESPONSE_BYTES = 4_000_000


def _unavailable(message: str) -> ServiceContractError:
    return ServiceContractError(
        "google_drive_access_unavailable",
        message,
        status_code=503,
    )


class ControlPlaneLeaseDriveReadPort(DriveReadPort):
    """Drive READ port using short-lived access leases from Control Plane.

    This canonical Production path has no client-secret or refresh-token field.
    The trusted D1 grant supplies ``binding_ref`` and ``actor_ref``; both are
    checked against the CP lease before the provider request is made.
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
        if tuple(required_scopes) != (DRIVE_READONLY_SCOPE,):
            raise _unavailable("Google Drive scope is not the reviewed readonly scope.")
        try:
            lease = await self._lease_client.issue_access_lease(
                binding_ref=binding_ref,
                connector_id="google-drive",
            )
        except ServiceContractError:
            raise
        except Exception:
            raise _unavailable("Control Plane Google OAuth access lease could not be issued.") from None
        if lease.binding_ref != binding_ref or lease.actor_ref != actor_ref:
            raise _unavailable("Google Drive access lease does not match the trusted grant.")
        if lease.scopes != (DRIVE_READONLY_SCOPE,):
            raise _unavailable("Google Drive access lease scope mismatch.")
        return lease

    @staticmethod
    def _url(*, base_url: str, path: str) -> str:
        if not isinstance(base_url, str) or not base_url.startswith("https://"):
            raise _unavailable("Google Drive base URL is invalid.")
        host = base_url.split("://", 1)[-1].split("/", 1)[0]
        if host != DRIVE_API_HOST:
            raise _unavailable("Google Drive host is not permitted.")
        if not isinstance(path, str) or not path.startswith("/"):
            raise _unavailable("Google Drive path is invalid.")
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
            raise _unavailable("Google Drive response bound is invalid.")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or not 1 <= timeout_seconds <= 60
        ):
            raise _unavailable("Google Drive timeout is invalid.")
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
                            raise _unavailable("Google Drive response exceeded the trusted bound.")
                    return response.status_code, bytes(chunks)
        except ServiceContractError:
            raise
        except (httpx.TimeoutException, httpx.TransportError):
            raise _unavailable("Google Drive provider request failed.") from None

    async def _request(
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
    ) -> bytes:
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
                raise _unavailable(f"Google Drive provider returned HTTP {status}.")
            return body
        raise _unavailable("Google Drive provider rejected refreshed access credentials.")

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
        body = await self._request(
            binding_ref=binding_ref,
            actor_ref=actor_ref,
            required_scopes=required_scopes,
            base_url=base_url,
            path=path,
            query=query,
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
        )
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise _unavailable("Google Drive provider response is invalid JSON.") from None
        if not isinstance(payload, dict):
            raise _unavailable("Google Drive provider response must be an object.")
        return payload

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
        body = await self._request(
            binding_ref=binding_ref,
            actor_ref=actor_ref,
            required_scopes=required_scopes,
            base_url=base_url,
            path=path,
            query=query,
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
        )
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError:
            raise _unavailable("Google Drive provider response is not UTF-8 text.") from None


RAW_REFRESH_TOKEN_ACCEPTED = False
ACCESS_TOKEN_CACHED = False
DRIVE_WRITE = False
