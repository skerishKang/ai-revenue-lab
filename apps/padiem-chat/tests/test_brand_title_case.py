from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
LOCALE = (ROOT / "static" / "locale.js").read_text(encoding="utf-8")


def test_visible_brand_reads_padiem_chat() -> None:
    assert "Padiem Chat" in HTML


def test_visible_brand_is_not_all_caps() -> None:
    brand_line = [line for line in HTML.splitlines() if 'class="brand"' in line and "Padiem Chat" in line][0]
    assert "PADIEM CHAT" not in brand_line


def test_logo_mark_remains_present() -> None:
    assert 'class="brand-mark"' in HTML
    assert 'aria-hidden="true">P</span>' in HTML


def test_settings_kicker_is_title_case() -> None:
    assert '"Padiem Chat"' in LOCALE
    assert '"PADIEM CHAT"' not in LOCALE


def test_no_unrelated_navigation_theme_changes() -> None:
    assert 'class="home-link" href="https://padiem.net/"' in HTML
    assert 'class="settings-button"' in HTML
    assert 'id="themePicker"' in HTML
    assert 'id="languagePicker"' in HTML
    assert 'id="loginButton"' in HTML
