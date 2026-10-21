"""#5481 the login modal: the forgot-password entry and the Google logo.

Two product-visible facts are pinned here:

* a member who lost the password gets a visible entry point from the email
  login form, with the request view, the confirm view and the way back;
* the "Continue with Google" button carries an identifiable Google mark, and
  the mark survives a locale change (the locale applier rewrites text content,
  so the label lives on an inner element and the logo is its sibling).

The contract is checked against the served markup, the client script, the
stylesheet and both locale dictionaries.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"

NEW_LOCALE_KEYS = [
    "auth-forgot-password",
    "auth-reset-request-title",
    "auth-reset-request-note",
    "auth-reset-request-submit",
    "auth-reset-request-sent",
    "auth-reset-back",
    "auth-reset-confirm-title",
    "auth-reset-confirm-submit",
    "auth-reset-confirm-done",
    "auth-reset-confirm-mismatch",
    "auth-reset-confirm-incomplete",
    "auth-reset-expired",
]


def html() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


def script() -> str:
    return (STATIC / "app.js").read_text(encoding="utf-8")


def styles() -> str:
    return (STATIC / "history.css").read_text(encoding="utf-8")


def locale() -> str:
    return (STATIC / "locale.js").read_text(encoding="utf-8")


def test_the_login_form_offers_the_forgot_password_entry():
    markup = html()
    assert 'id="passwordResetOpen"' in markup
    assert 'data-locale-key="auth-forgot-password"' in markup
    assert "비밀번호를 잊으셨나요?" in markup
    # The entry lives inside the email/password login form.
    login_form = markup.split('id="passwordLoginForm"', 1)[1].split("</form>", 1)[0]
    assert 'id="passwordResetOpen"' in login_form


def test_the_reset_views_and_the_way_back_are_served():
    markup = html()
    assert 'id="passwordResetPanel"' in markup
    assert 'id="passwordResetRequestView"' in markup
    assert 'id="passwordResetConfirmView"' in markup
    assert 'id="passwordResetRequestForm"' in markup
    assert 'id="passwordResetConfirmForm"' in markup
    assert 'id="passwordResetBack"' in markup
    assert 'id="passwordResetConfirmBack"' in markup
    # The request view asks for the account address, the confirm view asks for
    # the new password twice.
    assert 'id="passwordResetEmail"' in markup
    assert 'name="new_password"' in markup
    assert 'name="new_password_confirm"' in markup


def test_the_google_button_carries_an_identifiable_google_mark():
    markup = html()
    button = markup.split('id="googleLoginButton"', 1)[1].split("</button>", 1)[0]
    assert "<svg" in button
    assert 'class="auth-google-logo"' in button
    assert 'aria-hidden="true"' in button
    assert "#4285F4" in button
    assert "#EA4335" in button
    assert "#FBBC05" in button
    assert "#34A853" in button
    assert 'viewBox="0 0 48 48"' in button


def test_the_google_logo_survives_a_locale_change():
    # The locale applier sets textContent on the element that carries the
    # locale key, which would erase a child logo element. The label therefore
    # lives on an inner span and the logo is its sibling.
    markup = html()
    button = markup.split('id="googleLoginButton"', 1)[1].split("</button>", 1)[0]
    assert '<span data-locale-key="auth-google">' in button
    assert button.index("<svg") < button.index('<span data-locale-key="auth-google">')


def test_the_client_reads_the_one_time_token_from_the_url_fragment():
    client = script()
    assert "passwordResetTokenFromLocation" in client
    assert "window.location.hash" in client
    assert "window.location.search" in client
    # The token never travels in a query string.
    assert "reset=" in client
    assert "?reset=" not in client


def test_the_client_posts_only_the_reviewed_reset_fields():
    client = script()
    request_block = client.split(
        'await passwordAuthRequest("/api/auth/password/reset/request"', 1
    )[1].split("});", 1)[0]
    assert "email: passwordResetEmail.value" in request_block
    assert "password:" not in request_block
    assert "token:" not in request_block
    confirm_block = client.split(
        'await passwordAuthRequest("/api/auth/password/reset/confirm"', 1
    )[1].split("});", 1)[0]
    assert "token: passwordResetToken" in confirm_block
    assert "new_password: newPassword" in confirm_block
    # The browser never sends the account identifier on the confirm route, and
    # it never sends a current password.
    assert "identifier:" not in confirm_block
    assert "current_password:" not in confirm_block
    assert "email:" not in confirm_block


def test_the_reset_controls_keep_the_mobile_touch_target_floor():
    css = styles()
    assert ".auth-link {" in css
    link_block = css.split(".auth-link {", 1)[1].split("}", 1)[0]
    assert "min-height: 44px" in link_block
    assert ".auth-reset {" in css
    assert ".auth-status {" in css


def test_both_locales_define_the_same_reset_copy():
    text = locale()
    for key in NEW_LOCALE_KEYS:
        occurrences = re.findall(rf'"{re.escape(key)}":\s*"([^"]*)"', text)
        assert len(occurrences) >= 2, f"{key} is missing from one of the locales"
        # Korean first, English second: the two projections must differ.
        assert occurrences[0] != occurrences[1], f"{key} has the same copy in both locales"
        assert all(value.strip() for value in occurrences[:2])


def test_the_korean_copy_leads():
    text = locale()
    korean = text.split('ko:', 1)[1]
    assert '"auth-forgot-password": "비밀번호를 잊으셨나요?"' in korean
