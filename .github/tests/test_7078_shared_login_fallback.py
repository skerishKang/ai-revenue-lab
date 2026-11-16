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


# The Chat retry-page header names the finish stage; the client may only
# append a value from the closed list, and keeps absence distinguishable.


def _headers(value):
    from email.message import Message

    message = Message()
    if value is not None:
        message["X-Padiem-Login-Code"] = value
    return message


def test_login_code_suffix_uses_only_closed_values():
    suffix = shared_login_client._login_code_suffix
    assert suffix(_headers("exchange.invalid_grant")) == ".exchange.invalid_grant"
    assert suffix(_headers("resolve_account.service_rpc_forbidden")) == (
        ".resolve_account.service_rpc_forbidden"
    )
    assert suffix(_headers(None)) == "_noheader"
    assert suffix(None) == "_noheader"
    assert suffix(_headers("exchange.not_a_closed_code")) == "_unknownheader"
    assert suffix(_headers("not_a_stage.invalid_grant")) == "_unknownheader"
    assert suffix(_headers("unknown")) == "_unknownheader"
    assert suffix(_headers("exchange.invalid_grant.extra")) == "_unknownheader"


def test_refusal_code_keeps_the_closed_stage_suffix():
    assert shared_login_client.SharedLoginError(
        "shared_login_refused_http_503.exchange.invalid_grant"
    ).public_code == "shared_login_refused_http_503.exchange.invalid_grant"
    assert shared_login_client.SharedLoginError(
        "shared_login_refused_http_503_noheader"
    ).public_code == "shared_login_refused_http_503_noheader"
    assert shared_login_client.SharedLoginError("bad code").public_code == (
        "shared_login_failed"
    )


def _fake_opener(header_value, monkeypatch):
    from urllib.error import HTTPError

    class _Page:
        def __init__(self):
            self._body = b'<form method="post" action="/login/password?state=abc.def">'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def geturl(self):
            return "https://auth.padiem.net/login?client_id=b62"

        def read(self, *args):
            return self._body

    class _Body:
        def read(self, *args):
            return b"<html>synthetic retry page</html>"

    class _Opener:
        def open(self, request, timeout=None):
            if getattr(request, "data", None):  # the email-form POST
                raise HTTPError(
                    request.get_full_url(),
                    503,
                    "synthetic",
                    _headers(header_value),
                    _Body(),
                )
            return _Page()

    monkeypatch.setattr(shared_login_client, "build_opener", lambda *args: _Opener())


def _run_refusal(header_value, monkeypatch):
    _fake_opener(header_value, monkeypatch)
    try:
        shared_login_client.shared_login_session_cookie(
            "https://chat.padiem.net", "qa@example.test", "pw"
        )
    except shared_login_client.SharedLoginError as error:
        return error.public_code
    raise AssertionError("expected a refusal")


def test_http_refusal_appends_the_closed_login_code(monkeypatch):
    assert _run_refusal("exchange.invalid_grant", monkeypatch) == (
        "shared_login_refused_http_503.exchange.invalid_grant"
    )


def test_http_refusal_without_header_stays_distinguishable(monkeypatch):
    assert _run_refusal(None, monkeypatch) == "shared_login_refused_http_503_noheader"


def test_http_refusal_with_foreign_header_stays_distinguishable(monkeypatch):
    assert _run_refusal("exchange.not_a_closed_code", monkeypatch) == (
        "shared_login_refused_http_503_unknownheader"
    )


# #7853 follow-up: a pre-gate account gets the one-time 만 14세 확인 screen at
# login. The QA helper answers it once and continues; a second screen is a
# failure with its own code. Account values stay fake here.

_AGE_HANDLE = "h" + "0" * 21


def _age_screen(action="/age-confirm/password", handle=_AGE_HANDLE):
    return (
        '<html><body><h1>만 14세 이상인지 확인해 주세요</h1>'
        f'<form method="post" action="{action}">'
        '<input type="hidden" name="lt_theme" value="light">'
        f'<input type="hidden" name="handle" value="{handle}">'
        '<input id="ageConfirm" name="age_confirm" value="yes" type="checkbox">'
        '<button type="submit">확인</button></form></body></html>'
    )


def _plain_page():
    return "<html><body>계속 진행합니다</body></html>"


class _FakeResponse:
    def __init__(self, body, url):
        self._body = body.encode("utf-8")
        self._url = url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def geturl(self):
        return self._url

    def read(self, *args):
        return self._body


