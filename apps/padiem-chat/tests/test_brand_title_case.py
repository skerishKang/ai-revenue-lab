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


# Owner decision 2026-10-18: every visible brand string in the web app reads
# "Padiem ..." with only the P capital, and no stylesheet may force it back to
# caps. Machine tokens (PADIEM_* env names, PADIEM_4139_STAGE logs) and code
# comments are deliberately out of scope.
BRAND_BEARING = ("eyebrow", "-kicker", "model-pill", "brand")


def _visible_lines(path):
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(("//", "/*", "*", "<!--", "#")) or "PADIEM_" in line:
            continue
        yield line


def test_no_visible_all_caps_brand_string_left_in_the_ui():
    root = ROOT / "static"
    offenders = []
    for path in sorted(root.glob("*.html")) + sorted(root.glob("*.js")):
        for line in _visible_lines(path):
            if "PADIEM" in line:
                offenders.append(f"{path.name}: {line.strip()[:70]}")
    assert not offenders, offenders


def test_the_server_side_tier_label_is_title_case_too():
    routes = (ROOT / "app" / "b66_quote_routes.py").read_text(encoding="utf-8")
    assert '"name": "Padiem " + grade.capitalize()' in routes
    page = (ROOT / "app" / "connector_owner_setup_page.py").read_text(encoding="utf-8")
    assert "PADIEM CLAW" not in page
    assert "Padiem Claw" in page


def test_no_brand_rule_forces_uppercase():
    offenders = []
    for path in sorted((ROOT / "static").glob("*.css")):
        text = path.read_text(encoding="utf-8")
        for block in text.split("}"):
            if "text-transform: uppercase" in block or "text-transform:uppercase" in block:
                selector = block.split("{")[0].strip().splitlines()[-1] if "{" in block else ""
                if any(token in selector for token in BRAND_BEARING):
                    offenders.append(f"{path.name}: {selector[:60]}")
    assert not offenders, offenders
