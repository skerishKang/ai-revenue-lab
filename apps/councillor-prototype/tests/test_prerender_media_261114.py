"""#7702 follow-up: build-time prerender, thumbnails, media lightbox, and CLS."""
from __future__ import annotations

import http.server
import importlib.util
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
import time

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

    def translate_path(self, path):
        # Cloudflare Pages serves extensionless HTML URLs in the build.
        local = super().translate_path(path)
        if not Path(local).exists() and Path(local + ".html").is_file():
            return local + ".html"
        return local

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

ACTIVITY_ITEMS = json.loads((ROOT / "static" / "miraen.json").read_text(encoding="utf-8"))["activity"]["items"]


def test_dist_activity_without_javascript(browser, base_url):
    page = browser.new_page(viewport={"width": 1440, "height": 900}, java_script_enabled=False)
    try:
        page.goto(base_url + "activity", wait_until="load")
        rows = page.locator("#activityList .activity-item[id]")
        assert rows.count() == len(ACTIVITY_ITEMS)
        for i, item in enumerate(ACTIVITY_ITEMS):
            row = rows.nth(i)
            assert row.is_visible()
            assert item["title"] in row.inner_text()
            assert item.get("body", "") in row.inner_text()
        print(f"NO_JS main_chars={len(page.locator('main').inner_text())} body_chars={len(page.locator('body').inner_text())} rows={rows.count()}")
    finally:
        page.close()


@pytest.mark.parametrize("width,height", [(390, 844), (1440, 900)])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_dist_activity_hydrates_and_filters_in_place(browser, base_url, width, height, theme):
    page = browser.new_page(viewport={"width": width, "height": height})
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    try:
        page.add_init_script("""
          (() => {
            localStorage.setItem('theme', '%s');
            window.__cls = 0;
            new PerformanceObserver(list => {
              for (const entry of list.getEntries()) {
                if (!entry.hadRecentInput) window.__cls += entry.value;
              }
            }).observe({type: 'layout-shift', buffered: true});
            const observer = new MutationObserver(() => {
              const row = document.querySelector('#activityList .activity-item[id]');
              if (row) { window.__originalActivity = row; observer.disconnect(); }
            });
            observer.observe(document, {childList: true, subtree: true});
          })();
        """ % theme)
        page.goto(base_url + "activity", wait_until="load")
        page.wait_for_selector('#activityList[data-activity-ready="true"]')
        page.wait_for_timeout(1500)
        state = page.evaluate("""() => ({
          cls: window.__cls,
          overflow: document.documentElement.scrollWidth - innerWidth,
          same: window.__originalActivity === document.querySelector('#activityList .activity-item[id]'),
          body: getComputedStyle(document.querySelector('.item-title')).fontSize,
          label: getComputedStyle(document.querySelector('.item-tag')).fontSize,
          tap: document.querySelector('.activity-item').getBoundingClientRect().height,
          theme: document.documentElement.dataset.theme
        })""")
        print(f"ACTIVITY {width} {theme} {state} errors={len(errors)}")
        assert state["same"] and state["theme"] == theme
        assert state["overflow"] <= 0 and state["cls"] < 0.1
        assert state["body"] == "16px" and state["label"] == "14px" and state["tap"] >= 44
        rows = page.locator("#activityList .activity-item[id^='a-']")
        visible = page.locator("#activityList .activity-item[id^='a-']:visible")
        assert rows.count() == visible.count() == len(ACTIVITY_ITEMS)
        search = page.locator("#activitySearch")
        search.fill("\ud1a0\ub860")
        expected = [a["id"] for a in ACTIVITY_ITEMS if "\ud1a0\ub860" in a["title"] or "\ud1a0\ub860" in a.get("body", "")]
        assert visible.evaluate_all("(rows) => rows.map(row => row.id)") == expected
        search.fill("no-record-xyz-261124")
        assert visible.count() == 0
        assert page.locator("#activityEmpty").is_visible()
        assert page.locator("#activityEmpty").inner_text() == "\uac80\uc0c9 \uacb0\uacfc\uac00 \uc5c6\uc2b5\ub2c8\ub2e4."
        search.fill("")
        tag = ACTIVITY_ITEMS[0]["tag"]
        page.locator("#activityFilter").select_option(tag)
        assert visible.count() == sum(a["tag"] == tag for a in ACTIVITY_ITEMS)
        page.locator("#activityFilter").select_option("all")
        assert page.evaluate("window.__originalActivity === document.querySelector('#activityList .activity-item[id]')")
        visible.first.click()
        assert page.locator("#activityDetail").is_visible()
        assert page.locator("#detailTitle").inner_text() == ACTIVITY_ITEMS[0]["title"]
        assert page.locator("#detailTitle").evaluate("(el) => el === document.activeElement")
        assert page.locator("#detailBody").evaluate("(el) => getComputedStyle(el).fontSize") == "16px"
        assert page.locator("#activityBack").bounding_box()["height"] >= 44
        page.keyboard.press("Escape")
        page.wait_for_selector("#activityList", state="visible")
        assert page.locator("#activityDetail").is_hidden()
        assert page.evaluate("location.hash") == ""
        assert not errors
    finally:
        page.close()


