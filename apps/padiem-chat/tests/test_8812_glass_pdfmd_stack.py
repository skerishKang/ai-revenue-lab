"""#8812 D1·D4 follow-up (CTO 판정 수정 요청): padiem-glass의 공유 여섯 판 레인은
첫 화면 초상 아트워크 열을 유틸 화면에도 예약하는 고정 디자인이라 본문 판 폭을
넓히지 않는다. 대신 PDF→MD 화면 안의 두 칸(입력 판 + 오른쪽 안내 카드)을 판 폭
기준(컨테이너 쿼리)으로 한 칸에 쌓는다 — 안내 카드는 입력 판 아래.

계약(이 시험이 단정):
* 규칙은 새 단일 시트 ``util-pdfmd-glass-stack.css``에 있다(기존 시트 규칙 수
  불변 — #8054 구조 래칫).
* 컨테이너 선언과 @container 규칙은 pdfmd 도구 화면의 glass .util-view에만
  걸린다 — 다른 뷰·다른 테마는 컨테이너가 아니므로 절대 적용되지 않는다.
* 임계값 800px(내용 상자): 다른 테마가 두 칸을 유지하는 폭(872px+)에서는
  두 칸 그대로다.
* 새 important 선언·선택자 강화·새 색 숫자 없음. 원문 read_text는 _support로
  (#8054/#8060)."""

from __future__ import annotations

import re

from _support import pdfmd_glass_stack_source as sheets

STACK_CSS = sheets.stack_sheet()
FRAME_CSS = sheets.frame_sheet()
UTIL_APP_CSS = sheets.util_app_sheet()
INDEX_HTML = sheets.index_html()

MARKER = 'data-util-tool="pdfmd"'
PANEL_SELECTOR = ".util-tool-screen #utilPdfmdPanel"


def _rules(css: str):
    """(selector_text, body) pairs for every declaration rule in the sheet."""
    out = []
    for match in re.finditer(r"\{", css):
        start = match.end()
        depth = 1
        i = start
        while depth and i < len(css):
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
            i += 1
        body = css[start:i - 1]
        if "{" in body:
            continue  # a group rule (media/container), not a declaration rule
        selector_start = css.rfind("}", 0, match.start()) + 1
        selector = css[selector_start:match.start()]
        out.append((selector, body))
    return out


def test_container_is_declared_only_for_the_pdfmd_glass_view() -> None:
    rules = [r for r in _rules(STACK_CSS) if "container-type" in r[1]]
    assert len(rules) == 1, rules
    selector, body = rules[0]
    assert 'html[data-theme="padiem-glass"]' in selector
    assert '[data-state="util"]' in selector
    assert '.util-view:has(.util-tool-screen[data-util-tool="pdfmd"])' in selector
    assert body.strip() == "container-type: inline-size;"


def _container_blocks(css: str):
    """(header, body) for every @container block, comments stripped first."""
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out = []
    for match in re.finditer(r"@container\s*\([^)]*\)\s*\{", stripped):
        start = match.end()
        depth = 1
        i = start
        while depth and i < len(stripped):
            if stripped[i] == "{":
                depth += 1
            elif stripped[i] == "}":
                depth -= 1
            i += 1
        out.append((stripped[match.start():match.end()], stripped[start:i - 1]))
    return out


def test_stacking_rule_is_container_query_scoped_to_the_pdfmd_panel() -> None:
    blocks = _container_blocks(STACK_CSS)
    assert blocks, "the @container stacking rule is missing"
    header, body = blocks[0]
    assert "(max-width: 799px)" in header
    assert PANEL_SELECTOR in body
    assert "grid-template-columns: 1fr" in body
    # The override mirrors the winning util-app rule's own selector, so it wins
    # by added theme/state qualification, not by hacks.
    assert PANEL_SELECTOR in UTIL_APP_CSS
    assert "!important" not in STACK_CSS
    assert "#pdfmdPcPick" not in STACK_CSS


def test_threshold_leaves_other_themes_two_column_widths_untouched() -> None:
    # The stacking rule never applies outside padiem-glass: every @container
    # selector is theme-qualified, and only the glass pdfmd view is a container.
    for _header, body in _container_blocks(STACK_CSS):
        assert 'data-theme="padiem-glass"' in body
    # The shared frame sheet keeps the artwork reservation and the shared lane.
    assert "clamp(360px, 32vw, 560px)" in FRAME_CSS
    assert MARKER not in FRAME_CSS  # no width override there anymore


def test_stack_sheet_loads_after_the_shared_frame_and_util_app_sheets() -> None:
    stack_at = INDEX_HTML.index("./util-pdfmd-glass-stack.css")
    assert INDEX_HTML.index("./shared-six-panel-frame.css") < stack_at
    assert INDEX_HTML.index("./util-app.css") < stack_at
