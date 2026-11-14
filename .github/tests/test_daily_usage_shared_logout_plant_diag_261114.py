"""#7528: 심기 거절이 어느 로그인 단계에서 막혔는지 코드로 남는다 (2026-11-14).

browser_shared_login 이 shared_logout_runtimeerror 로만 실패해, 로그인
클라이언트가 어느 단계에서 거절했는지 실행 로그에서 볼 수 없었다. 이 파일은
세 가지를 고정한다:

  1. 심기 거절은 PlantSessionRefused(RuntimeError)로, 로그인 클라이언트의
     닫힌 코드를 public_code 에 담는다(자격·쿠키 값은 담지 않는다).
  2. 흐름 코드는 shared_logout_plant_<닫힌 코드>가 된다(예:
     shared_logout_plant_shared_login_refused).
  3. 로그인 세션이 없으면 심기는 여전히 실패다 — 조용한 녹색으로 덮지 않는다.

실행:
    python -m pytest .github/tests/test_daily_usage_shared_logout_plant_diag_261114.py -q
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import shared_login_client  # noqa: E402

CHECK = SCRIPTS / "daily_usage_browser_checks.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "daily_usage_browser_checks_diag", CHECK)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class FakeContext:
    def __init__(self):
        self.cookies = []

    def add_cookies(self, cookies):
        self.cookies.extend(cookies)


def _env(monkeypatch, mod):
    monkeypatch.setenv(mod.QA_USERNAME_ENV, "qa@example.test")
    monkeypatch.setenv(mod.QA_PASSWORD_ENV, "dummy-not-a-secret")


def test_refusal_carries_the_client_code(monkeypatch):
    mod = _load_module()
    _env(monkeypatch, mod)

    def refused(origin, username, password):
        raise shared_login_client.SharedLoginError("shared_login_refused")

    monkeypatch.setattr(shared_login_client, "login_session_cookie", refused)

    with pytest.raises(mod.PlantSessionRefused) as caught:
        mod._plant_legacy_session(FakeContext())

    assert isinstance(caught.value, RuntimeError)
    assert str(caught.value) == "legacy_plant_login_refused"
    assert caught.value.public_code == "shared_login_refused"
    assert "dummy-not-a-secret" not in caught.value.public_code


def test_missing_session_cookie_is_its_own_code(monkeypatch):
    mod = _load_module()
    _env(monkeypatch, mod)
    monkeypatch.setattr(shared_login_client, "login_session_cookie",
                        lambda origin, username, password: "")

    with pytest.raises(mod.PlantSessionRefused) as caught:
        mod._plant_legacy_session(FakeContext())

    assert caught.value.public_code == "session_cookie_missing"


def test_flow_code_names_the_refused_login_stage():
    mod = _load_module()
    exc = mod.PlantSessionRefused("shared_login_refused")
    assert mod.plant_refusal_code(exc) == "shared_logout_plant_shared_login_refused"


def test_plain_runtime_error_keeps_the_old_shape():
    mod = _load_module()
    assert mod.plant_refusal_code(RuntimeError("legacy_plant_login_refused")) == (
        "shared_logout_plant_legacy_plant_login_refused")


def test_flow_maps_plant_refusal_to_the_detail_code():
    """흐름 except 가 심기 거절을 plant_refusal_code 로 옮기는지 소스로 고정."""
    source = CHECK.read_text(encoding="utf-8")
    assert "except PlantSessionRefused as exc:" in source
    assert "flow.fail(plant_refusal_code(exc))" in source
    assert 'raise PlantSessionRefused(exc.public_code) from None' in source