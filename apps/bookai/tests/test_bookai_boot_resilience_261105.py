"""BookAI first-visit boot resilience (#boot).

A cold, cache-less visit must clear the startup gate within 10 seconds, and one
blocked script must not hold the gate or stop the remaining scripts.
"""

from __future__ import annotations

import http.server
import threading
import time
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
    yield f"http://127.0.0.1:{server.server_port}/index.html"
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


def _clear_gate(page, started: float) -> float:
    page.wait_for_function(
        "() => !document.getElementById('bookai-startup')",
        timeout=10000,
    )
    return time.perf_counter() - started


def test_first_visit_clears_the_start_gate_within_ten_seconds(base_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 375, "height": 812}, service_workers="block")
        page = context.new_page()
        started = time.perf_counter()
        page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
        elapsed = _clear_gate(page, started)
        assert elapsed < 10, f"startup gate took {elapsed:.2f}s"
        assert page.locator(".book-rig").count() > 0, "library must render after the gate clears"
        assert page.evaluate("document.body.getAttribute('aria-busy')") is None
        context.close()
        browser.close()


def test_one_blocked_script_still_clears_the_start_gate(base_url):
    blocked = "storymemory-legacy-hybrid-ai-v1.js"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 375, "height": 812}, service_workers="block")
        page = context.new_page()
        console_errors: list[str] = []
        page.on(
            "console",
            lambda message: console_errors.append(message.text) if message.type == "error" else None,
        )

        def block(route):
            route.fulfill(status=404, content_type="text/plain", body="blocked by test")

        page.route(f"**/{blocked}", block)
        started = time.perf_counter()
        page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
        elapsed = _clear_gate(page, started)
        assert elapsed < 10, f"startup gate took {elapsed:.2f}s with one blocked script"
        assert page.locator(".book-rig").count() > 0, "library must still render"
        assert any("bookai_script_failed" in text and blocked in text for text in console_errors), console_errors
        context.close()
        browser.close()
