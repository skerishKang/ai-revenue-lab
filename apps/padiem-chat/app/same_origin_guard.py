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
  multipart, ``text/plain``) is rejected with 415. No *guarded* browser route in
  this repository parses a non-JSON body. The one urlencoded browser route,
  ``/auth/android/confirm``, is explicitly exempt (class D) and authenticates
  with a signed handoff state plus the app-displayed code, not the cookie.

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
  the canonical Local Runner result family ``/api/claw/runs/{run_id}/local-result``
  only. The suffix alone is never an exemption: an unrelated browser route that
  happens to end with ``local-result`` stays guarded.
* **D — OAuth callback / Android handoff confirm:** ``/auth/google/callback`` is
  protocol authority and GET-only; listed explicitly below so the exemption is
  visible in one place. Its existing state/signature validation is unchanged.
  ``/auth/android/confirm`` is a POST-only, urlencoded form target rendered by
  the Google callback in the *external* browser, which may still carry an
  unrelated stale session cookie. It sets no cookie and authenticates with the
  signed handoff state plus the code shown inside the app (bound to the
  pending user row), so ambient cookie authority is never consulted. The
  exemption is exact-path, not prefix-based.
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
from .claw_local_task_result_routes import CLAW_LOCAL_TASK_RESULT_PATH
from .config import LOCAL_DEV_LOOPBACK_HOSTS

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
# Exact-path exemptions for browser-facing protocol endpoints that carry no
# ambient cookie authority. Exact matching keeps a lookalike route guarded.
PROTOCOL_EXEMPT_PATHS: tuple[str, ...] = (
    # Android external-browser return: signed handoff state + app-shown code.
    "/auth/android/confirm",
)

# Trusted Local Runner result ingress (see claw_local_task_result_routes),
# authenticated by its own run/owner authority. Split out of the route's own path
# template so the exemption can neither drift from the route nor widen past it.
_LOCAL_RESULT_PREFIX, _, _LOCAL_RESULT_SUFFIX = CLAW_LOCAL_TASK_RESULT_PATH.partition("{run_id}")

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
    origin is accepted, with one narrow exception: a run that explicitly
    opted into ``PADIEM_LOCAL_DEV=1`` (``Settings.local_dev``, which the
    Worker binding path can never set) may expect loopback HTTP, because
    the native CPython server on 127.0.0.1 has no TLS edge. Any other
    ``http`` base still resolves to ``None`` and the guard fails closed.
    """
    value = getattr(settings, "public_base_url", None)
    if not isinstance(value, str) or not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme == "https" and parsed.netloc:
        return f"https://{parsed.netloc}"
    if (
        parsed.scheme == "http"
        and parsed.netloc
        and getattr(settings, "local_dev", False) is True
        and (parsed.hostname or "") in LOCAL_DEV_LOOPBACK_HOSTS
    ):
        return f"http://{parsed.netloc}"
    return None


def is_local_runner_result_ingress(path: str) -> bool:
    """True only for the canonical ``/api/claw/runs/{run_id}/local-result``.

    A bare ``endswith("/local-result")`` also exempted any unrelated
    cookie-authenticated browser route that happened to share that last segment,
    which is a CSRF bypass rather than an ingress allowance. The run id must be
    exactly one non-empty segment; validating its shape stays the route's own
    authority.
    """
    if not path.startswith(_LOCAL_RESULT_PREFIX) or not path.endswith(_LOCAL_RESULT_SUFFIX):
        return False
    run_id = path[len(_LOCAL_RESULT_PREFIX) : len(path) - len(_LOCAL_RESULT_SUFFIX)]
    return bool(run_id) and "/" not in run_id


def is_exempt_path(path: str) -> bool:
    """True for explicitly exempt non-browser ingress paths (classes C/D)."""
    if path in PROTOCOL_EXEMPT_PATHS:
        return True
    for prefix in SERVER_TO_SERVER_EXEMPT_PATH_PREFIXES:
        if path.startswith(prefix):
            return True
    return is_local_runner_result_ingress(path)


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
        # XLSX originals are sent as raw octet streams to the exact
        # cookie-authenticated office source route. Keep Origin enforcement.
        if (
            scope.get("method") == "POST"
            and path == "/api/claw/office/web-sources"
            and media_type == "application/octet-stream"
        ):
            return None
        # B66 customer template originals use raw bytes on one owner-scoped route.
        # The exact Origin and authenticated session checks above still apply.
        if scope.get("method") == "POST" and path == "/api/b66/template-sources" and media_type == "application/octet-stream":
            return None
        # Standalone Chat accepts one bounded binary attachment with JSON metadata.
        # Origin and canonical session checks are unchanged.
        if scope.get("method") == "POST" and path == "/api/chat" and media_type == "application/octet-stream":
            return None
        # #2505: the Claw general lane accepts the SAME binary attachment frame,
        # so the shared attachment contract does not become a JSON-only lane on
        # one product. The exact Origin, cookie and route-local authority checks
        # above are unchanged; only the body media type is admitted.
        if scope.get("method") == "POST" and path == "/api/claw/general" and media_type == "application/octet-stream":
            return None
        # Voice audio is a raw browser POST on two exact authenticated routes.
        # The Origin check above and each route's canonical session remain mandatory.
        if (
            scope.get("method") == "POST"
            and path in ("/api/voice/transcribe", "/api/claw/voice/transcribe")
            and media_type == "application/octet-stream"
        ):
            return None
        # Project originals are raw binary, still subject to the same
        # cookie, fixed-origin and route-local owner checks.
        if (
            scope.get("method") == "POST"
            and media_type == "application/octet-stream"
            and len(path.split("/")) == 5
            and path.startswith("/api/projects/")
            and path.endswith("/files")
        ):
            return None
        # #5568 PDF/ZIP originals for the Markdown utility are raw binary on one
        # owner-scoped upload route, declaring their document type in a header. The
        # exact Origin, cookie and route-local owner checks above still apply.
        if (
            scope.get("method") == "POST"
            and media_type == "application/octet-stream"
            and len(path.split("/")) == 5
            and path.startswith("/api/document-conversions/")
            and path.endswith("/files")
        ):
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
    "PROTOCOL_EXEMPT_PATHS",
    "SERVER_TO_SERVER_EXEMPT_PATH_PREFIXES",
    "SameOriginGuardMiddleware",
    "expected_browser_origin",
    "is_exempt_path",
    "is_local_runner_result_ingress",
]
