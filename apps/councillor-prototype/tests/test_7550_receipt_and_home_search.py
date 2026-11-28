"""#7550 (third visit): the feedback receipt notice and the home first-screen
search, measured from the dist build in a real browser where it matters."""
from __future__ import annotations

import http.server
import os
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import unquote

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
RECEIPT = "보내 주셔서 고맙습니다. 사이트 오류·불편 의견은 확인 뒤 고치는 데 씁니다. 답장은 드리지 않습니다."


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


def test_index_carries_the_notice_and_the_search_form():
    sys.path.insert(0, str(ROOT / "scripts"))
    import assemble
    html = assemble.render("index.html")
    assert 'id="siteFeedbackDone"' in html and 'role="status"' in html and 'aria-live="polite"' in html
    assert RECEIPT in html
    assert 'id="siteFeedbackAgain"' in html
    assert '<form class="home-search" action="./activity.html" method="get"' in html
    assert 'name="q"' in html and 'name="scope" value="all"' in html
    assert 'class="home-search-alt"' not in html


def test_the_search_screens_read_the_forwarded_query():
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "function initialQueryParameter()" in js
    assert "search.value = query" in js
    assert "billSearch" in js and "search.oninput = applyFilter" in js and "applyFilter()" in js


def test_a_201_receipt_replaces_the_form_and_is_announced(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        page.route("**/api/site-feedback", lambda route: route.fulfill(
            status=201, content_type="application/json", body='{"ok": true}'))
        page.goto(base_url + "index.html", wait_until="load")
        page.click("#siteFeedbackOpen")
        page.fill("#siteFeedbackBody", "320에서 첫 화면이 길어요")
        page.click(".site-feedback-send")
        page.wait_for_selector("#siteFeedbackDone:not([hidden])")
        notice = page.evaluate(
            """() => { const n = document.getElementById('siteFeedbackDone');
                       return {text: n.textContent, live: n.getAttribute('aria-live'),
                               role: n.getAttribute('role'),
                               formHidden: document.getElementById('siteFeedbackForm').hidden}; }"""
        )
        assert RECEIPT in notice["text"]
        assert notice["live"] == "polite" and notice["role"] == "status"
        assert notice["formHidden"] is True
        # The way back: the form returns empty and the notice goes away.
        page.click("#siteFeedbackAgain")
        page.wait_for_selector("#siteFeedbackForm:not([hidden])")
        assert page.evaluate("() => document.getElementById('siteFeedbackDone').hidden") is True
        assert page.evaluate("() => document.getElementById('siteFeedbackBody').value") == ""
        page.unroute("**/api/site-feedback")
    finally:
        page.close()


def test_a_failure_keeps_the_form_with_the_office_contact(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        page.route("**/api/site-feedback", lambda route: route.fulfill(
            status=500, content_type="application/json", body='{"ok": false}'))
        page.goto(base_url + "index.html", wait_until="load")
        page.click("#siteFeedbackOpen")
        page.fill("#siteFeedbackBody", "페이지 오류 신고")
        page.click(".site-feedback-send")
        page.wait_for_timeout(300)
        status = page.evaluate("() => document.getElementById('siteFeedbackStatus').textContent")
        assert "보내지 못했습니다" in status
        assert "의원실 전화(062-613-5133)" in status
        assert page.evaluate("() => document.getElementById('siteFeedbackForm').hidden") is False
        assert page.evaluate("() => document.getElementById('siteFeedbackDone').hidden") is True
        page.unroute("**/api/site-feedback")
    finally:
        page.close()


def test_the_home_search_lands_in_the_existing_searches(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        page.goto(base_url + "index.html", wait_until="load")
        page.fill(".home-search-input", "주차")
        page.click(".home-search-go")
        page.wait_for_url(lambda url: "activity.html" in url and "q=" in url)
        # The page's own search control carries the forwarded query and the
        # existing renderer ran it.
        assert page.evaluate("() => document.getElementById('activitySearch').value") == "주차"
        assert page.locator("#activityList .activity-item:visible").count() >= 1
        # #8723: an empty policy group is no longer shown beside real activity hits.
        assert page.locator("#combinedPolicy").is_hidden()
        assert page.locator("#combinedActivityHeading").is_visible()

        page.goto(base_url + "index.html", wait_until="load")
        page.fill(".home-search-input", "조례")
        page.click(".home-search-go")
        page.wait_for_url(lambda url: "activity.html" in url and "q=" in url)
        page.wait_for_selector("#combinedPolicyList a")
        assert "조례" in page.locator("#combinedPolicyList").inner_text()
        page.goto(base_url + "policy.html?q=조례", wait_until="load")
        page.wait_for_function("document.getElementById('billSearch').value === '조례'")
    finally:
        page.close()


def test_bill_search_updates_group_counts_and_announces_results(browser, base_url):
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        page.goto(base_url + "policy.html", wait_until="load")
        page.wait_for_selector('#policyBills .bill-group[data-assembly="9"]')
        nine = page.locator('#policyBills .bill-group[data-assembly="9"]')
        eight = page.locator('#policyBills .bill-group[data-assembly="8"]')
        assert nine.locator(".bill-count").inner_text() == "29건"
        assert eight.locator(".bill-count").inner_text() == "32건"
        page.fill("#billSearch", "관광")
        assert nine.locator(".bill-count").inner_text() == "3건 / 전체 29건"
        assert eight.locator(".bill-count").inner_text() == "검색 결과 없음"
        assert page.locator("#policyBills .bill-row:visible").count() == 3
        assert page.locator("#billSearchStatus").inner_text() == "61건 중 3건 (제9대 3 · 제8대 0)"
        page.fill("#billSearch", "no-record-xyz-261125")
        assert nine.locator(".bill-count").inner_text() == "검색 결과 없음"
        assert eight.locator(".bill-count").inner_text() == "검색 결과 없음"
        assert page.locator("#policyBills .bill-row:visible").count() == 0
        assert page.locator("#billSearchStatus").inner_text() == "검색 결과가 없습니다. 전체 61건."
        page.fill("#billSearch", "")
        assert nine.locator(".bill-count").inner_text() == "29건"
        assert eight.locator(".bill-count").inner_text() == "32건"
        assert page.locator("#billSearchStatus").inner_text() == "61건 중 61건 (제9대 29 · 제8대 32)"
    finally:
        page.close()


def test_the_home_search_works_without_scripts(browser, base_url):
    context = browser.new_context(java_script_enabled=False, viewport={"width": 390, "height": 844})
    page = context.new_page()
    try:
        page.goto(base_url + "index.html", wait_until="load")
        page.fill(".home-search-input", "주차")
        page.click(".home-search-go")
        page.wait_for_url(lambda url: "activity.html" in url and "q=" in url)
        assert "주차" in unquote(page.url)

        page.goto(base_url + "index.html", wait_until="load")
        page.fill(".home-search-input", "조례")
        page.click(".home-search-go")
        page.wait_for_url(lambda url: "activity.html" in url and "q=" in url and "scope=all" in url)
        assert "조례" in unquote(page.url)
    finally:
        page.close()
        context.close()


def test_the_first_screen_has_no_horizontal_overflow(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        for width in (320, 390, 1440):
            for theme in ("light", "dark"):
                page.goto(base_url + "index.html", wait_until="load")
                current = page.evaluate("() => document.documentElement.getAttribute('data-theme')")
                if current != theme:
                    page.click("#themeToggle")
                    page.wait_for_timeout(100)
                page.set_viewport_size({"width": width, "height": 900})
                page.wait_for_timeout(150)
                overflow = page.evaluate(
                    "() => ({scroll: document.documentElement.scrollWidth,"
                    " client: document.documentElement.clientWidth})")
                assert overflow["scroll"] <= overflow["client"] + 1, f"{theme} {width}px: {overflow}"
    finally:
        page.close()
