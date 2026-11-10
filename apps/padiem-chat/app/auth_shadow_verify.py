"""Stage 1 shadow verification for #7078 (record-only, never judges).

When ``PADIEM_AUTH_LOCAL_VERIFY_SHADOW`` is ``true`` (default OFF), the
request-time session guard keeps deciding exactly as before. Beside that
verdict this module independently verifies the padiem-auth access token
carried in ``__Host-padiem-shared-access`` with JWKS (the same ES256
``Verifier`` the shared login flow uses) and contrasts the result with
the guard verdict, so stage-2 readiness can be measured without any
behaviour change.

Guarantees of this stage:

* 판정 변경 없음 — 이 모듈이 올리는 어떤 실패·불일치도 요청 결과에 닿지 않는다.
  전체 본문은 예외를 삼키고 한 줄의 기록만 남긴다.
* 비밀값·토큰·이메일·사용자 원문은 기록하지 않는다. 식별값은 SHA-256 해시 12자리만.
* 기록은 요청당 한 줄이다. 한 줄 안의 필드는 고정된 이름뿐이며 값은 해시·불리언·개수·ms뿐이다.
* 요청 경로 지연 추가 목표는 ≤5ms (JWKS 캐시 적중 시 ES256 검증만).
  요청 경로에서는 원격 JWKS 조회를 절대 하지 않는다 (캐시된 키로만 검증).
  키 갱신(만료·모르는 kid)은 요청 경로 밖(백그라운드)에서만, 재조회 쿨다운 60초
  + HTTP 타임아웃 3초로 감싼다. 모르는 kid는 ``unknown_kid``로 기록만.
  콜드 캐시의 JWKS 조회는 요청 경로 밖에서 예열한다 (`local_cpython.py`의 startup 예열).

Denylist (설계 2판 §2.3): 같은 호스트에서 폐기가 일어나면 폐기된 ``sid``와
``account_id``를 로컬 폐기 캐시에 기록한다. 최소 20분(수명 15분 + leeway 60초 + 전파 여유)
유지한다. 이 단계의 저장소는 프로세스 단위 dict(1.5단계에서 `auth_validation_cache`의
워커 공유 표로 옮긴다). 기록 자체는 best-effort이며 판정을 바꾸지 않는다.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from typing import Any

from .shared_login_flow import ACCESS_COOKIE

#: Same 20-minute floor as the design (§2.3): 15 min access + 60 s leeway + margin.
DENYLIST_TTL_SECONDS = 20 * 60
#: Token is "expiring soon" when less than this many seconds remain.
EXPIRING_SOON_SECONDS = 60
#: JWKS re-fetch cooldown on the background path (seconds).
JWKS_REFRESH_COOLDOWN_SECONDS = 60
#: Off-path HTTP timeout for JWKS fetches (seconds). 3 s proved too tight on
#: the COM2 host: every boot prewarm timed out (TimeoutError) and the cache
#: stayed cold for minutes. The request path itself never fetches (cached keys
#: only, verified below), so this bound only guards background threads.
JWKS_FETCH_TIMEOUT_SECONDS = 10

_LOCK = threading.Lock()
_denylist: dict[str, float] = {}  # hash12(sid) or hash12(account_id) -> hold_until (epoch s)
_denylist_clock = time.time

_VERIFIER: Any = None
_VERIFIER_LOCK = threading.Lock()
_REFRESH_LOCK = threading.Lock()
_refresh_state: dict[str, float] = {"last_attempt": 0.0, "attempts": 0.0}
# Background refresh threads are part of the production behaviour. Tests may
# disable thread spawning to observe the cooldown logic deterministically.
BACKGROUND_REFRESH_ENABLED = True

#: Startup prewarm retries (off the request path). A boot-time JWKS timeout is
#: transient (cold DNS/TLS on the host); retrying covers it without delaying
#: the first request or touching the request path.
PREWARM_RETRY_ATTEMPTS = 5
PREWARM_RETRY_DELAY_SECONDS = 15
PREWARM_RETRY_ENABLED = True


def shadow_enabled() -> bool:
    """True only when the explicit shadow switch is ON (default OFF)."""
    return os.environ.get("PADIEM_AUTH_LOCAL_VERIFY_SHADOW", "").strip().lower() == "true"


def hash12(value: Any) -> str:
    """Short SHA-256 hash of an identifier for safe journaling (never raw)."""
    if not isinstance(value, str) or not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


# --- Denylist -------------------------------------------------------------


def _denylist_key(value: Any) -> str:
    return hash12(value)


def _prune_denylist(now: float) -> None:
    for key in [k for k, until in _denylist.items() if until <= now]:
        _denylist.pop(key, None)


def record_denylist(session_id: Any = None, account_id: Any = None) -> None:
    """Record one revocation in the local denylist (best-effort, no judging)."""
    try:
        now = _denylist_clock()
        until = now + DENYLIST_TTL_SECONDS
        with _LOCK:
            _prune_denylist(now)
            for value in (session_id, account_id):
                if isinstance(value, str) and value:
                    _denylist[_denylist_key(value)] = until
    except Exception:
        return


def record_denylist_from_access_cookie(cookies) -> None:
    """Record the denylist from a signature-verified access token only.

    The sid/account_id are taken from ``Verifier.verify`` output, never from
    an unverified payload: a forged cookie logout must never seed another
    account's id into the denylist (Argon (c)-3 / (b)-3). Verification failure
    records nothing. Best-effort and judging-free.
    """
    try:
        raw = None
        try:
            raw = cookies.get(ACCESS_COOKIE)
        except Exception:
            raw = None
        if not isinstance(raw, str) or not raw:
            return
        verifier = _get_shadow_verifier()
        verified = verifier.verify(raw)
        if not isinstance(verified, dict):
            return
        record_denylist(verified.get("sessionId"), verified.get("accountId"))
    except Exception:
        return


def is_denylisted(session_id: Any = None, account_id: Any = None) -> bool:
    """Whether a verified token's sid/account_id is in the local denylist."""
    try:
        now = _denylist_clock()
        with _LOCK:
            _prune_denylist(now)
            for value in (session_id, account_id):
                if isinstance(value, str) and value and _denylist_key(value) in _denylist:
                    return True
        return False
    except Exception:
        return False


