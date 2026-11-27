"""#7811 C5 — padiem-cinematic-workspace.css 덮어쓰기 정리.

이 시트는 이름과 달리 모든 테마의 바탕이다. 선언 27개에 붙어 있던 !important를
걷어 냈고, 그 플래그가 실제로 이기던 상대(main 실측: 다섯 테마 × 두 폭, 쉼·hover·
focus 상태)마다 이렇게 정리했다.

* .project-banner — padiem-surfaces.css 공용 첨부 카드 규칙의 우선 표시가 테두리
  색·그림자를 칠하고 있었다. 그 규칙에서 .project-banner를 빼고, 칠하던 값을 이
  시트의 .project-banner 규칙으로 옮겼다(여기 있던 --ws-banner-edge 테두리와 바깥
  그림자는 늘 졌던 값이라 지웠다).
* 이 시트 안의 hover·focus 규칙 중 기본 규칙의 플래그에 늘 지던 색 선언(배너 단추,
  닫기 단추, primary 단추, 파일 추가, 입력 focus 테두리)은 칠해진 적이 없어 지웠다.

남은 우선 표시 3개는 토큰 하나로 풀 수 없다(아래 KEPT_FLAGS).
"""
from __future__ import annotations

from _support import theme_sheets as sheets

SHEET = "padiem-cinematic-workspace.css"

#: (선택자 목록의 첫 선택자, 속성) → 남긴 사유.
KEPT_FLAGS = {
    # projects.css .project-form-actions button(11px, 특이도 더 높음)을 이긴다.
    # 같은 규칙이 프로젝트 삭제 단추에는 11px로 칠해야 한다.
    (".project-secondary", "border-radius"),
    # .project-form label(특이도 더 높음)의 글자색을 이긴다(dark·cinematic에서 값이 다르다).
    (".project-file-add", "color"),
    # padiem-glass.css의 사이드바 공용 목록(.sidebar-footer 포함)이 glass에서 다른 색을 준다.
    (".history-empty", "color"),
}

DEAD_HOVER = (
    ".project-banner-actions button:hover",
    ".project-dialog-close:hover",
    ".project-primary:hover",
    ".project-file-add:hover",
)


def _first(rule) -> str:
    return rule.selector.split(",")[0].strip()


def test_only_the_three_unresolvable_flags_remain():
    flagged = {
        (_first(rule), prop)
        for rule in sheets.rules(SHEET)
        for prop, value in sheets.decl_map(rule).items()
        if "!important" in value
    }
    assert flagged == KEPT_FLAGS


def test_the_banner_left_the_shared_flagged_card_rule():
    for rule in sheets.rules("padiem-surfaces.css"):
        if ".attachment-chip" in rule.selector:
            assert ".project-banner" not in rule.selector
    banner = [
        r for r in sheets.rules(SHEET)
        if r.selector.strip() == ".project-banner" and "border" in sheets.decl_map(r)
    ]
    assert len(banner) == 1
    decls = sheets.decl_map(banner[0])
    assert decls["border"] == "1px solid var(--surfaces-attachment-edge)"
    assert decls["box-shadow"] == "inset 0 1px 0 var(--inset-veil-panel)"
    assert decls["color"] == "var(--surfaces-card-text)"
    assert all("!important" not in value for value in decls.values())


def test_the_hover_colours_that_never_painted_are_gone():
    selectors = {s.strip() for rule in sheets.rules(SHEET) for s in rule.selector.split(",")}
    for selector in DEAD_HOVER:
        assert selector not in selectors, selector
    focus = [r for r in sheets.rules(SHEET) if ".project-form input:focus" in r.selector]
    assert len(focus) == 1
    assert "border-color" not in sheets.decl_map(focus[0])
