"""#261114 — first Chat screen: calendar failures stay quiet, menu starts Korean."""

from __future__ import annotations

import http.server
import json
import os
import threading
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover
    sync_playwright = None

pytestmark = pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
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

EMPTY = {"ok": True, "projection": {"items": []}}
FAIL = {"ok": False, "error": {"code": "projection_failed", "message": "calendar failed"}}
AUTH = {
    "authenticated": True,
    "session_state": "signed_in",
    "owner_key": "test-owner",
    "display_name": "테스트",
}


class StaticHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def guess_type(self, path):
        value = super().guess_type(path)
        return "text/html; charset=utf-8" if path.endswith(".html") else value

    def log_message(self, *_args):
        pass


class StaticServer(http.server.ThreadingHTTPServer):
    request_queue_size = 256
    daemon_threads = True


@pytest.fixture(scope="module")
def base_url():
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


def _open_first_screen(page, base_url, locale="ko-KR"):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(base_url + "index.html?lang=ko", wait_until="load")
    page.wait_for_selector("#calendarNavButton")
    page.wait_for_timeout(500)


def _show_calendar_with_auth(page):
    page.evaluate(
        """() => {
          window.PadiemAuthSession = { get: () => ({ authenticated: true, owner_key: 'test-owner', display_name: '테스트' }) };
          document.querySelector('.app-shell').dataset.state = 'calendar';
          window.dispatchEvent(new CustomEvent('padiem:auth-state', { detail: { authenticated: true, owner_key: 'test-owner' } }));
        }"""
    )


def _route_calendar(page, today, upcoming=None):
    upcoming = upcoming or [EMPTY]

    def handler(route):
        url = route.request.url
        if "/api/calendar/today" in url:
            status, body = today.pop(0) if today else (200, EMPTY)
        elif "/api/calendar/upcoming" in url:
            status, body = upcoming.pop(0) if upcoming else (200, EMPTY)
        elif "/api/auth/session" in url:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(AUTH))
            return
        else:
            route.continue_()
            return
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body))

    page.route("**/*", handler)


def test_empty_calendar_is_an_empty_state_not_an_error(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844}, locale="ko-KR")
    try:
        _route_calendar(page, [(200, EMPTY)])
        _open_first_screen(page, base_url)
        _show_calendar_with_auth(page)
        page.locator('#calendarTodayTab').click()
        page.wait_for_selector("#calendarEmpty", state="visible", timeout=5000)
        state = page.evaluate(
            """() => ({
              empty: !document.getElementById('calendarEmpty').hidden,
              error: !document.getElementById('calendarErrorBox').hidden,
              menu: document.querySelector('#automationNavButton [data-locale-key="nav-automation"]').textContent.trim(),
            })"""
        )
        assert state == {"empty": True, "error": False, "menu": "자동화"}
    finally:
        page.close()


def test_transient_failure_retries_once_and_shows_empty(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844}, locale="ko-KR")
    try:
        _route_calendar(page, [(500, FAIL), (200, EMPTY)])
        _open_first_screen(page, base_url)
        _show_calendar_with_auth(page)
        page.locator('#calendarTodayTab').click()
        page.wait_for_selector("#calendarEmpty", state="visible", timeout=5000)
        state = page.evaluate(
            """() => ({
              empty: !document.getElementById('calendarEmpty').hidden,
              error: !document.getElementById('calendarErrorBox').hidden,
            })"""
        )
        assert state == {"empty": True, "error": False}
    finally:
        page.close()


def test_repeated_failure_shows_error_box_with_retry(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844}, locale="ko-KR")
    try:
        _route_calendar(page, [(500, FAIL), (500, FAIL)])
        _open_first_screen(page, base_url)
        _show_calendar_with_auth(page)
        page.locator('#calendarTodayTab').click()
        page.wait_for_selector("#calendarErrorBox", state="visible", timeout=5000)
        state = page.evaluate(
            """() => ({
              empty: !document.getElementById('calendarEmpty').hidden,
              error: !document.getElementById('calendarErrorBox').hidden,
              retryVisible: !!document.getElementById('calendarRetry')?.offsetParent,
            })"""
        )
        assert state["error"] is True
        assert state["retryVisible"] is True
        assert state["empty"] is False
    finally:
        page.close()


def test_korean_browser_first_render_uses_korean_menu(browser, base_url):
    page = browser.new_page(viewport={"width": 1440, "height": 900}, locale="ko-KR")
    try:
        _route_calendar(page, [(200, EMPTY)])
        _open_first_screen(page, base_url)
        assert page.locator('#automationNavButton [data-locale-key="nav-automation"]').inner_text().strip() == "자동화"
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(150)
        assert page.locator('#automationNavButton [data-locale-key="nav-automation"]').inner_text().strip() == "자동화"
    finally:
        page.close()