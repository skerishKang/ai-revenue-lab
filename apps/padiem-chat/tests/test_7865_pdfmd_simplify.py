"""#7865 PDF→MD 화면 단순화 — 새 한 줄기 화면의 계약.

이슈 #7865의 바꿀 모양 1~5(머리 / 올리기 칸 / 결과 카드 / 여러 파일 ZIP /
접힌 지난 변환)과 없애거나 숨길 목록(검토 단추·작업 id·새 작업·작업 삭제·
변환 방식 필드·중복 요약·선택 ZIP)을 잠근다. 서버 동작은 바꾸지 않는다.

- 문구는 locale 소유가 아닌 이 화면의 대표 결정 문장이라 문자열로 잠는다
  (tests/README_테스트작성규칙.md §2 — locale 키가 없는 화면 문장).
- CSS 계약은 tests/css_rules.py 헬퍼로 판정한다(§1).
- 브라우저 동작(실패 카드에 받기 단추가 없다)은 시험 대역에서 실제로 클릭해
  확인한다(§2-1 "브라우저 동작이 판정 대상이면 Chromium에서 직접 호출").
"""

from __future__ import annotations

import http.server
import json
import os
import shutil
import threading
from pathlib import Path

import pytest

from css_rules import declaration, find_rules_with_selector, parse_rules

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover - CI without a browser
    sync_playwright = None

# #8060: shipped reads live in _support; the parsed CSS and copy checks stay.
from _support import pdfmd_simplify_source as sheets

STATIC = sheets.static_dir()
CHROME_CANDIDATES = [os.environ.get("B61_CHROME_PATH"),
                     r"C:\Program Files\Google\Chrome\Application\chrome.exe"]
CHROME = next((c for c in CHROME_CANDIDATES if c and Path(c).is_file()), None)


# ── 정적 계약: 없애거나 숨길 것이 사라졌다 ─────────────────────────────────


def test_the_review_flow_controls_are_gone() -> None:
    js = sheets.pdfmd_js()
    assert "검토 완료" not in js, "[검토 완료] 단추가 돌아왔다"
    assert '"/review"' not in js, "검토 경로 호출이 돌아왔다"
    assert "검토중" not in js, "검토중 배지가 돌아왔다"


def test_job_id_and_job_buttons_are_gone() -> None:
    js = sheets.pdfmd_js()
    assert 'pdfmd-jobid' not in js, "작업 id 표시가 돌아왔다"
    assert '"새 작업"' not in js, "[새 작업] 단추가 돌아왔다"
    assert "작업 삭제" not in js, "[작업 삭제] 단추가 돌아왔다"


def test_single_choice_mode_field_is_hidden_but_kept() -> None:
    """변환 방식은 한 줄로 숨겨 둔다 — 서버가 빠른·검증 두 방식을 모두 받으므로
    선택지를 완전히 없애면 검증 변환(페이지별 일치도 보고)이 사라진다."""
    js = sheets.pdfmd_js()
    assert 'modeSel.setAttribute("aria-label", "바꾸기 방식")' in js
    assert "pdfmd-mode-help" not in js, "긴 도움말 문단이 돌아왔다"


def test_select_zip_controls_are_gone() -> None:
    js = sheets.pdfmd_js()
    assert "ZIP에 포함" not in js, "'ZIP에 포함' 칸이 돌아왔다"
    assert "선택 항목 ZIP" not in js, "[선택 항목 ZIP]이 돌아왔다"


def test_the_duplicated_stage_summary_is_gone() -> None:
    js = sheets.pdfmd_js()
    assert "STAGE_LINES" not in js, "카드마다 찍히던 단계 문구가 돌아왔다"


# ── 정적 계약: 바꿀 모양 1~5 ────────────────────────────────────────────────


def test_the_head_carries_quota_and_the_mode_switch() -> None:
    js = sheets.pdfmd_js()
    assert 'el("span", "pdfmd-quota"' in js
    assert "건 더 바꿀 수 있어요." in js
    assert "modeSwitchHost" in js, "머리 오른쪽 전환 자리가 없다"


def test_the_upload_box_matches_the_issue_copy() -> None:
    js = sheets.pdfmd_js()
    assert "PDF를 끌어다 놓거나 골라 주세요." in js
    assert "여러 개나 ZIP도 됩니다." in js
    assert '"파일 고르기"' in js
    assert 'pdfmd-link pdfmd-pc-pick' in js, "내 PC에서 가져오기가 글자 링크가 아니다"


def test_the_result_card_has_primary_secondary_and_more_menu() -> None:
    js = sheets.pdfmd_js()
    assert '"Markdown 받기"' in js
    assert '"원본과 비교"' in js
    assert 'el("details", "pdfmd-more")' in js
    for label in ("대화로 다듬기", "내 PC에 저장", "원본 PDF", "지우기"):
        assert f'"{label}"' in js
    assert "data-util-refine-chat" in js, "대화 진입 표지가 사라졌다(#7461 계약)"


