"""#7078: production checks keep working when the switch moves email login."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / ".github" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import b62_live_logout_reuse_check as logout_check  # noqa: E402
import shared_login_client  # noqa: E402


def test_shared_form_action_is_resolved_from_the_common_login_page():
    html = '<form method="post" action="/login/password?state=abc.def">'
    assert shared_login_client.shared_login_form_action(
        html, "https://auth.padiem.net/login?client_id=b62"
    ) == "https://auth.padiem.net/login/password?state=abc.def"


def test_direct_login_is_unchanged_when_the_switch_is_off(monkeypatch):
    calls = []
    monkeypatch.setattr(
        logout_check, "bounded_call",
        lambda *args, **kwargs: (401, {"error": {"code": "invalid_credentials"}}, None),
    )
    status, body, cookie = logout_check.login_bounded(object(), "qa@example.test", "pw")
    assert (status, body, cookie) == (
        401, {"error": {"code": "invalid_credentials"}}, None
    )
    assert calls == []


def test_moved_login_uses_the_common_flow(monkeypatch):
    seen = []

    def moved(origin, username, password):
        seen.append((origin, username))
        return "session-cookie-value"

    monkeypatch.setattr(shared_login_client, "shared_login_session_cookie", moved)
    monkeypatch.setattr(
        logout_check, "bounded_call",
        lambda *args, **kwargs: (409, {"error": {"code": "email_login_moved"}}, None),
    )
    status, body, cookie = logout_check.login_bounded(
        object(), "qa@example.test", "pw"
    )
    assert status == 200 and body == {"ok": True}
    assert cookie == "session-cookie-value"
    assert seen == [(logout_check.ORIGIN, "qa@example.test")]


def test_daily_check_and_live_scripts_use_the_fallback_login():
    daily = (SCRIPTS / "daily_real_usage_check.py").read_text(encoding="utf-8")
    assert "login_bounded" in daily
    assert "login_bounded(opener, username, password)" in daily
    long_context = (SCRIPTS / "b62_live_long_context_canary.py").read_text(encoding="utf-8")
    assert "shared_login_session_cookie" in long_context
    assert "email_login_moved" in long_context


def test_qa_provisioning_and_b66_smoke_cover_the_moved_login():
    qa = (SCRIPTS / "provision_qa_smoke_account.ps1").read_text(encoding="utf-8")
    assert "Invoke-SharedLogin" in qa
    assert "email_login_moved" in qa
    pc = (SCRIPTS / "provision_qa_pc_token.ps1").read_text(encoding="utf-8")
    assert "Get-SharedLoginSession" in pc
    assert "email_login_moved" in pc
    b66 = (SCRIPTS / "b66_cgi_final_handoff_smoke.py").read_text(encoding="utf-8")
    assert "email_login_moved" not in b66  # response status is the trigger there
    assert 'form[action^="/login/password"]' in b66


def test_the_council_client_also_moves():
    council = (
        REPO / "apps" / "padiem-council-apps" / "static" / "council-app.js"
    ).read_text(encoding="utf-8")
    assert "email_login_moved" in council
    assert "window.location.assign(data.login_url)" in council
