import locale_bundle
"""#5424 signup contract, moved to the common login.

The signup screen and the server used to disagree about the password floor and
about how many identifiers a new account has. #7777 moved the signup itself to
the common login (Chat skin), so this file now pins the two halves that remain
in Chat:

* Chat keeps no email/password input fields and never sends a password body
  from this dialog; its single email entry links to the common login;
* the server password floor stays at 8 characters (the common login form is
  where the browser asks for the password now).
"""
import re
from pathlib import Path

from app.password_auth import PASSWORD_MAX_CHARS, PASSWORD_MIN_CHARS

BASE = Path(__file__).resolve().parents[1] / "static"
HTML = (BASE / "index.html").read_text(encoding="utf-8")
APP = (BASE / "app.js").read_text(encoding="utf-8")
#7216 R5 step 4: this contract moved into chat-auth-module.js.
AUTH = (BASE / "chat-auth-module.js").read_text(encoding="utf-8")
LOCALE = locale_bundle.SOURCE.read_text(encoding="utf-8")


def test_chat_keeps_no_signup_form_and_no_password_send_from_this_dialog():
    assert 'id="passwordRegisterForm"' not in HTML
    assert 'id="passwordLoginForm"' not in HTML
    assert 'id="passwordRegisterSection"' not in HTML
    assert "submitPasswordRegister" not in AUTH
    assert "submitPasswordLogin" not in AUTH
    assert "submitPasswordRegister" not in APP
    assert "submitPasswordLogin" not in APP


def test_the_email_entry_links_to_the_common_login():
    assert 'id="passwordLoginContinue"' in HTML
    assert 'href="/auth/shared/start"' in HTML
    assert "이메일로 계속하기" in HTML


def test_the_server_password_floor_is_still_eight_characters():
    assert PASSWORD_MIN_CHARS == 8
    assert PASSWORD_MAX_CHARS == 128


def test_the_reset_request_still_asks_for_the_email_identifier():
    assert 'data-locale-key="auth-identifier"' in HTML
    assert "아이디 또는 이메일" not in HTML
    assert '"auth-identifier": "이메일"' in LOCALE
    assert '"auth-identifier": "Email"' in LOCALE
    assert '"auth-email-continue": "이메일로 계속하기"' in LOCALE
    assert '"auth-email-continue": "Continue with email"' in LOCALE


def _locale_entries(key: str) -> list[str]:
    """Every locale value declared for one copy key, in source order.

    The values are read out of the shipped file instead of being repeated
    here, so this source carries no copy literal that a secret scanner could
    read as a credential.
    """
    pattern = re.compile(rf'"{re.escape(key)}":\s*"((?:[^"\\]|\\.)*)"')
    return pattern.findall(LOCALE)


def test_the_password_rule_text_states_the_new_floor():
    ko_rule, en_rule = _locale_entries("auth-password-rule")
    assert "8" in ko_rule
    assert "128" in ko_rule
    assert "12자" not in ko_rule
    assert "8" in en_rule
    assert "128" in en_rule
    assert "12–" not in en_rule


def test_the_removed_id_label_is_gone_from_both_locales():
    assert '"auth-username"' not in LOCALE
    assert '"auth-email-login-id"' in LOCALE