def test_failed_card_shows_reason_and_delete_only() -> None:
    js = sheets.pdfmd_js()
    failed = js[js.index('if (item.status === "failed") {'):]
    failed = failed[: failed.index("list.appendChild(card);")]
    assert "지우기" in failed
    assert "Markdown 받기" not in failed
    assert "원본과 비교" not in failed


def test_the_all_zip_bar_sits_above_results_and_only_when_many() -> None:
    js = sheets.pdfmd_js()
    assert '"모두 ZIP으로 받기"' in js
    bar = js.index('resultCol.appendChild(zipBar);')
    items = js.index("resultCol.appendChild(itemsWrap);")
    assert bar < items, "ZIP 막대가 결과 아래에 있다"
    assert "available.length < 2" in js, "여러 파일일 때만 보여야 한다"


def test_the_history_folds_into_one_line() -> None:
    js = sheets.pdfmd_js()
    assert 'el("details", "pdfmd-history-fold")' in js
    assert '"지난 기록 "' in js
    css = sheets.util_menu_css()
    rules = parse_rules(css)
    fold = find_rules_with_selector(rules, ".pdfmd-history-summary")[0]
    assert int(declaration(fold, "min-height").replace("px", "")) >= 44


def test_badges_are_exactly_the_four_states() -> None:
    js = sheets.pdfmd_js()
    for status, label in (
        ("queued", "바꾸는 중"),
        ("working", "바꾸는 중"),
        ("reviewed", "완료"),
        ("done", "완료"),
        ("failed", "실패"),
    ):
        assert f'{status}: "{label}"' in js
    assert '"시간 초과"' in js
    css = sheets.util_menu_css()
    rules = parse_rules(css)
    timed = find_rules_with_selector(rules, '.pdfmd-status-chip[data-status="timed-out"]')
    assert timed, "시간 초과 배지 색이 없다"
    assert declaration(timed[0], "color") == "var(--danger)"


def test_the_new_css_stays_token_only_and_44px() -> None:
    css = sheets.util_menu_css()
    section = css[css.index("#7865 · PDF→MD"):]
    # 파일 전체에는 이전 계약의 !important가 남아 있고, 이 섹션은 어떤 것도 새로 붙이지 않는다.
    assert "!important" not in section, "새 !important가 들어왔다"
    rules = parse_rules(css)
    # 메뉴 항목은 .pdfmd-btn 을 함께 얹어 44px 바닥을 상속한다(#7865).
    btn = find_rules_with_selector(rules, ".pdfmd-btn")[0]
    assert int(declaration(btn, "min-height").replace("px", "")) >= 44
    menu = find_rules_with_selector(rules, ".pdfmd-menu-item")[0]
    assert declaration(menu, "border") == "0"
    assert declaration(menu, "text-align") == "left"
    pick = find_rules_with_selector(rules, ".pdfmd-pc-pick")[0]
    assert declaration(pick, "border") == "0"
    assert declaration(pick, "text-decoration") == "underline"
    assert int(declaration(pick, "font-size").replace("px", "")) >= 12


# ── 시험 대역: 실제 화면을 띄워 실패 카드 계약을 클릭으로 확인 ───────────────


class BandHandler(http.server.SimpleHTTPRequestHandler):
    linked = True
    sort_probe = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *_args):
        pass

    def _json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/api/pc/pairings":
            links = [{"link_id": "l1", "state": "active"}] if self.linked else []
            self._json({"links": links})
            return
        if path == "/api/document-conversions":
            if BandHandler.sort_probe:
                self._json({"jobs": [
                    {"id": "job_today", "mode": "fast", "status": "done", "item_count": 1,
                     "created_at": "2026-11-17T19:00:00Z", "updated_at": "2026-11-17T19:00:00Z"},
                    {"id": "job_old", "mode": "fast", "status": "done", "item_count": 1,
                     "created_at": "2026-11-08T03:41:00Z", "updated_at": "2026-11-17T18:02:00Z"},
                    {"id": "job_new", "mode": "fast", "status": "done", "item_count": 1,
                     "created_at": "2026-11-08T09:02:00Z", "updated_at": "2026-11-08T09:02:00Z"},
                ], "limit": 50, "new_work_enabled": True})
                return
            self._json({"jobs": [{"id": "job_failed", "mode": "fast", "status": "failed",
                                  "item_count": 1, "created_at": "2026-11-17T09:00:00Z",
                                  "updated_at": "2026-11-17T09:00:00Z"}],
                        "limit": 50, "new_work_enabled": True})
            return
        if path == "/api/document-conversions/job_failed":
            self._json({"job": {"id": "job_failed", "mode": "fast", "status": "failed",
                                "error_code": None, "item_count": 1,
                                "created_at": "2026-11-17T09:00:00Z",
                                "updated_at": "2026-11-17T09:00:00Z"},
                        "items": [{"id": "item_failed", "name": "스캔본-계약서.pdf",
                                   "status": "failed", "page_count": 0,
                                   "character_count": 0, "has_markdown": False,
                                   "has_original": True, "report": None,
                                   "error_code": "pdf_scanned_no_text"}]})
            return
        if path.startswith("/api/"):
            self._json({})
            return
        super().do_GET()

    def do_POST(self):  # noqa: N802
        self._json({"ok": True})


