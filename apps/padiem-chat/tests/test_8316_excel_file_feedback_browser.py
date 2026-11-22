"""Excel file feedback must reflect the current selection, not a prior missing file."""
from __future__ import annotations

import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path

import pytest

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
STATIC = Path(__file__).resolve().parents[1] / "static"


@pytest.fixture
def site():
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(STATIC), **kwargs)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/index.html"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _page(playwright, url):
    browser = playwright.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 950},
                            reduced_motion="reduce")

    def route_request(route):
        request_url = route.request.url
        if not request_url.startswith(url.rsplit("/", 1)[0] + "/"):
            return route.abort()
        if "/api/auth/status" in request_url:
            return route.fulfill(json={
                "ready": True, "authenticated": True,
                "user": {"email": "qa@padiem.local", "name": "QA"},
                "session_state": "active", "shared_login_enabled": False,
                "shared_session_present": False, "status_reachable": True,
                "history_ready": True, "project_files_ready": True,
                "model_requires_session": False,
            })
        if "/api/" in request_url:
            return route.fulfill(status=404, json={"ok": False})
        return route.continue_()

    page.route("**/*", route_request)
    page.goto(f"{url}?theme=padiem-glass", wait_until="load")
    page.wait_for_timeout(2200)
    return browser, page


def test_valid_excel_selection_clears_missing_file_feedback(site, tmp_path):
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.active.append(["Item", "Amount"])
    workbook.active.append(["Sample", 42])
    stream = BytesIO()
    workbook.save(stream)
    with sync_playwright() as playwright:
        browser, page = _page(playwright, site)
        try:
            page.evaluate("location.hash = '#util/excel'")
            form = page.locator("#utilToolForm-excel")
            form.wait_for(state="visible")
            file_input = form.locator('input[type="file"]')
            form.locator('button[type="submit"]').click()
            assert file_input.get_attribute("aria-invalid") == "true"
            assert page.locator(".util-excel-status").is_visible()
            file_input.set_input_files({
                "name": "sample.xlsx",
                "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "buffer": stream.getvalue(),
            })
            page.screenshot(path=tmp_path / "excel-selected.png", full_page=True)
            assert file_input.get_attribute("aria-invalid") != "true"
            assert not page.locator(".util-excel-status").is_visible()
            assert not form.locator(".util-excel-note").first.is_visible()
            file_input.set_input_files([])
            assert form.locator(".util-excel-note").first.is_visible()
        finally:
            browser.close()
