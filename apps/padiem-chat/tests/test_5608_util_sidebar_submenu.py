"""#5608 / #7460: the sidebar Util entry expands into all six manifest tools.

#7460:
- The top #appSwitch (Chat | Claw | 유틸) is retired; navigation lives in the
  left sidebar menu.
- #utilSubmenu renders all six tools from static/util-manifest.js and routes
  every tool inside the Util app (#util/<id>), never leaving Chat.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "static/index.html"
UTIL_MANIFEST_JS = ROOT / "static/util-manifest.js"
UTIL_MENU_JS = ROOT / "static/util-menu.js"
UTIL_MENU_CSS = ROOT / "static/util-menu.css"

SUBMENU = [
    ("speech", "축사·인사말"),
    ("sns", "SNS 홍보"),
    ("meeting", "회의정리·활동집"),
    ("pdfmd", "PDF → Markdown"),
    ("quote", "견적서 초안"),
    ("excel", "Excel 열기/검토"),
]


def _html() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def test_sidebar_util_entry_is_a_disclosure_driven_by_the_manifest() -> None:
    html = _html()
    assert 'id="utilNavGroup"' in html
    assert 'aria-controls="utilSubmenu"' in html
    assert 'id="utilNavButton"' in html and 'aria-expanded="false"' in html
    assert 'class="side-chevron" aria-hidden="true">›<' in html
    assert 'id="utilSubmenu" hidden' in html
    manifest = UTIL_MANIFEST_JS.read_text(encoding="utf-8")
    for key, label in SUBMENU:
        assert f'id: "{key}"' in manifest, f"missing manifest tool: {key}"
        assert f'"{label}"' in manifest, f"missing manifest label: {label}"


def test_top_app_switch_and_legacy_in_page_tabs_are_retired() -> None:
    """#7460 1·2번: 상단 Chat | Claw | 유틸 탭(#appSwitch)은 제거되고, 이동은 왼쪽
    사이드바 메뉴 하나로 일원화된다."""
    html = _html()
    assert '<nav class="util-tabs"' not in html
    assert 'id="appSwitch"' not in html
    css = (ROOT / "static/util-app.css").read_text(encoding="utf-8")
    assert "#utilNavGroup { display: none; }" not in css
    assert ".app-switch" not in css


def test_util_menu_js_renders_submenu_from_manifest_and_routes_in_app() -> None:
    js = UTIL_MENU_JS.read_text(encoding="utf-8")
    assert "window.PadiemUtilManifest" in js
    assert "function renderSubmenu()" in js
    assert "markActiveUtilSubmenuItem" in js
    assert "setUtilSubmenuOpen" in js
    assert 'setAttribute("aria-expanded", open ? "true" : "false")' in js
    assert '"⌄"' in js and '"›"' in js
    assert "utilSubmenuItems.forEach" in js
    assert 'attributeFilter: ["aria-current"]' in js
    assert 'classList.contains("sidebar-open")' in js
    assert "/apps/council" not in js


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