BAND_HTML = """<!DOCTYPE html>
<html lang="ko" data-theme="padiem-home"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="./padiem-themes.css">
<link rel="stylesheet" href="./sidebar-utility.css">
<link rel="stylesheet" href="./standalone-views.css">
<link rel="stylesheet" href="./util-menu.css">
<link rel="stylesheet" href="./util-pdfmd-recovery.css">
<link rel="stylesheet" href="./util-app.css">
<link rel="stylesheet" href="./util-chat-mode.css">
</head><body>
<main class="util-view" id="utilView" style="display:block">
<div class="util-app-root" id="utilAppRoot"></div>
</main>
<script>window.PadiemAuthSession = { get: function () { return { authenticated: true }; } };</script>
<script src="./util-manifest.js"></script>
<script src="./util-chat-mode.js"></script>
<script src="./util-pdfmd-pages.js"></script>
<script src="./util-pdfmd-recovery.js"></script>
<script src="./util-pdfmd.js"></script>
<script>
  const panel = document.createElement("div");
  panel.id = "utilPdfmdPanel";
  panel.className = "util-panel";
  const body = document.createElement("div");
  body.className = "util-tool-body";
  body.appendChild(panel);
  document.getElementById("utilAppRoot").appendChild(body);
  window.initPdfMdUtility(panel, "open");
</script>
</body></html>"""


@pytest.fixture()
def band_url():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), BandHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d/index.html" % server.server_port
    server.shutdown()
    thread = threading.current_thread()
    del thread


@pytest.mark.skipif(sync_playwright is None or not CHROME,
                    reason="playwright or Chrome is not installed")
def test_a_failed_card_in_the_browser_has_reason_and_delete_only(band_url):
    """뮤테이션 표적: 실패 카드에 [Markdown 받기]가 다시 나오면 이 시험이 잡는다."""

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=CHROME)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            page.route("**/index.html", lambda route: route.fulfill(
                status=200, headers={"content-type": "text/html; charset=utf-8"},
                body=BAND_HTML))
            page.goto(band_url, wait_until="domcontentloaded")
            page.wait_for_selector(".pdfmd-history-fold summary", state="visible", timeout=8000)
            if not page.locator(".pdfmd-history-fold").evaluate("(el) => el.open"):
                page.locator(".pdfmd-history-fold summary").click()
            page.locator(".pdfmd-history-item").first.click()
            page.wait_for_selector(".pdfmd-item", state="visible", timeout=8000)
            card = page.locator(".pdfmd-item").first
            assert "스캔본이라 글자가 없어" in card.inner_text(), "실패 이유 줄이 없다"
            labels = [b.inner_text() for b in card.locator("button").all()]
            assert labels == ["지우기"], labels
        finally:
            browser.close()


@pytest.mark.skipif(sync_playwright is None or not CHROME,
                    reason="playwright or Chrome is not installed")
def test_history_rows_follow_the_time_they_show(band_url):
    """뮤테이션 표적: created_at 정렬을 빼면 이전 묶음에서 12:41이 18:02 위에 온다."""

    BandHandler.sort_probe = True
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, executable_path=CHROME)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            try:
                page.route("**/index.html", lambda route: route.fulfill(
                    status=200, headers={"content-type": "text/html; charset=utf-8"},
                    body=BAND_HTML))
                page.goto(band_url, wait_until="domcontentloaded")
                page.wait_for_selector(".pdfmd-history-fold summary", state="visible", timeout=8000)
                if not page.locator(".pdfmd-history-fold").evaluate("(el) => el.open"):
                    page.locator(".pdfmd-history-fold summary").click()
                page.locator(".pdfmd-history-item").first.wait_for(state="visible", timeout=8000)
                ids = [b.get_attribute("data-job-id")
                       for b in page.locator(".pdfmd-history-item").all()]
                assert ids == ["job_today", "job_new", "job_old"], ids
            finally:
                browser.close()
    finally:
        BandHandler.sort_probe = False
