"""#8812·#8814 PDF→MD 디자인 점검 수리 1차 — CTO 판정 1·2차와 대표 확인의 계약.

기준: 프로젝트 문서 claude/디자인점검_기준과절차_CTO·페르소나·레인공통_20261126.md
'6. 수리 레인이 지킬 것' — 고치기 전에 실패하는 시험, 토큰만, 새 !important 없음.

- #8812 D4: 사이드바 실패 줄의 글과 [다시 시도]가 겹치지 않는다(단추는 글 아래 줄).
- #8812 D5·D6: 하루 한도 0이면 [파일 고르기]가 비활성이고, 한도·쪽수 안내는
  끌어다 놓기 상자 바로 아래의 경고 상자(경고 색 토큰·제목 한 줄+설명) 하나로 나온다.
- #8812 D5: 올리는 중 목록은 끌어다 놓기 상자 바로 아래, 요약 한 줄 복제는 없다.
- #8812 D6·D7 대표 확인: 로그아웃 화면의 가운데 단추는 [로그인](같은 동작)이고
  위쪽 안내 줄의 중복 로그인 단추는 없다.
- #8814 D6·D7: 실패 카드는 [다시 하기](주)·[지우기](보조). 글자 없는 스캔본은 안내만.
- #8814 D3: [실패] 표지는 오류 색 토큰(다섯 테마 대비 3:1 이상).
- #8814 D7: 결과가 없는 카드(실패·바꾸는 중)에는 글자 수 칩이 없다.
- #8814 D5: [바꾸는 중] 칩 앞에 작은 진행 표시(움직임 줄이기에서는 멈춘 표시).
- 낱말(대표 확인): 빠르게/꼼꼼히 바꾸기 · 첫 PDF를 바꿔 보세요 · 지난 기록 N건 ·
  바꾸지 못했어요 · 오늘 바꿀 수 있는 양을 다 썼어요 · 바꾼 결과.
  ("PDF → Markdown", "Markdown 받기"는 그대로다.)
"""
from __future__ import annotations

import http.server
import io
import json
import re
import threading
from functools import partial
from pathlib import Path

import pytest

from _support.claw_static import sheet
from _support.contrast_repair_source import contrast, resolve
from css_rules import declaration, find_rules_with_selector, parse_rules

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover - CI without a browser
    sync_playwright = None

try:
    from PIL import Image
except ModuleNotFoundError:  # pragma: no cover
    Image = None

STATIC = Path(__file__).resolve().parents[1] / "static"
CHROME_CANDIDATES = [__import__("os").environ.get("B61_CHROME_PATH"),
                     r"C:\Program Files\Google\Chrome\Application\chrome.exe"]
CHROME = next((c for c in CHROME_CANDIDATES if c and Path(c).is_file()), None)

PDFMD = sheet("util-pdfmd.js")
RECOVERY_JS = sheet("util-pdfmd-recovery.js")
UTIL_MENU = sheet("util-menu.css")
HISTORY_CSS = sheet("history.css")
RECOVERY_CSS = sheet("util-pdfmd-recovery.css")
LOCALE_UTILITY = sheet("locale-utility.js")
MANIFEST = sheet("util-manifest.js")

THEMES = ("light", "dark", "padiem-glass", "cinematic", "padiem-home")
BADGE_AA = 3.0


# ── #8812 D4: 사이드바 실패 줄 — 글 아래 줄에 단추 ────────────────────────────


def test_sidebar_failed_row_stacks_the_retry_button_below_the_text() -> None:
    rules = parse_rules(HISTORY_CSS)
    failed = find_rules_with_selector(rules, ".history-row.history-load-failed")
    assert failed, "사이드바 실패 줄 규칙이 없다"
    assert declaration(failed[0], "flex-direction") == "column", \
        "글과 단추가 같은 줄에 나란히 있으면 좁은 사이드바에서 다시 겹친다"


# ── #8812 D5·D6: 하루 한도 0 — 파일 고르기 비활성 + 경고 상자 ─────────────────


