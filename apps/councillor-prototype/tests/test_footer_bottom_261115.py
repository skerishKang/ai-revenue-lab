"""Footer bottom contract: a short page still fills the viewport, so the footer
sits at the bottom edge (above the phone tab bar) with no empty band under it,
while long pages keep the footer last. Measured in a real browser from the dist
build, the way the QA capture driver measures it: scrolled to the bottom, which
is where a reader sees the footer and where the fixed tab bar decides."""
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


MEASURE = """() => {
  window.scrollTo(0, document.documentElement.scrollHeight);
  const docBottom = (el) => el ? el.getBoundingClientRect().bottom + window.scrollY : null;
  const viewBottom = (el) => el ? el.getBoundingClientRect().bottom : null;
  const viewTop = (el) => el ? el.getBoundingClientRect().top : null;
  const bodyPad = parseFloat(getComputedStyle(document.body).paddingBottom) || 0;
  const bar = document.querySelector('.mobile-tabbar');
  return {
    scrollY: window.scrollY,
    innerHeight: window.innerHeight,
    scrollHeight: document.documentElement.scrollHeight,
    bodyPad: bodyPad,
    footerTopDoc: docBottom(document.querySelector('main')),
    footerDocBottom: docBottom(document.querySelector('.site-footer')),
    noteDocBottom: docBottom(document.querySelector('.footer-note')),
    footerViewBottom: viewBottom(document.querySelector('.site-footer')),
    noteViewBottom: viewBottom(document.querySelector('.footer-note')),
    tabbarViewTop: viewTop(bar),
    tabbarShown: !!bar && getComputedStyle(bar).display !== 'none',
  };
}"""


def _bottom_checks(m, *, short):
    # The footer must end exactly at the reserved band: nothing between the footer
    # edge and the space the fixed tab bar covers (desktop reserves nothing).
    gap = m["scrollHeight"] - m["footerDocBottom"]
    assert abs(gap - m["bodyPad"]) <= 1.5, (
        f"footer bottom {m['footerDocBottom']:.1f} vs scrollHeight {m['scrollHeight']}"
        f" leaves a {gap:.1f}px band (body pad {m['bodyPad']:.0f}px)"
    )
    if short:
        assert m["scrollHeight"] <= m["innerHeight"] + 2, (
            f"a short page must not scroll: scrollHeight {m['scrollHeight']} > viewport {m['innerHeight']}"
        )
    if m["tabbarShown"]:
        # The bar's own hairline border can overlap the footer's bottom padding edge
        # by ~1px; the last LINE of the footer must stay clear.
        assert m["footerViewBottom"] <= m["tabbarViewTop"] + 2.5, (
            f"footer bottom {m['footerViewBottom']:.1f} tucks under the tab bar top {m['tabbarViewTop']:.1f}"
        )
        assert m["noteViewBottom"] <= m["tabbarViewTop"] + 0.5, (
            f"the tab bar covers the footer's last line (note bottom {m['noteViewBottom']:.1f}"
            f" vs bar top {m['tabbarViewTop']:.1f})"
        )


def test_short_page_keeps_the_footer_at_the_bottom(browser, base_url):
    # The empty activity search result is the shortest real page of the site.
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        page.goto(base_url + "activity.html?q=zzzzqqq9999", wait_until="load")
        page.wait_for_selector(".site-footer")
        page.wait_for_timeout(300)
        for width, height in ((390, 844), (820, 1180), (1440, 900)):
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_timeout(250)
            _bottom_checks(page.evaluate(MEASURE), short=True)
    finally:
        page.close()


def test_long_page_keeps_the_footer_last(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        page.goto(base_url + "index.html", wait_until="load")
        page.wait_for_selector(".site-footer")
        page.wait_for_timeout(300)
        for width, height in ((390, 844), (1440, 900)):
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_timeout(250)
            m = page.evaluate(MEASURE)
            assert m["scrollHeight"] > m["innerHeight"] + 10, (
                f"the home page should still scroll at {width}px"
            )
            _bottom_checks(m, short=False)
    finally:
        page.close()


def test_tab_bar_stays_clear_of_the_footer_in_dark_mode(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        page.goto(base_url + "activity.html?q=zzzzqqq9999", wait_until="load")
        page.wait_for_selector(".site-footer")
        page.click("#themeToggle")
        page.wait_for_timeout(150)
        assert page.evaluate("() => document.documentElement.getAttribute('data-theme')") == "dark"
        _bottom_checks(page.evaluate(MEASURE), short=True)
    finally:
        page.close()
