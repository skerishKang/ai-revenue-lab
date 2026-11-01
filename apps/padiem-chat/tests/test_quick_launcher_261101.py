"""Quick launcher uses the real utility and project-file UI with synthetic API data."""
import http.server
import threading
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright

STATIC = Path(__file__).resolve().parents[1] / "static"
PID = "proj_" + "1" * 32
FID = "file_" + "2" * 32

@pytest.fixture(scope="module")
def site():
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(STATIC), **kwargs)
        def log_message(self, *_):
            pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/index.html"
    server.shutdown()
    thread.join()
    server.server_close()

@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        yield browser
        browser.close()

def page_for(browser, site, width, theme):
    page = browser.new_page(viewport={"width": width, "height": 900}, color_scheme=theme)
    def api(route):
        path = urlsplit(route.request.url).path
        if not path.startswith("/api/"):
            if urlsplit(route.request.url).netloc != urlsplit(site).netloc:
                route.abort()
            else:
                route.continue_()
            return
        data = {"ok": True}
        if path == "/api/auth/status":
            data = {"ready": True, "authenticated": True, "session_state": "signed_in",
                    "user": {"name": "Test"}, "history_ready": True, "project_files_ready": True}
        elif path == "/api/projects":
            data = {"projects": [{"id": PID, "name": "Test project", "instructions": ""}]}
        elif path == "/api/project-files":
            data = {"files": [{"id": FID, "name": "recent.txt", "project_id": PID,
                                "project_name": "Test project"}], "has_more": False}
        elif path == f"/api/projects/{PID}/files":
            data = {"files": [{"id": FID, "name": "recent.txt", "media_type": "text/plain",
                                "content_chars": 7}]}
        route.fulfill(json=data)
    page.route("**/*", api)
    page.goto(site)
    page.evaluate("(theme) => document.documentElement.dataset.theme = theme", theme)
    page.wait_for_timeout(500)
    return page

@pytest.mark.parametrize("width", [1440, 390])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_shortcuts_and_recent_project_file(browser, site, width, theme):
    page = page_for(browser, site, width, theme)
    if width == 390:
        page.locator("#mobileMenu").click()
    page.locator("#quickRecentFiles button").first.wait_for()
    page.locator("#quickRecentFiles button").first.click()
    page.locator("#projectDialog[open] .quick-selected-file").wait_for()
    assert page.locator("#projectDialog .quick-selected-file").inner_text().startswith("recent.txt")
    page.wait_for_function("document.activeElement?.classList.contains('quick-selected-file')")
    page.locator("#projectDialogClose").click()
    for key, panel in [("speech", "utilSpeechPanel"), ("sns", "utilSnsPanel"),
                       ("meeting", "utilMeetingPanel"), ("pdfmd", "utilPdfmdPanel")]:
        if width == 390:
            page.locator("#mobileMenu").click()
        page.locator(f'[data-quick-util="{key}"]').click()
        assert page.locator(f"#{panel}").is_visible()
    if width == 390:
        page.locator("#mobileMenu").click()
    page.locator('[data-quick-util="claw-quote"]').click()
    assert page.locator(".app-shell").get_attribute("data-state") == "claw"
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.close()
