"""#7702 follow-up: build-time prerender, thumbnails, media lightbox, and CLS."""
from __future__ import annotations

import http.server
import importlib.util
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
_spec = importlib.util.spec_from_file_location("prerender", ROOT / "scripts" / "prerender.py")
prerender = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prerender)
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


BUILD_DIR = None


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


def test_dist_prerenders_home_and_policy(build_dir):
    index = (build_dir / "index.html").read_text(encoding="utf-8")
    assert 'class="key-activity-card"' in index
    assert "./activity#a-2026-11-04-01" in index
    assert "보건복지위원회" in index
    assert 'class="col-item"' in index
    assert "./static/images/media-01.jpg" in index
    assert "./static/images/thumbs/media-01-320.webp" in index
    assert 'class="col-tile"' in index
    assert "전체 의정활동 보기" in index

    policy = (build_dir / "policy.html").read_text(encoding="utf-8")
    assert 'class="info-card"' in policy
    assert 'class="bill-group"' in policy
    assert "<details" in policy and "제8대" in policy
    assert "제9대" in policy

    media = (build_dir / "media.html").read_text(encoding="utf-8")
    assert 'class="media-tile"' in media
    assert "media-01" in media
    assert "tile-thumb" in media

    thumbs = list((build_dir / "static" / "images" / "thumbs").glob("*.webp"))
    assert len(thumbs) >= 20
    home_js = (build_dir / "static" / "home.js").read_text(encoding="utf-8")
    assert "./activity#" in home_js


def test_media_lightbox_opens_and_returns_focus(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        page.goto(base_url + "media.html", wait_until="load")
        page.wait_for_selector(".media-tile")
        first = page.locator(".media-tile").first
        first.click()
        page.wait_for_timeout(400)
        opened = page.evaluate(
            """() => {
              const dialog = document.getElementById('mediaLightbox');
              return {open: !!dialog?.open, src: document.getElementById('lightboxImg')?.src || '', title: document.getElementById('lightboxTitle')?.textContent || '', href: document.getElementById('lightboxLink')?.getAttribute('href') || ''};
            }"""
        )
        assert opened["open"] is True
        assert opened["src"].endswith("profile-portrait.webp")
        assert opened["title"]
        assert opened["href"].startswith("https://")
        await_page = page
        await_page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        closed = page.evaluate(
            """() => ({open: !!document.getElementById('mediaLightbox')?.open, active: document.activeElement === document.querySelector('.media-tile')})"""
        )
        assert closed["open"] is False
        assert closed["active"] is True
        first.click()
        page.wait_for_timeout(300)
        before = page.evaluate("() => document.getElementById('lightboxImg')?.src || ''")
        page.keyboard.press("ArrowRight")
        page.wait_for_timeout(300)
        after = page.evaluate("() => document.getElementById('lightboxImg')?.src || ''")
        assert before != after
    finally:
        page.close()


def test_dist_content_is_visible_without_javascript(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844}, java_script_enabled=False)
    try:
        page.goto(base_url + "index.html", wait_until="load")
        assert page.locator(".key-activity-card").count() >= 3
        assert "보건복지위원회" in page.locator("#keyActivities").inner_text()
        page.goto(base_url + "policy.html", wait_until="load")
        assert page.locator(".info-card").count() >= 3
        assert page.locator(".bill-group").count() >= 2
        page.goto(base_url + "media.html", wait_until="load")
        assert page.locator(".media-tile").count() >= 3
    finally:
        page.close()


@pytest.mark.parametrize("name", ["index.html", "policy.html", "media.html"])
def test_home_and_policy_cls_under_0_1(browser, base_url, name):
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        page.add_init_script(
            """(() => {
              window.__cls = 0;
              new PerformanceObserver((list) => {
                for (const entry of list.getEntries()) {
                  if (!entry.hadRecentInput) window.__cls += entry.value;
                }
              }).observe({type: 'layout-shift', buffered: true});
            })();"""
        )
        page.goto(base_url + name, wait_until="load")
        page.wait_for_timeout(1500)
        cls = page.evaluate("() => window.__cls")
        assert cls < 0.1, f"{name} CLS {cls}"
    finally:
        page.close()


def test_prerender_only_links_http_or_relative():
    data = {
        "activity": {
            "items": [
                {
                    "id": "a-2026-01-01-01",
                    "date": "2026-01-01",
                    "tag": "위원회",
                    "title": "테스트 활동",
                    "body": "본문",
                    "thumb": None,
                    "url": "mailto:test@example.com",
                }
            ]
        },
        "media": {
            "tiles": [
                {"kind": "프로필", "title": "프로필", "url": "./about", "thumb": "./static/images/profile-portrait.webp", "notes": []},
                {"kind": "포토", "title": "사진", "url": "mailto:test@example.com", "thumb": "./static/images/media-01.jpg", "notes": []},
            ]
        },
    }
    home = prerender.prerender_home(data)
    assert 'href="mailto:' not in home["homeMedia"]
    assert "사진" in home["homeMedia"]

    media = prerender.prerender_media(data)
    assert 'href="mailto:' not in media
    assert "사진" in media

    policy = prerender.prerender_policy(
        {
            "policy": {
                "forums": [{"date": "2026-01-01", "title": "토론회", "summary": "요약", "url": "mailto:z"}],
                "videos": [],
                "bills": [{"assembly": 9, "number": "9-1", "title": "조례", "date": "2026-01-01", "result": "원안가결", "url": "#"}],
            }
        }
    )
    assert 'href="mailto:' not in policy["policyForums"]
    assert 'href="#"' not in policy["policyBills"]
    assert "토론회" in policy["policyForums"]
    assert "조례" in policy["policyBills"]