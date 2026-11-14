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
* every cookie-bearing request checks that canonical session and refuses the
  request when it is no longer effective-ACTIVE. The COM2 composition may reuse
  a successful check for a bounded window in SQLite - 300 s by default,
  ``PADIEM_CHAT_AUTH_SESSION_CACHE_SECONDS`` (#7084) - and reloads it shortly
  before it expires on a background task so the reloading request does not wait
  for the authority. Every revocation event this host serves (logout, the
  self-service password change, account deletion, admin membership and role
  changes) deletes that entry and fences in-flight loads before returning
  success. An expired entry is never served, so the bound for a revocation made
  in another product stays the window.

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

import inspect
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, MutableMapping

from starlette.responses import JSONResponse

from .auth import SESSION_COOKIE, decode_session_claims, sidless_session_cutoff_passed
from .config import session_local_verify_enabled, session_user_row_check_enabled
from .request_timing import measure

ACCESS_COOKIE = "__Host-padiem-shared-access"
LOCAL_VERIFY_LEEWAY_SECONDS = 60

# The request-state key that carries the resolved verdict.  ``request.state``
# is backed by the ASGI ``scope["state"]`` mapping, so the route layer reads
# exactly the verdict this guard resolved.
SESSION_VERDICT_STATE_KEY = "padiem_session_verdict"

# Bounded public error vocabulary (no configuration or secret data).
SESSION_AUTHORITY_UNAVAILABLE_CODE = "session_authority_unavailable"
SESSION_AUTHORITY_UNAVAILABLE_MESSAGE = "세션 확인을 사용할 수 없습니다. 잠시 후 다시 시도해 주세요."

# Internal audit H1 (2026-11-10): this guard reads the first session cookie in
# the Cookie header, while a route that re-parses the header would read the
# last one. Two or more same-name cookies make that ordering an identity
# confusion, so such a request is refused outright instead of being resolved
# from either copy.
SESSION_COOKIE_DUPLICATED_CODE = "session_cookie_duplicated"
SESSION_COOKIE_DUPLICATED_MESSAGE = (
    "세션 쿠키가 두 개 이상 감지되었습니다. 브라우저의 쿠키를 정리한 뒤 다시 시도해 주세요."
)

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

_LOCAL_VERIFY_EXEMPT_PATHS: frozenset[str] = SESSION_GUARD_EXEMPT_PATHS | frozenset(
    {
        "/auth/shared/start",
        "/auth/shared/callback",
        "/auth/shared/refresh",
        "/auth/shared/logout",
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


class _InactiveCachedSession(Exception):
    """Do not put a negative or revoked authority result in the success cache."""


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


def _cookie_value(scope: MutableMapping[str, Any], cookie_name: str) -> str | None:
    """Read the first raw cookie value matching ``cookie_name`` from headers."""

    cookie_header = _header(scope, b"cookie")
    if not cookie_header:
        return None
    for part in cookie_header.split(";"):
        name, _, value = part.partition("=")
        if name.strip() == cookie_name:
            cleaned = value.strip()
            return cleaned or None
    return None


def _session_cookie(scope: MutableMapping[str, Any]) -> str | None:
    """Read the raw signed session cookie value from the request headers."""

    return _cookie_value(scope, SESSION_COOKIE)


_DEFAULT_LOCAL_VERIFIER: Any = None
_VERIFY_MODULE: Any = None


def load_padiem_auth_verify_module() -> Any:
    """Load ``padiem_auth_verify`` from the host install or the repo package."""
    global _VERIFY_MODULE
    if _VERIFY_MODULE is not None:
        return _VERIFY_MODULE
    try:
        import padiem_auth_verify as mod
        if "leeway_seconds" in inspect.signature(mod.Verifier.__init__).parameters:
            _VERIFY_MODULE = mod
            return mod
    except Exception:
        pass
    import importlib.util
    from pathlib import Path

    candidate = Path(__file__).resolve().parents[3] / "packages" / "padiem-auth-verify" / "verify.py"
    spec = importlib.util.spec_from_file_location("padiem_auth_verify_repo", candidate)
    if spec is None or spec.loader is None:
        raise ImportError("padiem_auth_verify_unavailable")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _VERIFY_MODULE = mod
    return mod


def get_local_token_verifier(state: Any = None, *, audience: str = "b62") -> Any:
    """Return the ES256 verifier for #7078 B request-time local verification."""
    global _DEFAULT_LOCAL_VERIFIER
    if state is not None:
        explicit = getattr(state, "local_token_verifier", None)
        if explicit is not None:
            return explicit
        flow_auth = getattr(getattr(state, "shared_login_flow", None), "auth", None)
        flow_verifier = getattr(flow_auth, "verifier", None)
        if flow_verifier is not None:
            return flow_verifier
    if _DEFAULT_LOCAL_VERIFIER is None:
        verify_mod = load_padiem_auth_verify_module()
        from .auth_shadow_verify import _short_fetch

        _DEFAULT_LOCAL_VERIFIER = verify_mod.Verifier(
            audience=audience,
            fetcher=_short_fetch,
            leeway_seconds=LOCAL_VERIFY_LEEWAY_SECONDS,
        )
    return _DEFAULT_LOCAL_VERIFIER


def prewarm_local_token_verifier(verifier: Any = None) -> None:
    """Warm the JWKS cache off the request path on startup (best-effort)."""
    import threading

    target = verifier if verifier is not None else get_local_token_verifier()
    inner = getattr(target, "_verifier", target)
    keys_fn = getattr(inner, "_keys", None)
    if not callable(keys_fn):
        return
    try:
        keys_fn(True)
        print("local_verify_prewarm outcome=ok attempt=1", flush=True)
    except Exception as exc:
        print("local_verify_prewarm outcome=fail attempt=1 code=%s" % type(exc).__name__, flush=True)

        def _retry():
            for attempt in range(2, 6):
                try:
                    time.sleep(15)
                    keys_fn(True)
                    print("local_verify_prewarm outcome=ok attempt=%d" % attempt, flush=True)
                    return
                except Exception as retry_exc:
                    print(
                        "local_verify_prewarm outcome=fail attempt=%d code=%s"
                        % (attempt, type(retry_exc).__name__),
                        flush=True,
                    )

        threading.Thread(target=_retry, daemon=True, name="local-verify-jwks-prewarm").start()


async def _verify_access_token_locally(state: Any, raw_access: str) -> tuple[dict[str, Any] | None, str]:
    """Verify a padiem-auth ES256 access token without blocking on remote JWKS."""
    from cryptography.exceptions import InvalidSignature
    from .auth_shadow_verify import (
        _cached_kids,
        _decode_header_kid,
        _schedule_jwks_refresh,
        _short_fetch,
    )

    try:
        verify_mod = load_padiem_auth_verify_module()
        _default_jwks_fetch = getattr(verify_mod, "_fetch", None)
    except Exception:
        _default_jwks_fetch = None

    try:
        verifier = get_local_token_verifier(state)
    except Exception:
        return None, "unavailable"
    inner = getattr(verifier, "_verifier", verifier)
    if not hasattr(inner, "cached") or not hasattr(inner, "until"):
        try:
            result = inner.verify(raw_access)
            if inspect.isawaitable(result):
                result = await result
            if not isinstance(result, dict):
                return None, "invalid_token"
            return dict(result), "ok"
        except (ValueError, InvalidSignature, KeyError, TypeError):
            return None, "invalid_token"
        except Exception:
            return None, "unavailable"

    fetcher = getattr(inner, "fetcher", None)
    is_remote_fetcher = fetcher is _default_jwks_fetch or fetcher is _short_fetch
    clock = getattr(inner, "clock", time.time)
    now = clock() if callable(clock) else time.time()

    def _reason(default: str) -> str:
        value = getattr(inner, "last_refresh_reason", "")
        if value in ("jwks_refreshed", "jwks_stale_used", "jwks_unavailable"):
            return value
        return default

    kids = _cached_kids(inner)
    if kids is None:
        # #7078 B: a cold/expired JWKS cache is not a reason to refuse the
        # request. Refresh once here, under the verifier's single-flight lock
        # (bounded by the 3 s fetcher timeout); a failed refresh falls back to
        # the last good keys for up to STALE_KEY_MAX_SECONDS.
        try:
            inner._keys(True)
        except Exception:
            print("local_verify outcome=jwks_unavailable", flush=True)
            return None, "unavailable"
        print("local_verify outcome=%s" % _reason("jwks_refreshed"), flush=True)
        kids = _cached_kids(inner)
        if kids is None:
            return None, "unavailable"
    else:
        until = getattr(inner, "until", 0)
        if isinstance(until, (int, float)) and until - now <= 60:
            # Refresh ahead on the request that would otherwise go cold; a
            # failure keeps the still-valid keys instead of a 503.
            try:
                inner._keys(True)
            except Exception:
                pass
            print("local_verify outcome=%s" % _reason("jwks_stale_used"), flush=True)

    kid = _decode_header_kid(raw_access)
    if kid is None:
        return None, "invalid_token"
    if kid not in kids:
        # Key rotation: one bounded refresh (single-flight, 5 s cooldown for a
        # burst). If the new kid is still absent the token is simply invalid.
        try:
            inner._keys(True)
        except Exception:
            print("local_verify outcome=jwks_unavailable", flush=True)
            return None, "unavailable"
        kids = _cached_kids(inner) or []
        if kid not in kids:
            return None, "invalid_token"

    try:
        verified = inner.verify(raw_access)
        if inspect.isawaitable(verified):
            verified = await verified
        if not isinstance(verified, dict):
            return None, "invalid_token"
        return dict(verified), "ok"
    except (ValueError, InvalidSignature, KeyError, TypeError):
        return None, "invalid_token"
    except Exception:
        return None, "unavailable"


async def verify_access_cookie_for_revocation(request: Any) -> dict[str, str] | None:
    """Extract signature-verified ``(sessionId, accountId)`` from ACCESS_COOKIE."""
    try:
        raw = request.cookies.get(ACCESS_COOKIE)
    except Exception:
        raw = None
    if not isinstance(raw, str) or not raw:
        return None
    from .auth_validation_cache import _state_for_request
    state = _state_for_request(request)
    verified, code = await _verify_access_token_locally(state, raw)
    if code != "ok" or not isinstance(verified, dict):
        return None
    sid = verified.get("sessionId")
    aid = verified.get("accountId")
    out: dict[str, str] = {}
    if isinstance(sid, str) and sid:
        out["sessionId"] = sid
    if isinstance(aid, str) and aid.startswith("sub_"):
        out["accountId"] = aid
    return out or None


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
        app = scope.get("app")
        state = getattr(app, "state", None)
        settings = getattr(state, "settings", None)
        if session_local_verify_enabled(settings):
            if path in _LOCAL_VERIFY_EXEMPT_PATHS:
                return None
            return await self._resolve_local_verdict(scope, state, settings)
        return await self._resolve_legacy_verdict(scope)

    async def _resolve_legacy_verdict(self, scope: MutableMapping[str, Any]) -> SessionVerdict | None:
        """The pre-#7527 verification path: legacy authority + cache rules.

        Shared by the switch-OFF hot path and the #7078 B legacy-cookie
        fallback (CTO decision 2026-11-12): a request carrying only the old
        session cookie is checked exactly as when the local-verify switch is
        off — same authority call rules, same cache, same deny handling — so
        turning the switch on never force-logs-out live legacy-cookie traffic.
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
            # pre-existing compatibility session (a login the canonical
            # authority could not confirm, or one minted before the authority
            # was bound). It keeps its reviewed cookie-only behaviour: the
            # guard refuses authority it cannot check, it never withholds
            # a session the server itself issued.
            #
            # Internal audit H2 (2026-11-10): an authority-backed deployment
            # now mints every session cookie with a canonical session id and
            # refuses issuances it cannot bind. A compatibility cookie like
            # this one has no canonical session for account deletion to
            # revoke, so its user row is the last guard against reusing a
            # deleted account's cookie; it also keeps working only through the
            # fixed 7-day transition window
            # (auth.sidless_session_cutoff_passed), after which the guard
            # refuses it instead of extending an unrevocable session
            # indefinitely.
            #
            # The row check runs when the bound store declares the
            # ``user_row_exists`` capability — both production stores do, and
            # a production composition whose bound store does not declare it
            # fails the start (app_factory). A store that declares nothing
            # refuses compatibility cookies in production mode ("declared
            # nowhere" is the refusal side) and keeps the reviewed cookie-only
            # behaviour elsewhere, so a partial store double in a test is
            # never read as an account deletion. A store that cannot answer
            # right now must not widen the row check into an outage of its
            # own, so only a clean "no such row" refuses.
            row_exists = getattr(getattr(state, "history_store", None), "user_row_exists", None)
            if callable(row_exists):
                try:
                    known_user = await row_exists(claims.user_id)
                except Exception:
                    known_user = True
                if known_user is False:
                    return SessionVerdict(
                        authenticated=False,
                        user_id=claims.user_id,
                        canonical_session_id=None,
                        reason="user_row_missing",
                    )
            elif (str(getattr(settings, "runtime_mode", "")).strip().lower() == "b14"
                    and session_user_row_check_enabled(settings)):
                return SessionVerdict(
                    authenticated=False,
                    user_id=claims.user_id,
                    canonical_session_id=None,
                    reason="revoked",
                )
            if sidless_session_cutoff_passed():
                return SessionVerdict(
                    authenticated=False,
                    user_id=claims.user_id,
                    canonical_session_id=None,
                    reason="revoked",
                )
            return None
        cache = getattr(state, 'auth_validation_cache', None)
        return await self._resolve_canonical_session(
            claims, canonical_session_id, resolve, cache)

    async def _resolve_canonical_session(self, claims, canonical_session_id, resolve, cache):
        from .request_telemetry import current_request_id
        from .shared_login_timing import (
            begin_login_timings, emit_identity_timing, end_login_timings,
            record_login_timing,
        )

        token_context, details = begin_login_timings()
        started = time.perf_counter()
        request_id = current_request_id()
        try:
            try:
                if cache is not None:
                    def active_session_loader(*, timed):
                        async def load():
                            started_at = time.perf_counter() if timed else None
                            try:
                                session = await resolve(session_id=canonical_session_id)
                            finally:
                                if started_at is not None:
                                    record_login_timing(
                                        'session_revocation_authority',
                                        (time.perf_counter() - started_at) * 1000)
                            if not _is_effective_active(session, now=datetime.now(timezone.utc)):
                                raise _InactiveCachedSession()
                            return claims.user_id, session.expires_at.timestamp()
                        return load
                    ahead = getattr(cache, 'get_or_load_ahead', None)
                    if callable(ahead):
                        cached_user = await ahead(
                            'legacy', claims.user_id, canonical_session_id,
                            active_session_loader(timed=True),
                            # The reload runs after the response, so its authority
                            # time is not this request's waiting time.
                            active_session_loader(timed=False))
                    else:
                        cached_user = await cache.get_or_load(
                            'legacy', claims.user_id, canonical_session_id,
                            active_session_loader(timed=True))
                    active = cached_user == claims.user_id
                else:
                    authority_started = time.perf_counter()
                    try:
                        session = await resolve(session_id=canonical_session_id)
                    finally:
                        record_login_timing(
                            'session_revocation_authority',
                            (time.perf_counter() - authority_started) * 1000)
                    active = _is_effective_active(session, now=datetime.now(timezone.utc))
            except Exception as exc:
                code = getattr(exc, "code", "")
                if (isinstance(exc, _InactiveCachedSession) or code in _TERMINAL_SESSION_CODES
                        or getattr(exc, "status_code", None) == 401):
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
            if not active:
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
        finally:
            record_login_timing('session_revocation_check',
                                (time.perf_counter() - started) * 1000)
            emit_identity_timing(request_id, started, details)
            end_login_timings(token_context)

    async def _resolve_local_verdict(
        self,
        scope: MutableMapping[str, Any],
        state: Any,
        settings: Any,
    ) -> SessionVerdict | None:
        """#7078 B: verify padiem-auth ES256 token + SQLite denylist locally (0 upstream calls)."""
        from .request_telemetry import current_request_id
        from .shared_login_timing import (
            begin_login_timings,
            emit_identity_timing,
            end_login_timings,
            record_login_timing,
        )

        raw_access = _cookie_value(scope, ACCESS_COOKIE)
        raw_session = _session_cookie(scope)
        if not raw_access and not raw_session:
            return None
        if settings is None:
            return SessionVerdict(authenticated=False, reason="unavailable")

        legacy_claims = decode_session_claims(settings, raw_session) if raw_session else None
        if not raw_access:
            # CTO decision 2026-11-12 (#7078 B follow-up): a request carrying
            # only the legacy session cookie (no padiem-auth access token) is
            # NOT refused. It is verified through the exact pre-switch path —
            # legacy authority + cache rules — so live traffic on old cookies
            # is never force-logged-out by the switch. The shared denylist is
            # consulted first so a Chat-internal logout, password change or
            # deletion still revokes in 0 s, and an unreadable denylist stays
            # fail-closed. The access-table fast path above keeps 0 upstream
            # calls; this fallback follows the legacy cache rules instead.
            if legacy_claims is None:
                return None
            verdict: SessionVerdict | None = None
            outcome = "passthrough"
            cache = getattr(state, "auth_validation_cache", None)
            is_revoked_fn = getattr(cache, "is_revoked", None) if cache is not None else None
            if callable(is_revoked_fn):
                try:
                    legacy_denied = await is_revoked_fn(
                        session_ids=(
                            (legacy_claims.canonical_session_id,)
                            if legacy_claims.canonical_session_id else ()
                        ),
                        user_id=legacy_claims.user_id,
                    )
                except Exception:
                    # Denylist unreadable -> fail closed (503), unchanged.
                    verdict = SessionVerdict(authenticated=False, reason="unavailable")
                    outcome = "unavailable"
                else:
                    if legacy_denied:
                        verdict = SessionVerdict(
                            authenticated=False,
                            user_id=legacy_claims.user_id,
                            canonical_session_id=legacy_claims.canonical_session_id,
                            reason="revoked",
                        )
                        outcome = "revoked"
            if verdict is None:
                verdict = await self._resolve_legacy_verdict(scope)
                outcome = verdict.reason if verdict is not None else "passthrough"
            # Countable reason code only — never the cookie, token, or user id.
            print("legacy_session_fallback outcome=%s" % outcome, flush=True)
            return verdict

        token_context, details = begin_login_timings()
        started = time.perf_counter()
        request_id = current_request_id()
        try:
            verify_started = time.perf_counter()
            try:
                verified, verify_code = await _verify_access_token_locally(state, raw_access)
            finally:
                record_login_timing(
                    "account_token_verify",
                    (time.perf_counter() - verify_started) * 1000,
                )
            if verify_code == "unavailable":
                return SessionVerdict(authenticated=False, reason="unavailable")
            if verify_code != "ok" or verified is None:
                return SessionVerdict(authenticated=False, reason="revoked")

            account_id = verified.get("accountId")
            token_sid = verified.get("sessionId")
            if (not isinstance(account_id, str) or not account_id.startswith("sub_")
                    or not isinstance(token_sid, str) or not token_sid):
                return SessionVerdict(authenticated=False, reason="revoked")

            cache = getattr(state, "auth_validation_cache", None)
            is_revoked_fn = getattr(cache, "is_revoked", None) if cache is not None else None
            resolve_user_fn = (
                getattr(cache, "resolve_local_product_user", None)
                if cache is not None
                else None
            )
            if not callable(is_revoked_fn) or not callable(resolve_user_fn):
                # Revocation store missing or disabled -> fail closed (503).
                return SessionVerdict(
                    authenticated=False,
                    canonical_session_id=token_sid,
                    reason="unavailable",
                )

            try:
                user_id = await resolve_user_fn(account_id)
                session_ids: tuple[str, ...] = (
                    (token_sid, legacy_claims.canonical_session_id)
                    if legacy_claims is not None and legacy_claims.canonical_session_id
                    else (token_sid,)
                )
                revoked = await is_revoked_fn(
                    session_ids=session_ids,
                    account_id=account_id,
                    user_id=user_id,
                )
            except Exception:
                # SQLite / revocation check error -> fail closed (503).
                return SessionVerdict(
                    authenticated=False,
                    canonical_session_id=token_sid,
                    reason="unavailable",
                )

            if revoked or not isinstance(user_id, str) or not user_id:
                return SessionVerdict(
                    authenticated=False,
                    user_id=user_id if isinstance(user_id, str) else None,
                    canonical_session_id=token_sid,
                    reason="revoked",
                )
            if legacy_claims is not None and legacy_claims.user_id != user_id:
                return SessionVerdict(
                    authenticated=False,
                    user_id=user_id,
                    canonical_session_id=token_sid,
                    reason="revoked",
                )
            from .connector_account_subject import _remember_verified_login
            _remember_verified_login(verified, user_id)
            return SessionVerdict(
                authenticated=True,
                user_id=user_id,
                canonical_session_id=token_sid,
                reason="active",
            )
        finally:
            record_login_timing(
                "session_revocation_check",
                (time.perf_counter() - started) * 1000,
            )
            emit_identity_timing(request_id, started, details)
            end_login_timings(token_context)

    @staticmethod
    def _duplicate_cookie_count(scope: MutableMapping[str, Any], cookie_name: str) -> int:
        cookie_header = _header(scope, b"cookie")
        if not cookie_header:
            return 0
        return sum(
            1
            for part in cookie_header.split(";")
            if part.partition("=")[0].strip() == cookie_name
        )

    @staticmethod
    def _duplicate_session_cookie_count(scope: MutableMapping[str, Any]) -> int:
        """How many times the session cookie name appears in the Cookie header.

        Counts raw occurrences, not the collapsed mapping a request object
        builds: the whole point (internal audit H1, 2026-11-10) is that the
        first and the last occurrence can disagree.
        """

        cookie_header = _header(scope, b"cookie")
        if not cookie_header:
            return 0
        return sum(
            1
            for part in cookie_header.split(";")
            if part.partition("=")[0].strip() == SESSION_COOKIE
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
        state = getattr(scope.get("app"), "state", None)
        settings = getattr(state, "settings", None)
        local_mode = session_local_verify_enabled(settings)
        if settings is not None:
            path = str(scope.get("path") or "")
            exempt_paths = _LOCAL_VERIFY_EXEMPT_PATHS if local_mode else SESSION_GUARD_EXEMPT_PATHS
            if path not in exempt_paths and (
                self._duplicate_session_cookie_count(scope) > 1
                or (local_mode and self._duplicate_cookie_count(scope, ACCESS_COOKIE) > 1)
            ):
                await _error(
                    401,
                    SESSION_COOKIE_DUPLICATED_CODE,
                    SESSION_COOKIE_DUPLICATED_MESSAGE,
                )(scope, receive, send)
                return
        with measure('auth'):
            verdict = await self.resolve_verdict(scope)
        # Stage 1 shadow (#7078): record-only comparison. Never judges.
        try:
            from .auth_shadow_verify import run_shadow_compare as _run_shadow

            _run_shadow(scope, verdict)
        except Exception:
            pass
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
        if local_mode:
            if verdict.authenticated and isinstance(verdict.user_id, str) and verdict.user_id:
                state["padiem_shared_user_id"] = verdict.user_id
            else:
                state.pop("padiem_shared_user_id", None)
        await self.app(scope, receive, send)


__all__ = [
    "SESSION_AUTHORITY_UNAVAILABLE_CODE",
    "SESSION_AUTHORITY_UNAVAILABLE_MESSAGE",
    "SESSION_COOKIE_DUPLICATED_CODE",
    "SESSION_COOKIE_DUPLICATED_MESSAGE",
    "SESSION_GUARD_EXEMPT_PATHS",
    "SESSION_VERDICT_STATE_KEY",
    "SessionRevocationGuardMiddleware",
    "session_verdict",
]
