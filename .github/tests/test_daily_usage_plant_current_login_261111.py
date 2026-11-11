"""#7440 후속: 브라우저 점검의 padiem_session 심기가 현재 로그인 경로를 따른다
(2026-11-11).

공통 로그인 전환 뒤 옛 같은 호스트 엔드포인트(/api/auth/password/login)는
409 email_login_moved를 반환한다(#7449). #7509가 browser_shared_login의
자격을 QA_SMOKE_*로 맞추자 심기(_plant_legacy_session)가 그 엔드포인트를
그대로 쳤고, 실행 43069955981에서 409를 받아
RuntimeError("legacy_plant_login_refused")로 흐름이 FAIL
(shared_logout_runtimeerror)이 됐다. 이 파일은 세 가지를 고정한다:

  1. 심기는 공통 로그인 클라이언트(login_session_cookie)로 한다 — 스위치가
     끝났으면 레거시 경로를, 409 email_login_moved면 공통 로그인 폼을 따라
     가고 둘 다 padiem_session을 돌려준다. 심은 쿠키는 padiem_session이고
     chat.padiem.net이다.
  2. 심기가 자격을 못 받으면 흐름은 여전히 실패다 — 로그아웃 판정이 공허해
     지는 것을 조용한 녹색으로 덮지 않는다(#6720·#7440 계약 유지).
  3. 심기 소스에 옛 엔드포인트 직접 호출(bounded_call·LOGIN import)이
     남지 않는다.

실행:
    python -m pytest .github/tests/test_daily_usage_plant_current_login_261111.py -q
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import shared_login_client  # noqa: E402

CHECK = SCRIPTS / "daily_usage_browser_checks.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "daily_usage_browser_checks", CHECK)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class FakeContext:
    """add_cookies로 심은 쿠키를 기록한다. 값은 시험 더미다."""

    def __init__(self):
        self.cookies = []

    def add_cookies(self, cookies):
        self.cookies.extend(cookies)


def test_plant_uses_the_current_login_client(monkeypatch):
    """심기는 login_session_cookie(현재 경로)를 부르고 padiem_session을 심는다."""
    mod = _load_module()
    seen = []

    def fake_login(origin, username, password):
        seen.append((origin, username, password))
        return "plant-session-dummy-value"

    monkeypatch.setattr(shared_login_client, "login_session_cookie", fake_login)
    monkeypatch.setenv(mod.QA_USERNAME_ENV, "qa@example.test")
    monkeypatch.setenv(mod.QA_PASSWORD_ENV, "dummy-not-a-secret")
    context = FakeContext()

    mod._plant_legacy_session(context)

    assert seen == [(mod.ORIGIN, "qa@example.test", "dummy-not-a-secret")]
    assert len(context.cookies) == 1
    cookie = context.cookies[0]
    assert cookie["name"] == mod.PADIEM_SESSION_COOKIE == "padiem_session"
    assert cookie["value"] == "plant-session-dummy-value"
    assert cookie["domain"] == "chat.padiem.net"
    assert cookie["path"] == "/"
    assert cookie["httpOnly"] is True and cookie["secure"] is True


def test_plant_refusal_still_fails(monkeypatch):
    """자격을 못 받으면 RuntimeError — 공허한 로그아웃 판정을 덮지 않는다."""
    mod = _load_module()

    def refused(origin, username, password):
        raise shared_login_client.SharedLoginError("shared_login_refused")

    monkeypatch.setattr(shared_login_client, "login_session_cookie", refused)
    monkeypatch.setenv(mod.QA_USERNAME_ENV, "qa@example.test")
    monkeypatch.setenv(mod.QA_PASSWORD_ENV, "dummy-not-a-secret")

    try:
        mod._plant_legacy_session(FakeContext())
    except RuntimeError as exc:
        assert str(exc) == "legacy_plant_login_refused"
    else:
        raise AssertionError("a refused plant must fail the flow, not pass quietly")


def test_plant_source_has_no_direct_moved_endpoint_call():
    """심기 소스에 옛 엔드포인트 직접 호출(bounded_call·LOGIN)이 남지 않는다."""
    source = CHECK.read_text(encoding="utf-8")
    assert "from b62_live_logout_reuse_check import" not in source, (
        "the moved endpoint answered 409 email_login_moved (#7449) and left "
        "browser_shared_login FAIL shared_logout_runtimeerror")
    assert "login_session_cookie" in source
    assert 'QA_USERNAME_ENV = "QA_SMOKE_USERNAME"' in source


def test_login_session_cookie_falls_back_on_409_moved(monkeypatch):
    """클라이언트 자체가 409 email_login_moved에서 공통 로그인으로 폴백한다."""
    def moved_direct(origin, username, password, timeout):
        return 409, {"error": {"code": "email_login_moved"}}, None

    monkeypatch.setattr(shared_login_client, "_direct_login", moved_direct)
    monkeypatch.setattr(
        shared_login_client, "shared_login_session_cookie",
        lambda origin, username, password, timeout: "shared-session-dummy-value")

    cookie = shared_login_client.login_session_cookie(
        "https://chat.padiem.net", "qa@example.test", "dummy-not-a-secret")
    assert cookie == "shared-session-dummy-value"


def test_login_session_cookie_refuses_other_failures(monkeypatch):
    """409 외의 실패(401 등)는 폴백이 아니라 거절이다 — 판정이 흐려지지 않는다."""
    def refused_direct(origin, username, password, timeout):
        return 401, {"error": {"code": "invalid_credentials"}}, None

    monkeypatch.setattr(shared_login_client, "_direct_login", refused_direct)
    try:
        shared_login_client.login_session_cookie(
            "https://chat.padiem.net", "qa@example.test", "dummy-not-a-secret")
    except shared_login_client.SharedLoginError as exc:
        assert str(exc) == "login_refused_http_401_invalid_credentials"
    else:
        raise AssertionError("a non-409 refusal must not fall back quietly")
