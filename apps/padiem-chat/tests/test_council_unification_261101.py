"""2026-11-01 unification + 2026-11-08 #7173 reversal of its Chat side.

The three 의원3종 tools keep ONE product surface, /apps/council/ — that app,
its store and its PC bridge stay exactly as shipped. What changed is Chat's
util entry: #6562 made the cards navigate to the council app, and the Owner's
2026-11-08 request (#7173) is that pressing a util card must not leave the app
or jump into a Claw conversation. Chat's util page therefore hosts its own
screens again, calling the same backend contracts (POST /api/chat/stream,
/api/projects files, /api/claw/manual-intake/preview) without a second store.

These tests pin the static shape. The executed behaviour — a screen opens, ←
유틸 returns, the document is never replaced — is browser-level in
browser_util_inapp_screens_7173.py.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
UTIL_MENU = STATIC / "util-menu.js"
INDEX_HTML = STATIC / "index.html"
UTIL_CSS = STATIC / "util-menu.css"
APP_JS = STATIC / "app.js"


def _util_section() -> str:
    html = INDEX_HTML.read_text(encoding="utf-8")
    return html[html.index('id="utilView"') : html.index('id="calendarView"')]


def test_the_util_page_hosts_each_tool_screen() -> None:
    section = _util_section()
    for panel in ("utilSpeechPanel", "utilSnsPanel", "utilMeetingPanel",
                  "utilQuotePanel", "utilPdfmdPanel"):
        assert f'id="{panel}"' in section, panel
    # The back control is part of the page, not a browser-history gesture.
    assert 'id="utilBack"' in section
    assert "← 유틸" in section


def test_the_cards_do_not_leave_the_app() -> None:
    js = UTIL_MENU.read_text(encoding="utf-8")
    # #7173: no link out, whether to the council app or anywhere else.
    assert "/apps/council" not in js
    assert "location.assign" not in js
    assert "location.href" not in js
    # The one switch that opens a tool screen.
    assert "function openUtilScreen(key)" in js


def test_the_screens_reuse_the_existing_backend_contracts() -> None:
    js = UTIL_MENU.read_text(encoding="utf-8")
    # The in-page tool code is the shipped util logic moved back into the page:
    # generation, storage and the quote preview keep their existing routes.
    assert '"/api/chat/stream"' in js
    assert '"/api/projects"' in js
    assert '"/api/claw/manual-intake/preview"' in js
    # The Claw conversation is reachable from exactly one place: the quote
    # result's secondary action.
    assert js.count("clawNavButton") == 1


def test_the_council_app_itself_is_untouched() -> None:
    council = (ROOT.parent / "padiem-council-apps" / "static" / "council-app.js").read_text(
        encoding="utf-8")
    assert 'COMPUTER_CONNECT_HREF = "/#padiem-connectors"' in council
    assert "/api/chat/stream" in council


def test_the_retired_councillor_screen_is_gone_and_the_alias_redirects() -> None:
    assert not (STATIC / "councillor").exists()
    assert not (STATIC / "councillor" / "brands" / "miraen.json").exists()
    factory = (ROOT / "app" / "app_factory.py").read_text(encoding="utf-8")
    assert 'COUNCILLOR_REDIRECT_PATH = "/councillor/"' in factory
    assert 'RedirectResponse("/apps/council/", status_code=302)' in factory
    assert 'Route(COUNCILLOR_REDIRECT_PATH, councillor_redirect, methods=["GET"])' in factory


def test_the_councillor_prototype_site_is_untouched() -> None:
    prototype = ROOT.parent.parent / "apps" / "councillor-prototype"
    assert (prototype / "static" / "miraen.json").is_file()
    assert (prototype / "static" / "app.js").is_file()


def test_the_council_connect_button_has_a_connectors_deep_link() -> None:
    app_js = APP_JS.read_text(encoding="utf-8")
    assert 'CONNECTORS_ROUTE_HASH = "#padiem-connectors"' in app_js
    assert "openConnectorsView()" in app_js.split("CONNECTORS_ROUTE_HASH", 1)[1]
    council = (ROOT.parent / "padiem-council-apps" / "static" / "council-app.js").read_text(encoding="utf-8")
    assert 'COMPUTER_CONNECT_HREF = "/#padiem-connectors"' in council


def test_the_util_css_keeps_the_legacy_panel_surface() -> None:
    css = UTIL_CSS.read_text(encoding="utf-8")
    for selector in ("#utilSpeechPanel", "#utilSnsPanel", "#utilMeetingPanel"):
        assert selector in css, selector
    assert ".util-panel {" in css
    assert ".util-back" in css
