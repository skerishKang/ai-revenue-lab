"""Login-gate wiring for #6259 5-2: the PADIEM entry must be visible and act."""

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


def _open_gate(page, base_url: str):
    page.goto(base_url, wait_until="domcontentloaded")
    page.locator("#library.active").wait_for()
    page.wait_for_function(
        "() => window.BookAISession && !document.getElementById('authGatePrimary').hidden",
        timeout=30000,
    )
    page.locator("#todayEntry").click()
    page.locator("#today.active").wait_for()
    page.locator("#todayCloudButton").click()
    page.locator("#authGateSheet").wait_for(state="visible")


def _stub_session(page, authenticated: bool, **extra):
    body = json.dumps({"authenticated": authenticated, **extra})

    def session(route):
        route.fulfill(status=200, content_type="application/json", body=body)

    page.route("**/auth/session*", session)
    page.route("**/auth/refresh", lambda route: route.fulfill(status=401, body=""))
    page.route(
        "**/api/bookai/records*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"records":[],"next_since":0,"more":false}',
        ),
    )


def test_logged_out_entry_is_visible_and_opens_the_google_login(page, base_url):
    _stub_session(page, False)
    _open_gate(page, base_url)
    primary = page.locator("#authGatePrimary")
    assert primary.is_visible()
    assert primary.inner_text() == "파디엠으로 로그인"
    assert page.locator("#todayCloudLabel").inner_text() == "기기 저장"
    assert page.locator("#authGateState b").inner_text() == "기기 저장"
    with page.expect_navigation(timeout=15000, wait_until="domcontentloaded"):
        primary.click()
    assert "/auth/login" in page.url


def test_authenticated_entry_logs_out_and_returns_to_local(page, base_url):
    _stub_session(page, True, account_id="sub_test_lane6", user={"name": "시험 계정"})
    logout = []

    def logout_route(route):
        logout.append(route.request.method)
        route.fulfill(status=200, body="{}")

    page.route("**/auth/logout", logout_route)
    _open_gate(page, base_url)
    primary = page.locator("#authGatePrimary")
    assert primary.inner_text() == "로그아웃"
    assert page.locator("#todayCloudLabel").inner_text() == "로그인됨"
    assert page.locator("#authGateState b").inner_text() == "PADIEM"
    primary.click()
    page.wait_for_function(
        "() => document.getElementById('authGatePrimary').textContent === '파디엠으로 로그인'"
    )
    assert logout == ["POST"]
    assert page.locator("#todayCloudLabel").inner_text() == "기기 저장"


def test_expired_session_keeps_reading_available_offline(page, base_url):
    _stub_session(page, False)
    _open_gate(page, base_url)
    assert page.locator("#authGateCopy").inner_text().startswith("기록은 이 기기에 저장됩니다")
    assert page.evaluate("() => window.BookAISession.isAuthenticated()") is False
    page.locator("#authGateSheet [data-close-sheet], #authGateClose").first.click()
    assert page.locator("#reader").is_visible() is False
    assert page.locator("#today.active").is_visible()
