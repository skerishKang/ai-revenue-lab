"""One central same-origin guard for cookie-authenticated browser mutations (#3476).

Why this exists
---------------
The Padiem Chat session cookie is ``Secure; HttpOnly; SameSite=Lax`` (see
``app.auth.session_cookie_kwargs``). SameSite is a *site* boundary, not an
*origin* boundary: a sibling origin on the same registrable domain still sends
the cookie on mutations. This module defines the repository's single reviewed
origin-isolation policy for those mutations instead of leaving each route to
invent its own check.

Contract
--------
* Scope: ``POST``/``PUT``/``PATCH``/``DELETE`` requests that carry the
  ``padiem_session`` cookie. A request with no session cookie carries no
  ambient browser authority, so it is not a CSRF subject here — it continues to
  the route and keeps its existing auth error semantics (401 etc.).
* Expected origin derives **only** from reviewed server configuration
  (``Settings.public_base_url``); the request's own ``Host``/``Origin`` is
  never used to build the expectation.
* Exact string comparison of scheme + host + port:
  ``https://chat.example.com != https://app.example.com`` — same registrable
  domain is still denied.
* Missing ``Origin`` on a cookie-authenticated mutation is denied (fail
  closed). An unset/invalid ``public_base_url`` is denied with 503 — the guard
  never weakens to "allow without expectation".
* JSON binding: a guarded request carrying a body must declare
  ``Content-Type: application/json``; a non-JSON ``Content-Type`` (form,
  multipart, ``text/plain``) is rejected with 415. No browser route in this
  repository parses a non-JSON body, so no multipart exception exists.

Route inventory (the #3476 read-only classification, kept next to the policy)
--------------------------------------------------------------------------
* **A — browser + cookie-authenticated + mutation (guarded):** every API route
  registered by ``app_factory`` with a mutating method (chat/orchestration
  POST, project create/update/delete, project file create/delete, saved output
  create/update/delete, conversation delete, drive-case-folder put/delete, B66
  company-profile put + quote interpret, Claw manual-intake/general/approval/
  memory/automation/inbox mutations, Calendar work-log/appointment create,
  logout, connector ticket + Calendar READ activation) — plus the
  ``/api/orchestration`` routes installed later by
  ``install_orchestration_routes``. One middleware covers all of them.
* **B — read-only (GET/HEAD):** out of scope; untouched.
* **C — server-to-server ingress (explicitly exempt below):**
  ``/api/claw/telegram/ingest/*`` (Telegram webhook, proof-authenticated) and
  ``*/local-result`` (trusted Local Runner result ingress).
* **D — OAuth callback:** ``/auth/google/callback`` is protocol authority and
  GET-only; listed explicitly below so the exemption is visible in one place.
  Its existing state/signature validation is unchanged.
* **E — private Engine / Control Plane ingress:** not present in this app's
  route table; there is nothing to exempt and no browser guard is applied to
  any such route should one be added later (it must be registered as an
  explicit exemption, never by weakening the browser policy).

The two historical route-local exact-Origin checks (Calendar READ activation
#2952 and connector ticket issuance) import :func:`expected_browser_origin`
from here, so the expected-origin authority stays single-sourced. Their
route-specific error vocabulary is preserved.

``AUTHORITY_CHANGE = NO`` — session cookie semantics, owner/account/workspace
checks, entitlement checks, P01/connector/Engine/Control Plane authority are
untouched; this guard only runs *before* them.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, MutableMapping
from urllib.parse import urlsplit

from starlette.responses import JSONResponse

from .auth import SESSION_COOKIE

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Public error vocabulary (bounded; contains no configuration or secret data).
ORIGIN_REJECTED_CODE = "origin_rejected"
JSON_CONTENT_TYPE_REQUIRED_CODE = "unsupported_media_type"
ORIGIN_GUARD_UNAVAILABLE_CODE = "origin_guard_unavailable"

ORIGIN_REJECTED_MESSAGE = "요청 출처를 확인할 수 없습니다."
JSON_CONTENT_TYPE_REQUIRED_MESSAGE = "JSON 요청만 허용됩니다."
ORIGIN_GUARD_UNAVAILABLE_MESSAGE = "요청 출처 확인을 사용할 수 없습니다."

# Class C/D explicit exemptions. Denials never fall back to "no Origin means
# pass"; each exempt path is named here.
SERVER_TO_SERVER_EXEMPT_PATH_PREFIXES: tuple[str, ...] = (
    # Telegram webhook ingress: authenticated by its own constant-time
    # webhook proof (see app.claw_telegram_routes), never by a browser cookie.
    "/api/claw/telegram/ingest/",
    # Class D: OAuth provider callback (GET-only protocol authority).
    "/auth/google/callback",
)
SERVER_TO_SERVER_EXEMPT_PATH_SUFFIXES: tuple[str, ...] = (
    # Trusted Local Runner result ingress (see claw_local_task_result_routes),
    # authenticated by its own run/owner authority.
    "/local-result",
)

_JSON_MEDIA_TYPE = "application/json"

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def expected_browser_origin(settings: Any) -> str | None:
    """Return the exact expected browser Origin from reviewed server config.

    Single authority promoted from the two historical route-local checks
    (``calendar_read_activation_routes`` and ``connector_ticket_routes``).
    Only ``Settings.public_base_url`` is consulted — never the request's
    ``Host`` or ``Origin`` header — and only a fully-qualified ``https``
    origin is accepted.
    """
    value = getattr(settings, "public_base_url", None)
    if not isinstance(value, str) or not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    return f"https://{parsed.netloc}"


def is_exempt_path(path: str) -> bool:
    """True for explicitly exempt non-browser ingress paths (classes C/D)."""
    for prefix in SERVER_TO_SERVER_EXEMPT_PATH_PREFIXES:
        if path.startswith(prefix):
            return True
    for suffix in SERVER_TO_SERVER_EXEMPT_PATH_SUFFIXES:
        if path.endswith(suffix):
            return True
    return False


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message}},
        status_code=status,
        headers=_NO_STORE_HEADERS,
    )


def _header(scope: MutableMapping[str, Any], name: bytes) -> str | None:
    try:
        for key, value in scope.get("headers") or ():
            if key.lower() == name:
                return value.decode("latin-1")
    except Exception:
        return None
    return None


def _carries_session_cookie(cookie_header: str) -> bool:
    for part in cookie_header.split(";"):
        name, _, _value = part.partition("=")
        if name.strip() == SESSION_COOKIE:
            return True
    return False


def _body_present(scope: MutableMapping[str, Any]) -> bool:
    if _header(scope, b"transfer-encoding"):
        return True
    raw = _header(scope, b"content-length")
    if raw is None:
        return False
    try:
        return int(raw) > 0
    except ValueError:
        # Undecodable length: treat as a body so the JSON binding still holds.
        return True


class SameOriginGuardMiddleware:
    """Central same-origin + JSON content-type guard (raw ASGI middleware).

    Implemented as raw ASGI (not ``BaseHTTPMiddleware``) so streaming
    responses pass through untouched. Runs inside the #1975 telemetry
    middleware, which stays outermost and therefore still observes guard
    rejections.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    def decide(self, scope: MutableMapping[str, Any]) -> JSONResponse | None:
        """Return the denial response, or ``None`` to let the request through."""
        method = str(scope.get("method") or "").upper()
        if method not in MUTATING_METHODS:
            # Class B: read-only requests are outside this policy.
            return None
        path = str(scope.get("path") or "")
        if is_exempt_path(path):
            # Classes C/D: explicit server-to-server / protocol exemptions.
            return None
        cookie_header = _header(scope, b"cookie")
        if cookie_header is None or not _carries_session_cookie(cookie_header):
            # Not cookie-authenticated: no ambient browser authority to abuse;
            # the route keeps its existing auth error semantics untouched.
            return None

        app = scope.get("app")
        settings = getattr(getattr(app, "state", None), "settings", None)
        expected = expected_browser_origin(settings)
        if expected is None:
            # Fail closed: no reviewed expectation, no cookie-authenticated
            # mutation. Never derive the expectation from the request.
            return _error(503, ORIGIN_GUARD_UNAVAILABLE_CODE, ORIGIN_GUARD_UNAVAILABLE_MESSAGE)

        origin = _header(scope, b"origin")
        if origin is None or origin.strip() != expected:
            return _error(403, ORIGIN_REJECTED_CODE, ORIGIN_REJECTED_MESSAGE)

        content_type = _header(scope, b"content-type") or ""
        media_type = content_type.split(";", 1)[0].strip().lower()
        if media_type == _JSON_MEDIA_TYPE:
            return None
        # No body and no declared type (e.g. an empty POST/DELETE) is fine;
        # any declared non-JSON type, or a body without a JSON type, is not.
        if media_type or _body_present(scope):
            return _error(415, JSON_CONTENT_TYPE_REQUIRED_CODE, JSON_CONTENT_TYPE_REQUIRED_MESSAGE)
        return None

    async def __call__(
        self,
        scope: MutableMapping[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        denial = self.decide(scope)
        if denial is None:
            await self.app(scope, receive, send)
            return
        await denial(scope, receive, send)


__all__ = [
    "JSON_CONTENT_TYPE_REQUIRED_CODE",
    "MUTATING_METHODS",
    "ORIGIN_GUARD_UNAVAILABLE_CODE",
    "ORIGIN_REJECTED_CODE",
    "SERVER_TO_SERVER_EXEMPT_PATH_PREFIXES",
    "SERVER_TO_SERVER_EXEMPT_PATH_SUFFIXES",
    "SameOriginGuardMiddleware",
    "expected_browser_origin",
    "is_exempt_path",
]
