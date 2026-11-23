"""#6460 — PDF→Markdown borrows the shared "bring from / save to my PC" parts.

The council app's PC import (#6620) and PC save (#6607) live in the one shared
dialog (``static/pc-file-exchange.js``), and the quote screen already reuses
them (#6613). This file pins the same reuse for the PDF→MD utility:

* the pick is a text link under the upload field (#7865), same 44px / 14px floor;
* an unlinked computer gets the council app's own sentence and connect action,
  never a dialog that can only fail inside;
* a picked file travels the existing conversion upload, and the finished
  Markdown is offered back through the same save half of the dialog.

The browser half runs only where Playwright is installed; the static half runs
everywhere and is what CI always checks.
"""

from __future__ import annotations

import http.server
import json
import re
import threading
from pathlib import Path

import pytest
from _support.pdfmd_source_261102 import (
    council_app_js, document_convert_routes, index_html, local_cpython,
    pc_file_exchange_js, util_app_js, util_manifest_js, util_menu_css, util_pdfmd_js,
)

from css_rules import declaration, find_rules_with_selector, parse_rules

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover - CI without a browser
    sync_playwright = None

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
PDFMD_JS = util_pdfmd_js()
EXCHANGE_JS = pc_file_exchange_js()
UTIL_MENU_CSS = util_menu_css()
COUNCIL_JS = council_app_js()

TARGET_FLOOR = 44.0
TEXT_FLOOR = 14.0
VIEWPORTS = ((1440, 900), (820, 1180), (390, 844))


# ── static contracts (always run) ───────────────────────────────────────────


def test_the_guidance_is_the_council_apps_own_sentence_and_action() -> None:
    """One sentence naming the computer, one action — copied, not paraphrased."""
    council_save = re.search(r'saveNoPc: "([^"]+)"', COUNCIL_JS)
    council_connect = re.search(r'connect: "([^"]+)"', COUNCIL_JS)
    assert council_save and council_connect
    assert council_save.group(1) in PDFMD_JS
    assert council_connect.group(1) in PDFMD_JS
    # The import sentence keeps the same opening the council app uses.
    assert '"컴퓨터를 연결하면 내 PC의 PDF를 가져올 수 있습니다."' in PDFMD_JS


def test_both_actions_check_the_computer_before_opening_the_shared_dialog() -> None:
    # #7865: the pick is the text link under the upload box; the save lives in
    # the result card's ··· menu. Both still check the computer first.
    pick = PDFMD_JS.index('pcPick.addEventListener("click"')
    save = PDFMD_JS.index('pcSaveBtn.addEventListener("click"')
    first_open = PDFMD_JS.index('component.open({\n        mode: "import"')
    save_open = PDFMD_JS.index('component.open({\n          mode: "save"')
    assert "await pcLinked() !== true" in PDFMD_JS[pick:first_open], "pick opens before it knows"
    assert "await pcLinked() !== true" in PDFMD_JS[save:save_open], "save opens before it knows"


def test_the_pick_is_a_text_link_under_the_upload_field() -> None:
    """#7865: the second way in is a quiet text link below the one upload box.

    The old beside-the-field button contract moved with the layout: the link
    keeps the 44px floor but reads as text, so the upload box stays the only
    primary thing in the column.
    """
    assert "formWrap.appendChild(drop);" in PDFMD_JS
    assert 'const pcLinkRow = el("div", "pdfmd-upload-foot");' in PDFMD_JS
    assert "pcLinkRow.appendChild(pcPick);" in PDFMD_JS
    # §1: 셀렉터 계약은 css_rules 헬퍼로 — 결합 셀렉터(.pdfmd-zipbar 와 나란히)도 허용.
    foot = [r for r in find_rules_with_selector(parse_rules(UTIL_MENU_CSS), ".pdfmd-upload-foot")
            if declaration(r, "display") == "flex"]
    assert foot, ".pdfmd-upload-foot 의 flex 규칙이 없다"
    # The link reads as text, not as the bordered pill the action buttons use.
    css = parse_rules(UTIL_MENU_CSS)
    pick = find_rules_with_selector(css, ".pdfmd-pc-pick")[0]
    assert declaration(pick, "border") == "0"
    assert declaration(pick, "text-decoration") == "underline"
    assert int(declaration(pick, "min-height").replace("px", "")) >= 44


