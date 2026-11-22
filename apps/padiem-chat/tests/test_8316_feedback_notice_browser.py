"""Fixed-feedback notice must not overlap the first-screen greeting."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import pytest

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
STATIC = Path(__file__).resolve().parents[1] / "static"
THEMES = ("light", "dark", "cinematic", "padiem-home", "padiem-glass")
ORIGIN = "http://feedback-notice.invalid"


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            yield browser
        finally:
            browser.close()


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("width,height", [(390, 844), (768, 1024), (1440, 900)])
def test_fixed_notice_does_not_cover_greeting(browser, tmp_path, theme, width, height):
    page = browser.new_page(viewport={"width": width, "height": height},
                            locale="ko-KR", reduced_motion="reduce")

    def route_request(route):
        url = urlsplit(route.request.url)
        if url.netloc != "feedback-notice.invalid" or route.request.resource_type == "media":
            return route.abort()
        if url.path == "/api/auth/status":
            return route.fulfill(json={
                "ready": True, "authenticated": True,
                "user": {"email": "qa@padiem.local", "name": "QA"},
                "session_state": "active", "shared_login_enabled": False,
                "shared_session_present": False, "status_reachable": True,
                "history_ready": True, "project_files_ready": True,
                "model_requires_session": False,
            })
        if url.path == "/api/chat/feedback" and route.request.method == "GET":
            return route.fulfill(json={"ok": True, "feedback": [],
                                       "unread_fixed_count": 1})
        if url.path.startswith("/api/"):
            return route.fulfill(status=404, json={"ok": False})
        asset = STATIC / url.path.lstrip("/")
        if asset.is_file():
            return route.fulfill(path=asset)
        return route.abort()

    try:
        page.route("**/*", route_request)
        page.goto(f"{ORIGIN}/index.html?theme={theme}", wait_until="domcontentloaded")
        notice = page.locator("#feedbackNotice")
        greeting = page.locator("#emptyState h1")
        notice.wait_for(state="visible")
        greeting.wait_for(state="visible")
        assert page.locator("html").get_attribute("data-theme") == theme
        page.evaluate("document.fonts.ready")
        page.screenshot(path=tmp_path / f"{width}-{theme}.jpg", quality=85,
                        animations="disabled")
        n, g = notice.bounding_box(), greeting.bounding_box()
        assert n and g
        print(f"{width}/{theme}: notice={n}, heading={g}")
        # A mobile/tablet notice must reserve its own row, including the gap.
        if width <= 920:
            assert g["y"] - (n["y"] + n["height"]) >= 8
        # Desktop heading is a wide block; measure the rendered text instead.
        text_rects = greeting.evaluate("""heading => {
            const walker = document.createTreeWalker(heading, NodeFilter.SHOW_TEXT);
            const rects = [];
            while (walker.nextNode()) {
                const range = document.createRange();
                range.selectNodeContents(walker.currentNode);
                for (const r of range.getClientRects())
                    if (r.width && r.height) rects.push(r.toJSON());
            }
            return rects;
        }""")
        assert text_rects
        for rect in text_rects:
            assert (n["x"] + n["width"] <= rect["left"] or
                    rect["right"] <= n["x"] or
                    n["y"] + n["height"] <= rect["top"] or
                    rect["bottom"] <= n["y"])
        assert n["x"] >= 0 and n["x"] + n["width"] <= width
        assert n["y"] >= 0 and n["y"] + n["height"] <= height
        assert g["y"] >= 0 and g["y"] + g["height"] <= height
    finally:
        page.close()
