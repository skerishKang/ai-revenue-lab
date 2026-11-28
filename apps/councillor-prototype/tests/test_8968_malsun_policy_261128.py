# -*- coding: utf-8 -*-
"""#8968 말순 4회차: 브라우저 동작과 무자바스크립트 정적 계약."""
from __future__ import annotations

import http.server
from html import escape
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading

import pytest

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

ROOT = Path(__file__).resolve().parents[1]
CHROME = next((
    Path(value) for value in (
        os.environ.get("B61_CHROME_PATH"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ) if value and Path(value).is_file()
), None)
TERMS = {
    "대표발의": "의원이 앞장서 낸 조례안",
    "원안가결": "낸 그대로 통과됨",
    "수정가결": "고쳐서 통과됨",
}
NEWS_LINE = "정책자료 조례안 말에 쉬운 풀이를 붙이고, '조례안 찾기'로 바로 검색할 수 있습니다."


@pytest.fixture(scope="module")
def dist():
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build-dist")], check=True)
    return ROOT / "dist"


@pytest.fixture(scope="module")
def site(dist):
    if sync_playwright is None or CHROME is None:
        pytest.skip("계약 CI는 정적 검증, Chrome이 있는 브라우저 환경에서 동작 검증")
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(dist), **kwargs)
        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, executable_path=str(CHROME))
            try:
                yield browser, f"http://127.0.0.1:{server.server_port}/"
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


def open_page(site, name, width=1440, height=900, javascript=True):
    browser, base = site
    page = browser.new_page(
        viewport={"width": width, "height": height},
        java_script_enabled=javascript,
        reduced_motion="reduce",
        color_scheme="light",
    )
    page.goto(base + name, wait_until="load")
    if javascript:
        page.evaluate("document.fonts.ready")
    return page


def test_policy_bill_chip_moves_focus_to_visible_search_field(site):
    page = open_page(site, "policy.html", width=820, height=1180)
    try:
        page.locator("#textSizeToggle").click()
        assert page.locator("html").get_attribute("data-text-size") == "large"
        jump = page.get_by_role("navigation", name="정책자료 바로가기")
        assert jump.get_by_role("link", name="정책토론회").get_attribute("href") == "#policyForumsTitle"
        assert jump.get_by_role("link", name="발언 영상").get_attribute("href") == "#policyVideosTitle"
        jump.get_by_role("link", name="조례안 찾기").click()
        assert page.evaluate("document.activeElement === document.getElementById('billSearch')")
        assert jump.get_by_role("link", name="조례안 찾기").get_attribute("href") == "#billSearch"
        check = page.locator("#billSearch").evaluate("""input => {
          const box = input.getBoundingClientRect(), css = getComputedStyle(input);
          return {visible: box.top >= 0 && box.bottom <= innerHeight,
            outline: css.outlineStyle, width: parseFloat(css.outlineWidth),
            unobscured: box.top >= document.querySelector('.topbar').getBoundingClientRect().bottom + 4
              && document.elementFromPoint(box.left + 20, box.top + box.height / 2) === input,
            focusVisible: input.matches(':focus-visible')};
        }""")
        assert check["visible"] and check["unobscured"] and check["focusVisible"], check
        assert check["outline"] != "none" and check["width"] >= 2, check
    finally:
        page.close()


def test_policy_bill_terms_data_and_static_prerender(dist):
    data = json.loads((ROOT / "static" / "miraen.json").read_text(encoding="utf-8"))
    assert data["policy"]["glossary"]["terms"] == TERMS
    html = (dist / "policy.html").read_text(encoding="utf-8")
    assert '<div class="activity-terms" id="policyBillTerms" role="note"' in html
    assert html.index('id="billSearch"') < html.index('id="policyBillTerms"') < html.index('id="policyBills"')
    contents = html.split('id="policyBillTerms"', 1)[1].split("</div>", 1)[0]
    assert contents.count("<p>") == 3
    positions = [contents.index(f"<p><b>{term}</b> — {meaning}</p>") for term, meaning in TERMS.items()]
    assert positions == sorted(positions)


def test_bill_terms_visible_without_javascript(site):
    page = open_page(site, "policy.html", javascript=False)
    try:
        assert page.locator("#policyBillTerms p").all_text_contents() == [
            f"{term} — {meaning}" for term, meaning in TERMS.items()
        ]
    finally:
        page.close()


def test_all_built_source_links_use_council_original_label(dist):
    for name in ("index.html", "activity.html", "policy.html", "media.html", "about.html", "news.html", "404.html"):
        html = (dist / name).read_text(encoding="utf-8")
        assert not re.search(r">\s*원문 보기(?:\s*↗)?\s*<", html), name
    assert "의회 원문 보기" in (dist / "policy.html").read_text(encoding="utf-8")
    for name in ("index.html", "media.html"):
        assert ">의회 원문 보기 ↗</a>" in (dist / name).read_text(encoding="utf-8")
    assert "공식 페이지 보기" in (dist / "activity.html").read_text(encoding="utf-8")


def test_photo_lightbox_updates_link_and_accessible_name(site):
    page = open_page(site, "media.html", width=390, height=844)
    try:
        page.locator(".media-tile").nth(1).click()
        page.locator("#mediaLightbox[open]").wait_for()
        assert page.locator("#lightboxLink").inner_text() == "의회 원문 보기 ↗"
        assert page.locator("#lightboxLink").get_attribute("aria-label") == "의회 원문 보기 (새 탭)"
    finally:
        page.close()


def test_november_28_news_last_change_is_exact_in_data_and_html(dist):
    source = (ROOT / "static" / "miraen.json").read_bytes()
    assert b"\r\n" not in source
    assert bytes.fromhex("EFBFBD") not in source
    assert not source.startswith(bytes.fromhex("EFBBBF"))
    data = json.loads(source)
    entry = next(item for item in data["news"] if item["date"] == "2026-11-28")
    assert entry["changes"][-1] == NEWS_LINE
    html = (dist / "news.html").read_text(encoding="utf-8")
    first = html.split('<article class="info-card site-change">', 1)[1].split("</article>", 1)[0]
    assert '<time datetime="2026-11-28">' in first
    assert f"<li>{escape(NEWS_LINE, quote=True)}</li>" in first
