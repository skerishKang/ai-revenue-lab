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
* 요청 경로 지연 추가 목표는 ≤5ms (JWKS 캐시 적중 시 ES256 검증만). 콜드 캐시의
  JWKS 조회는 요청 경로 밖에서 예열한다 (`local_cpython.py`의 startup 예열).
  300초 경계에 걸린 요청 1건이 재조회를 지불할 수 있으므로, 그 요청의 지연은
  별도로 계측해 30분 표본에서 제외하지 않고 보고한다.

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

_LOCK = threading.Lock()
_denylist: dict[str, float] = {}  # hash12(sid) or hash12(account_id) -> hold_until (epoch s)
_denylist_clock = time.time

_VERIFIER: Any = None
_VERIFIER_LOCK = threading.Lock()


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
    """Best-effort denylist recording from the shared access cookie payload.

    The payload is decoded without validation for recording only: the stage-2
    verifier still validates the signature before any denylist check, so an
    unverified payload can never grant access. It only seeds a denied
    candidate for a random-looking opaque ``sid``/``account_id``.
    """
    try:
        import base64
        import json as _json

        raw = None
        try:
            raw = cookies.get(ACCESS_COOKIE)
        except Exception:
            raw = None
        if not isinstance(raw, str) or raw.count(".") != 2:
            return
        payload_part = raw.split(".")[1]
        decoded = base64.urlsafe_b64decode(payload_part + "=" * (-len(payload_part) % 4))
        payload = _json.loads(decoded)
        if not isinstance(payload, dict):
            return
        record_denylist(payload.get("sid"), payload.get("account_id"))
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


def _get_shadow_verifier() -> Any:
    """Process-wide ES256 verifier (JWKS cached 300 s, same as shared login)."""
    global _VERIFIER
    with _VERIFIER_LOCK:
        if _VERIFIER is None:
            from padiem_auth_verify import Verifier

            _VERIFIER = Verifier(audience="b62")
        return _VERIFIER


def prewarm_shadow_verifier() -> None:
    """Fetch JWKS once at startup so the first request does not pay it.

    Called from the host startup (off the request path) only when the
    shadow switch is ON. Any failure is swallowed — the request path will
    simply hit the normal cached-key flow.
    """
    if not shadow_enabled():
        return
    try:
        verifier = _get_shadow_verifier()
        _keys = getattr(verifier, "_keys", None)
        if callable(_keys):
            _keys(True)
    except Exception:
        return


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
    verify_started = time.perf_counter()
    verified: dict[str, Any] | None = None
    verify_code = ""
    try:
        verifier = _get_shadow_verifier()
        result = verifier.verify(raw_shared)
        verified = dict(result)
    except Exception as exc:
        verify_code = str(getattr(exc, "args", [""])[0] if getattr(exc, "args", None) else type(exc).__name__) or type(exc).__name__
        # Bounded code vocabulary: keep only the closed set shape.
        if not verify_code.replace("_", "").replace("-", "").isalnum():
            verify_code = type(exc).__name__
        verify_code = verify_code[:48]
    verify_ms = (time.perf_counter() - verify_started) * 1000

    if verified is None:
        code_h = hash12(verify_code)
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
    "DENYLIST_TTL_SECONDS",
    "EXPIRING_SOON_SECONDS",
    "clear_denylist_for_tests",
    "is_denylisted",
    "prewarm_shadow_verifier",
    "record_denylist",
    "record_denylist_from_access_cookie",
    "run_shadow_compare",
    "shadow_enabled",
]
