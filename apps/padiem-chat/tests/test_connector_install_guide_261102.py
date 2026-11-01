"""#6659 2: the PC connect program install guide is real, reachable and readable.

What this pins, in order of importance:

1. **Every step is one the code performs.** File name, install folder, service
   name, warning wording, backup folder, uninstall commands and tray items are
   each checked against the file that implements them, so the page cannot
   describe a step that does not exist or a tray item that was never built.
2. **The page is a document.** No script, no network dependency, the same
   design tokens as the Chat screen, reachable from the usage guide and back.
3. **The phone floor holds.** Nothing past the viewport, 44px press targets and
   14px text at 1440 and 390.
"""

from __future__ import annotations

import http.server
import re
import threading
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover
    sync_playwright = None

CHAT = Path(__file__).resolve().parents[1]
REPO = CHAT.parents[1]
STATIC = CHAT / "static"
HELP = (STATIC / "help.html").read_text(encoding="utf-8")
INSTALL = (STATIC / "install.html").read_text(encoding="utf-8")
INSTALL_CSS = (STATIC / "help.css").read_text(encoding="utf-8")

TARGET_FLOOR = 44.0
TEXT_FLOOR = 14.0
WIDTHS = ((1440, 900), (390, 844))

#: What the page says, and the source that makes it true. The string is looked
#: up in the source file; a rewrite of the source that removes the behaviour
#: also fails here.
GROUNDED = {
    "padiem-pc-connect.exe": "apps/padiem-chat/static/pc-pairing-card.js",
    "이 PC 연결하기": "apps/padiem-chat/static/pc-pairing-card.js",
    "알 수 없는 게시자": "apps/padiem-chat/static/pc-pairing-card.js",
    "추가 정보": "apps/padiem-chat/static/pc-pairing-card.js",
    "설치 파일로 받기 (.ps1)": "apps/padiem-chat/static/pc-pairing-card.js",
    "PADIEM PC 연결": "scripts/pc_pairing/connect-exe/PadiemPcConnect.cs",
    "Mesh Agent": "scripts/pc_pairing/connect-exe/PadiemPcConnect.cs",
    "%ProgramFiles%\\PADIEM\\MeshAgent.exe": "docs/operations/PC_CONNECT_EXE_20261028.md",
    "-uninstall": "docs/operations/PC_CONNECT_EXE_20261028.md",
    "Win32_Service": "docs/operations/PC_CONNECT_EXE_20261028.md",
    ".padiem-backup": "apps/padiem-chat/app/oracle_mesh_read_return_routes.py",
    "로그 폴더 열기": "apps/claw-connect/claw_connect/menu_model.py",
    "다시 연결": "apps/claw-connect/claw_connect/menu_model.py",
    "일시중지": "apps/claw-connect/claw_connect/menu_model.py",
    "-Uninstall": "apps/claw-connect/install.ps1",
}

#: Behaviour the page states in its own words, anchored to the source that
#: implements it. The anchor is English because the source is.
BEHAVIOUR = {
    "자동 시작": (
        "by default once the install succeeded",
        "apps/claw-connect/claw_connect/autostart.py",
    ),
}

MEASURE = """(cfg) => {
  const round = (n) => Math.round(n * 10) / 10;
  const vw = window.innerWidth;
  const label = (el) => el.id ? '#' + el.id
    : el.tagName.toLowerCase() + (typeof el.className === 'string' && el.className.trim()
      ? '.' + el.className.trim().split('\\s+').slice(0, 2).join('.') : '');
  const text = (el) => (el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 44);
  const taps = [], fonts = [], wide = [];
  const interactive = 'a[href], button, input:not([type=hidden]), select, textarea, summary,'
    + ' [role="button"], [role="tab"], [role="menuitem"]';
  document.querySelectorAll('body *').forEach((el) => {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return;
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || el.closest('[hidden]')) return;
    if (r.right > 0 && (r.right > vw + 1 || r.left < -1)) {
      wide.push({ el: label(el), text: text(el), right: round(r.right), left: round(r.left) });
    }
    if (el.matches(interactive)
        && (round(r.width) < cfg.floor || round(r.height) < cfg.floor)) {
      taps.push({ el: label(el), text: text(el), w: round(r.width), h: round(r.height) });
    }
    let own = false;
    for (const node of el.childNodes) { if (node.nodeType === 3 && node.textContent.trim()) { own = true; break; } }
    if (!own) return;
    const size = parseFloat(s.fontSize);
    if (size > 0 && size < cfg.textFloor) fonts.push({ el: label(el), size: round(size), text: text(el) });
  });
  return {
    vw, scrollWidth: document.documentElement.scrollWidth,
    overflowPx: round(document.documentElement.scrollWidth - vw),
    wide, taps, fonts,
    headings: Array.from(document.querySelectorAll('h2')).map((el) => el.textContent.trim()),
  };
}
"""


class StaticHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def static_origin():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StaticHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % server.server_port
    server.shutdown()
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def browser_page():
    if sync_playwright is None:
        pytest.skip("playwright is not installed in this environment")
    with sync_playwright() as driver:
        browser = driver.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page()
        yield page
        browser.close()


# ── the facts are the code's facts ──────────────────────────────────────────


def test_every_claimed_step_exists_in_the_code_that_does_it():
    stale = []
    for claim, source in sorted(GROUNDED.items()):
        path = REPO / source
        if claim not in path.read_text(encoding="utf-8"):
            stale.append("%s (not in %s)" % (claim, source))
    assert not stale, stale
    # And the page really says each of them; a claim that quietly left the page
    # would otherwise pass simply because the code still has it.
    absent = [claim for claim in GROUNDED if claim not in INSTALL]
    assert not absent, absent
    for wording, (anchor, source) in sorted(BEHAVIOUR.items()):
        assert wording in INSTALL, wording
        assert anchor in (REPO / source).read_text(encoding="utf-8"), source


def test_the_page_names_only_the_controls_that_exist():
    # The tray's own order: status, web, state, logs, login, pause, reconnect,
    # autostart, disconnect, quit. It has no uninstall item, and the page says so.
    assert "제거</strong> 항목이 없습니다" in INSTALL
    assert "트레이에는" in INSTALL
    assert "연결 해제" in INSTALL
    # The web card's own actions, from the card copy.
    for action in ("이름 바꾸기", "잠시 멈춤", "연결 끊기"):
        assert action in INSTALL, action


def test_the_page_carries_no_script_no_network_and_the_same_sheets():
    assert "<script" not in INSTALL
    assert not re.search(r"https?://", INSTALL), "an external URL in the install guide"
    assert 'lang="ko"' in INSTALL
    assert 'name="viewport" content="width=device-width, initial-scale=1"' in INSTALL
    assert 'name="robots" content="noindex"' in INSTALL
    assert '<link rel="stylesheet" href="./styles.css" />' in INSTALL
    assert '<link rel="stylesheet" href="./help.css" />' in INSTALL
    assert "PADIEM" in INSTALL


def test_the_guide_is_reachable_from_the_usage_guide_and_returns():
    assert 'href="./install.html"' in HELP
    assert "컴퓨터 연결 설치 안내" in HELP
    assert 'href="./help.html"' in INSTALL
    # The usage guide itself is still free of product-name copy (#6659 1 rule).
    assert "PADIEM" not in HELP


def test_the_install_sheet_keeps_its_text_floor():
    declared = [float(size) for size in re.findall(
        r"font-size:\s*(\d+(?:\.\d+)?)px", INSTALL_CSS)]
    assert declared and min(declared) >= TEXT_FLOOR, declared
    assert "min-height: 44px" in INSTALL_CSS


# ── measured phone floor ────────────────────────────────────────────────────


def test_the_install_guide_renders_inside_the_viewport(browser_page, static_origin):
    page = browser_page
    for width, height in WIDTHS:
        page.set_viewport_size({"width": width, "height": height})
        page.goto(static_origin + "/install.html", wait_until="load")
        report = page.evaluate(MEASURE, {"floor": TARGET_FLOOR, "textFloor": TEXT_FLOOR})
        assert report["overflowPx"] == 0, (width, report["overflowPx"], report["wide"])
        assert report["wide"] == [], (width, report["wide"])
        assert report["taps"] == [], (width, report["taps"])
        assert report["fonts"] == [], (width, report["fonts"])
        for heading in ("설치 순서", "PC에 남는 것", "자주 막히는 곳", "제거"):
            assert heading in report["headings"], (width, heading)


def test_the_usage_guide_link_opens_the_install_guide(browser_page, static_origin):
    page = browser_page
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(static_origin + "/help.html", wait_until="load")
    link = page.locator("a.chat-help-install-link")
    assert link.is_visible()
    box = link.bounding_box()
    assert box["height"] >= TARGET_FLOOR - 0.6, box
    link.click()
    page.wait_for_url(static_origin + "/install.html")
    assert page.locator("h1").inner_text().strip() == "컴퓨터 연결 프로그램 설치 안내"


def test_the_install_guide_links_back_where_a_step_needs_it(browser_page, static_origin):
    page = browser_page
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(static_origin + "/install.html", wait_until="load")
    back = page.locator("header .chat-help-back")
    assert back.get_attribute("href") == "./help.html"
    remove = page.locator('a[href="#installRemove"]').first
    remove.click()
    assert page.url.endswith("#installRemove")