def test_daily_quota_zero_disables_the_file_picker() -> None:
    assert "function exhaust" in RECOVERY_JS, "한도 0 상태로 들어가는 길이 없다"
    body = PDFMD[PDFMD.index("onExhausted: () => {"):] 
    body = body[: body.index("},")]
    assert "dropCta.disabled = true" in body, "[파일 고르기]가 눌린 채로 남는다"
    assert "fileInput.disabled = true" in body, "숨은 파일 입력이 남아 있다"
    assert 'drop.removeAttribute("role")' in body
    picker = PDFMD[PDFMD.index("function openPicker"):]
    picker = picker[: picker.index("\n    }")]
    assert "quotaExhausted" in picker, "한도 0인데 상자가 파일 창을 연다"


def test_limit_notices_are_one_warning_box_below_the_drop_box() -> None:
    rules = parse_rules(RECOVERY_CSS)
    box = find_rules_with_selector(rules, ".pdfmd-limit-note")
    assert box, "경고 상자 규칙이 없다"
    assert "var(--gold)" in (declaration(box[0], "border") or ""), "경고 색 토큰이 아니다"
    assert declaration(box[0], "background") == "var(--gold-soft)"
    title = find_rules_with_selector(rules, ".pdfmd-limit-title")
    assert title and declaration(title[0], "color") == "var(--util-menu-pdfmd-warn-ink)"
    # CTO 검토 D1·D2: 머리(아이콘+제목)와 설명은 세로로 쌓인다 — 판이 좁아도
    # 두 칸으로 갈라지지 않는다.
    assert declaration(box[0], "flex-direction") == "column", "경고 상자가 가로 두 칸으로 갈라진다"
    head = find_rules_with_selector(rules, ".pdfmd-limit-head")
    assert head and declaration(head[0], "display") == "flex", "아이콘+제목 한 줄이 없다"
    # 밝은 판 테마에서 제목 잉크가 읽히는지 — 토큰 값으로 잰다(본문 4.5:1).
    # 어두운 판 테마(dark·cinematic)는 기존 #f0c48a 덮기 규칙을 타므로 아래
    # 브라우저 시험이 실제로 칠해진 픽셀로 잰다.
    for theme in ("light", "padiem-home", "padiem-glass"):
        ink = resolve(theme, "var(--util-menu-pdfmd-warn-ink)")
        surface = _over(resolve(theme, "var(--gold-soft)"), resolve(theme, "var(--panel)"))
        painted = contrast(ink, surface)
        assert painted >= 4.5, (theme, round(painted, 2))
    # 위치: 진행 목록 다음, PC 링크 줄 바로 앞 — DOM에서는 끌어다 놓기 상자 바로 아래.
    drop_at = PDFMD.index("formWrap.appendChild(drop);")
    progress_at = PDFMD.index("formWrap.appendChild(uploadProgress);")
    assert 'formWrap.insertBefore(recovery.note, pcLinkRow)' in PDFMD, \
        "경고 상자가 끌어다 놓기 상자 바로 아래가 아니다"
    assert drop_at < progress_at


def _over(top, bottom):
    alpha = top[3]
    return tuple(top[i] * alpha + bottom[i] * (1 - alpha) for i in range(3)) + (1.0,)


def test_the_upload_progress_list_sits_below_the_drop_box_without_a_duplicate_line() -> None:
    drop_at = PDFMD.index("formWrap.appendChild(drop);")
    progress_at = PDFMD.index("formWrap.appendChild(uploadProgress);")
    foot_at = PDFMD.index("const pcLinkRow = el(")
    assert drop_at < progress_at < foot_at, "올리는 중 목록이 끌어다 놓기 상자 바로 아래가 아니다"
    # 요약 한 줄 복제 금지: 진행 행이 있는 동안은 요약 줄에 쓰지 않는다.
    assert "uploadRowsActive" in PDFMD
    update = PDFMD[PDFMD.index("const update = (message) => {"):]
    update = update[: update.index("};")]
    assert 'if (typeof onProgress === "function") onProgress(message);' in update
    assert "uploadStatus.textContent = message;" in update.split("else")[-1], \
        "진행 행이 있을 때도 요약 줄에 같은 말을 다시 쓴다"


