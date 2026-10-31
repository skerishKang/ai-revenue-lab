"""#5474 Owner decision 2026-10-24: Free runs without a login, and the login
modal says what a login adds.

The product-visible contract pinned here:

* the note sits directly under the Google login button inside the existing auth
  dialog, so no new screen or forced signup is introduced;
* both locales carry the copy, and the Korean copy is the served default;
* the note keeps the panel typography and wraps inside the dialog width;
* the browser pre-gate lets a guest use Free on the Chat lane and still stops
  Claw and paid tiers before the request leaves the browser;
* the Chat routes no longer answer an anonymous Free request with 401.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
LOCALE_KEYS = ["auth-free-start", "auth-free-benefit"]


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
    assert "로그인 없이도 바로 시작하세요." in dialog
    assert "로그인하면 대화 저장·복원까지 편리하게." in dialog


def test_both_locales_define_the_note():
    locale = read_static("locale.js")
    for key in LOCALE_KEYS:
        occurrences = re.findall(rf'"{re.escape(key)}":\s*"([^"]*)"', locale)
        assert len(occurrences) >= 2, f"{key} is missing from one of the locales"
        assert occurrences[0] != occurrences[1], f"{key} has the same copy in both locales"
        assert all(value.strip() for value in occurrences[:2])
    korean = locale.split("ko:", 1)[1]
    assert '"auth-free-start": "로그인 없이도 바로 시작하세요."' in korean


def test_the_note_uses_the_panel_typography_and_wraps():
    css = read_static("history.css")
    assert ".auth-free-note {" in css
    block = css.split(".auth-free-note {", 1)[1].split("}", 1)[0]
    assert "text-align: center" in block
    assert "line-height" in block
    # No fixed width, so the note wraps inside the 390px dialog instead of
    # overflowing it.
    assert "width:" not in block


def test_the_browser_gate_keeps_free_for_guests_but_not_paid_or_claw():
    client = read_static("app.js")
    gate = client.split("function requireSessionForModelUse() {", 1)[1].split("return false;", 1)[0]
    assert 'selectedProductTier() === "free"' in gate
    assert "clawGeneralRequestActive()" in gate
    assert 'authState.model_requires_session !== true' in gate


def test_the_chat_routes_do_not_answer_anonymous_free_with_401():
    routes = (ROOT / "app" / "chat_routes.py").read_text(encoding="utf-8")
    assert "무료 AI를 사용하려면 로그인이 필요합니다." not in routes
    assert 'anonymous_free = uid is None and raw.get("tier") == "free"' in routes