def test_the_new_controls_share_the_44px_and_14px_floor() -> None:
    btn = re.search(r"\.pdfmd-btn \{([^}]*)\}", UTIL_MENU_CSS, re.S)
    link = re.search(r"\.pdfmd-link \{([^}]*)\}", UTIL_MENU_CSS, re.S)
    assert btn and "min-height: 44px" in btn.group(1) and "font-size: 14px" in btn.group(1)
    assert link and "min-height: 44px" in link.group(1) and "font-size: 14px" in link.group(1)


def test_no_second_upload_or_server_route_is_introduced() -> None:
    # The shared dialog and the existing conversion API are the only doors.
    assert 'script.src = "./pc-file-exchange.js"' in PDFMD_JS
    assert 'mode: "import"' in PDFMD_JS and 'mode: "save"' in PDFMD_JS
    paths = set(re.findall(r'"(/api/[a-z0-9/_.-]+)', PDFMD_JS))
    assert paths == {
        "/api/pc/pairings",
        "/api/pc/file",
        "/api/document-conversions",
        "/api/document-conversions/",
        "/api/document-conversions/items/",
    }, paths
    assert "/files/tus" not in PDFMD_JS and "tus-upload" not in PDFMD_JS,         "the conversion lane's own upload stays the route"


# ── browser half ────────────────────────────────────────────────────────────

MEASURE = """() => {
  const round = (n) => Math.round(n * 10) / 10;
  const box = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return { w: round(r.width), h: round(r.height), font: round(parseFloat(s.fontSize)) };
  };
  const panel = document.querySelector(".pdfmd-shell");
  const note = document.getElementById("pdfmdPcNote");
  return {
    pick: box(document.getElementById("pdfmdPcPick")),
    connect: note && !note.hidden ? box(note.querySelector(".pdfmd-link")) : null,
    save: box(document.querySelector(".pdfmd-item-actions .pdfmd-btn")),
    panelOverflow: panel ? round(panel.scrollWidth - panel.clientWidth) : null,
    pageOverflow: round(document.documentElement.scrollWidth - window.innerWidth),
  };
}"""


class ChatMock(http.server.SimpleHTTPRequestHandler):
    """Chat's static screen with the four reads this flow makes."""

    linked = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *args):
        pass

    def _json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, body, content_type="application/octet-stream"):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/api/auth/status":
            self._json({"ready": True, "authenticated": True,
                        "user": {"id": "usr_qa", "name": "의원"}})
            return
        if path == "/api/pc/pairings":
            links = [{"link_id": "pclink_qa", "state": "active", "label": "테스트 PC"}] if self.linked else []
            self._json({"ok": True, "links": links})
            return
        if path == "/api/document-conversions":
            self._json({"new_work_enabled": True, "jobs": []})
            return
        if path == "/api/document-conversions/job_qa":
            self._json({"items": [{
                "id": "item_qa", "name": "원본.pdf", "status": "done",
                "has_markdown": True, "page_count": 1, "character_count": 12,
            }]})
            return
        if path == "/api/document-conversions/items/item_qa/markdown":
            self._bytes("# 제목\n\n변환된 본문입니다.\n".encode("utf-8"), "text/markdown; charset=utf-8")
            return
        if path == "/api/document-conversions/items/item_qa/original":
            self._bytes(b"%PDF-1.4 conversion-qa")
            return
        if path == "/api/pc/file":
            self._bytes(b"%PDF-1.4 pc-import-qa")
            return
        if path.startswith("/api/"):
            self._json({})
            return
        super().do_GET()

    def do_POST(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/api/document-conversions":
            self._json({"job": {"id": "job_qa"}})
            return
        if path == "/api/document-conversions/job_qa/files":
            self._json({"rejected": []})
            return
        self._json({"ok": True})


@pytest.fixture(scope="module")
def chat_url():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ChatMock)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d/index.html" % server.server_port
    server.shutdown()
    thread.join(timeout=5)


