"""Request-time canonical session revocation guard (#5225).

Why this exists
---------------
The Padiem Chat session cookie is a signed, stateless bearer value: the
signature and the expiry are the only offline authority.  Before #5225 a
logout only deleted the browser cookie, so a stored copy of that cookie kept
working on every protected Chat/Claw API until it expired.

The canonical Control Plane identity authority already owns one server-side
auth-session row per login, and its canonical contract already defines a
terminal, monotonic ``REVOKE`` transition.  This module connects those two
facts without adding a second session store:

* the login binds the canonical session id into the signed cookie;
* the logout revokes that exact canonical session in the Control Plane;
* every cookie-bearing request re-reads that one canonical session and refuses
  the request when the canonical session is no longer effective-ACTIVE.

Scope and boundaries
--------------------
* Only the session *id* is read from the cookie.  The canonical subject, the
  tenant, the product and the user identity are resolved inside the private
  Control Plane authority, never from request content.
* Exactly one session is revoked.  A second device that signed in normally
  owns a different canonical session and keeps it.
* The guard never grants authority.  It can only refuse a request whose
  canonical session was revoked, expired, is unknown, or cannot be resolved.
* A deployment without the canonical identity authority bound has no canonical
  sessions at all, so there is nothing to revoke and the guard is inert there.

``AUTHORITY_CHANGE = NO`` for everything else: the cookie format, the origin
guard, the product/tenant separation and the admin-role lookup are untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, MutableMapping

from starlette.responses import JSONResponse

from .auth import SESSION_COOKIE, decode_session_claims
from .request_timing import measure

# The request-state key that carries the resolved verdict.  ``request.state``
# is backed by the ASGI ``scope["state"]`` mapping, so the route layer reads
# exactly the verdict this guard resolved.
SESSION_VERDICT_STATE_KEY = "padiem_session_verdict"

# Bounded public error vocabulary (no configuration or secret data).
SESSION_AUTHORITY_UNAVAILABLE_CODE = "session_authority_unavailable"
SESSION_AUTHORITY_UNAVAILABLE_MESSAGE = "세션 확인을 사용할 수 없습니다. 잠시 후 다시 시도해 주세요."

# Paths that carry no ambient browser session authority and therefore must not
# be refused by the guard.  They are exact paths, never prefixes.
#   * the Google OAuth callback — it re-issues a session instead of using one;
#   * the Android external-browser confirm — it authenticates with a signed
#     handoff state and an app-shown code, not with the cookie;
#   * the logout route itself — it reports its own honest revocation failure.
SESSION_GUARD_EXEMPT_PATHS: frozenset[str] = frozenset(
    {
        "/auth/google/callback",
        "/auth/android/confirm",
        "/api/auth/logout",
    }
)

# Canonical session states that are no longer effective-ACTIVE.
_TERMINAL_SESSION_CODES = frozenset(
    {
        "canonical_auth_session_not_found",
        "inactive_auth_session",
        "control_plane_session_inactive",
    }
)


@dataclass(frozen=True, slots=True)
class SessionVerdict:
    """The request-time verdict for one signed Padiem session cookie."""

    authenticated: bool
    user_id: str | None = None
    canonical_session_id: str | None = None
    reason: str = "absent"


def session_verdict(request: Any) -> SessionVerdict | None:
    """Read the verdict the session guard resolved for this request.

    ``None`` means the guard did not run for this request (for example a
    directly invoked route handler in a unit test).  The caller then keeps the
    pre-existing cookie-only behaviour.
    """

    state = getattr(request, "state", None)
    if state is None:
        return None
    verdict = getattr(state, SESSION_VERDICT_STATE_KEY, None)
    return verdict if isinstance(verdict, SessionVerdict) else None


def _header(scope: MutableMapping[str, Any], name: bytes) -> str | None:
    try:
        for key, value in scope.get("headers") or ():
            if key.lower() == name:
                return value.decode("latin-1")
    except Exception:
        return None
    return None


def _session_cookie(scope: MutableMapping[str, Any]) -> str | None:
    """Read the raw signed session cookie value from the request headers."""

    cookie_header = _header(scope, b"cookie")
    if not cookie_header:
        return None
    for part in cookie_header.split(";"):
        name, _, value = part.partition("=")
        if name.strip() == SESSION_COOKIE:
            return value.strip()
    return None


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message}},
        status_code=status,
        headers={"Cache-Control": "no-store, max-age=0"},
    )


def _is_effective_active(session: Any, *, now: datetime) -> bool:
    """Whether the canonical session is a B62 user session that is still active."""

    product_id = getattr(session, "product_id", None)
    if product_id != "b62":
        # A session of another product is never B62 authority.
        return False
    subject = getattr(session, "subject", None)
    subject_type = getattr(subject, "subject_type", None)
    if getattr(subject_type, "value", subject_type) != "user":
        return False
    effective_state = getattr(session, "effective_state", None)
    if not callable(effective_state):
        return False
    try:
        state = effective_state(now=now)
    except TypeError:
        return False
    return getattr(state, "value", state) == "active"


class SessionRevocationGuardMiddleware:
    """Resolve the canonical session behind the session cookie, once per request.

    Implemented as raw ASGI (not ``BaseHTTPMiddleware``) so streaming responses
    pass through untouched, exactly like the same-origin guard.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def resolve_verdict(self, scope: MutableMapping[str, Any]) -> SessionVerdict | None:
        """Resolve the canonical session verdict for this request.

        Returns ``None`` when the guard does not apply (no session cookie, an
        exempt protocol path, or a deployment without the canonical identity
        authority).  Otherwise it returns the authoritative verdict.
        """

        path = str(scope.get("path") or "")
        if path in SESSION_GUARD_EXEMPT_PATHS:
            return None
        raw_cookie = _session_cookie(scope)
        if not raw_cookie:
            return None
        app = scope.get("app")
        state = getattr(app, "state", None)
        settings = getattr(state, "settings", None)
        if settings is None:
            return None
        claims = decode_session_claims(settings, raw_cookie)
        if claims is None:
            # An unparsable or expired cookie carries no session at all; the
            # route layer already refuses it as signed out.
            return None
        authority = getattr(state, "control_plane_identity_authority", None)
        if authority is None:
            # No canonical authority bound: this deployment has no canonical
            # sessions, so there is nothing to revoke and nothing to refuse.
            return None
        resolve = getattr(authority, "resolve_auth_session", None)
        if not callable(resolve):
            return None
        canonical_session_id = claims.canonical_session_id
        if not canonical_session_id:
            # The session was not bound to a canonical session, so there is no
            # canonical session that could be revoked for it. That is the
            # pre-existing compatibility session (a deployment without the
            # canonical identity authority, or a login the canonical authority
            # could not confirm). It keeps its reviewed cookie-only behaviour:
            # the guard refuses authority it cannot check, it never withholds
            # a session the server itself issued.
            return None
        try:
            session = await resolve(session_id=canonical_session_id)
        except Exception as exc:
            code = getattr(exc, "code", "")
            if code in _TERMINAL_SESSION_CODES or getattr(exc, "status_code", None) == 401:
                # The canonical session is gone or no longer active.
                return SessionVerdict(
                    authenticated=False,
                    user_id=claims.user_id,
                    canonical_session_id=canonical_session_id,
                    reason="revoked",
                )
            # The authority itself is unavailable. The verdict is unknown, so
            # the request is refused with a retryable error rather than being
            # accepted or silently reclassified as signed out.
            return SessionVerdict(
                authenticated=False,
                user_id=claims.user_id,
                canonical_session_id=canonical_session_id,
                reason="unavailable",
            )
        if not _is_effective_active(session, now=datetime.now(timezone.utc)):
            return SessionVerdict(
                authenticated=False,
                user_id=claims.user_id,
                canonical_session_id=canonical_session_id,
                reason="revoked",
            )
        return SessionVerdict(
            authenticated=True,
            user_id=claims.user_id,
            canonical_session_id=canonical_session_id,
            reason="active",
        )

    async def __call__(
        self,
        scope: MutableMapping[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        with measure('auth'):
            verdict = await self.resolve_verdict(scope)
        if verdict is None:
            await self.app(scope, receive, send)
            return
        if verdict.reason == "unavailable":
            await _error(
                503,
                SESSION_AUTHORITY_UNAVAILABLE_CODE,
                SESSION_AUTHORITY_UNAVAILABLE_MESSAGE,
            )(scope, receive, send)
            return
        state = scope.setdefault("state", None)
        if not isinstance(state, dict):
            state = {}
            scope["state"] = state
        state[SESSION_VERDICT_STATE_KEY] = verdict
        await self.app(scope, receive, send)


__all__ = [
    "SESSION_AUTHORITY_UNAVAILABLE_CODE",
    "SESSION_AUTHORITY_UNAVAILABLE_MESSAGE",
    "SESSION_GUARD_EXEMPT_PATHS",
    "SESSION_VERDICT_STATE_KEY",
    "SessionRevocationGuardMiddleware",
    "session_verdict",
]