# ── #8812 D6·D7 대표 확인: 로그인 단추 하나 ───────────────────────────────────


def test_the_logout_screen_has_one_login_button_and_it_is_the_drop_box_cta() -> None:
    assert 'dropCta.textContent = "로그인";' in PDFMD
    assert 'if (PDFMD_LOGIN_REQUIRED) { openExistingLogin(); return; }' in PDFMD, \
        "가운데 단추가 위 단추와 같은 동작을 하지 않는다"
    assert 'loginEntry.id = "pdfmdLoginEntry";' not in PDFMD, "위쪽 줄의 중복 로그인 단추가 남아 있다"
    # 안내 줄은 문장만 남는다.
    notice = PDFMD[PDFMD.index("} else if (PDFMD_LOGIN_REQUIRED) {"):]
    notice = notice[: notice.index("} else if (PDFMD_CHECKING) {")]
    assert "로그인하면 PDF를 바꿀 수 있어요." in notice
    assert "appendChild(loginEntry)" not in notice


# ── #8814 D6·D7: 실패 카드의 단추 ─────────────────────────────────────────────


def test_a_failed_card_has_retry_as_primary_and_delete_as_secondary() -> None:
    failed = PDFMD[PDFMD.index('if (item.status === "failed") {'):]
    failed = failed[: failed.index("list.appendChild(card);")]
    assert "recovery.retryButton(item)" in failed, "실패 카드에 [다시 하기]가 없다"
    assert "deleteButton(item)" in failed
    assert failed.index("recovery.retryButton(item)") < failed.index("deleteButton(item)"), \
        "[다시 하기]가 주 단추로 먼저 놓여야 한다"
    assert 'el("button", "pdfmd-btn pdfmd-btn-primary", "다시 하기")' in RECOVERY_JS
    # 글자 없는 스캔본: 다시 하기 대신 안내만.
    guard = PDFMD[PDFMD.index('if (item.error_code !== "pdf_scanned_no_text")'):]
    guard = guard[: guard.index("\n")]
    assert "retryButton" in guard
    assert "다시 하기" in RECOVERY_JS and "지우기" in PDFMD


def test_retry_reruns_the_same_item_the_same_way() -> None:
    rerun = RECOVERY_JS[RECOVERY_JS.index("async function rerun(item)"):]
    rerun = rerun[: rerun.index("\n      }")]
    assert '"/api/document-conversions/items/" + item.id + "/run"' in rerun, \
        "같은 파일을 다시 실행하는 요청이 아니다"
    assert 'method: "POST"' in rerun


# ── #8814 D3: 실패 표지 — 오류 색 토큰, 다섯 테마 3:1 ─────────────────────────


def test_the_failed_badge_is_painted_with_the_error_tokens() -> None:
    rules = parse_rules(UTIL_MENU)
    failed = [r for r in find_rules_with_selector(rules, '.pdfmd-status-chip[data-status="failed"]')
              if r.media is None]
    assert failed, "[실패] 표지 색 규칙이 없다"
    assert declaration(failed[0], "color") == "var(--danger)"
    assert declaration(failed[0], "background") == "var(--danger-surface)"
    assert declaration(failed[0], "border-color") == "var(--danger-border)"
    # 선택자 나열 버그 재발 금지: [실패] 칩이 .pdfmd-item-actions 규칙에 끼어 있으면 안 된다.
    actions = [r for r in find_rules_with_selector(rules, ".pdfmd-item-actions") if r.media is None]
    assert actions and all(
        '.pdfmd-status-chip[data-status="failed"]' not in ",".join(r.selectors) for r in actions
    ), "[실패] 칩이 단추 행 규칙에 묻혀 색을 잃는다"
    # 토큰 값으로 다섯 테마 대비를 잰다(칩 글자 12px — 본문 기준 4.5:1을 넘는지 확인).
    for theme in THEMES:
        ink = resolve(theme, "var(--danger)")
        surface = _over(resolve(theme, "var(--danger-surface)"), resolve(theme, "var(--panel)"))
        ratio = contrast(ink, surface)
        assert ratio >= BADGE_AA, (theme, round(ratio, 2))


