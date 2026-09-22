"""Canonical Google Calendar READ port over Control Plane access leases (#2010).

This is the canonical Production Calendar path. It is the Calendar equivalent
of ``drive_port_cp_lease.py`` / ``gmail_port_cp_lease.py``: the Engine receives
only server-derived ``binding_ref``/``actor_ref`` values plus a short-lived
access lease issued by the Control Plane private RPC. The Control Plane owns the
long-lived Google refresh credential and performs the OAuth refresh; the Engine
performs the bounded Calendar provider GET.

Design invariants (enforced on this trusted boundary, outside Core):

* connector id ``google-calendar`` only, with exactly the reviewed readonly
  provider scope on the lease;
* no refresh token, no client secret and no engine-owned long-lived Google
  credential exists anywhere in this module;
* the access token is never persisted and never projected;
* the server-derived Calendar allowlist gate is preserved: an empty allowlist
  fails closed and a caller-supplied calendar id can never widen it;
* only the four promoted READ paths are reachable, GET only, official
  ``www.googleapis.com`` host only;
* response bytes, timeout and RFC 3339 window bounds stay bounded;
* a single provider 401 triggers exactly one fresh lease and exactly one retry
  of the same bounded GET (``MAX_PROVIDER_ATTEMPTS = 2``), then fails closed.
"""

from __future__ import annotations

import json
import re
from typing import Any, Awaitable

import httpx

from padiem_ai_core.calendar_capability import (
    CALENDAR_READONLY_AUTH_SCOPE,
    GOOGLE_CALENDAR_API_HOST,
    GOOGLE_CALENDAR_READONLY_OAUTH_SCOPE,
    MAX_CALENDARS,
    CalendarReadPort,
)
from padiem_ai_core.tool_runtime import ToolHandlerError

from app.google_oauth_access_lease import (
    CloudflareControlPlaneGoogleOAuthAccessLeaseClient,
    EngineGoogleOAuthAccessLease,
)
from app.service import ServiceContractError


CALENDAR_CP_CONNECTOR_ID = "google-calendar"
CALENDAR_CP_PROVIDER_SCOPE = GOOGLE_CALENDAR_READONLY_OAUTH_SCOPE
MAX_PROVIDER_ATTEMPTS = 2
MAX_GOOGLE_API_RESPONSE_BYTES = 4_000_000

CALENDAR_LIST_PATH = "/users/me/calendarList"

_CALENDAR_ID_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._%+@\-]{0,511}"
_EVENT_ID_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._\-]{0,255}"
_CALENDAR_ID_RE = re.compile(rf"^{_CALENDAR_ID_PATTERN}$")
_EVENT_ID_RE = re.compile(rf"^{_EVENT_ID_PATTERN}$")
_RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)
_CALENDAR_LIST_GET_ID_RE = re.compile(
    rf"^{re.escape(CALENDAR_LIST_PATH)}/(?P<calendar_id>{_CALENDAR_ID_PATTERN})$"
)
_EVENTS_LIST_GET_RE = re.compile(rf"^/calendars/(?P<calendar_id>{_CALENDAR_ID_PATTERN})/events$")
_EVENT_GET_RE = re.compile(
    rf"^/calendars/(?P<calendar_id>{_CALENDAR_ID_PATTERN})"
    rf"/events/(?P<event_id>{_EVENT_ID_PATTERN})$"
)


def _lease_mismatch(message: str) -> ToolHandlerError:
    return ToolHandlerError("calendar_access_lease_mismatch", message)


def _provider_unavailable(message: str) -> ToolHandlerError:
    return ToolHandlerError("calendar_provider_unavailable", message)


def _provider_credential_rejected(message: str) -> ToolHandlerError:
    return ToolHandlerError("calendar_provider_credential_rejected", message)


def parse_calendar_ids(value: str | None) -> frozenset[str]:
    """Parse the server-derived Calendar allowlist. Fail-closed on garbage."""

    if value is None or not value.strip():
        return frozenset()
    calendar_ids: set[str] = set()
    for item in value.split(","):
        token = item.strip()
        if not token:
            continue
        if not _CALENDAR_ID_RE.fullmatch(token):
            raise ValueError("calendar_id_invalid")
        calendar_ids.add(token)
    if len(calendar_ids) > MAX_CALENDARS:
        raise ValueError("calendar_id_invalid")
    return frozenset(calendar_ids)