def _age_opener(monkeypatch, *, login_body, confirm_body=None, seen=None):
    """Drive the shared flow with a fake transport; record what was posted."""
    seen = [] if seen is None else seen

    class _Opener:
        def open(self, request, timeout=None):
            data = getattr(request, "data", None)
            url = request.get_full_url()
            if data is None:
                seen.append(("GET", url))
                return _FakeResponse(
                    '<form method="post" action="/login/password?state=abc.def">',
                    "https://auth.padiem.net/login?client_id=b62",
                )
            seen.append(("POST", url, data.decode("utf-8")))
            if url.endswith("/age-confirm/password"):
                return _FakeResponse(
                    confirm_body if confirm_body is not None else _plain_page(),
                    "https://auth.padiem.net/age-confirm/password",
                )
            return _FakeResponse(login_body, "https://auth.padiem.net/login/password?state=abc.def")

    monkeypatch.setattr(shared_login_client, "build_opener", lambda *args: _Opener())
    return seen


def test_the_age_screen_is_answered_once_and_the_login_continues(monkeypatch):
    seen = _age_opener(monkeypatch, login_body=_age_screen())
    state = {"answered": False}

    def jar_cookie(_jar):
        return "session-cookie-value" if state["answered"] else None

    def submit(opener, action, handle, timeout):
        state["answered"] = True
        return real_submit(opener, action, handle, timeout)

    real_submit = shared_login_client._submit_age_confirm
    monkeypatch.setattr(shared_login_client, "_session_from_jar", jar_cookie)
    monkeypatch.setattr(shared_login_client, "_submit_age_confirm", submit)
    cookie = shared_login_client.shared_login_session_cookie(
        "https://chat.padiem.net", "qa@example.test", "pw"
    )
    assert cookie == "session-cookie-value"
    posts = [entry for entry in seen if entry[0] == "POST"]
    assert posts[-1][1] == "https://auth.padiem.net/age-confirm/password"
    assert posts[-1][2] == f"lt_theme=light&handle={_AGE_HANDLE}&age_confirm=yes"
    assert state["answered"] is True


def test_a_login_without_the_age_screen_is_unchanged(monkeypatch):
    seen = _age_opener(monkeypatch, login_body=_plain_page())
    monkeypatch.setattr(shared_login_client, "_session_from_jar", lambda _jar: "session-cookie-value")
    cookie = shared_login_client.shared_login_session_cookie(
        "https://chat.padiem.net", "qa@example.test", "pw"
    )
    assert cookie == "session-cookie-value"
    assert [entry[1] for entry in seen if entry[0] == "POST"] == [
        "https://auth.padiem.net/login/password?state=abc.def"
    ]


def test_a_second_age_screen_is_reported_as_a_loop(monkeypatch):
    _age_opener(monkeypatch, login_body=_age_screen(), confirm_body=_age_screen())
    monkeypatch.setattr(shared_login_client, "_session_from_jar", lambda _jar: "session-cookie-value")
    try:
        shared_login_client.shared_login_session_cookie(
            "https://chat.padiem.net", "qa@example.test", "pw"
        )
    except shared_login_client.SharedLoginError as error:
        assert error.public_code == "shared_login_age_confirm_loop"
    else:
        raise AssertionError("expected the loop refusal")


def test_the_deploy_smoke_keeps_the_loop_code(monkeypatch):
    import post_deploy_real_chat_smoke as smoke

    def loop(origin, username, password):
        raise shared_login_client.SharedLoginError("shared_login_age_confirm_loop")

    monkeypatch.setattr(smoke, "login_session_cookie", loop)
    try:
        smoke._sign_in_shared(object(), "https://chat.padiem.net", "qa@example.test", "pw")
    except smoke.CanaryError as error:
        assert error.public_code == "qa_age_confirm_loop"
    else:
        raise AssertionError("expected qa_age_confirm_loop")


def test_the_deploy_smoke_still_reports_a_refused_login(monkeypatch):
    import post_deploy_real_chat_smoke as smoke

    def refused(origin, username, password):
        raise shared_login_client.SharedLoginError("shared_login_session_missing")

    monkeypatch.setattr(smoke, "login_session_cookie", refused)
    try:
        smoke._sign_in_shared(object(), "https://chat.padiem.net", "qa@example.test", "pw")
    except smoke.CanaryError as error:
        assert error.public_code == "qa_login_refused"
    else:
        raise AssertionError("expected qa_login_refused")