def test_dist_activity_clean_deep_link_and_home_card(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        first = ACTIVITY_ITEMS[0]
        page.goto(base_url + "activity#" + first["id"], wait_until="load")
        page.wait_for_selector("#activityDetail", state="visible")
        assert page.locator("#detailTitle").inner_text() == first["title"]
        page.wait_for_function("document.activeElement.id === 'detailTitle'")
        page.keyboard.press("Escape")
        page.wait_for_selector("#activityList", state="visible")
        page.goto(base_url + "index.html", wait_until="load")
        page.locator(".key-activity-card").first.click()
        page.wait_for_selector("#activityDetail", state="visible")
        assert page.evaluate("location.pathname + location.hash") == "/activity#" + first["id"]
        assert page.locator("#detailTitle").inner_text() == first["title"]
    finally:
        page.close()

@pytest.mark.parametrize("width,height", [(390, 844), (820, 1180), (1440, 900)])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_senior_media_and_readability(browser, base_url, width, height, theme):
    context = browser.new_context(viewport={"width": width, "height": height})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.add_init_script("""(() => {
      localStorage.setItem('theme', '%s');
      window.__cls = 0;
      new PerformanceObserver(l => {for (const e of l.getEntries()) if (!e.hadRecentInput) window.__cls += e.value})
        .observe({type:'layout-shift', buffered:true});
    })()""" % theme)
    evidence = os.environ.get("COUNCILLOR_QA_8673")
    try:
        for name, selector in (("index.html", "#homeMedia .col-item"), ("media.html", ".media-tile"), ("activity.html", "#activityList .activity-item"), ("about.html", ".profile-list")):
            page.goto(base_url + name, wait_until="load")
            page.wait_for_selector(selector)
            page.wait_for_timeout(1100)
            state = page.evaluate("() => ({cls: window.__cls, overflow: document.documentElement.scrollWidth-innerWidth})")
            print("SENIOR", width, theme, name, state, "errors", len(errors), flush=True)
            assert state["overflow"] <= 0 and state["cls"] < 0.1
            assert not errors
            if evidence:
                Path(evidence).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(evidence) / f"{width}-{theme}-{name}.png"), full_page=True)
            if name in ("index.html", "media.html"):
                card = page.locator(selector).first
                source = card.locator("xpath=following-sibling::a[contains(@class, 'media-source')]")
                assert source.bounding_box()["width"] >= 44 and source.bounding_box()["height"] >= 44
                card.locator("img").click()
                page.wait_for_selector("#mediaLightbox[open]")
                assert len(context.pages) == 1
                assert page.locator("#lightboxTitle").inner_text() == card.get_attribute("data-media-title")
                original = page.locator("#lightboxImg").get_attribute("src")
                page.locator("#lightboxNext").click()
                assert page.locator("#lightboxImg").get_attribute("src") != original
                page.locator("#lightboxPrev").click()
                assert page.locator("#lightboxImg").get_attribute("src") == original
                if evidence:
                    page.screenshot(path=str(Path(evidence) / f"{width}-{theme}-{name}-lightbox.png"))
                page.keyboard.press("Escape")
                page.wait_for_selector("#mediaLightbox", state="hidden")
                assert card.evaluate("(el) => el === document.activeElement")
                card.click()
                page.locator("#lightboxClose").click()
                assert card.evaluate("(el) => el === document.activeElement")
            if name == "index.html":
                assert page.locator(".home-search button").count() == 1
                phone = page.locator(".office-number")
                assert phone.evaluate("(e) => parseFloat(getComputedStyle(e).fontSize)") >= 20
                assert phone.locator("xpath=..").bounding_box()["height"] >= 44
            if name == "about.html":
                phone = page.locator('.profile-list a[href^="tel:"]')
                assert phone.evaluate("(e) => parseFloat(getComputedStyle(e).fontSize)") >= 20
                assert phone.bounding_box()["height"] >= 44
            if name == "activity.html":
                assert page.locator("#activityLegend > span").count() == 7
                assert page.locator("#activityLegend").evaluate("(e) => getComputedStyle(e).fontSize") == "16px"
                page.locator("#a-2026-11-04-01").click()
                assert page.locator("#detailTerms").is_visible()
                assert "행정사무감사" in page.locator("#detailTerms").inner_text()
        assert not errors
    finally:
        context.close()


def test_prerender_media_works_before_data_fetch(browser, base_url):
    context = browser.new_context(viewport={"width": 820, "height": 1180})
    page = context.new_page()
    # Keep the fetch pending until the photo interaction has happened.
    page.route("**/miraen.json", lambda route: None)
    try:
        for name, selector in (("index.html", "#homeMedia .col-item"), ("media.html", ".media-tile")):
            page.goto(base_url + name, wait_until="domcontentloaded")
            card = page.locator(selector).first
            card.locator("img").click()
            assert page.locator("#mediaLightbox").evaluate("(e) => e.open")
            assert len(context.pages) == 1
            page.keyboard.press("Escape")
            page.wait_for_selector("#mediaLightbox", state="hidden")
            assert card.evaluate("(e) => e === document.activeElement")
    finally:
        context.close()