def _open_pdfmd(page, url):
    page.goto(url, wait_until="domcontentloaded")
    # #7365: Util moved from the top app switch to the shared sidebar.
    if page.locator("#mobileMenu").is_visible() and page.evaluate(
            "() => !document.querySelector('.app-shell').classList.contains('sidebar-open')"):
        page.locator("#mobileMenu").click()
    page.locator("#utilNavButton").click()
    if page.locator("#mobileClose").is_visible() and page.evaluate(
            "() => document.querySelector('.app-shell').classList.contains('sidebar-open')"):
        page.locator("#mobileClose").click()
    page.wait_for_selector('.util-card[data-util-route="#util/pdfmd"]', state="visible")
    page.locator('.util-card[data-util-route="#util/pdfmd"]').click()
    page.wait_for_selector("#pdfmdPcPick", state="visible")
    page.wait_for_timeout(400)


@pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")
@pytest.mark.parametrize("width,height", VIEWPORTS)
def test_the_pc_controls_keep_the_floor_and_fit_the_width(chat_url, width, height):
    ChatMock.linked = True
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        try:
            _open_pdfmd(page, chat_url)
            # Upload first so the result row (and its save action) is measured.
            page.set_input_files('input[type="file"][accept*="pdf"]',
                                 {"name": "원본.pdf", "mimeType": "application/pdf",
                                  "buffer": b"%PDF-1.4 browser-qa"})
            page.wait_for_selector(".pdfmd-item-actions .pdfmd-btn")
            page.wait_for_timeout(300)
            value = page.evaluate(MEASURE)
        finally:
            browser.close()
    for name in ("pick", "save"):
        control = value[name]
        assert control, "%s missing at %s" % (name, width)
        assert control["h"] >= TARGET_FLOOR and control["w"] >= TARGET_FLOOR, (name, control)
        assert control["font"] >= TEXT_FLOOR, (name, control)
    assert value["panelOverflow"] <= 0, value
    assert value["pageOverflow"] <= 0, value


@pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")
def test_an_unlinked_computer_gets_the_guidance_not_a_dialog(chat_url):
    ChatMock.linked = False
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 390, "height": 844})
            try:
                _open_pdfmd(page, chat_url)
                page.evaluate("() => document.getElementById('pdfmdPcPick').click()")
                page.wait_for_selector("#pdfmdPcNote:not([hidden])", timeout=5000)
                note = page.locator("#pdfmdPcNote").inner_text()
                assert "컴퓨터를 연결하면" in note, note
                link = page.locator("#pdfmdPcNote .pdfmd-link")
                assert link.inner_text().strip() == "컴퓨터 연결하기"
                value = page.evaluate(MEASURE)
                assert value["connect"]["h"] >= TARGET_FLOOR and value["connect"]["font"] >= TEXT_FLOOR, value
                shared = page.locator('[role="dialog"][aria-label="내 PC에서 가져오기"]')
                assert shared.count() == 0, "a dialog opened without a computer"
            finally:
                browser.close()
    finally:
        ChatMock.linked = True


@pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")
def test_import_convert_and_save_use_the_shared_parts(chat_url):
    ChatMock.linked = True
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            _open_pdfmd(page, chat_url)
            # Import half of the one shared dialog.
            page.evaluate("() => document.getElementById('pdfmdPcPick').click()")
            dialog = page.locator('[role="dialog"][aria-label="내 PC에서 가져오기"]')
            dialog.wait_for(timeout=5000)
            page.evaluate("() => window.PadiemPcFileExchange.close()")
            page.wait_for_timeout(250)
            # The existing conversion upload is still the only path in.
            page.set_input_files('input[type="file"][accept*="pdf"]',
                                 {"name": "원본.pdf", "mimeType": "application/pdf",
                                  "buffer": b"%PDF-1.4 browser-qa"})
            # #7865: 내 PC에 저장 lives in the card's ··· menu.
            more = page.locator(".pdfmd-item-actions .pdfmd-more > summary")
            more.wait_for(timeout=5000)
            more.click()
            save = page.locator(".pdfmd-more-menu .pdfmd-menu-item", has_text="내 PC에 저장")
            save.wait_for(timeout=5000)
            # Save half, named after the original with the new extension.
            save.click()
            save_dialog = page.locator('[role="dialog"][aria-label="내 PC에 저장"]')
            save_dialog.wait_for(timeout=5000)
            name_input = page.locator('[role="dialog"] input.pc-exchange-filename')
            assert name_input.input_value() == "원본.md", name_input.input_value()
        finally:
            browser.close()
