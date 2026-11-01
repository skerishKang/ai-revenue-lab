"""#6659 1: the Chat usage guide is a reachable page of recognised sentences.

Three things are pinned here, in this order of importance:

1. **Every example sentence is one the product recognises today.** The guide
   quotes a sentence only if the same text appears in the code or the test that
   acts on it, so the page cannot teach a phrase that does nothing, and a future
   edit that invents one fails.
2. **The page is a document, not a script.** No inline script, no network
   dependency, the same design tokens as the Chat screen, and it is reachable
   from the sidebar in both locales.
3. **The phone floor holds.** Nothing past the viewport, 44px press targets,
   14px text at 1440 and 390, and pressing an example lands the words in the
   composer - typed, unsent, and gone from the address bar.
"""

from __future__ import annotations

import http.server
import json
import re
from pathlib import Path
import threading
from urllib.parse import unquote

import pytest

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover
    sync_playwright = None

CHAT = Path(__file__).resolve().parents[1]
REPO = CHAT.parents[1]
STATIC = CHAT / "static"
HELP = (STATIC / "help.html").read_text(encoding="utf-8")
HELP_CSS = (STATIC / "help.css").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
LOCALE = (STATIC / "locale.js").read_text(encoding="utf-8")

TARGET_FLOOR = 44.0
TEXT_FLOOR = 14.0
WIDTHS = ((1440, 900), (390, 844))

# Each sentence the guide offers, with the file that recognises it today. The
# guide may only ever offer what is in here.
EVIDENCE = {
    "내 PC 파일 목록 보여줘": "apps/padiem-chat/tests/test_5121_byok_claw_b66_direct.py",
    "내 컴퓨터에서 xlsx 파일 검색해줘": "apps/padiem-chat/tests/test_6460_pc_search_dispatch.py",
    "내 PC의 sample 폴더 파일 목록 보여줘": "apps/padiem-chat/tests/test_5573_pc_context_entry.py",
    "그 폴더 목록만 보여줘": "apps/padiem-chat/tests/test_chat_pc_drive.py",
    "내 PC 파일을 읽어 줘": "apps/padiem-chat/tests/test_chat_pc_drive.py",
    "이 파일 저장해 줘": "apps/padiem-chat/tests/test_6044_chat_pc_write_scope.py",
    "내 PC 화면 보여줘": "apps/padiem-chat/tests/test_pc_screen_view_s1_261102.py",
    "지금 화면 캡처해 줘": "apps/padiem-chat/tests/test_pc_screen_view_s1_261102.py",
    "내 컴퓨터 화면 스크린샷 찍어줘": "apps/padiem-chat/tests/test_pc_screen_view_s1_261102.py",
    "PC 화면 봐줘": "apps/padiem-chat/tests/test_pc_screen_view_s1_261102.py",
    "example.com 열어서 제목 알려 줘": "apps/padiem-chat/tests/test_3782_browser_live_intent.py",
    "브라우저 페이지 캡처해 줘": "apps/padiem-chat/tests/test_3782_browser_live_intent.py",
    "이 사진을 설명해줘": "apps/padiem-chat/tests/test_attachments.py",
    "목적과 읽는 사람에 맞는 이메일이나 문장 초안을 작성해줘": "apps/padiem-chat/static/index.html",
    "광주에서 AI 교육 견적서를 만들어 주세요": "apps/padiem-chat/tests/browser_voice_turn_authority_4643.py",
}

# Sentences the guide quotes to tell the person what will NOT run. Same rule:
# the refusal has to be a real refusal in a real test.
REFUSAL_EVIDENCE = {
    "내 PC 화면 클릭해 줘": "apps/padiem-chat/tests/test_pc_screen_view_s1_261102.py",
    "내 PC 화면에서 입력해 줘": "apps/padiem-chat/tests/test_pc_screen_view_s1_261102.py",
    "내 PC notes/report.txt 읽어줘": "apps/padiem-chat/tests/test_3782_browser_live_intent.py",
}