def clear_denylist_for_tests() -> None:
    with _LOCK:
        _denylist.clear()


# --- JWKS verifier ---------------------------------------------------------


def _short_fetch():
    """Background JWKS fetcher with a short timeout (never on the request path).

    Mirrors ``padiem_auth_verify._fetch`` (fixed URL, redirects refused) but
    with a 3 s timeout so a slow endpoint cannot park a background refresh.
    """
    import json as _json
    import urllib.request as _request

    try:
        from padiem_auth_verify import JWKS_URL as _URL
    except Exception:
        _URL = "https://auth.padiem.net/.well-known/jwks.json"

    class NoRedirect(_request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    request = _request.Request(_URL, headers={"User-Agent": "padiem-shadow-verify/1.0"})
    with _request.build_opener(NoRedirect).open(request, timeout=JWKS_FETCH_TIMEOUT_SECONDS) as response:
        return _json.load(response)


def _get_shadow_verifier() -> Any:
    """Process-wide ES256 verifier (JWKS cached 300 s, same as shared login).

    The same object is reused for every call (module singleton): the JWKS
    cache lives on the verifier, so recreating it per request would turn
    every request into a ~400 ms fetch. Verified by
    ``test_shadow_verifier_is_singleton``.
    """
    global _VERIFIER
    with _VERIFIER_LOCK:
        if _VERIFIER is None:
            from padiem_auth_verify import Verifier

            _VERIFIER = Verifier(audience="b62", fetcher=_short_fetch)
        return _VERIFIER


def _schedule_jwks_refresh(verifier: Any, *, now: float | None = None) -> bool:
    """Schedule an off-path JWKS refresh (cooldown 60 s). Returns whether fired.

    Cooldown- and time-bounded so unknown-``kid`` traffic cannot turn into a
    remote-fetch storm: at most one refresh attempt per cooldown window is
    recorded, and when spawning is enabled one daemon thread runs it. Callers
    on the request path never block on it.
    """
    moment = time.time() if now is None else now
    with _REFRESH_LOCK:
        if moment - _refresh_state["last_attempt"] < JWKS_REFRESH_COOLDOWN_SECONDS:
            return False
        _refresh_state["last_attempt"] = moment
        _refresh_state["attempts"] += 1
    if not BACKGROUND_REFRESH_ENABLED:
        return True

    def _run() -> None:
        try:
            keys = getattr(verifier, "_keys", None)
            if callable(keys):
                keys(True)
        except Exception:
            return

    thread = threading.Thread(target=_run, daemon=True, name="shadow-jwks-refresh")
    thread.start()
    return True


def reset_jwks_refresh_for_tests() -> None:
    with _REFRESH_LOCK:
        _refresh_state["last_attempt"] = 0.0
        _refresh_state["attempts"] = 0.0


def jwks_refresh_attempts() -> int:
    with _REFRESH_LOCK:
        return int(_refresh_state["attempts"])


def _decode_header_kid(token: Any) -> str | None:
    """Decode the (untrusted) JWT header ``kid`` for cache-presence check."""
    try:
        import base64
        import json as _json

        if not isinstance(token, str) or token.count(".") != 2:
            return None
        part = token.split(".")[0]
        decoded = base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))
        header = _json.loads(decoded)
        kid = header.get("kid") if isinstance(header, dict) else None
        return kid if isinstance(kid, str) and kid else None
    except Exception:
        return None


