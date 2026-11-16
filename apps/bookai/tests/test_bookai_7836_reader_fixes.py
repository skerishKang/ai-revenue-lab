"""#7836: Korean first visit, zero English flash, one-time guest cloud notice."""

from __future__ import annotations

import http.server
import os
import threading
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover
    sync_playwright = None

pytestmark = pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")

PUBLIC = Path(__file__).resolve().parents[1] / "public"
CHROME_CANDIDATES = [os.environ.get("B61_CHROME_PATH"), r"C:\Program Files\Google\Chrome\Application\chrome.exe"]
CHROME = next((c for c in CHROME_CANDIDATES if c and Path(c).is_file()), None)


class StaticHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def log_message(self, *_args):
        pass


@pytest.fixture
def base_url():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StaticHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/index.html?view=reader"
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


def _open_reader(page, base_url):
    page.goto(base_url, wait_until="load")
    page.wait_for_function("() => window.__smReaderSettingsV1 && typeof window.__smReaderSettingsV1.get === 'function'")
    page.wait_for_selector("#readerPageBody")


FIXTURE = """() => {
  const passages = [1,2].map(n => ({
    id: 'fixture-gen-1-'+n, canonicalLocator: 'bible:web:GEN:1:'+n,
    sequence: n, language: 'ko', text: ('한글 절 '+n+' ').repeat(80),
    sourceText: ('English verse '+n+' ').repeat(80), locator: {verse:n}, sourceRef: null
  }));
  const bundle = {mode:'static', content:{kind:'bible'}, work:{work_key:'bible-web'}, passages};
  const built = storyMemoryBuildDynamicReaderPages(bundle, {targetChars:80, pageMaxPassages:1});
  READER_PAGES = built.pages;
  window.__pages = built.pages;
  readerPageIndex = 0;
  __smDynamicReaderState = {generation:1, mode:'static', content:bundle.content,
    work:bundle.work, unitOrdinal:1, passages:built.passages,
    pagePassages:built.groups, pageSourceRefs:built.pageSourceRefs, remoteError:null};
  document.getElementById('readerPageBody').innerHTML = built.pages[0];
  return built.pages.length;
}"""


def test_first_korean_visit_defaults_to_korean_only(base_url):
    if CHROME and not Path(CHROME).is_file():
        pytest.skip("Chrome unavailable")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=CHROME) if CHROME else pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        _open_reader(page, base_url)
        assert page.evaluate("window.__smReaderSettingsV1.get().englishMode") == "hide"
        assert page.evaluate("document.body.classList.contains('smr-en-hide')")
        browser.close()


def test_english_screen_keeps_the_previous_default(base_url):
    if CHROME and not Path(CHROME).is_file():
        pytest.skip("Chrome unavailable")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=CHROME) if CHROME else pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        _open_reader(page, base_url + "&lang=en")
        assert page.evaluate("window.__smReaderSettingsV1.get().englishMode") == "compact"
        browser.close()


def test_existing_setting_is_preserved(base_url):
    if CHROME and not Path(CHROME).is_file():
        pytest.skip("Chrome unavailable")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=CHROME) if CHROME else pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.add_init_script("""localStorage.setItem('storymemory.readerSettings.v1', JSON.stringify({version:1,font:'noto-sans-kr',fontSize:'base',lineHeight:'relaxed',theme:'default',englishMode:'show',verseNumbers:true}));""")
        _open_reader(page, base_url)
        assert page.evaluate("window.__smReaderSettingsV1.get().englishMode") == "show"
        browser.close()


def test_no_english_width_on_any_frame_after_page_turn(base_url):
    if CHROME and not Path(CHROME).is_file():
        pytest.skip("Chrome unavailable")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=CHROME) if CHROME else pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        _open_reader(page, base_url)
        # Pin 한글만 for this check so boot timing cannot change the mode under test.
        page.locator("#smalOverflowBtn").click()
        page.locator(".smal-overflow-menu .srsg-btn").click()
        panel = page.locator(".srsg-panel")
        panel.wait_for(state="visible")
        panel.get_by_role("group", name="번역본 표시").get_by_role("button", name="한글만").click()
        panel.locator(".srsg-x").click()
        pages = page.evaluate(FIXTURE)
        assert pages >= 2
        page.evaluate("applyReaderViewMode('page')")
        page.evaluate("""() => {
          window.__enWidths = []; window.__stopEnWatch = false;
          (function loop(){
            if (window.__stopEnWatch) return;
            let sum = 0;
            document.querySelectorAll('.verse-en').forEach(function(e){
              const cs = getComputedStyle(e);
              if (cs.display === 'none' || cs.visibility === 'hidden') return;
              const r = e.getBoundingClientRect();
              if (r.width > 0 && r.height > 0) sum += r.width;
            });
            window.__enWidths.push(sum);
            requestAnimationFrame(loop);
          })();
        }""")
        # The flash lives in the curl under-page: __smCurlPageMarkup() clones the
        # next page outside #readerPageBody and strips its ids, so the old hide
        # rule never reached it. Build that exact layer and watch every frame.
        page.evaluate("""() => {
          READER_PAGES = window.__pages;
          __smEnsureCurlLayers();
          __smCurlUnder.innerHTML = '<div class="curl-under-inner">' + __smCurlPageMarkup(1) + '</div>';
          __smCurlUnder.classList.add('show');
          applyCurl(0.5, 1);
        }""")
        page.wait_for_timeout(400)
        widths = page.evaluate("() => {window.__stopEnWatch=true;return window.__enWidths;}")
        assert widths and max(widths) == 0, f"English visible during page turn: {max(widths) if widths else 'no frames'}"
        assert widths and max(widths) == 0, f"English visible during page turn: {max(widths) if widths else 'no frames'}"
        assert widths and max(widths) == 0, f"English visible during page turn: {max(widths) if widths else 'no frames'}"
        assert widths and max(widths) == 0, f"English visible during page turn: {max(widths) if widths else 'no frames'}"
        browser.close()


def test_guest_cloud_notice_shows_once_and_stays_onscreen(base_url):
    if CHROME and not Path(CHROME).is_file():
        pytest.skip("Chrome unavailable")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=CHROME) if CHROME else pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        _open_reader(page, base_url)
        page.evaluate("openAuthGate()")
        sheet = page.locator("#authGateSheet")
        assert page.evaluate("document.body.classList.contains('auth-gate-open')")
        rect = sheet.bounding_box()
        assert rect and rect["x"] >= 0 and rect["y"] >= 0, rect
        assert rect["x"] + rect["width"] <= 390 and rect["y"] + rect["height"] <= 844, rect
        page.locator("#authGateSecondary").click()
        assert not page.evaluate("document.body.classList.contains('auth-gate-open')")
        page.evaluate("openAuthGate()")
        assert not page.evaluate("document.body.classList.contains('auth-gate-open')"), "notice reappeared after dismissal"
        browser.close()
