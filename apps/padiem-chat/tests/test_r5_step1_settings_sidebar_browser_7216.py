"""#7216 R5 1단계 — 실제 Chromium에서 app.js 전달 함수 호출 계약.

app.js에서 추출한 9개 한 줄 전달 함수를 실제 Chromium 페이지에 주입하고, 모듈
파일(실제 소스)과 deps를 연결해 호출한다. 설정 dialog 열기/닫기, 사이드바 접기/
펴기, 모바일 오버레이, 아이콘 생성이 브라우저에서 그대로 동작하는지 확인한다.
문자열 존재 검사가 아니라 실행 검사다.
"""
from __future__ import annotations

import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")

FORWARDER_NAMES = (
    "selectedProductTier", "openSettings", "closeSettings",
    "openAdvancedSettingsView", "closeAdvancedSettingsView",
    "sidebarActionIcon", "setSidebarCollapsed", "closeSidebar", "openSidebar",
)

HARNESS = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>R5 forwarders</title></head>
<body>
<button id="settingsButton" type="button" aria-expanded="false">설정</button>
<button id="accountProfileButton" type="button" aria-expanded="false">프로필</button>
<dialog id="settingsDialog"><button id="settingsCloseButton" type="button">닫기</button></dialog>
<section id="advancedSettingsView" hidden></section>
<div class="app-shell" id="shell">
  <button id="sidebarCollapseButton" type="button" aria-expanded="true">접기</button>
  <button id="sidebarRestoreButton" type="button" aria-expanded="false">펴기</button>
  <button id="mobileMenu" type="button" aria-expanded="false">메뉴</button>
  <button id="mobileClose" type="button">닫기</button>
  <div id="sidebarScrim" hidden></div>
</div>
<script src="/static/chat-settings-module.js"></script>
<script src="/static/chat-sidebar-module.js"></script>
<script>
window.__events = [];
window.__deps = {
  settingsDialog: document.getElementById("settingsDialog"),
  settingsButton: document.getElementById("settingsButton"),
  profileToggle: document.getElementById("accountProfileButton"),
  advancedSettingsView: document.getElementById("advancedSettingsView"),
  advancedSettingsReturnState: null,
  shell: document.getElementById("shell"),
  setNavActive: () => { window.__events.push("nav"); },
  selectAdvancedMenu: (key) => { window.__events.push("menu:" + key); },
  sidebarCollapseButton: document.getElementById("sidebarCollapseButton"),
  sidebarRestoreButton: document.getElementById("sidebarRestoreButton"),
  mobileMenu: document.getElementById("mobileMenu"),
  mobileClose: document.getElementById("mobileClose"),
  sidebarScrim: document.getElementById("sidebarScrim"),
  closeProfilePanel: () => { window.__events.push("profile-close"); },
};
let __settings = null, __sidebar = null;
function settingsModule() {
  if (!__settings) __settings = window.PadiemChatSettingsModule.create(window.__deps);
  return __settings;
}
function sidebarModule() {
  if (!__sidebar) __sidebar = window.PadiemChatSidebarModule.create(window.__deps);
  return __sidebar;
}
__FORWARDERS__
</script>
</body></html>
"""


def _forwarder_lines() -> str:
    lines = []
    for name in FORWARDER_NAMES:
        marker = f"function {name}(...a) {{"
        line = next(line.strip() for line in APP.splitlines() if marker in line)
        lines.append(line)
    return "\n".join(lines)


class _StaticHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC.parent), **kwargs)

    def log_message(self, *args):  # keep the test output quiet
        pass


@pytest.fixture(scope="module")
def page_url():
    harness = Path(STATIC.parent) / "tests" / "_r5_forwarder_harness.html"
    harness.write_text(HARNESS.replace("__FORWARDERS__", _forwarder_lines()),
                       encoding="utf-8", newline="\n")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StaticHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/tests/_r5_forwarder_harness.html"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        harness.unlink(missing_ok=True)


def test_settings_forwarders_run_in_chromium(page_url) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(page_url)
        page.evaluate("openSettings()")
        assert page.evaluate("document.getElementById('settingsDialog').open") is True
        assert page.get_attribute("#settingsButton", "aria-expanded") == "true"
        assert page.get_attribute("#accountProfileButton", "aria-expanded") == "true"
        page.evaluate("closeSettings()")
        assert page.evaluate("document.getElementById('settingsDialog').open") is False
        assert page.get_attribute("#settingsButton", "aria-expanded") == "false"

        page.evaluate("window.__deps.shell.dataset.state = 'claw'; openAdvancedSettingsView()")
        assert page.evaluate("document.getElementById('advancedSettingsView').hidden") is False
        assert page.get_attribute("#shell", "data-state") == "settings"
        assert page.evaluate("window.__events") == ["nav", "menu:pc"]
        page.evaluate("closeAdvancedSettingsView()")
        assert page.get_attribute("#shell", "data-state") == "claw"

        # The tier value is read through the forwarding function on every call.
        page.evaluate("window.PadiemTierSelection = { get: () => 'plus' }")
        assert page.evaluate("selectedProductTier()") == "plus"
        page.evaluate("window.PadiemTierSelection = { get: () => 'nope' }")
        assert page.evaluate("selectedProductTier()") == "free"
        browser.close()


def test_sidebar_forwarders_run_in_chromium(page_url) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(page_url)
        page.evaluate("setSidebarCollapsed(true)")
        assert page.evaluate("document.getElementById('shell').classList.contains('sidebar-collapsed')") is True
        assert page.get_attribute("#sidebarRestoreButton", "aria-expanded") == "false"
        page.evaluate("setSidebarCollapsed(false)")
        assert page.evaluate("document.getElementById('shell').classList.contains('sidebar-collapsed')") is False

        page.evaluate("openSidebar()")
        assert page.evaluate("document.getElementById('shell').classList.contains('sidebar-open')") is True
        assert page.get_attribute("#mobileMenu", "aria-expanded") == "true"
        assert page.evaluate("document.getElementById('sidebarScrim').hidden") is False
        page.evaluate("closeSidebar()")
        assert page.evaluate("document.getElementById('shell').classList.contains('sidebar-open')") is False
        assert page.evaluate("window.__events.includes('profile-close')") is True

        icon = page.evaluate("(() => { const svg = sidebarActionIcon('settings');"
                             " return { tag: svg.tagName, aria: svg.getAttribute('aria-hidden'),"
                             " nodes: svg.querySelectorAll('path,circle').length }; })()")
        assert icon == {"tag": "svg", "aria": "true", "nodes": 2}
        browser.close()


def test_sidebar_collapse_is_inert_on_mobile_width(page_url) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(page_url)
        page.evaluate("setSidebarCollapsed(true)")
        assert page.evaluate("document.getElementById('shell').classList.contains('sidebar-collapsed')") is False
        browser.close()
