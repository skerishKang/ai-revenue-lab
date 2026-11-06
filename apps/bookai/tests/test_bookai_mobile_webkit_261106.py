"""One representative WebKit phone pass for the #6476 audit (390x844)."""

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


@pytest.fixture(scope="module")
def browser():
    if sync_playwright is None:
        pytest.skip("playwright is not installed")
    with sync_playwright() as playwright:
        try:
            instance = playwright.webkit.launch(headless=True)
        except Exception as error:  # pragma: no cover - depends on the host
            pytest.skip(f"webkit is not installed: {error}")
        yield instance
        instance.close()


@pytest.fixture
def page(browser):
    context = browser.new_context(
        viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True
    )
    yield context.new_page()
    context.close()


def _contrast(foreground: str, background: str) -> float:
    def luminance(color: str) -> float:
        channels = [int(value) / 255 for value in re.findall(r"[\d.]+", color)[:3]]
        linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    high, low = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _assert_no_overflow(page, step: str):
    metrics = page.evaluate("() => ({viewport: innerWidth, width: document.documentElement.scrollWidth})")
    assert metrics["width"] <= metrics["viewport"], (step, metrics)


def _open_reader(page, base_url: str):
    page.goto(base_url, wait_until="domcontentloaded")
    page.locator("#library.active").wait_for()
    _assert_no_overflow(page, "library")
    page.locator("#openBook").click()
    page.locator("#index.active").wait_for()
    _assert_no_overflow(page, "chapter-picker")
    page.locator("#resume").click()
    page.locator("#reader.active").wait_for()
    page.locator("#readerPageBody .sm-source-passage").first.wait_for(timeout=20000)


def _open_settings(page):
    page.locator("#smalOverflowBtn").click()
    page.get_by_role("button", name="읽기 설정", exact=True).click()
    return page.locator(".srsg-panel")


def test_webkit_phone_flow_keeps_the_reader_on_screen(page, base_url):
    _open_reader(page, base_url)
    assert page.locator("#readerPageBody .sm-source-passage").first.is_visible()
    _assert_no_overflow(page, "reader")
    panel = _open_settings(page)
    assert panel.is_visible()
    _assert_no_overflow(page, "reader-settings")
    panel.locator("button.srsg-x").click()
    page.locator("[data-mobile=ai]").click()
    page.locator("#askInput").wait_for()
    _assert_no_overflow(page, "ai-sheet")
    page.locator("#scrim").click(position={"x": 10, "y": 200})
    page.locator("[data-mobile=memory]").click()
    page.locator(".memory-rail").wait_for()
    _assert_no_overflow(page, "memory-sheet")


def test_webkit_dark_ai_sheet_keeps_readable_contrast(page, base_url):
    _open_reader(page, base_url)
    panel = _open_settings(page)
    panel.locator('button[data-value="dark"]').click()
    assert "smr-theme-dark" in page.evaluate("() => document.body.className")
    panel.locator("button.srsg-x").click()
    page.locator("[data-mobile=ai]").click()
    page.locator("#askInput").wait_for()
    styles = page.evaluate(
        """() => {
          const input = getComputedStyle(document.querySelector('#askInput'));
          const heading = getComputedStyle(document.querySelector('.companion-empty-state h3'));
          const panel = getComputedStyle(document.querySelector('.ai-panel'));
          return {
            inputColor: input.color, inputBackground: input.backgroundColor,
            headingColor: heading.color, panelBackground: panel.backgroundColor,
          };
        }"""
    )
    assert _contrast(styles["inputColor"], styles["inputBackground"]) >= 4.5
    assert _contrast(styles["headingColor"], styles["panelBackground"]) >= 4.5
    _assert_no_overflow(page, "ai-sheet-dark")
