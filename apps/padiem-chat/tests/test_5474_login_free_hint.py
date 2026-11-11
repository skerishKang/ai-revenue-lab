"""Owner decision 2026-11-05: Chat/Claw AI answers are signed-in only.

The product-visible contract pinned here:

* the note sits directly under the Google login button inside the existing auth
  dialog and says what signing in enables;
* both locales carry the copy, and the Korean copy is the served default;
* the note keeps the panel typography and wraps inside the dialog width;
* the browser pre-gate stops a guest before any Chat or Claw request leaves the
  browser and opens the existing login dialog while keeping the typed text;
* the first screen carries one quiet guest invitation with the same login
  entry, and it stays hidden on the network-free CI mock;
* the Chat routes answer a guest with 401 ``login_required`` before B14.
"""
from __future__ import annotations

import re
from pathlib import Path

from _r5_auth_module_harness import observations

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
LOCALE_KEYS = ["auth-free-start", "auth-free-benefit", "guest-login-hint", "guest-login-hint-action"]


def read_static(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_the_note_sits_under_the_login_button_in_the_existing_dialog():
    markup = read_static("index.html")
    dialog = markup.split('id="authDialog"', 1)[1].split("</dialog>", 1)[0]
    assert 'id="authFreeNote"' in dialog
    google_end = dialog.index("</button>", dialog.index('id="googleLoginButton"'))
    note_start = dialog.index('id="authFreeNote"')
    divider = dialog.index('id="authDivider"')
    assert google_end < note_start < divider
    assert "로그인하면 바로 쓸 수 있어요." in dialog
    assert "대화 저장·복원도 함께 됩니다." in dialog


def test_both_locales_define_the_note():
    locale = read_static("locale.js")
    for key in LOCALE_KEYS:
        occurrences = re.findall(rf'"{re.escape(key)}":\s*"([^"]*)"', locale)
        assert len(occurrences) >= 2, f"{key} is missing from one of the locales"
        assert occurrences[0] != occurrences[1], f"{key} has the same copy in both locales"
        assert all(value.strip() for value in occurrences[:2])
    korean = locale.split("ko:", 1)[1]
    assert '"auth-free-start": "로그인하면 바로 쓸 수 있어요."' in korean


def test_the_note_uses_the_panel_typography_and_wraps():
    css = read_static("history.css")
    assert ".auth-free-note {" in css
    block = css.split(".auth-free-note {", 1)[1].split("}", 1)[0]
    assert "text-align: center" in block
    assert "line-height" in block
    # No fixed width, so the note wraps inside the 390px dialog instead of
    # overflowing it.
    assert "width:" not in block


def test_the_browser_gate_stops_every_guest_and_keeps_the_mock_flag():
    #7216 R5 step 4: this contract moved into chat-auth-module.js.
    # R2(#7186): the gate decision is observed by executing the module; only
    # the tier-independence boundary stays as text (a negative a single
    # execution cannot prove: any tier value must not change the decision).
    client = read_static("chat-auth-module.js")
    gate = client.split("function requireSessionForModelUse() {", 1)[1].split("return false;", 1)[0]
    assert 'selectedProductTier() === "free"' not in gate
    seen = observations()
    assert seen["gateBlocked"] is False
    assert seen["gateNote"] == ["model-requires-login", "error"]
    assert seen["gateClicked"] == 1
    # The mock flag (model_requires_session === false) lets the same guest in.
    assert seen["gateAllowed"] is True
    assert seen["gateSignedIn"] is True
    # An "unavailable" guest has no clickable entry, so the gate opens the
    # dialog instead — the dialog path is exercised, not merely grepped.
    assert seen["gateUnavailableBlocked"] is False
    assert seen["gateUnavailableDialog"] == 1


def test_the_first_screen_has_one_quiet_guest_login_invitation():
    markup = read_static("index.html")
    empty = markup.split('id="emptyState"', 1)[1].split("clawTaskHub", 1)[0]
    assert 'id="guestLoginHint"' in empty
    assert 'id="guestLoginEntryButton"' in empty
    assert 'data-locale-key="guest-login-hint"' in empty
    dialog = markup.split('id="authDialog"', 1)[1].split("</dialog>", 1)[0]
    assert 'id="guestLoginHint"' not in dialog
    css = read_static("history.css")
    assert ".empty-login-hint {" in css
    assert ".empty-login-hint[hidden]" in css


def test_the_chat_routes_refuse_a_guest_with_login_required():
    routes = (ROOT / "app" / "chat_routes.py").read_text(encoding="utf-8")
    assert 'code": "login_required"' in routes
    assert "anonymous_free" not in routes


def test_the_claw_ui_maps_login_required_to_the_login_guidance():
    client = read_static("app.js")
    assert "login_required: Object.freeze({" in client
    assert '"claw-login-required-note"' in client
    locale = read_static("locale.js")
    assert locale.count('"claw-login-required-note"') >= 2
