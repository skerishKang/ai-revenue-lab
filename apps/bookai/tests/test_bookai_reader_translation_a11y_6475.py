"""Focused B61 #6475 checks for reader translation settings and accessibility."""

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
CHROME_CANDIDATES = [
    os.environ.get("B61_CHROME_PATH"),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]
CHROME = next((candidate for candidate in CHROME_CANDIDATES if candidate and Path(candidate).is_file()), None)


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
    yield f"http://127.0.0.1:{server.server_port}/index.html"
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


def _open_acts_reader(page, base_url):
    page.goto(base_url + "?view=reader", wait_until="load")
    page.wait_for_function("() => window.__smReaderSettingsV1 && typeof window.__smReaderSettingsV1.get === 'function'")
    page.wait_for_selector("#smalOverflowBtn")
    page.wait_for_selector("#readerPageBody")
    # Exercise the production passage renderer without depending on a remote DB
    # or the repository's bundled scripture corpus in this settings-only test.
    page.evaluate("""() => {
      const bundle = {
        mode: 'static',
        content: {kind: 'bible'},
        work: {work_key: 'bible-web'},
        passages: [{
          id: 'fixture-act-9-1', canonicalLocator: 'bible:web:ACT:9:1',
          sequence: 1, language: 'ko', text: '한글 본문 예시',
          sourceText: 'English passage example', locator: {verse: 1},
          sourceRef: null
        }]
      };
      const built = storyMemoryBuildDynamicReaderPages(bundle);
      READER_PAGES = built.pages;
      readerPageIndex = 0;
      __smDynamicReaderState = {
        generation: 1, mode: 'static', content: bundle.content,
        work: bundle.work, unitOrdinal: 1, passages: built.passages,
        pagePassages: built.groups, pageSourceRefs: built.pageSourceRefs,
        remoteError: null
      };
      document.getElementById('readerVolumeTitle').textContent = '사도행전';
      document.getElementById('readerChapterTitle').textContent = '9장';
      document.getElementById('readerSourceBadge').textContent = '한·영';
      document.getElementById('readerPageBody').innerHTML = built.pages[0];
    }""")
    assert page.locator("#readerPageBody .verse[lang='ko']").count() == 1
    assert page.locator("#readerPageBody .verse-en[lang='en']").count() == 1


def _open_settings(page):
    page.locator("#smalOverflowBtn").click()
    page.locator(".smal-overflow-menu .srsg-btn").click()
    panel = page.locator(".srsg-panel")
    panel.wait_for(state="visible")
    return panel


def _contrast(rgb_a: str, rgb_b: str) -> float:
    def luminance(rgb: str) -> float:
        channels = [float(value) / 255 for value in rgb.strip("rgba() ").split(",")[:3]]
        linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    first, second = sorted((luminance(rgb_a), luminance(rgb_b)), reverse=True)
    return (first + 0.05) / (second + 0.05)


