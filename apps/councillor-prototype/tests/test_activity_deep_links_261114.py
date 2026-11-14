"""#7702 — activity detail URLs, theme wording, and the activity list affordances."""

from __future__ import annotations

import http.server
import json
import os
import re
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

DATA = json.loads((ROOT / "static" / "miraen.json").read_text(encoding="utf-8"))
ITEMS = DATA["activity"]["items"]
APP_JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
HOME_JS = (ROOT / "static" / "home.js").read_text(encoding="utf-8")
ACTIVITY_HTML = (ROOT / "activity.html").read_text(encoding="utf-8")


class StaticHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def guess_type(self, path):
        value = super().guess_type(path)
        return "text/html; charset=utf-8" if path.endswith(".html") else value

    def log_message(self, *_args):
        pass


class StaticServer(http.server.ThreadingHTTPServer):
    request_queue_size = 256
    daemon_threads = True


@pytest.fixture(scope="module")
def base_url():
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


def _open_activity(page, base_url, hash_value=""):
    page.goto(base_url + "activity.html" + hash_value, wait_until="load")
    page.wait_for_function(
        "() => document.getElementById('activityList') && document.getElementById('activityList').children.length > 0",
        timeout=15000,
    )
    page.wait_for_timeout(350)


def test_every_activity_has_a_stable_unique_id():
    ids = [item.get("id") for item in ITEMS]
    assert all(re.fullmatch(r"a-\d{4}-\d{2}-\d{2}-\d{2}", str(value)) for value in ids), ids
    assert len(ids) == len(set(ids)), "activity ids must be unique"
    keys = [(item["date"], item["title"]) for item in ITEMS]
    assert len(keys) == len(set(keys)), "two records share a date and title"


def test_home_cards_link_to_activity_detail():
    assert 'card.href = "./activity.html#" + activityId(a);' in HOME_JS
    assert "const activityId = (a) => a.id ||" in HOME_JS


def test_activity_detail_opens_from_url_and_focuses_title(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        first = ITEMS[0]
        _open_activity(page, base_url, "#" + first["id"])
        state = page.evaluate(
            """() => ({
              hash: location.hash,
              listHidden: document.getElementById('activityList').hidden,
              detailHidden: document.getElementById('activityDetail').hidden,
              title: document.getElementById('detailTitle').textContent,
              active: document.activeElement.id,
              overflow: document.documentElement.scrollWidth > innerWidth
            })"""
        )
        assert state["hash"] == "#" + first["id"]
        assert state["listHidden"] is True
        assert state["detailHidden"] is False
        assert state["title"] == first["title"]
        assert state["active"] == "detailTitle"
        assert state["overflow"] is False
    finally:
        page.close()


def test_list_click_updates_hash_and_back_returns(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        _open_activity(page, base_url)
        first = ITEMS[0]
        page.locator(".activity-item").first.click()
        page.wait_for_timeout(400)
        opened = page.evaluate(
            """() => ({hash: location.hash, listHidden: document.getElementById('activityList').hidden, detailHidden: document.getElementById('activityDetail').hidden})"""
        )
        assert opened["hash"] == "#" + first["id"]
        assert opened["listHidden"] is True
        assert opened["detailHidden"] is False
        page.locator("#activityBack").click()
        page.wait_for_timeout(600)
        back = page.evaluate(
            """() => ({hash: location.hash, listHidden: document.getElementById('activityList').hidden, detailHidden: document.getElementById('activityDetail').hidden})"""
        )
        assert back["hash"] == ""
        assert back["listHidden"] is False
        assert back["detailHidden"] is True
    finally:
        page.close()


def test_unknown_activity_shows_list_and_message(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        _open_activity(page, base_url, "#a-0000-00-00-00")
        state = page.evaluate(
            """() => ({
              hash: location.hash,
              listHidden: document.getElementById('activityList').hidden,
              detailHidden: document.getElementById('activityDetail').hidden,
              status: document.getElementById('activityStatus').textContent,
              statusHidden: document.getElementById('activityStatus').hidden
            })"""
        )
        assert state["hash"] == "#a-0000-00-00-00"
        assert state["listHidden"] is False
        assert state["detailHidden"] is True
        assert state["status"] == "찾는 활동이 없습니다."
        assert state["statusHidden"] is False
    finally:
        page.close()


def test_theme_button_copy_toggles(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        _open_activity(page, base_url)
        initial = page.evaluate(
            """() => ({text: document.getElementById('themeToggle').textContent, aria: document.getElementById('themeToggle').getAttribute('aria-label'), pressed: document.getElementById('themeToggle').getAttribute('aria-pressed')})"""
        )
        assert initial == {
            "text": "어둡게 보기",
            "aria": "어두운 화면으로 보기",
            "pressed": "false",
        }
        page.locator("#themeToggle").click()
        page.wait_for_timeout(250)
        dark = page.evaluate(
            """() => ({text: document.getElementById('themeToggle').textContent, aria: document.getElementById('themeToggle').getAttribute('aria-label'), pressed: document.getElementById('themeToggle').getAttribute('aria-pressed')})"""
        )
        assert dark == {
            "text": "밝게 보기",
            "aria": "밝은 화면으로 보기",
            "pressed": "true",
        }
    finally:
        page.close()


def test_activity_legend_and_more_marker_are_visible(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        _open_activity(page, base_url)
        state = page.evaluate(
            """() => ({
              legend: (document.querySelector('.activity-legend') || {}).innerText || '',
              more: (document.querySelector('.activity-item .item-more') || {}).innerText || '',
              moreVisible: !!document.querySelector('.activity-item .item-more')
            })"""
        )
        assert "본회의" in state["legend"] and "본회의장에서 한 발언" in state["legend"]
        assert "5분발언" in state["legend"] and "5분 동안 하는 자유발언" in state["legend"]
        assert "위원회" in state["legend"] and "상임위원회에서 한 활동" in state["legend"]
        assert state["moreVisible"] is True
        assert state["more"] == "자세히 ›"
    finally:
        page.close()


@pytest.mark.parametrize("width,height", [(390, 844), (1440, 900)])
def test_no_horizontal_overflow_in_light_and_dark(browser, base_url, width, height):
    page = browser.new_page(viewport={"width": width, "height": height})
    try:
        _open_activity(page, base_url, "#" + ITEMS[0]["id"])
        for theme in ("light", "dark"):
            page.evaluate("theme => document.documentElement.setAttribute('data-theme', theme)", theme)
            page.wait_for_timeout(150)
            overflow = page.evaluate("() => document.documentElement.scrollWidth > innerWidth")
            assert overflow is False, f"{width}x{height} {theme} overflows"
    finally:
        page.close()