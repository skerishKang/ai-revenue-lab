"""#8954-2: active-project ribbon action label and border contrast on all themes.

The visible ribbon is a synthetic display fixture, not a project mutation.
"""
from __future__ import annotations

import http.server
import os
import re
import threading
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

STATIC = Path(__file__).resolve().parents[1] / "static"
THEMES = ["light", "dark", "cinematic", "padiem-glass", "padiem-home"]


class _Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def url():
    port = int(os.getenv("CGI_8954_PORT", "0"))
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), _Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_address[1]}/index.html"
        finally:
            server.shutdown()
            thread.join(timeout=5)


@pytest.fixture(scope="module")
def browser():
    if sync_playwright is None:
        pytest.skip("Playwright is required")
    with sync_playwright() as pw:
        instance = pw.chromium.launch(headless=True)
        try:
            yield instance
        finally:
            instance.close()


def _color(css: str) -> tuple[float, float, float]:
    match = re.fullmatch(r"rgba?\(([^)]+)\)", css.strip())
    assert match, css
    values = [float(v.strip()) for v in match.group(1).split(",")]
    assert len(values) == 3 or (len(values) == 4 and values[3] == 1.0), css
    return tuple(values[:3])


def _luminance(rgb):
    channels = [v / 255 for v in rgb]
    return sum(factor * (v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4)
               for factor, v in zip((0.2126, 0.7152, 0.0722), channels))


def _contrast(a, b):
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("width", [390, 1440])
@pytest.mark.parametrize("theme", THEMES)
def test_project_ribbon_action_label_and_border_contrast(browser, url, width, theme):
    page = browser.new_page(viewport={"width": width, "height": 844})
    try:
        page.goto(f"{url}?theme={theme}", wait_until="domcontentloaded")
        details = page.evaluate("""() => {
          const banner = document.getElementById('projectBanner');
          banner.hidden = false;
          document.getElementById('activeProjectName').textContent = '프로젝트 이름';
          return [...banner.querySelectorAll('.project-banner-actions button')].map(button => {
            const style = getComputedStyle(button);
            return {label:button.textContent.trim(), background:style.backgroundColor,
              foreground:style.color, edge:style.borderTopColor,
              width:button.getBoundingClientRect().width, height:button.getBoundingClientRect().height};
          });
        }""")
        assert len(details) == 2, details
        for item in details:
            assert item["width"] > 40 and item["height"] >= 40, (theme, width, item)
            bg = _color(item["background"])
            assert _contrast(_color(item["foreground"]), bg) >= 4.5, (theme, width, item)
            assert _contrast(_color(item["edge"]), bg) >= 4.5, (theme, width, item)
    finally:
        page.close()
