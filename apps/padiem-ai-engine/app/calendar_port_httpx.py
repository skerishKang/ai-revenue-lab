"""httpx Google Calendar read port for the Engine Worker (#2358).

The Engine runs as a Python Worker (Pyodide) where there is no socket and
``urllib.request`` is unavailable, so every outbound HTTP call is async
through ``httpx``. This module owns the OAuth token refresh and the bounded
provider GET; the trusted :class:`padiem_ai_core.calendar_capability.CalendarReadPort`
contract is implemented here, not in Padiem AI Core.

This port reuses the existing single Google OAuth authority: the same three
Worker secrets already used by the Gmail and Drive ports
(``ENGINE_GOOGLE_OAUTH_CLIENT_ID/SECRET/REFRESH_TOKEN``) and the same official
token endpoint. No second Google OAuth stack, client or token cache is
introduced; the granted provider scope must include the readonly Calendar
scope. Secrets are injected, never stored, and never appear in error strings.

Authority gates enforced here (outside Core, on the trusted boundary):

* official Google Calendar API host (``www.googleapis.com``) only;
* GET-only: this port implements exactly the four promoted READ paths and no
  mutation path exists anywhere in this module;
* path allowlist: ``/users/me/calendarList``, ``/users/me/calendarList/{id}``,
  ``/calendars/{id}/events`` and ``/calendars/{id}/events/{eventId}`` — any
  other path is rejected as ``method_not_permitted``;
* calendar gate: every calendar-scoped read stays inside the server-derived
  allowlist (``ENGINE_CALENDAR_ALLOWED_CALENDARS``); an empty allowlist fails
  closed and caller-supplied ids can never widen it;
* bounded response bytes with sanitized fixed safe error codes.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Awaitable, Callable
from urllib.parse import urlencode

import httpx

from padiem_ai_core.calendar_capability import (
    CALENDAR_READONLY_AUTH_SCOPE,
    GOOGLE_CALENDAR_API_HOST,
    GOOGLE_CALENDAR_READONLY_OAUTH_SCOPE,
    MAX_CALENDARS,
    CalendarReadPort,
)

# Worker secret names. The values themselves are never written to source,
# logs, error messages, or D1 — only the names are declared here so callers
# know which env vars to inject. These are the same existing Google OAuth
# secrets used by the Gmail and Drive ports: no new OAuth secret is added.
ENGINE_GOOGLE_OAUTH_CLIENT_ID = "ENGINE_GOOGLE_OAUTH_CLIENT_ID"
ENGINE_GOOGLE_OAUTH_CLIENT_SECRET = "ENGINE_GOOGLE_OAUTH_CLIENT_SECRET"
ENGINE_GOOGLE_OAUTH_REFRESH_TOKEN = "ENGINE_GOOGLE_OAUTH_REFRESH_TOKEN"

# Server-derived configuration (not a secret): comma-separated calendar ids.
ENGINE_CALENDAR_ALLOWED_CALENDARS = "ENGINE_CALENDAR_ALLOWED_CALENDARS"

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
CALENDAR_LIST_PATH = "/users/me/calendarList"
TOKEN_REFRESH_SKEW_SECONDS = 60
MAX_TOKEN_RESPONSE_BYTES = 64_000
MAX_CALENDAR_RESPONSE_BYTES = 2_000_000
CALENDAR_PROVIDER_REQUEST_FAILED = "calendar_provider_request_failed"

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
_EVENTS_LIST_GET_RE = re.compile(
    rf"^/calendars/(?P<calendar_id>{_CALENDAR_ID_PATTERN})/events$"
)
_EVENT_GET_RE = re.compile(
    rf"^/calendars/(?P<calendar_id>{_CALENDAR_ID_PATTERN})"
    rf"/events/(?P<event_id>{_EVENT_ID_PATTERN})$"
)
_SAFE_PORT_ERROR_RE = re.compile(
    r"^(scope_not_permitted|method_not_permitted|host_not_permitted|calendar_not_allowed"
    r"|calendar_id_invalid|event_id_invalid|response_too_large|provider_response_invalid"
    r"|provider_http_[0-9]{3}|provider_token_http_[0-9]{3}"
    r"|provider_token_response_too_large|provider_token_invalid|scope_not_granted)$"
)


def parse_calendar_ids(value: str | None) -> frozenset[str]:
    """Parse a server-derived Calendar allowlist. Fail-closed on garbage."""

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


class HttpxGoogleCalendarReadPort(CalendarReadPort):
    """Bounded GET-only Google Calendar API port over httpx with OAuth refresh.

    Constructed only when the existing Google OAuth secrets and a non-empty
    server-derived calendar allowlist are present; the composition root
    (``worker_identity._calendar_port_for_env``) refuses to build the port
    otherwise, keeping Production fail-closed.
    """

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        allowed_calendar_ids: frozenset[str],
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not isinstance(client_id, str) or not client_id:
            raise ValueError("calendar_id_invalid")
        if not isinstance(allowed_calendar_ids, frozenset) or any(
            not isinstance(item, str) or not _CALENDAR_ID_RE.fullmatch(item)
            for item in allowed_calendar_ids
        ):
            raise ValueError("calendar_id_invalid")
        if not allowed_calendar_ids:
            raise ValueError("calendar_id_invalid")
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._allowed_calendar_ids = allowed_calendar_ids
        self._transport = transport
        self._clock = clock
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    # --- token refresh ---------------------------------------------------

    async def _refresh(self) -> str:
        # OAuth token requests are application/x-www-form-urlencoded. Always
        # percent-encode credential values rather than concatenating them:
        # real secrets may legally contain reserved characters.
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
        # The granted scope must include the reviewed readonly Calendar scope.
        returned_scopes = payload.get("scope")
        if (
            not isinstance(returned_scopes, str)
            or GOOGLE_CALENDAR_READONLY_OAUTH_SCOPE not in returned_scopes.split()
        ):
            raise ValueError("scope_not_granted")
        self._access_token = access_token
        self._token_expires_at = self._clock() + float(expires_in) - TOKEN_REFRESH_SKEW_SECONDS
        return access_token

    async def _access_token_for(self) -> str:
        if self._access_token is not None and self._clock() < self._token_expires_at:
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

    # --- CalendarReadPort --------------------------------------------------

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
        # (1) Scope gate: the port only ever runs the promoted readonly scope.
        if not set(required_scopes) <= {CALENDAR_READONLY_AUTH_SCOPE}:
            raise ValueError("scope_not_permitted")
        # (2) Host gate: the official Calendar API host is the only transport.
        host = base_url.split("://", 1)[-1].split("/", 1)[0]
        if host != GOOGLE_CALENDAR_API_HOST:
            raise ValueError("host_not_permitted")
        # (3) Path gate: GET is the only method this port implements and only
        # the four promoted READ paths exist; anything else is rejected.
        calendar_id: str | None = None
        if path == CALENDAR_LIST_PATH:
            calendar_id = None
        elif (match := _CALENDAR_LIST_GET_ID_RE.fullmatch(path)) is not None:
            calendar_id = match.group("calendar_id")
        elif (match := _EVENTS_LIST_GET_RE.fullmatch(path)) is not None:
            calendar_id = match.group("calendar_id")
        elif (match := _EVENT_GET_RE.fullmatch(path)) is not None:
            calendar_id = match.group("calendar_id")
        else:
            raise ValueError("method_not_permitted")
        # (4) Calendar gate: calendar-scoped reads stay inside the
        # server-derived allowlist; caller-supplied ids can never widen it.
        if calendar_id is not None and calendar_id not in self._allowed_calendar_ids:
            raise ValueError("calendar_not_allowed")
        # Event-window query bounds must be RFC 3339 timestamps (mirrors the
        # Core contract; defense in depth on the trusted boundary).
        for key, value in (query or {}).items():
            if key in {"timeMin", "timeMax"} and not _RFC3339_RE.fullmatch(str(value)):
                raise ValueError("method_not_permitted")
        # (5) Token-bearing request. From here on, every error path must be a
        # safe fixed code: the bearer header carries the raw OAuth token.
        url = f"https://{GOOGLE_CALENDAR_API_HOST}/calendar/v3{path}"
        params = {key: str(value) for key, value in (query or {}).items()}
        bound = max(1, min(int(max_response_bytes), MAX_CALENDAR_RESPONSE_BYTES))
        try:
            token = await self._access_token_for()
            for attempt in range(2):
                try:
                    payload = await self._stream_get(
                        token=token,
                        url=url,
                        params=params,
                        max_response_bytes=bound,
                        timeout_seconds=timeout_seconds,
                    )
                except ValueError as exc:
                    if str(exc) == "provider_http_401" and attempt == 0:
                        # Token rejected once: drop the cache and retry exactly once.
                        self._access_token = None
                        token = await self._access_token_for()
                        continue
                    raise
                else:
                    return payload
            raise ValueError("provider_http_401")
        except ValueError as exc:
            if _SAFE_PORT_ERROR_RE.fullmatch(str(exc)):
                raise
            # Assigned below (outside the handler) so neither __cause__ nor an
            # implicit __context__ can carry the token-bearing request.
            failure: Exception = ValueError(CALENDAR_PROVIDER_REQUEST_FAILED)
        except Exception:
            failure = ValueError(CALENDAR_PROVIDER_REQUEST_FAILED)
        raise failure


__all__ = [
    "CALENDAR_LIST_PATH",
    "ENGINE_CALENDAR_ALLOWED_CALENDARS",
    "ENGINE_GOOGLE_OAUTH_CLIENT_ID",
    "ENGINE_GOOGLE_OAUTH_CLIENT_SECRET",
    "ENGINE_GOOGLE_OAUTH_REFRESH_TOKEN",
    "HttpxGoogleCalendarReadPort",
    "CalendarReadPort",
    "parse_calendar_ids",
]