# ── #8814 D7: 결과 없는 카드의 글자 수 칩 ─────────────────────────────────────


def test_the_character_count_chip_needs_a_result() -> None:
    assert "if (item.has_markdown && item.character_count) {" in PDFMD, \
        "실패·바꾸는 중 카드에 글자 수가 다시 나왔다"


# ── #8814 D5: 바꾸는 중 칩의 진행 표시 ────────────────────────────────────────


def test_the_working_chip_carries_a_movement_marker_that_stops_without_motion() -> None:
    rules = parse_rules(RECOVERY_CSS)
    marker = [r for r in find_rules_with_selector(rules, '.pdfmd-status-chip[data-status="working"]::before')
              if r.media is None]
    assert marker, "칩 앞의 진행 표시가 없다"
    assert declaration(marker[0], "animation") is not None
    reduced = [r for r in parse_rules(RECOVERY_CSS)
               if r.media and "prefers-reduced-motion" in r.media
               and '.pdfmd-status-chip[data-status="working"]::before' in ",".join(r.selectors)]
    assert reduced and declaration(reduced[0], "animation") == "none", \
        "움직임 줄이기에서 진행 표시가 멈추지 않는다"


def test_the_working_stage_line_wraps_inside_the_card() -> None:
    """CTO 검토 D4: "바꾸는 중 — …" 안내 줄이 카드 오른쪽 끝을 넘지 않는다."""
    rules = parse_rules(RECOVERY_CSS)
    stage = find_rules_with_selector(rules, ".pdfmd-stage")
    assert stage, "안내 줄 규칙이 없다"
    assert declaration(stage[0], "white-space") == "normal", "안내 줄이 한 줄로 민려 나간다"
    assert declaration(stage[0], "word-break") == "keep-all"
    assert declaration(stage[0], "max-width") == "100%"


# ── 낱말(대표 확인) — PDF→MD 화면 안에서만 ────────────────────────────────────


def test_the_screen_speaks_the_confirmed_words() -> None:
    for present in (
        "빠르게 바꾸기", "꼼꼼히 바꾸기",
        '"첫 PDF를 바꿔 보세요."',
        '"지난 기록 "',
        "바꾸지 못했어요. 다시 해 주세요.",
        "오늘 바꿀 수 있는 양을 다 썼어요. 내일 다시 해 주세요.",
        '"Markdown 받기"',
        # CTO 검토(261127) 3번 — 화면 안 남은 낱말
        "PDF·ZIP을 Markdown으로 바꾸고, 비교하고, 내려받아요",
        "로그인하면 PDF를 바꿀 수 있어요.",
        "로그인한 뒤 PDF를 올려 바꿀 수 있어요.",
        "올리면 바로 바꾸기 시작해요.",
        "지금은 새 바꾸기를 시작할 수 없습니다",
        '"바꾸기 방식"',
    ):
        assert present in PDFMD or present in MANIFEST, f"확인된 문구가 없다: {present}"
    for gone in (
        "빠른 변환", "검증 변환", "변환본", "변환 결과", "지난 변환",
        "변환에 실패했습니다", "변환 시작 실패", "오늘 변환 한도",
        "첫 PDF를 변환해 보세요",
        # CTO 검토(261127) 3번 — 고치기 전 문구
        "변환·비교·다운로드", "로그인 후 PDF 변환을", "로그인 후 PDF를 올려 변환할",
        "올리면 바로 변환이", "새 변환을", '"변환 방식"',
    ):
        assert gone not in PDFMD and gone not in MANIFEST, f"고치기 전 낱말이 남아 있다: {gone}"
    # locale 키(이 화면 전용)와 대화 전환 문구도 같은 낱말로.
    assert "빠르게 바꾸기:" in LOCALE_UTILITY and "꼼꼼히 바꾸기:" in LOCALE_UTILITY
    assert "빠른 변환:" not in LOCALE_UTILITY and "검증 변환:" not in LOCALE_UTILITY
    assert "변환 결과" not in LOCALE_UTILITY
    assert '"빠르게 바꾸기", "Fast conversion"' in MANIFEST
    assert '"꼼꼼히 바꾸기", "Verified conversion"' in MANIFEST
    assert "빠른 변환" not in MANIFEST and "검증 변환" not in MANIFEST