def test_translation_settings_persist_lang_labels_focus_contrast_and_zoom(base_url, tmp_path):
    if CHROME and not Path(CHROME).is_file():
        pytest.skip("Chrome executable is unavailable")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=CHROME) if CHROME else playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1)
        page_errors = []
        page.on("pageerror", lambda error: page_errors.append(f"{error} | {getattr(error, 'stack', '')}"))
        page.on("console", lambda msg: page_errors.append(f"console:{msg.type}:{msg.text} @ {msg.location}") if msg.type == "error" and "Unexpected token" in msg.text else None)
        _open_acts_reader(page, base_url)

        settings = page.evaluate("window.__smReaderSettingsV1.get()")
        assert settings["englishMode"] == "show"
        assert settings["fontSize"] == "base"
        assert settings["lineHeight"] == "relaxed"
        assert page.locator("#readerPageBody .verse[lang='ko']").count() > 0
        assert page.locator("#readerPageBody .verse-en[lang='en']").count() > 0
        source_note = page.locator("#readerPageBody .sm-verified-source-note").first.inner_text()
        assert "KRV-1961" in source_note
        assert "WEB" in source_note and "World English Bible" in source_note
        assert "ENGWEBP" in source_note

        panel = _open_settings(page)
        font = panel.get_by_role("group", name="글꼴")
        language = panel.get_by_role("group", name="번역본 표시")
        size = panel.get_by_role("group", name="글자 크기")
        spacing = panel.get_by_role("group", name="줄 간격")
        theme = panel.get_by_role("group", name="테마 · 배경")
        assert font.count() == language.count() == size.count() == spacing.count() == theme.count() == 1
        assert page.evaluate("document.activeElement.classList.contains('srsg-x')")
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.closest('.srsg-seg')?.dataset.field") == "font"
        assert language.get_by_role("button", name="한영 함께").get_attribute("aria-pressed") == "true"
        assert theme.get_by_role("button", name="밝게").get_attribute("aria-label")

        contrast = page.evaluate("""() => {
          const label = document.querySelector('.srsg-label');
          const panel = document.querySelector('.srsg-panel');
          const plainButton = document.querySelector('.srsg-seg button:not(.on)');
          const selectedButton = document.querySelector('.srsg-seg button.on');
          return {
            label: [getComputedStyle(label).color, getComputedStyle(panel).backgroundColor],
            plain: [getComputedStyle(plainButton).color, getComputedStyle(plainButton).backgroundColor],
            selected: [getComputedStyle(selectedButton).color, getComputedStyle(selectedButton).backgroundColor]
          };
        }""")
        assert _contrast(*contrast["label"]) >= 4.5
        assert _contrast(*contrast["plain"]) >= 4.5
        assert _contrast(*contrast["selected"]) >= 4.5

        language.get_by_role("button", name="한글만").click()
        assert page.locator("body").evaluate("element => element.classList.contains('smr-en-hide')")
        assert page.locator("#readerPageBody .verse-en").first.is_visible() is False
        saved = page.evaluate("BookAILocalDB.flush().then(() => JSON.parse(BookAIStorage.getItem('storymemory.readerSettings.v1')))")
        assert saved["englishMode"] == "hide"

        language.get_by_role("button", name="한영 함께").click()
        assert page.locator("#readerPageBody .verse-en[lang='en']").first.is_visible()
        initial_size = page.locator("#readerPageBody .verse[lang='ko']").first.evaluate("el => parseFloat(getComputedStyle(el).fontSize)")
        initial_line_height = page.locator("#readerPageBody .verse[lang='ko']").first.evaluate("el => parseFloat(getComputedStyle(el).lineHeight)")
        size.get_by_role("button", name="매우 크게").click()
        larger_size = page.locator("#readerPageBody .verse[lang='ko']").first.evaluate("el => parseFloat(getComputedStyle(el).fontSize)")
        assert larger_size > initial_size
        spacing.get_by_role("button", name="넓게").click()
        loose_height = page.locator("#readerPageBody .verse[lang='ko']").first.evaluate("el => parseFloat(getComputedStyle(el).lineHeight)")
        assert loose_height > initial_line_height
        saved = page.evaluate("BookAILocalDB.flush().then(() => JSON.parse(BookAIStorage.getItem('storymemory.readerSettings.v1')))")
        assert saved["englishMode"] == "show" and saved["fontSize"] == "xl" and saved["lineHeight"] == "loose"

        page.reload(wait_until="load")
        page.wait_for_function("() => window.__smReaderSettingsV1 && typeof window.__smReaderSettingsV1.get === 'function'")
        assert page.evaluate("window.__smReaderSettingsV1.get().fontSize") == "xl"
        assert page.evaluate("window.__smReaderSettingsV1.get().lineHeight") == "loose"
        _open_acts_reader(page, base_url)
        assert page.locator("#readerPageBody .verse-en[lang='en']").first.is_visible()

        panel = _open_settings(page)
        gear = page.locator(".srsg-btn")
        assert gear.get_attribute("aria-controls") == "smReaderSettingsPanel"
        assert gear.get_attribute("aria-expanded") == "true"
        page.keyboard.press("Escape")
        assert panel.is_visible() is False
        assert gear.get_attribute("aria-expanded") == "false"
        assert page.evaluate("document.activeElement.id") == "smalOverflowBtn"

        page.set_viewport_size({"width": 195, "height": 422})  # 390 CSS px at 200% zoom
        panel = _open_settings(page)
        geometry = page.evaluate("""() => {
          const panel = document.querySelector('.srsg-panel').getBoundingClientRect();
          return {width: innerWidth, scrollWidth: document.documentElement.scrollWidth, left: panel.left, right: panel.right};
        }""")
        assert geometry["scrollWidth"] <= geometry["width"]
        assert geometry["left"] >= 0 and geometry["right"] <= geometry["width"]

        screenshot_path = os.environ.get("B61_TRANSLATION_A11Y_SCREENSHOT")
        if screenshot_path:
            assert page.locator("#readerPageBody .verse-en[lang='en']").first.is_visible()
            Path(screenshot_path).parent.mkdir(parents=True, exist_ok=True)
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=screenshot_path, full_page=True)

        assert page_errors == []
        browser.close()
