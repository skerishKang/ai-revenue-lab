"""#8954-2 project ribbon button colors: mobile and desktop, bright themes."""
from __future__ import annotations

import http.server
import re
import threading
from pathlib import Path

import pytest
sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

STATIC = Path(__file__).resolve().parents[1] / "static"


class StaticHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def site():
    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), StaticHandler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_address[1]}/index.html"
        finally:
            server.shutdown()
            thread.join(timeout=5)


def rgb(css_color):
    match = re.fullmatch(r"rgb\((\d+), (\d+), (\d+)\)", css_color)
    assert match, f"expected opaque color: {css_color}"
    return tuple(int(x) / 255 for x in match.groups())


def luminance(color):
    def linear(value):
        return value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4
    return sum(weight * linear(v) for weight, v in zip((.2126, .7152, .0722), color))


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + .05) / (low + .05)


@pytest.mark.parametrize("width", [390, 1440])
@pytest.mark.parametrize("theme", ["light", "dark", "cinematic", "padiem-glass", "padiem-home"])
def test_project_ribbon_buttons_have_45_contrast(site, width, theme):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": width, "height": 844}, reduced_motion="reduce")
            page.goto(f"{site}?theme={theme}", wait_until="domcontentloaded")
            assert page.evaluate("document.documentElement.dataset.theme") == theme
            page.evaluate("document.getElementById('projectBanner').hidden = false")
            states = page.locator("#projectBanner .project-banner-actions button").evaluate_all(
                """buttons => buttons.map(b => {
                    const s = getComputedStyle(b);
                    return {color: s.color, border: s.borderTopColor, background: s.backgroundColor};
                })"""
            )
            assert len(states) == 2
            for colors in states:
                bg = rgb(colors["background"])
                assert contrast(rgb(colors["color"]), bg) >= 4.5, colors
                assert contrast(rgb(colors["border"]), bg) >= 4.5, colors
            page.close()
        finally:
            browser.close()
