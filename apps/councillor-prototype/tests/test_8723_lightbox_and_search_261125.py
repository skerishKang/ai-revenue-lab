"""#8723 (순영 2회차): lightbox clears the fixed tab bar, the two opinion
entrances have distinct names, and the home search hides empty result groups.
Browser checks run against the dist build at a 390px phone viewport."""
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
COUNCIL = "https://council.jeonnam-gwangju.go.kr/jngjassem/board/16"


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
    out = tmp_path_factory.mktemp("councillor-8723-dist")
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


def test_opinion_names_and_office_link_are_distinct():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "의회 홈페이지에 의견" in html and "의회에 의견 보내기" not in html
    assert "이 사이트 오류·불편 알리기" in html and "사이트 의견 보내기" not in html
    assert "의원님께 드리는 민원·제안은" in html and "의회 홈페이지로" in html
    assert html.count(COUNCIL) >= 2  # first-screen exit and the feedback notice
    news = (ROOT / "static" / "miraen.json").read_text(encoding="utf-8")
    assert "출처 안내가 아래 메뉴에 가리지 않게" in news
    assert "검색은 결과가 있는 묶음만 보여줍니다." in news
    assert "이 사이트 오류·불편 알리기" in news


def test_lightbox_source_and_link_clear_the_tab_bar_at_390(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        page.goto(base_url + "index.html", wait_until="load")
        page.wait_for_selector("[data-media-thumb]")
        page.click("[data-media-thumb]")
        page.wait_for_selector("#mediaLightbox[open]")
        geo = page.evaluate("""() => {
          const box = (el) => { const r = el.getBoundingClientRect();
            return { top: r.top, bottom: r.bottom, left: r.left, right: r.right }; };
          const tab = document.querySelector('.mobile-tabbar');
          const tabBox = box(tab);
          const overlap = (el) => { const r = box(el);
            return Math.max(0, Math.min(r.bottom, tabBox.bottom) - Math.max(r.top, tabBox.top)) *
                   Math.max(0, Math.min(r.right, tabBox.right) - Math.max(r.left, tabBox.left)); };
          const dialog = document.getElementById('mediaLightbox');
          const atTab = document.elementFromPoint(195, 821);
          return {
            linkOverlap: overlap(document.getElementById('lightboxLink')),
            sourceOverlap: overlap(document.getElementById('lightboxSource')),
            dialogZ: Number(getComputedStyle(dialog).zIndex),
            tabZ: Number(getComputedStyle(tab).zIndex),
            tabVisibility: getComputedStyle(tab).visibility,
            tabTop: tabBox.top,
            linkBottom: box(document.getElementById('lightboxLink')).bottom,
            sourceBottom: box(document.getElementById('lightboxSource')).bottom,
            topAtTab: atTab ? (atTab.id || atTab.className) : null,
            bodyClass: document.body.classList.contains('lightbox-open'),
          };
        }""")
        assert geo["linkOverlap"] == 0, geo
        assert geo["sourceOverlap"] == 0, geo
        assert geo["dialogZ"] > geo["tabZ"], geo
        assert geo["tabVisibility"] == "hidden" and geo["bodyClass"] is True, geo
        assert geo["linkBottom"] <= geo["tabTop"] and geo["sourceBottom"] <= geo["tabTop"], geo
        assert "lightbox" in str(geo["topAtTab"]), geo
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        assert page.evaluate("() => !document.getElementById('mediaLightbox').open") is True
        assert page.evaluate("() => !document.body.classList.contains('lightbox-open')") is True
        assert page.evaluate("() => getComputedStyle(document.querySelector('.mobile-tabbar')).visibility") == "visible"
    finally:
        page.close()


def _home_search(page, base_url, query):
    page.goto(base_url + "index.html", wait_until="load")
    page.fill(".home-search-input", query)
    page.click(".home-search-go")
    page.wait_for_url(lambda url: "activity.html" in url and "scope=all" in url)
    page.wait_for_function("() => document.querySelectorAll('#activityList .activity-item[id]').length > 0")
    page.wait_for_timeout(200)


def test_home_search_shows_only_non_empty_groups(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        # Activity hit, no policy hit: activity group only.
        _home_search(page, base_url, "주거")
        assert page.locator("#combinedActivityHeading").is_visible()
        assert page.locator("#activityList .activity-item:visible").count() == 1
        assert page.locator("#combinedPolicy").is_hidden()
        assert "검색 결과가 없습니다" not in page.locator("#activityList").inner_text()

        # Both groups hit: both stay visible.
        _home_search(page, base_url, "조례")
        assert page.locator("#combinedActivityHeading").is_visible()
        assert page.locator("#combinedPolicy").is_visible()
        assert page.locator("#combinedPolicyList .combined-policy-row").count() >= 1

        # No hit at all: one line only, no empty policy block.
        _home_search(page, base_url, "no-record-xyz-261125")
        assert page.locator("#combinedActivityHeading").is_hidden()
        assert page.locator("#combinedPolicy").is_hidden()
        assert page.locator("#activityEmpty").is_visible()
        assert page.locator("#activityList").inner_text().count("검색 결과가 없습니다") == 1
        assert page.locator("#activityList").get_attribute("aria-live") == "polite"
        assert page.locator("#combinedPolicyList").get_attribute("aria-live") == "polite"
    finally:
        page.close()