def _cached_kids(verifier: Any) -> list[str] | None:
    """Kid list from the verifier's JWKS cache, or None when cold/unavailable.

    Reads the cached keys only (no remote fetch). Returns None when the
    verifier keeps no cache or the cache is not fresh — the caller then
    records a cold/stale outcome and refreshes off-path instead of blocking.
    """
    try:
        clock = getattr(verifier, "clock", None)
        now = clock() if callable(clock) else time.time()
        cached = getattr(verifier, "cached", None)
        until = getattr(verifier, "until", 0)
        if cached is None or now >= until:
            return None
        return [k.get("kid") for k in cached if isinstance(k, dict) and isinstance(k.get("kid"), str)]
    except Exception:
        return None


def _verify_cached_only(verifier: Any, token: Any) -> tuple[dict[str, Any] | None, str]:
    """Verify against cached JWKS keys only. Returns (verified, code).

    Never performs a remote JWKS fetch on the request path:
    * cold/stale cache -> (None, "jwks_cold"), background refresh scheduled;
    * unknown ``kid``    -> (None, "unknown_kid"), background refresh scheduled;
    * fresh cache + known kid -> ``verifier.verify`` (which itself sees a fresh
      cache and a matching kid, so it will not fetch either).

    Objects without the cache introspection surface (test doubles) fall back
    to a plain ``verify()`` call so tests keep the existing coverage.
    """
    if not hasattr(verifier, "cached") or not hasattr(verifier, "until"):
        return dict(verifier.verify(token)), ""
    kids = _cached_kids(verifier)
    if kids is None:
        _schedule_jwks_refresh(verifier)
        return None, "jwks_cold"
    kid = _decode_header_kid(token)
    if kid is None or kid not in kids:
        _schedule_jwks_refresh(verifier)
        return None, "unknown_kid"
    return dict(verifier.verify(token)), ""


def _prewarm_once() -> None:
    verifier = _get_shadow_verifier()
    _keys = getattr(verifier, "_keys", None)
    if callable(_keys):
        _keys(True)


def _prewarm_retry_loop(attempts: int, delay: float) -> None:
    """Retry the startup JWKS fetch off-path until it lands or the bound ends."""

    for attempt in range(2, attempts + 1):
        try:
            time.sleep(delay)
            _prewarm_once()
            print("shadow_prewarm outcome=ok attempt=%d" % attempt, flush=True)
            return
        except Exception as exc:
            try:
                print(
                    "shadow_prewarm outcome=fail attempt=%d code=%s"
                    % (attempt, type(exc).__name__),
                    flush=True,
                )
            except Exception:
                return