# ── 시험 대역: 실제 화면을 띄워 판정 항목을 클릭으로 확인 ─────────────────────

BAND_JOBS = [{"id": "job1", "mode": "fast", "status": "done", "item_count": 1,
              "created_at": "2026-11-27T09:00:00Z", "updated_at": "2026-11-27T09:00:00Z"}]


def _item(**kw):
    item = {"id": "it1", "name": "rulings.pdf", "status": "done", "has_markdown": True,
            "page_count": 12, "character_count": 34567, "has_original": True,
            "report": None, "error_code": None}
    item.update(kw)
    return item


class BandHandler(http.server.SimpleHTTPRequestHandler):
    """Answers /api from one scenario dict the tests mutate per case."""

    scenario = {"items": [], "run": {"status": 202, "body": {}}, "list_status": 200}

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
        if path == "/api/document-conversions":
            status = BandHandler.scenario.get("list_status", 200)
            if status != 200:
                self._json({"error": {"code": "unauthorized"}}, status)
                return
            self._json({"jobs": BAND_JOBS, "limit": 50, "new_work_enabled": True})
            return
        if path == "/api/document-conversions/job1":
            self._json({"job": dict(BAND_JOBS[0]), "items": BandHandler.scenario["items"]})
            return
        if path == "/api/pc/pairings":
            self._json({"links": []})
            return
        if path.startswith("/api/"):
            self._json({})
            return
        super().do_GET()

    def do_POST(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path.endswith("/run"):
            answer = BandHandler.scenario["run"]
            self._json(answer["body"], answer["status"])
            return
        self._json({"ok": True})


BAND_PAGE = """<!DOCTYPE html>
<html lang="ko" data-theme="__THEME__"><head><meta charset="utf-8">
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
  window.__loginClicks = 0;
  const panel = document.createElement("div");
  panel.id = "utilPdfmdPanel";
  panel.className = "util-panel";
  const body = document.createElement("div");
  body.className = "util-tool-body";
  body.appendChild(panel);
  document.getElementById("utilAppRoot").appendChild(body);
  window.initPdfMdUtility(panel, "__STATE__");
</script>
</body></html>"""

SIDEBAR_PAGE = """<!DOCTYPE html>
<html lang="ko" data-theme="light"><head><meta charset="utf-8">
<link rel="stylesheet" href="./padiem-tokens.css">
<link rel="stylesheet" href="./styles.css">
<link rel="stylesheet" href="./history.css">
</head><body style="margin:0">
<div class="app-shell" data-state="main"><div class="sidebar" id="sidebar">
  <section class="recent-section" id="historySection">
    <div id="historyList"><div class="history-row history-load-failed">
      <span class="history-load-failed-text">대화 목록을 불러오지 못했어요</span>
      <button class="history-retry" type="button">다시 시도</button>
    </div></div>
  </section>
</div></div>
</body></html>"""


@pytest.fixture()
def band_url():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), BandHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d/index.html" % server.server_port
    server.shutdown()


def _open(browser, band_url, *, theme="light", state="open", width=1440, reduced=True):
    ctx = browser.new_context(
        viewport={"width": width, "height": 950},
        reduced_motion="reduce" if reduced else "no-preference")
    page = ctx.new_page()
    page.route("**/index.html", lambda route: route.fulfill(
        status=200, headers={"content-type": "text/html; charset=utf-8"},
        body=BAND_PAGE.replace("__THEME__", theme).replace("__STATE__", state)))
    page.goto(band_url, wait_until="domcontentloaded")
    page.wait_for_selector(".pdfmd-shell", timeout=8000)
    return ctx, page


