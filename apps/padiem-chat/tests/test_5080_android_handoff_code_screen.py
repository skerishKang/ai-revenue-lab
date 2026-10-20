"""#5080: the Android sign-in code screen in the login dialog.

The user read the eight character code in the login dialog and could not copy
it, and "Open Google sign-in again" repeated the code procedure. The dialog
therefore carries a copy button with a copied confirmation, and the
re-open button is only offered while the Google sign-in itself is pending.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_the_code_screen_has_a_copy_button_and_a_copied_notice() -> None:
    markup = _read("index.html")
    assert 'id="androidHandoffCopy"' in markup
    assert 'id="androidHandoffCopied"' in markup
    assert 'data-locale-key="auth-android-copy"' in markup
    assert 'data-locale-key="auth-android-copied"' in markup


def test_the_copy_button_copies_the_code_and_shows_the_notice() -> None:
    script = _read("app.js")
    assert 'const androidHandoffCopy = document.getElementById("androidHandoffCopy");' in script
    assert 'const androidHandoffCopied = document.getElementById("androidHandoffCopied");' in script
    assert "navigator.clipboard.writeText(code)" in script
    assert "androidHandoffCopied.hidden = false;" in script
    # A copy that the browser refused still selects the code by hand.
    assert "range.selectNodeContents(androidHandoffCode)" in script


def test_reopening_google_is_only_offered_while_the_login_is_pending() -> None:
    script = _read("app.js")
    assert 'const awaitingLogin = androidHandoff.phase === "waiting";' in script
    assert "androidHandoffOpen.hidden = busy || !awaitingLogin;" in script
    assert "androidHandoffOpen.disabled = busy || !awaitingLogin;" in script


def test_both_locales_carry_the_new_copy_strings() -> None:
    locale = _read("locale.js")
    assert locale.count('"auth-android-copy"') == 2
    assert locale.count('"auth-android-copied"') == 2
    assert "Copy sign-in code" in locale
    assert "Sign-in code copied." in locale
