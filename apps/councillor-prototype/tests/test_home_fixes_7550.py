"""#7550 follow-up: hero button wrapping, media card external markers, and the
feedback failure guidance, measured in a real browser from the dist build."""
from __future__ import annotations

import http.server
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover
    sync_playwright = None

pytestmark = pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")

ROOT = Path(__file__).resolve().parents[1]
CHROME = next(
    (
        candidate
        for candidate in (
            os.environ.get("B61_CHROME_PATH"),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        )
        if candidate and Path(candidate).is_file()
    ),
    None,
)
FAIL_GUIDE = "급한 일은 의원실 전화(062-613-5133)·이메일로 연락해 주세요"


class StaticHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BUILD_DIR), **kwargs)

    def guess_type(self, path):
        value = super().guess_type(path)
        return "text/html; charset=utf-8" if path.endswith(".html") else value

    def log_message(self, *_args):
        pass


class StaticServer(http.server.ThreadingHTTPServer):
    request_queue_size = 256
    daemon_threads = True


BUILD_DIR = None


@pytest.fixture(scope="module")
def build_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("councillor-dist")
    result = subprocess.run(
        [sys.executable, "scripts/build-dist", "--out", str(out)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    return out


@pytest.fixture(scope="module")
def base_url(build_dir):
    global BUILD_DIR
    BUILD_DIR = build_dir
    server = StaticServer(("127.0.0.1", 0), StaticHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/"
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


@pytest.fixture(scope="module")
def browser():
    if sync_playwright is None or not CHROME:
        pytest.skip("playwright or Chrome is not installed")
    with sync_playwright() as playwright:
        launched = playwright.chromium.launch(headless=True, executable_path=CHROME)
        yield launched
        launched.close()


def _hero_button_heights(page):
    return page.evaluate(
        """() => Array.from(document.querySelectorAll('.hero-actions .btn'))
            .map((a) => ({text: a.textContent.trim().slice(0, 12),
                          h: a.getBoundingClientRect().height}))"""
    )


def test_hero_buttons_stay_low_at_390_320_1440(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        page.goto(base_url + "index.html", wait_until="load")
        page.wait_for_selector(".hero-actions .btn")
        heights = _hero_button_heights(page)
        assert len(heights) == 4
        for row in heights:
            assert row["h"] < 60, f"390px: {row['text']!r} button is {row['h']:.0f}px tall"
        page.set_viewport_size({"width": 320, "height": 700})
        page.wait_for_timeout(150)
        for row in _hero_button_heights(page):
            # one line (~49px) or a word-wrapped two lines; never a per-character stack
            assert row["h"] < 100, f"320px: {row['text']!r} button is {row['h']:.0f}px tall"
        page.set_viewport_size({"width": 1440, "height": 900})
        page.wait_for_timeout(150)
        for row in _hero_button_heights(page):
            assert row["h"] < 60, f"1440px: {row['text']!r} button is {row['h']:.0f}px tall"
    finally:
        page.close()


def test_hero_buttons_stay_low_in_dark_mode_at_390(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        page.goto(base_url + "index.html", wait_until="load")
        page.wait_for_selector(".hero-actions .btn")
        page.click("#themeToggle")
        page.wait_for_timeout(100)
        assert page.evaluate("() => document.documentElement.getAttribute('data-theme')") == "dark"
        for row in _hero_button_heights(page):
            assert row["h"] < 60, f"dark 390px: {row['text']!r} button is {row['h']:.0f}px tall"
    finally:
        page.close()


def test_media_cards_carry_the_external_link_marker(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        page.goto(base_url + "index.html", wait_until="load")
        page.wait_for_selector("#homeMedia .col-item")
        marked = page.evaluate(
            """() => Array.from(document.querySelectorAll('#homeMedia a[target="_blank"]'))
                .map((a) => ({mark: !!a.querySelector('.ext-mark') || a.textContent.includes('↗'),
                              label: a.getAttribute('aria-label') || ''}))"""
        )
        assert len(marked) >= 2
        for row in marked:
            assert row["mark"], "a home media card is missing the ↗ marker"
            assert "(새 탭)" in row["label"], "a home media card aria-label misses (새 탭)"

        page.goto(base_url + "media.html", wait_until="load")
        page.wait_for_selector(".media-tile")
        tiles = page.evaluate(
            """() => Array.from(document.querySelectorAll('.media-tile'))
                .map((a) => ({blank: a.target === '_blank',
                              mark: !!a.querySelector('.ext-mark') || a.textContent.includes('↗'),
                              label: a.getAttribute('aria-label') || ''}))"""
        )
        assert len(tiles) >= 3
        for row in tiles:
            assert row["blank"], "a media tile lost target=_blank"
            assert row["mark"], "a media tile is missing the ↗ marker"
            assert "(새 탭)" in row["label"], "a media tile aria-label misses (새 탭)"
    finally:
        page.close()


def test_media_tile_still_opens_the_lightbox(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        page.goto(base_url + "media.html", wait_until="load")
        page.wait_for_selector(".media-tile")
        page.locator(".media-tile").first.click()
        page.wait_for_timeout(400)
        assert page.evaluate("() => !!document.getElementById('mediaLightbox')?.open") is True
    finally:
        page.close()


def test_feedback_failure_shows_the_office_contact(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        for mode, stub in (
            ("refused", lambda route: route.fulfill(
                status=500, content_type="application/json", body='{"ok": false}')),
            ("offline", lambda route: route.abort()),
        ):
            page.route("**/api/site-feedback", stub)
            page.goto(base_url + "index.html", wait_until="load")
            page.click("#siteFeedbackOpen")
            page.fill("#siteFeedbackBody", "페이지 오류 신고")
            page.click(".site-feedback-send")
            page.wait_for_timeout(300)
            status = page.evaluate("() => document.getElementById('siteFeedbackStatus').textContent")
            assert "보내지 못했습니다" in status, f"{mode}: {status!r}"
            assert FAIL_GUIDE in status, f"{mode}: the failure status misses the office contact"
            page.unroute("**/api/site-feedback")
    finally:
        page.close()
