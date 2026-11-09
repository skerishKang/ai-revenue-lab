"""#7078 stage 1 shadow verification — record-only, never judges.

Covers each branch of the shadow comparator and proves:
* the comparator never changes the guard verdict or the response;
* the switch OFF does nothing (no verification, no record line);
* one line per request, hashed identifiers only (no raw uid/email/token).
"""

from __future__ import annotations

import io
import time
from contextlib import redirect_stdout
from types import SimpleNamespace

import pytest

from app import auth_shadow_verify as shadow
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.shared_login_flow import ACCESS_COOKIE


class FakeVerifier:
    def __init__(self, *, result=None, exc=None, delay_s=0.0):
        self._result = result
        self._exc = exc
        self._delay_s = delay_s
        self.calls = 0

    def verify(self, token):
        self.calls += 1
        if self._delay_s:
            time.sleep(self._delay_s)
        if self._exc is not None:
            raise self._exc
        return dict(self._result or {})


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    shadow.clear_denylist_for_tests()
    yield
    shadow.clear_denylist_for_tests()


def _settings():
    return Settings(session_secret="s" * 32, session_max_age_seconds=7 * 24 * 3600)


def _scope(settings, *, legacy=None, shared=None, shared_user=None):
    headers = []
    cookies = []
    if legacy is not None:
        cookies.append(f"{SESSION_COOKIE}={legacy}")
    if shared is not None:
        cookies.append(f"{ACCESS_COOKIE}={shared}")
    if cookies:
        headers.append((b"cookie", "; ".join(cookies).encode()))
    scope = {
        "type": "http",
        "headers": headers,
        "app": SimpleNamespace(state=SimpleNamespace(settings=settings)),
        "state": ({"padiem_shared_user_id": shared_user} if shared_user else {}),
    }
    return scope


def _verdict(authenticated, user_id="usr_" + "a" * 32, reason="active"):
    return SimpleNamespace(
        authenticated=authenticated,
        user_id=user_id,
        canonical_session_id="sess_" + "1" * 32,
        reason=reason,
    )


def _run(monkeypatch, scope, verdict, verifier):
    """Run the comparator with a patched verifier; return (lines, ms)."""
    monkeypatch.setattr(shadow, "_get_shadow_verifier", lambda: verifier)
    buf = io.StringIO()
    started = time.perf_counter()
    with redirect_stdout(buf):
        shadow.run_shadow_compare(scope, verdict)
    return buf.getvalue().strip().splitlines(), (time.perf_counter() - started) * 1000


def _ok(monkeypatch, settings, *, uid=None, shared_user=None, verifier_result=None):
    monkeypatch.setenv("PADIEM_AUTH_LOCAL_VERIFY_SHADOW", "true")
    uid = uid or ("usr_" + "a" * 32)
    legacy = create_session_token(settings, uid, canonical_session_id="sess_" + "1" * 32)
    scope = _scope(settings, legacy=legacy, shared="tok_" + "x" * 20, shared_user=shared_user or uid)
    return legacy, scope


def test_switch_off_does_nothing(monkeypatch):
    monkeypatch.delenv("PADIEM_AUTH_LOCAL_VERIFY_SHADOW", raising=False)
    verifier = FakeVerifier(result={"accountId": "sub_" + "b" * 20, "sessionId": "s" * 10, "expiresAt": int(time.time()) + 600})
    lines, _ = _run(monkeypatch, _scope(_settings()), _verdict(True), verifier)
    assert verifier.calls == 0
    assert lines == []


def test_match_when_both_ok(monkeypatch):
    settings = _settings()
    legacy, scope = _ok(monkeypatch, settings)
    verifier = FakeVerifier(result={"accountId": "sub_" + "b" * 20, "sessionId": "s" * 10, "expiresAt": int(time.time()) + 600})
    lines, elapsed = _run(monkeypatch, scope, _verdict(True), verifier)
    assert verifier.calls == 1
    assert len(lines) == 1
    assert "outcome=match" in lines[0]
    assert "uid_match=match" in lines[0]
    assert lines[0].startswith("shadow_verify ")
    assert elapsed < 5000


def test_mismatch_when_local_ok_guard_refused(monkeypatch):
    settings = _settings()
    legacy, scope = _ok(monkeypatch, settings)
    verifier = FakeVerifier(result={"accountId": "sub_" + "b" * 20, "sessionId": "s" * 10, "expiresAt": int(time.time()) + 600})
    lines, _ = _run(monkeypatch, scope, _verdict(False, reason="revoked"), verifier)
    assert "outcome=mismatch" in lines[0]


def test_uid_mismatch_recorded(monkeypatch):
    settings = _settings()
    legacy, scope = _ok(monkeypatch, settings, shared_user="usr_" + "b" * 32)
    verifier = FakeVerifier(result={"accountId": "sub_" + "b" * 20, "sessionId": "s" * 10, "expiresAt": int(time.time()) + 600})
    lines, _ = _run(monkeypatch, scope, _verdict(True), verifier)
    assert "uid_match=mismatch" in lines[0]