@pytest.mark.skipif(sync_playwright is None or not CHROME or Image is None,
                    reason="playwright, Chrome or PIL is not installed")
def test_quota_zero_disables_the_picker_and_shows_the_warning_box(band_url):
    """하루 한도 0 답을 받으면 [파일 고르기]가 비활성이고 경고 상자가 상자 아래에 뜬다."""
    BandHandler.scenario = {
        "items": [_item(status="queued", has_markdown=False, character_count=0)],
        "run": {"status": 429, "body": {"error": {"code": "conversion_quota_exhausted"},
                                        "conversion": {"daily_limit": 2, "remaining": 0}}},
    }
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=CHROME)
        try:
            _ctx, page = _open(browser, band_url)
            page.wait_for_selector(".pdfmd-history-item", timeout=8000)
            page.locator(".pdfmd-history-item").first.click()
            page.wait_for_selector(".pdfmd-item", timeout=8000)
            page.wait_for_selector("#pdfmdLimitNote:not([hidden])", timeout=8000)
            cta = page.locator(".pdfmd-drop-cta")
            assert cta.is_disabled(), "한도 0인데 [파일 고르기]가 눌린다"
            assert page.locator("input[type=file]").first.is_disabled(), "숨은 파일 입력이 남아 있다"
            box = page.locator("#pdfmdLimitNote")
            text = box.inner_text()
            assert "오늘 바꿀 수 있는 양을 다 썼어요." in text, text
            assert "내일 다시 해 주세요." in text, text
            drop_box = page.locator(".pdfmd-drop").bounding_box()
            note_box = box.bounding_box()
            assert note_box["y"] >= drop_box["y"] + drop_box["height"] - 1, "경고 상자가 상자 아래가 아니다"
            assert (note_box["y"] - (drop_box["y"] + drop_box["height"])) < 40, "경고 상자가 멀어져 있다"
        finally:
            browser.close()


@pytest.mark.skipif(sync_playwright is None or not CHROME,
                    reason="playwright or Chrome is not installed")
def test_failed_cards_carry_retry_primary_delete_secondary_and_no_count_chip(band_url):
    BandHandler.scenario = {
        "items": [
            _item(id="it1", status="failed", has_markdown=False, error_code="convert_failed"),
            _item(id="it2", name="broken-scan.pdf", status="failed", has_markdown=False,
                  error_code="pdf_scanned_no_text"),
        ],
        "run": {"status": 202, "body": {"item": _item(status="working", has_markdown=False)}},
    }
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=CHROME)
        try:
            _ctx, page = _open(browser, band_url)
            page.wait_for_selector(".pdfmd-history-item", timeout=8000)
            page.locator(".pdfmd-history-item").first.click()
            page.wait_for_selector(".pdfmd-item", timeout=8000)
            cards = page.locator(".pdfmd-item")
            first, second = cards.nth(0), cards.nth(1)
            buttons = [b.inner_text() for b in first.locator("button").all()]
            assert buttons == ["다시 하기", "지우기"], buttons
            assert "pdfmd-btn-primary" in (first.locator("button").first.get_attribute("class") or ""), \
                "[다시 하기]가 주 단추가 아니다"
            assert first.locator(".pdfmd-item-count").count() == 0, "실패 카드에 글자 수 칩이 보인다"
            assert [b.inner_text() for b in second.locator("button").all()] == ["지우기"], \
                "글자 없는 스캔본에 [다시 하기]가 대신 나왔다"
            assert "스캔본이라 글자가 없어" in second.inner_text()
            assert second.locator(".pdfmd-item-count").count() == 0
        finally:
            browser.close()


@pytest.mark.skipif(sync_playwright is None or not CHROME,
                    reason="playwright or Chrome is not installed")