SAY_HREF = 'href="./?say='
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
    // A skip link parked left of the window is off-screen by intent; overflow
    // is measured by the document scroll width below.
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

    def log_message(self, *args):  # silence the request line
        pass

    def do_GET(self):  # noqa: N802 - the composer tools are capability-gated
        # The Chat shell keeps the web tools hidden until /health answers, the
        # same way the mock runtime does. Everything else is the static screen.
        if self.path.split("?")[0] == "/health":
            body = json.dumps({
                "runtime": "mock", "live_enabled": False,
                "web_tools_ready": True, "deep_research_ready": True,
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


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


def _say_links():
    """(sentence, href value) for every example the guide offers."""
    found = []
    for chunk in HELP.split(SAY_HREF)[1:]:
        value = chunk.split('"', 1)[0]
        label = chunk.split('">', 1)[1].split("</a>", 1)[0]
        found.append((unquote(value), label))
    return found


def test_the_guide_offers_only_sentences_that_are_evidenced():
    offered = {sentence for sentence, _ in _say_links()}
    assert offered, "the guide must offer example sentences"
    unsupported = sorted(offered - set(EVIDENCE))
    assert not unsupported, "add the recognising file to EVIDENCE first: %s" % unsupported


def test_every_evidenced_sentence_really_sits_in_the_file_that_acts_on_it():
    stale = []
    for sentence, source in sorted(EVIDENCE.items()):
        text = (REPO / source).read_text(encoding="utf-8")
        if sentence not in text:
            stale.append("%s (expected in %s)" % (sentence, source))
    assert not stale, stale


def test_the_refusal_examples_are_refusals_too():
    offered = {sentence for sentence, _ in _say_links()}
    for sentence, source in sorted(REFUSAL_EVIDENCE.items()):
        assert sentence in (REPO / source).read_text(encoding="utf-8"), source
        # The guide names them to warn about what will not run, never to invite.
        assert sentence not in offered


def test_an_example_links_with_its_own_words():
    for sentence, label in _say_links():
        assert sentence == label, (sentence, label)


def test_the_page_carries_no_script_no_network_and_no_shout():
    assert "<script" not in HELP
    assert not re.search(r"https?://", HELP), "an external URL in the guide"
    assert "PADIEM" not in HELP
    assert 'lang="ko"' in HELP
    assert 'name="viewport" content="width=device-width, initial-scale=1"' in HELP
    assert 'name="robots" content="noindex"' in HELP
    # The canonical tokens, then the page's own layout: the same two files every
    # standalone page in this static tree links.
    assert '<link rel="stylesheet" href="./styles.css" />' in HELP
    assert '<link rel="stylesheet" href="./help.css" />' in HELP


def test_the_guide_holds_its_phone_floor_in_plain_css():
    # The browser check below measures it; this one keeps the rule written down
    # where an editor can see it before running anything.
    assert "min-height: 44px" in HELP_CSS
    declared = [float(size) for size in re.findall(
        r"font-size:\s*(\d+(?:\.\d+)?)px", HELP_CSS)]
    assert declared, "the guide sheet must size its own text"
    assert min(declared) >= TEXT_FLOOR, declared


def test_the_sidebar_link_is_locale_driven_in_both_languages():
    # The first-use sheet hides `.sidebar-footer` (the old home of the OSS link),
    # so the guide hangs off the visible workspace nav instead of a hidden footer.
    assert '<a class="side-item" id="helpNavLink" href="./help.html">' in INDEX
    assert '<span data-locale-key="nav-help">사용 안내</span>' in INDEX
    assert '"nav-help": "사용 안내"' in LOCALE
    assert '"nav-help": "How to use"' in LOCALE


def test_the_guide_renders_inside_the_viewport(browser_page, static_origin):
    page = browser_page
    for width, height in WIDTHS:
        page.set_viewport_size({"width": width, "height": height})
        page.goto(static_origin + "/help.html", wait_until="load")
        report = page.evaluate(MEASURE, {"floor": TARGET_FLOOR, "textFloor": TEXT_FLOOR})
        assert report["overflowPx"] == 0, (width, report["overflowPx"], report["wide"])
        assert report["wide"] == [], (width, report["wide"])
        assert report["taps"] == [], (width, report["taps"])
        assert report["fonts"] == [], (width, report["fonts"])
        assert "컴퓨터 연결하기" in report["headings"], width


def test_the_sidebar_link_opens_the_guide(browser_page, static_origin):
    page = browser_page
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(static_origin + "/index.html", wait_until="domcontentloaded")
    page.wait_for_function("() => document.getElementById('helpNavLink') !== null")
    link = page.locator("#helpNavLink")
    assert link.is_visible()
    box = link.bounding_box()
    assert box["height"] >= TARGET_FLOOR - 0.6, box
    link.click()
    page.wait_for_url(static_origin + "/help.html")
    assert page.locator("h1").inner_text().strip() == "이렇게 말해 보세요"


def test_pressing_an_example_fills_the_composer_and_leaves_the_address(
    browser_page, static_origin,
):
    page = browser_page
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(static_origin + "/help.html", wait_until="load")
    first = page.locator(".chat-help-say").first
    sentence = first.inner_text().strip()
    report = page.evaluate(MEASURE, {"floor": TARGET_FLOOR, "textFloor": TEXT_FLOOR})
    assert report["taps"] == [], report["taps"]
    first.click()
    page.wait_for_function(
        "() => (document.getElementById('messageInput') || {}).value !== ''", timeout=5000,
    )
    assert page.locator("#messageInput").input_value() == sentence
    assert "say=" not in page.url, page.url
    # Filled, not sent: no request leaves the screen for it.
    assert page.locator("#sendButton").is_visible()
