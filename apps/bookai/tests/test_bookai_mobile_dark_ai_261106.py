"""390px regression for the #6476 mobile audit: Dark AI surfaces and touch targets."""

from __future__ import annotations

import http.server
import os
import re
import threading
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover
    sync_playwright = None

pytestmark = pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")

PUBLIC = Path(__file__).resolve().parents[1] / "public"
CHROME = os.environ.get("B61_CHROME_PATH")


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
    yield f"http://127.0.0.1:{server.server_port}/"
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


@pytest.fixture
def page(base_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=CHROME)
        context = browser.new_context(
            viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True
        )
        yield context.new_page()
        context.close()
        browser.close()


def _contrast(foreground: str, background: str) -> float:
    def luminance(color: str) -> float:
        channels = [int(value) / 255 for value in re.findall(r"[\d.]+", color)[:3]]
        linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    high, low = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _open_reader(page, base_url: str):
    page.goto(base_url, wait_until="domcontentloaded")
    page.locator("#library.active").wait_for()
    page.locator("#openBook").click()
    page.locator("#index.active").wait_for()
    page.locator("#resume").click()
    page.locator("#reader.active").wait_for()
    page.locator("#readerPageBody .sm-source-passage").first.wait_for(timeout=20000)


def _set_theme(page, value: str):
    page.locator("#smalOverflowBtn").click()
    page.get_by_role("button", name="읽기 설정", exact=True).click()
    page.locator(f'.srsg-panel button[data-value="{value}"]').click()
    page.locator(".srsg-x").click()
    page.wait_for_timeout(300)


def _open_ai(page):
    page.locator("[data-mobile=ai]").click()
    page.locator("#askInput").wait_for()
    page.wait_for_timeout(400)


def _box(page, selector):
    return page.locator(selector).first.bounding_box()


def _effective_target(page, selector):
    """Visual box plus any absolutely positioned ::after hit-area overlay."""
    return page.evaluate(
        """(selector) => {
          const element = document.querySelector(selector);
          const rect = element.getBoundingClientRect();
          const overlay = getComputedStyle(element, '::after');
          const borderTop = parseFloat(getComputedStyle(element).borderTopWidth) || 0;
          const borderBottom = parseFloat(getComputedStyle(element).borderBottomWidth) || 0;
          let top = rect.top;
          let bottom = rect.bottom;
          const hasOverlay = overlay.content && overlay.content !== 'none'
            && overlay.position === 'absolute';
          if (hasOverlay) {
            const overlayTop = parseFloat(overlay.top);
            const overlayBottom = parseFloat(overlay.bottom);
            if (!Number.isNaN(overlayTop) || !Number.isNaN(overlayBottom)) {
              top = rect.top + borderTop + (Number.isNaN(overlayTop) ? 0 : overlayTop);
              bottom = rect.bottom - borderBottom - (Number.isNaN(overlayBottom) ? 0 : overlayBottom);
            }
          }
          const centerX = rect.left + rect.width / 2;
          const hits = [top + 2, bottom - 2].map((y) => {
            const hit = document.elementFromPoint(centerX, y);
            return !!hit && (hit === element || element.contains(hit));
          });
          return {height: bottom - top, hitTop: hits[0], hitBottom: hits[1]};
        }""",
        selector,
    )


def test_dark_ai_text_is_readable(page, base_url):
    _open_reader(page, base_url)
    _set_theme(page, "dark")
    _open_ai(page)
    styles = page.evaluate(
        """() => {
          const style = (selector) => {
            const element = document.querySelector(selector);
            if (!element) return null;
            const computed = getComputedStyle(element);
            return {color: computed.color, background: computed.backgroundColor};
          };
          return {
            input: style('#askInput'),
            heading: style('.companion-empty-state h3'),
            card: style('.ai-panel .context-card'),
            panel: style('.ai-panel'),
          };
        }"""
    )
    assert styles["input"] and styles["heading"] and styles["card"] and styles["panel"]
    assert _contrast(styles["input"]["color"], styles["input"]["background"]) >= 4.5
    assert _contrast(styles["heading"]["color"], styles["panel"]["background"]) >= 4.5
    assert _contrast(styles["card"]["color"], styles["card"]["background"]) >= 4.5
    page.locator("#askInput").fill("테스트 입력")
    assert _contrast(styles["input"]["color"], styles["input"]["background"]) >= 4.5


def test_light_ai_input_keeps_light_surface(page, base_url):
    _open_reader(page, base_url)
    _open_ai(page)
    background = page.evaluate(
        "() => getComputedStyle(document.querySelector('#askInput')).backgroundColor"
    )
    assert _contrast("rgb(0, 0, 0)", background) > 15  # light surface: black text is high contrast


def test_mobile_targets_are_at_least_44(page, base_url):
    _open_reader(page, base_url)
    selectors = ["#v2ChapterChip", "#smalOverflowBtn"]
    for selector in selectors:
        box = _box(page, selector)
        target = _effective_target(page, selector)
        assert box and box["width"] >= 44, (selector, box)
        assert target["height"] >= 44 and target["hitTop"] and target["hitBottom"], (selector, target)

    page.locator("#bibleSearchPanel summary").click()
    for selector in ["#bibleSearchInput", "#bibleSearchSubmit"]:
        box = _box(page, selector)
        target = _effective_target(page, selector)
        assert box and box["width"] >= 44, (selector, box)
        assert target["height"] >= 44 and target["hitTop"] and target["hitBottom"], (selector, target)
    page.locator("#bibleSearchPanel summary").click()

    _open_ai(page)
    selectors = [
        "#aiOverflowBtn",
        ".ai-panel .ai-head-actions .sheet-close",
        ".ai-panel .quick button",
        "#askInput",
        "#sendBtn",
    ]
    for selector in selectors:
        box = _box(page, selector)
        target = _effective_target(page, selector)
        assert box and box["width"] >= 44, (selector, box)
        assert target["height"] >= 44 and target["hitTop"] and target["hitBottom"], (selector, target)


def test_reader_and_ai_do_not_overflow_horizontally(page, base_url):
    _open_reader(page, base_url)
    metrics = page.evaluate(
        "() => ({viewport: innerWidth, width: document.documentElement.scrollWidth})"
    )
    assert metrics["width"] <= metrics["viewport"]
    _open_ai(page)
    metrics = page.evaluate(
        "() => ({viewport: innerWidth, width: document.documentElement.scrollWidth})"
    )
    assert metrics["width"] <= metrics["viewport"]