def test_the_retry_button_reruns_the_same_item(band_url):
    seen = []
    BandHandler.scenario = {
        "items": [_item(id="it1", status="failed", has_markdown=False, error_code="convert_failed")],
        "run": {"status": 202, "body": {"item": _item(status="working", has_markdown=False)}},
    }

    original_do_post = BandHandler.do_POST

    def do_POST(self):  # noqa: N802
        seen.append(self.path.split("?")[0])
        original_do_post(self)

    BandHandler.do_POST = do_POST
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, executable_path=CHROME)
            try:
                _ctx, page = _open(browser, band_url)
                page.wait_for_selector(".pdfmd-history-item", timeout=8000)
                page.locator(".pdfmd-history-item").first.click()
                page.wait_for_selector(".pdfmd-item", timeout=8000)
                page.locator(".pdfmd-item button", has_text="다시 하기").first.click()
                page.wait_for_timeout(600)
                assert "/api/document-conversions/items/it1/run" in seen, seen
            finally:
                browser.close()
    finally:
        BandHandler.do_POST = original_do_post


@pytest.mark.skipif(sync_playwright is None or not CHROME or Image is None,
                    reason="playwright, Chrome or PIL is not installed")
def test_the_failed_badge_paints_at_least_3_to_1_in_all_five_themes(band_url):
    BandHandler.scenario = {
        "items": [_item(id="it1", status="failed", has_markdown=False, error_code="convert_failed")],
        "run": {"status": 202, "body": {}},
    }
    hide_text = ("*,*::before,*::after{color:transparent!important;"
                 "-webkit-text-fill-color:transparent!important;text-shadow:none!important}")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=CHROME)
        try:
            for theme in THEMES:
                ctx, page = _open(browser, band_url, theme=theme)
                page.wait_for_selector(".pdfmd-history-item", timeout=8000)
                page.locator(".pdfmd-history-item").first.click()
                page.wait_for_selector('.pdfmd-status-chip[data-status="failed"]', timeout=8000)
                chip = page.locator('.pdfmd-status-chip[data-status="failed"]').first
                color = chip.evaluate("(el) => getComputedStyle(el).color")
                box = chip.bounding_box()
                style = page.add_style_tag(content=hide_text)
                page.wait_for_timeout(120)
                image = Image.open(io.BytesIO(page.screenshot(animations="disabled"))).convert("RGB")
                style.evaluate("el => el.remove()")
                crop = image.crop((int(box["x"]), int(box["y"]),
                                   int(box["x"] + box["width"] + 0.999),
                                   int(box["y"] + box["height"] + 0.999)))
                numbers = [float(x) for x in re.findall(r"[\d.]+", color)]
                ink = tuple(numbers[:3]) + (numbers[3] if len(numbers) > 3 else 1.0,)
                worst = min(contrast(ink, pixel + (1.0,)) for pixel in set(crop.getdata()))
                assert worst >= BADGE_AA, (theme, round(worst, 2))
                ctx.close()
        finally:
            browser.close()


@pytest.mark.skipif(sync_playwright is None or not CHROME,
                    reason="playwright or Chrome is not installed")
def test_the_working_chip_marker_spins_and_stops_for_reduced_motion(band_url):
    BandHandler.scenario = {
        "items": [_item(id="it1", status="working", has_markdown=False, character_count=34567)],
        "run": {"status": 202, "body": {}},
    }
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=CHROME)
        try:
            for reduced, expected in ((False, "pdfmd-working-spin"), (True, "none")):
                ctx, page = _open(browser, band_url, reduced=reduced)
                page.wait_for_selector(".pdfmd-history-item", timeout=8000)
                page.locator(".pdfmd-history-item").first.click()
                page.wait_for_selector('.pdfmd-status-chip[data-status="working"]', timeout=8000)
                chip = page.locator('.pdfmd-status-chip[data-status="working"]').first
                before = chip.evaluate("(el) => { const s = getComputedStyle(el, '::before');"
                                       " return {content: s.content, animation: s.animationName,"
                                       " width: parseFloat(s.width)}; }")
                assert before["content"] != "none", "진행 표시가 없다"
                assert before["width"] > 4, "진행 표시가 너무 작다"
                assert before["animation"] == expected, (reduced, before["animation"])
                assert chip.locator(".pdfmd-item-count").count() == 0, "바꾸는 중 카드에 글자 수 칩이 보인다"
                ctx.close()
        finally:
            browser.close()