class ControlPlaneLeaseGoogleCalendarReadPort(CalendarReadPort):
    """Calendar READ port backed by short-lived Control Plane access leases.

    The server-derived Calendar allowlist (``ENGINE_CALENDAR_ALLOWED_CALENDARS``)
    is applied here exactly as it was for the previous direct-secret port: a
    non-empty allowlist is mandatory and calendar-scoped reads never leave it.
    """

    def __init__(
        self,
        *,
        lease_client: CloudflareControlPlaneGoogleOAuthAccessLeaseClient,
        allowed_calendar_ids: frozenset[str],
        allowlist_configured: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not callable(getattr(lease_client, "issue_access_lease", None)):
            raise ValueError("lease_client must expose issue_access_lease")
        if not isinstance(allowed_calendar_ids, frozenset) or any(
            not isinstance(item, str) or not _CALENDAR_ID_RE.fullmatch(item)
            for item in allowed_calendar_ids
        ):
            raise ValueError("calendar_id_invalid")
        if not allowed_calendar_ids:
            raise ValueError("calendar_id_invalid")
        self._lease_client = lease_client
        self._allowed_calendar_ids = allowed_calendar_ids
        # Recorded contract evidence only: the canonical port never receives a
        # client secret or a long-lived refresh token.
        self._allowlist_configured = bool(allowlist_configured)
        self._transport = transport

    # --- lease ----------------------------------------------------------

    async def _lease_for(
        self,
        *,
        binding_ref: str,
        actor_ref: str,
        required_scopes: tuple[str, ...],
    ) -> EngineGoogleOAuthAccessLease:
        if not isinstance(required_scopes, tuple) or tuple(required_scopes) != (
            CALENDAR_READONLY_AUTH_SCOPE,
        ):
            raise _lease_mismatch("Calendar scope is not the reviewed readonly scope.")
        try:
            lease = await self._lease_client.issue_access_lease(
                binding_ref=binding_ref,
                connector_id=CALENDAR_CP_CONNECTOR_ID,
            )
        except ServiceContractError as exc:
            raise ToolHandlerError(exc.code, exc.safe_message) from exc
        except Exception:
            raise ToolHandlerError(
                "google_oauth_access_lease_unavailable",
                "Control Plane Google OAuth access lease could not be issued.",
            ) from None
        if lease.binding_ref != binding_ref or lease.actor_ref != actor_ref:
            raise _lease_mismatch("Calendar access lease does not match the trusted grant.")
        if tuple(lease.scopes) != (CALENDAR_CP_PROVIDER_SCOPE,):
            raise _lease_mismatch("Calendar access lease scope mismatch.")
        return lease

    # --- bounded GET ----------------------------------------------------

    @staticmethod
    def _url(*, base_url: str, path: str) -> str:
        if not isinstance(base_url, str) or not base_url.startswith("https://"):
            raise _provider_unavailable("Calendar base URL is invalid.")
        host = base_url.split("://", 1)[-1].split("/", 1)[0]
        if host != GOOGLE_CALENDAR_API_HOST:
            raise _provider_unavailable("Calendar host is not permitted.")
        if not isinstance(path, str) or not path.startswith("/"):
            raise _provider_unavailable("Calendar path is invalid.")
        return f"{base_url.rstrip('/')}{path}"

    def _calendar_id_for(self, path: str) -> str | None:
        """Apply the GET-only path allowlist and return the calendar scope id."""

        if path == CALENDAR_LIST_PATH:
            return None
        for pattern in (_CALENDAR_LIST_GET_ID_RE, _EVENTS_LIST_GET_RE, _EVENT_GET_RE):
            match = pattern.fullmatch(path)
            if match is not None:
                return match.group("calendar_id")
        raise _provider_unavailable("Calendar method is not permitted.")

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
            raise _provider_unavailable("Calendar response bound is invalid.")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or not 1 <= timeout_seconds <= 60
        ):
            raise _provider_unavailable("Calendar timeout is invalid.")
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
                                "Calendar response exceeded the trusted bound."
                            )
                    return response.status_code, bytes(chunks)
        except ToolHandlerError:
            raise
        except httpx.HTTPError:
            # Includes transport, timeout and decoding failures: never let an
            # HTTPX implementation detail carry the bearer token into Core.
            raise _provider_unavailable("Calendar provider request failed.") from None

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
        calendar_id = self._calendar_id_for(path)
        # Server-derived Calendar allowlist gate: an id outside the allowlist is
        # never readable, and caller payloads can never widen it.
        if calendar_id is not None and calendar_id not in self._allowed_calendar_ids:
            raise _provider_unavailable("Calendar is not server-derived allowed.")
        for key, value in dict(query or {}).items():
            if key in {"timeMin", "timeMax"} and not _RFC3339_RE.fullmatch(str(value)):
                raise _provider_unavailable("Calendar window bound is not RFC 3339.")
        for attempt in range(MAX_PROVIDER_ATTEMPTS):
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
                # Never cache the access token. Request exactly one fresh CP
                # lease and retry the same bounded GET exactly once.
                continue
            if status < 200 or status >= 300:
                raise _provider_unavailable(f"Calendar provider returned HTTP {status}.")
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise _provider_unavailable("Calendar provider response is invalid JSON.") from None
            if not isinstance(payload, dict):
                raise _provider_unavailable("Calendar provider response must be an object.")
            return payload
        raise _provider_credential_rejected(
            "Calendar provider rejected refreshed access credentials."
        )


RAW_REFRESH_TOKEN_ACCEPTED = False
RAW_CLIENT_SECRET_ACCEPTED = False
ACCESS_TOKEN_CACHED = False
ACCESS_TOKEN_PERSISTED = False
SECOND_GOOGLE_OAUTH_STACK = False
CALENDAR_WRITE = False
CALENDAR_CREATE = False
CALENDAR_UPDATE = False
CALENDAR_DELETE = False
CALENDAR_RESPOND = False
CALENDAR_CP_LEASE_CANONICAL = True
CALENDAR_ENGINE_DIRECT_REFRESH_PRODUCTION_FALLBACK = False


__all__ = [
    "ACCESS_TOKEN_CACHED",
    "ACCESS_TOKEN_PERSISTED",
    "CALENDAR_CP_CONNECTOR_ID",
    "CALENDAR_CP_LEASE_CANONICAL",
    "CALENDAR_CP_PROVIDER_SCOPE",
    "CALENDAR_CREATE",
    "CALENDAR_DELETE",
    "CALENDAR_ENGINE_DIRECT_REFRESH_PRODUCTION_FALLBACK",
    "CALENDAR_LIST_PATH",
    "CALENDAR_RESPOND",
    "CALENDAR_UPDATE",
    "CALENDAR_WRITE",
    "MAX_PROVIDER_ATTEMPTS",
    "RAW_CLIENT_SECRET_ACCEPTED",
    "RAW_REFRESH_TOKEN_ACCEPTED",
    "SECOND_GOOGLE_OAUTH_STACK",
    "ControlPlaneLeaseGoogleCalendarReadPort",
    "parse_calendar_ids",
]
