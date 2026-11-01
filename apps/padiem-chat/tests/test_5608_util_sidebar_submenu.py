"""#5608 follow-up: the sidebar Util entry expands into its four rows.

2026-11-01: the three 의원3종 rows leave for /apps/council/ with the tool in
the fragment; only PDF → Markdown stays inside Chat. The disclosure, its
keyboard/touch styling and the one-active-row highlight are unchanged.
The executed link behaviour lives in test_council_unification_261101.py.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "static/index.html"
UTIL_MENU_JS = ROOT / "static/util-menu.js"
UTIL_MENU_CSS = ROOT / "static/util-menu.css"

SUBMENU = [
    ("speech", "축사·인사말"),
    ("sns", "SNS 홍보"),
    ("meeting", "회의정리·활동집"),
    ("pdfmd", "PDF → Markdown"),
]


def _html() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def test_sidebar_util_entry_is_a_disclosure_with_four_tools() -> None:
    html = _html()
    assert 'id="utilNavGroup"' in html
    assert 'aria-controls="utilSubmenu"' in html
    assert 'id="utilNavButton"' in html and 'aria-expanded="false"' in html
    assert 'class="side-chevron" aria-hidden="true">›<' in html
    assert 'id="utilSubmenu" hidden' in html
    section = html[html.index('id="utilSubmenu"') : html.index("</nav>", html.index('id="utilSubmenu"'))]
    for key, label in SUBMENU:
        assert f'data-util="{key}"' in section, f"missing submenu tool: {key}"
        assert f">{label}</button>" in section, f"missing submenu label: {label}"


def test_duplicate_in_page_tabs_are_hidden_not_deleted() -> None:
    html = _html()
    assert '<nav class="util-tabs" hidden' in html
    # The rows stay in the DOM; the council ones navigate, pdfmd switches panels.
    for key, _label in SUBMENU:
        assert f'data-util="{key}"' in html


def test_util_menu_js_routes_the_submenu_through_one_switch() -> None:
    js = UTIL_MENU_JS.read_text(encoding="utf-8")
    assert "function activateUtilTab(tab)" in js
    assert "markActiveUtilSubmenuItem" in js
    assert "setUtilSubmenuOpen" in js
    assert 'setAttribute("aria-expanded", open ? "true" : "false")' in js
    assert '"⌄"' in js and '"›"' in js
    assert 'utilSubmenu.querySelectorAll(".util-submenu-item")' in js
    assert 'utilSubmenuItems.forEach' in js
    # Leaving the util view must not leave a stale highlight on a submenu row.
    assert 'attributeFilter: ["aria-current"]' in js
    # Entering a tool from the drawer must close the drawer.
    assert 'classList.contains("sidebar-open")' in js


def test_util_menu_css_hides_duplicate_tabs_and_styles_submenu() -> None:
    css = UTIL_MENU_CSS.read_text(encoding="utf-8")
    assert ".util-tabs[hidden] { display: none; }" in css
    assert ".util-submenu[hidden] { display: none; }" in css
    assert ".util-submenu-item" in css
    assert ".util-submenu-item:focus-visible" in css
    assert ".util-submenu-item.active" in css
    assert 'html[data-theme="padiem-glass"] .util-submenu-item' in css


def test_util_parent_shows_the_active_treatment_while_a_tool_is_open() -> None:
    css = UTIL_MENU_CSS.read_text(encoding="utf-8")
    rule = css[css.index('#utilNavButton[aria-current="page"]') :]
    assert "var(--accent-soft" in rule[:200]
    assert "inset 3px 0 0 var(--accent" in rule[:200]