@pytest.mark.skipif(sync_playwright is None or not CHROME,
                    reason="playwright or Chrome is not installed")
def test_the_logout_screen_has_one_login_button_that_opens_the_existing_login(band_url):
    BandHandler.scenario = {"items": [], "run": {"status": 202, "body": {}}, "list_status": 401}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=CHROME)
        try:
            _ctx, page = _open(browser, band_url, state="login_required")
            page.wait_for_selector(".pdfmd-shell", timeout=8000)
            page.evaluate("""() => {
              const b = document.createElement('button');
              b.id = 'loginButton'; b.textContent = '로그인';
              b.addEventListener('click', () => { window.__loginClicks += 1; });
              document.body.appendChild(b);
            }""")
            cta = page.locator(".pdfmd-drop-cta")
            assert cta.inner_text() == "로그인", cta.inner_text()
            assert page.locator("#pdfmdLoginEntry").count() == 0, "위쪽 줄의 중복 로그인 단추가 남아 있다"
            notice = page.locator(".pdfmd-head-row .pdfmd-status")
            assert notice.locator("button").count() == 0, "안내 줄에 단추가 남아 있다"
            cta.click()
            page.wait_for_timeout(200)
            assert page.evaluate("window.__loginClicks") == 1, "가운데 단추가 로그인을 열지 않는다"
        finally:
            browser.close()


@pytest.mark.skipif(sync_playwright is None or not CHROME,
                    reason="playwright or Chrome is not installed")
def test_the_sidebar_failed_row_never_overlaps_text_and_button(band_url):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=CHROME)
        try:
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            page.route("**/index.html", lambda route: route.fulfill(
                status=200, headers={"content-type": "text/html; charset=utf-8"},
                body=SIDEBAR_PAGE))
            page.goto(band_url, wait_until="domcontentloaded")
            page.wait_for_selector(".history-load-failed", timeout=8000)
            measured = page.evaluate("""() => {
              const row = document.querySelector('.history-load-failed');
              const text = row.querySelector('.history-load-failed-text').getBoundingClientRect();
              const button = row.querySelector('.history-retry').getBoundingClientRect();
              const overlapX = Math.max(0, Math.min(text.right, button.right) - Math.max(text.left, button.left));
              const overlapY = Math.max(0, Math.min(text.bottom, button.bottom) - Math.max(text.top, button.top));
              return {overlap: overlapX * overlapY, below: button.top >= text.bottom - 1};
            }""")
            assert measured["overlap"] == 0, "글과 단추가 겹친다"
            assert measured["below"], "단추가 글 아래 줄에 없다"
        finally:
            browser.close()


@pytest.mark.skipif(sync_playwright is None or not CHROME,
                    reason="playwright or Chrome is not installed")
def test_the_screen_speaks_the_confirmed_words_in_the_browser(band_url):
    BandHandler.scenario = {
        "items": [_item(id="it1", status="done", has_markdown=True)],
        "run": {"status": 202, "body": {}},
    }
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=CHROME)
        try:
            _ctx, page = _open(browser, band_url)
            page.wait_for_selector(".pdfmd-history-fold", timeout=8000)
            assert "첫 PDF를 바꿔 보세요." in page.locator(".pdfmd-items").inner_text()
            options = page.locator("#pdfmdMode option").all_inner_texts()
            assert options == ["빠르게 바꾸기", "꼼꼼히 바꾸기"], options
            assert "지난 기록 1건" in page.locator(".pdfmd-history-summary").inner_text()
            assert "바꾼 결과" in page.locator(".pdfmd-retention-note").inner_text()
        finally:
            browser.close()
