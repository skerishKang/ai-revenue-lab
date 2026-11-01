"""2026-11-01: the design gap work (시안 04 대비).

- 홈 상단 메뉴: 시안의 메뉴 자리를 채우되 **실제 있는 화면으로만** 연결한다
  (홈·업무 도구·도구 3종). 화면이 없는 항목(활용 사례·가이드·공지사항)은 만들지 않는다.
- 검색 상자: 도구 3종 안에서만 길을 찾고, 걸리지 않으면 그 사실을 알린다.
- 카드 동작 문구: "열기" → 시안의 "바로 시작하기 →".
- 도구 화면 머리: 열린 카드의 색·사진을 이어받는 시네마틱 밴드(양식은 16px/44px 유지).

동작은 shipped 모듈을 하네스 문서에서 실행해 확인한다(scenario: nav_search).
"""
from __future__ import annotations

import re
from pathlib import Path

from _council_module import run

APP_ROOT = Path(__file__).resolve().parents[1]
STATIC = APP_ROOT / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "council-app.css").read_text(encoding="utf-8")
JS = (STATIC / "council-app.js").read_text(encoding="utf-8")

TOOLS = ("speech", "sns", "meeting")
REAL_SCREENS = {"home", "tools", *TOOLS}
BAND_NUMBER = {"speech": "1", "sns": "2", "meeting": "3"}


def last_rule(selector: str) -> str:
    """The last declaration of a selector — the one the browser applies."""
    rules = re.findall(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert rules, f"missing rule: {selector}"
    return rules[-1]


def test_the_nav_row_targets_real_screens_only():
    items = re.findall(r'data-nav="([a-z-]+)"', HTML)
    assert items, "the design's nav row is missing"
    assert set(items) == REAL_SCREENS, items
    for dead in ("활용 사례", "공지사항", "가이드"):
        assert f'data-nav="{dead}"' not in HTML


def test_the_search_field_is_present_and_wired():
    assert 'id="councilSearchForm"' in HTML and 'role="search"' in HTML
    assert 'id="councilSearch"' in HTML and 'aria-label="업무 도구 검색"' in HTML
    assert 'id="councilSearchStatus"' in HTML and 'aria-live="polite"' in HTML
    assert "function wireSearch" in JS and "function bestToolFor" in JS
    init_body = JS[JS.index("  async function init() {"):]
    assert "wireMenu();" in init_body and "wireSearch();" in init_body


def test_card_buttons_say_start_now_like_the_design():
    assert HTML.count("바로 시작하기 →</button>") == 3
    assert '>열기</button>' not in HTML
    assert '"닫기" : "바로 시작하기 →"' in JS


def test_the_menu_and_search_behave_through_the_shipped_module():
    seen = run("nav_search")
    signed_in = seen["signedIn"]
    # 메뉴 → 실제 화면(도구 3종)
    assert signed_in["navSpeech"]["activeTool"] == "speech"
    assert signed_in["navSpeech"]["inWorkspace"] is True
    assert signed_in["navSpeech"]["title"] == "축사·인사말"
    assert signed_in["navSpeech"]["openBodies"] == ["councilSpeechBody"]
    # 업무 도구 → 홈의 도구 목록으로 복귀
    assert signed_in["navTools"]["inWorkspace"] is False
    assert signed_in["navTools"]["activeTool"] is None
    # 다른 도구로 바로 이동
    assert signed_in["navMeeting"]["activeTool"] == "meeting"
    assert signed_in["navMeeting"]["openBodies"] == ["councilMeetingBody"]
    # 홈 → 작업실 닫힘
    assert signed_in["navHome"]["inWorkspace"] is False
    # 검색 → 실제 도구로 이동, 일치하지 않으면 안내만
    assert signed_in["searchSpeech"]["state"]["activeTool"] == "speech"
    assert signed_in["searchSpeech"]["statusHidden"] is True
    miss = signed_in["searchMiss"]
    assert miss["statusShown"] is True
    assert miss["state"]["activeTool"] is None
    assert "일치하는 업무 도구가 없습니다" in miss["statusText"]


def test_the_gate_stays_closed_on_the_new_paths():
    seen = run("nav_search")
    off = seen["signedOut"]
    assert off["panelHidden"] is False, "a signed-out menu entry opens the in-page login gate"
    assert off["navSns"]["forms"] == 1, "only the login form may exist while signed out"
    assert off["navSns"]["openBodies"] == []
    assert off["searchSns"]["forms"] == 1, "the search path is fail-closed too"


def test_the_workspace_head_inherits_the_cards_cinematic_face():
    bar = last_rule("html.council-in-workspace .council-workspace-bar")
    assert "background: var(--band-face, var(--panel))" in bar
    assert "color: var(--band-ink, var(--text))" in bar
    assert "overflow: hidden" in bar
    for floating in ("position: sticky", "position: fixed"):
        assert floating not in bar, "the bar must stay in the flow (S0 lesson)"
    photo = last_rule("html.council-in-workspace .council-workspace-bar::before")
    assert "background-image: var(--band-image, none)" in photo
    assert "opacity: var(--card-photo-op)" in photo
    scrim = last_rule("html.council-in-workspace .council-workspace-bar::after")
    assert "--band-face" in scrim
    for tool, number in BAND_NUMBER.items():
        block = re.search(
            r'(?m)^html\[data-active-tool="' + tool + r'"\] \.council-workspace-bar\s*\{(.*?)\n\}',
            CSS, re.S)
        assert block, f"no band variables for {tool}"
        assert f"--band-face: var(--work-{number})" in block.group(1)
        assert f"--band-image: var(--card-image-{number})" in block.group(1)


def test_the_workspace_state_marks_the_active_tool():
    assert "dataset.activeTool" in JS, "the band selector has no state to read"


def test_the_nav_and_search_stay_off_the_mobile_header():
    """#6065 S0 모바일 헤더 계약 보호: 새 컨트롤은 ≥901px에서만 연다."""
    assert ".council-nav { display: none; }" in CSS
    assert ".council-tool-search-wrap { display: none; }" in CSS
    assert re.search(r"@media \(min-width: 901px\)\s*\{", CSS), "the desktop gate is missing"