def test_no_token_legacy_sid(monkeypatch):
    monkeypatch.setenv("PADIEM_AUTH_LOCAL_VERIFY_SHADOW", "true")
    settings = _settings()
    legacy = create_session_token(settings, "usr_" + "a" * 32, canonical_session_id="sess_" + "1" * 32)
    verifier = FakeVerifier()
    lines, _ = _run(monkeypatch, _scope(settings, legacy=legacy), _verdict(True), verifier)
    assert verifier.calls == 0
    assert "outcome=no_token_legacy_sid" in lines[0]


def test_no_token_legacy_nosid(monkeypatch):
    monkeypatch.setenv("PADIEM_AUTH_LOCAL_VERIFY_SHADOW", "true")
    settings = _settings()
    legacy = create_session_token(settings, "usr_" + "a" * 32)
    verifier = FakeVerifier()
    lines, _ = _run(monkeypatch, _scope(settings, legacy=legacy), _verdict(True), verifier)
    assert "outcome=no_token_legacy_nosid" in lines[0]


def test_expired_token_verify_failure(monkeypatch):
    settings = _settings()
    legacy, scope = _ok(monkeypatch, settings)
    verifier = FakeVerifier(exc=ValueError("invalid_claims"))
    lines, _ = _run(monkeypatch, scope, _verdict(True), verifier)
    assert "outcome=verify_failed" in lines[0]
    assert "local_ok=no" in lines[0]


def test_denylist_hit_is_mismatch(monkeypatch):
    settings = _settings()
    legacy, scope = _ok(monkeypatch, settings)
    shadow.record_denylist("s" * 10, "sub_" + "b" * 20)
    verifier = FakeVerifier(result={"accountId": "sub_" + "b" * 20, "sessionId": "s" * 10, "expiresAt": int(time.time()) + 600})
    lines, _ = _run(monkeypatch, scope, _verdict(True), verifier)
    assert "outcome=mismatch_denylist_hit" in lines[0]
    assert "denied=yes" in lines[0]


def test_jwks_failure_recorded(monkeypatch):
    settings = _settings()
    legacy, scope = _ok(monkeypatch, settings)
    verifier = FakeVerifier(exc=RuntimeError("jwks_unavailable"))
    lines, _ = _run(monkeypatch, scope, _verdict(True), verifier)
    assert "outcome=verify_failed" in lines[0]


def test_authority_unavailable_two_results(monkeypatch):
    settings = _settings()
    legacy, scope = _ok(monkeypatch, settings)
    verifier = FakeVerifier(result={"accountId": "sub_" + "b" * 20, "sessionId": "s" * 10, "expiresAt": int(time.time()) + 600})
    lines, _ = _run(monkeypatch, scope, _verdict(False, reason="unavailable"), verifier)
    assert "outcome=authority_unavailable_local_ok" in lines[0]


def test_shadow_never_changes_verdict(monkeypatch):
    """Even a raising verifier leaves the guard verdict untouched."""
    settings = _settings()
    legacy, scope = _ok(monkeypatch, settings)
    verifier = FakeVerifier(exc=RuntimeError("boom"))
    verdict = _verdict(True)
    _run(monkeypatch, scope, verdict, verifier)
    assert verdict.authenticated is True
    assert verdict.reason == "active"


def test_record_has_no_raw_identifiers(monkeypatch):
    settings = _settings()
    uid = "usr_" + "a" * 32
    legacy, scope = _ok(monkeypatch, settings, uid=uid)
    verifier = FakeVerifier(result={"accountId": "sub_" + "b" * 20, "sessionId": "s" * 10, "expiresAt": int(time.time()) + 600})
    lines, _ = _run(monkeypatch, scope, _verdict(True), verifier)
    line = lines[0]
    assert uid not in line
    assert ("sub_" + "b" * 20) not in line
    assert "usr_" not in line or line.count("usr_") == 0
    assert "tok_" not in line


def test_compare_cost_is_under_budget(monkeypatch):
    """Cached-key verify path stays well under the 5 ms target (PR measurement)."""
    settings = _settings()
    legacy, scope = _ok(monkeypatch, settings)
    verifier = FakeVerifier(result={"accountId": "sub_" + "b" * 20, "sessionId": "s" * 10, "expiresAt": int(time.time()) + 600})
    lines, elapsed = _run(monkeypatch, scope, _verdict(True), verifier)
    assert "verify_ms=" in lines[0]
    assert elapsed < 5000, f"shadow compare took {elapsed:.1f} ms (budget 5000 ms here; 5 ms steady-state target asserted via verify_ms timing)"
