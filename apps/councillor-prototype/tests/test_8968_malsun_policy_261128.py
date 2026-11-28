# -*- coding: utf-8 -*-
"""#8968 말순 4회차: 검색 초점·조례안 풀이·원문 이름·새 소식 회귀."""
from __future__ import annotations

import http.server
import json
from pathlib import Path
import re
import subprocess
import sys
import threading

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
TERMS = {
    "대표발의": "의원이 앞장서 낸 조례안",
    "원안가결": "낸 그대로 통과됨",
    "수정가결": "고쳐서 통과됨",
}
NEWS_LINE = "정책자료 조례안 말에 쉬운 풀이를 붙이고, '조례안 찾기'로 바로 검색할 수 있습니다."


@pytest.fixture(scope="module")
def site():
    assert CHROME.is_file(), "실제 Chrome으로 확인해야 합니다"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build-dist")], check=True)
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ROOT / "dist"), **kwargs)
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
        assert page.evaluate("location.hash") == "#billSearch"
        check = page.locator("#billSearch").evaluate("""input => {
          const box = input.getBoundingClientRect(), css = getComputedStyle(input);
          return {visible: box.top >= 0 && box.bottom <= innerHeight,
            outline: css.outlineStyle, width: parseFloat(css.outlineWidth),
            focusVisible: input.matches(':focus-visible')};
        }""")
        assert check["visible"] and check["focusVisible"], check
        assert check["outline"] != "none" and check["width"] >= 2, check
    finally:
        page.close()


def test_policy_bill_terms_are_exact_and_prerendered(site):
    data = json.loads((ROOT / "static" / "miraen.json").read_text(encoding="utf-8"))
    assert data["policy"]["glossary"]["terms"] == TERMS
    page = open_page(site, "policy.html", javascript=False)
    try:
        glossary = page.locator("#policyBillTerms")
        assert "activity-terms" in (glossary.get_attribute("class") or "")
        assert glossary.locator("p").all_text_contents() == [
            f"{term} — {meaning}" for term, meaning in TERMS.items()
        ]
        assert page.evaluate("""() => {
          const g = document.querySelector('#policyBillTerms');
          const b = document.querySelector('#policyBills');
          return !!g && !!b && !!(g.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
        }""")
    finally:
        page.close()


def test_all_visible_source_links_use_council_original_label(site):
    for name in ("index.html", "activity.html", "policy.html", "media.html", "about.html", "news.html", "404.html"):
        html = (ROOT / "dist" / name).read_text(encoding="utf-8")
        assert not re.search(r">\s*원문 보기(?:\s*↗)?\s*<", html), name
    policy = open_page(site, "policy.html")
    media = open_page(site, "media.html", width=390, height=844)
    try:
        assert "의회 원문 보기" in policy.locator("#policyForums").inner_text()
        assert "공식 페이지 보기" in (ROOT / "dist" / "activity.html").read_text(encoding="utf-8")
        media.locator(".media-tile").nth(1).click()
        media.locator("#mediaLightbox[open]").wait_for()
        assert media.locator("#lightboxLink").inner_text() == "의회 원문 보기 ↗"
        assert media.locator("#lightboxLink").get_attribute("aria-label") == "의회 원문 보기 (새 탭)"
    finally:
        policy.close()
        media.close()


def test_november_28_news_last_change_is_exact(site):
    data = json.loads((ROOT / "static" / "miraen.json").read_text(encoding="utf-8"))
    entry = next(item for item in data["news"] if item["date"] == "2026-11-28")
    assert entry["changes"][-1] == NEWS_LINE
    page = open_page(site, "news.html", javascript=False)
    try:
        article = page.locator("#siteChangeList .site-change").first
        assert article.locator("time").get_attribute("datetime") == "2026-11-28"
        assert article.locator("li").last.inner_text() == NEWS_LINE
    finally:
        page.close()