def prewarm_shadow_verifier() -> None:
    """Fetch JWKS once at startup so the first request does not pay it.

    Called from the host startup (off the request path) only when the
    shadow switch is ON. Any JWKS outage is swallowed and reported on one
    journal line — the server always starts. A transient boot-time timeout is
    retried by a bounded background thread so the cache does not stay cold
    for the whole first traffic window; the request path itself never fetches.
    """

    if not shadow_enabled():
        return
    try:
        _prewarm_once()
        print("shadow_prewarm outcome=ok attempt=1", flush=True)
    except Exception as exc:
        try:
            print(
                "shadow_prewarm outcome=fail attempt=1 code=%s" % type(exc).__name__,
                flush=True,
            )
        except Exception:
            return
        if PREWARM_RETRY_ENABLED and PREWARM_RETRY_ATTEMPTS > 1:
            thread = threading.Thread(
                target=_prewarm_retry_loop,
                args=(PREWARM_RETRY_ATTEMPTS, PREWARM_RETRY_DELAY_SECONDS),
                daemon=True,
                name="shadow-jwks-prewarm-retry",
            )
            thread.start()


# --- Shadow comparison -----------------------------------------------------


def _cookie(scope: Any, name: str) -> str | None:
    try:
        headers = scope.get("headers") or ()
    except Exception:
        return None
    cookie_header: str | None = None
    try:
        for key, value in headers:
            if key.lower() == b"cookie":
                cookie_header = value.decode("latin-1")
                break
    except Exception:
        return None
    if not cookie_header:
        return None
    for part in cookie_header.split(";"):
        key, _, value = part.partition("=")
        if key.strip() == name:
            return value.strip() or None
    return None


def _shared_user_from_scope(scope: Any) -> str | None:
    """``padiem_shared_user_id`` set by SharedSessionMiddleware (outer layer)."""
    try:
        state = scope.get("state")
        if isinstance(state, dict):
            user = state.get("padiem_shared_user_id")
            return user if isinstance(user, str) and user else None
    except Exception:
        return None
    return None


def run_shadow_compare(scope: Any, verdict: Any) -> None:
    """Compare guard verdict with local JWKS verification. Never judges.

    Always returns ``None`` and never changes the request outcome. When the
    switch is OFF this does essentially nothing (no import, no fetch, no log).
    """
    started = time.perf_counter()
    try:
        if not shadow_enabled():
            return
        _run_shadow_compare(scope, verdict, started)
    except Exception:
        # A shadow failure is a recording failure only (one error line).
        try:
            print("shadow_verify outcome=error ms=%d" % int(round((time.perf_counter() - started) * 1000)), flush=True)
        except Exception:
            return


def _run_shadow_compare(scope: Any, verdict: Any, started: float) -> None:
    from .auth import SESSION_COOKIE, decode_session_claims

    state = getattr(scope.get("app"), "state", None)
    settings = getattr(state, "settings", None)
    raw_shared = _cookie(scope, ACCESS_COOKIE)
    raw_legacy = _cookie(scope, SESSION_COOKIE)

    legacy_uid: str | None = None
    legacy_has_sid = False
    legacy_sid: str | None = None
    if settings is not None and raw_legacy:
        try:
            claims = decode_session_claims(settings, raw_legacy)
        except Exception:
            claims = None
        if claims is not None:
            legacy_uid = claims.user_id
            legacy_has_sid = bool(claims.canonical_session_id)
            legacy_sid = claims.canonical_session_id

    verdict_ok: bool | None = None
    verdict_reason = "none"
    verdict_uid: str | None = None
    if verdict is not None:
        verdict_ok = bool(getattr(verdict, "authenticated", None))
        verdict_reason = str(getattr(verdict, "reason", "unknown") or "unknown")
        verdict_uid = getattr(verdict, "user_id", None)
        if not isinstance(verdict_uid, str):
            verdict_uid = None

    def _line(outcome: str, *, verify_ms: int = 0, local_ok: Any = None,
              uid_match: str = "unknown", token: str = "", denylisted: bool = False,
              exp_slack: str = "", code: str = "") -> None:
        print(
            "shadow_verify outcome=%s verdict=%s reason=%s local_ok=%s uid_match=%s "
            "token=%s denied=%s exp_slack=%s code=%s verify_ms=%d uid_h=%s vuid_h=%s "
            "suid_h=%s acc_h=%s sid_h=%s" % (
                outcome,
                ("authenticated" if verdict_ok is True else "refused" if verdict_ok is False else "none"),
                verdict_reason,
                ("yes" if local_ok is True else "no" if local_ok is False else "unknown"),
                uid_match,
                token,
                ("yes" if denylisted else "no"),
                exp_slack,
                code,
                int(round(verify_ms)),
                hash12(legacy_uid or verdict_uid),
                hash12(verdict_uid),
                hash12(claims_sid if raw_legacy else None) if legacy_has_sid else "",
                hash12(token_account),
                hash12(token_sid),
            ),
            flush=True,
        )

    claims_sid = legacy_sid  # legacy cookie sid (hashed below)
    token_account: Any = None
    token_sid: Any = None

    # No shared access token: classify by the legacy cookie instead of
    # pretending a mismatch (email-logged and legacy sessions have no token).
    if not raw_shared:
        if raw_legacy is None:
            _line("no_token_guest", token="absent_guest")
        elif legacy_uid is None:
            _line("no_token_unparsable_cookie", token="absent_unparsable")
        elif legacy_has_sid:
            _line("no_token_legacy_sid", token="absent_legacy_sid")
        else:
            _line("no_token_legacy_nosid", token="absent_legacy_nosid")
        return

    # Shared access token present: verify local + denylist, then compare.
    # Cached keys only — never a remote JWKS fetch on the request path.
    verify_started = time.perf_counter()
    verified: dict[str, Any] | None = None
    verify_code = ""
    try:
        verified, verify_code = _verify_cached_only(_get_shadow_verifier(), raw_shared)
    except Exception as exc:
        verify_code = str(getattr(exc, "args", [""])[0] if getattr(exc, "args", None) else type(exc).__name__) or type(exc).__name__
        # Bounded code vocabulary: keep only the closed set shape.
        if not verify_code.replace("_", "").replace("-", "").isalnum():
            verify_code = type(exc).__name__
        verify_code = verify_code[:48]
    verify_ms = (time.perf_counter() - verify_started) * 1000

    if verified is None:
        code_h = hash12(verify_code)
        if verify_code in ("unknown_kid", "jwks_cold"):
            _line(verify_code, verify_ms=verify_ms, local_ok=False,
                  token="present", code=code_h)
        else:
            _line("verify_failed", verify_ms=verify_ms, local_ok=False,
                  token="present", code=code_h)
        return

    token_account = verified.get("accountId")
    token_sid = verified.get("sessionId")
    expires_at = verified.get("expiresAt")
    exp_slack = ""
    try:
        if isinstance(expires_at, int):
            exp_slack = str(int(expires_at - time.time()))
    except Exception:
        exp_slack = ""

    denylisted = is_denylisted(token_sid, token_account)
    local_ok = not denylisted

    shared_user = _shared_user_from_scope(scope)
    if shared_user and legacy_uid:
        # claims.uid (legacy cookie) vs reverse-mapped shared user id.
        uid_match = "match" if shared_user == legacy_uid else "mismatch"
    elif shared_user:
        uid_match = "unmapped_no_claims"
    elif legacy_uid:
        uid_match = "unmapped_no_shared"
    else:
        uid_match = "unmapped"

    token_kind = "present"
    if isinstance(expires_at, int) and expires_at - time.time() <= EXPIRING_SOON_SECONDS:
        token_kind = "present_expiring"

    if verdict_ok is None:
        outcome = "verdict_none_local_ok" if local_ok else "verdict_none_local_no"
    elif verdict_reason == "unavailable":
        outcome = "authority_unavailable_local_ok" if local_ok else "authority_unavailable_local_no"
    elif verdict_ok == local_ok:
        outcome = "match"
    else:
        outcome = "mismatch"
    if denylisted and verdict_ok:
        outcome = "mismatch_denylist_hit"

    _line(outcome, verify_ms=verify_ms, local_ok=local_ok, uid_match=uid_match,
          token=token_kind, denylisted=denylisted, exp_slack=exp_slack, code="")


__all__ = [
    "BACKGROUND_REFRESH_ENABLED",
    "DENYLIST_TTL_SECONDS",
    "EXPIRING_SOON_SECONDS",
    "JWKS_FETCH_TIMEOUT_SECONDS",
    "JWKS_REFRESH_COOLDOWN_SECONDS",
    "clear_denylist_for_tests",
    "is_denylisted",
    "jwks_refresh_attempts",
    "prewarm_shadow_verifier",
    "record_denylist",
    "record_denylist_from_access_cookie",
    "reset_jwks_refresh_for_tests",
    "run_shadow_compare",
    "shadow_enabled",
]
