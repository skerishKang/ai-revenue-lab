"""#7811 C2 — history.css 바탕 색 토큰화("선언 하나를 푸는 절차").

history.css의 바탕 색 9선언을 padiem-tokens.css 토큰으로 옮긴다. 값은 치환 전
사용처 리터럴 그대로다(--computed 5테마 실측에서 모두 같은 값 → :root 하나).
예외 --dialog-dim만 glass 블록이 덮는다 — history.css의 glass
.auth-dialog::backdrop 배경 선언은 지웠고(절차 5단계), 그 값은 토큰의 glass
블록이 소유한다. backdrop-filter는 색이 아니라 그 규칙에 남는다.

--dialog-dim은 padiem-settings.css .settings-dialog::backdrop과 같은 값(#5666
공유 딤)이라 부품 이름을 dialog로 지었다. 그 시트는 이 PR에서 안 바꾼다.

이번에 안 바꾼 것(다음 라운드 — 아래 시험이 지금 상태를 고정한다):
- .auth-panel/.auth-primary 계열: padiem-chat-ui-polish.css가 glass·dark 패널을
  덮어쓰고(#7118 후속 접근성 핀) @media(prefers-color-scheme: dark) 블록이
  얽혀 있다.
- 흰색 배경(.history-delete hover .08, skeleton 그라디언트): #7187 베일
  라운드 소재다.
- box-shadow·border: 바탕 색이 아니다.

판정은 "브라우저가 하는 일"(README_테스트작성규칙)이다. 선언 단위로 토큰 소비와
"토큰을 원래 리터럴로 되돌리면 치환 전 값"을 보고, 바이트 비교를 하지 않는다.
"""
from __future__ import annotations

import re
from pathlib import Path

from css_rules import (
    declaration,
    find_rules_with_selector,
    parse_rules,
    rule_selector_list_contains,
)

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
TOKENS = STATIC / "padiem-tokens.css"
HISTORY = STATIC / "history.css"

#: :root 토큰 값 — 치환 전 리터럴 그대로. 이 문자열이 계약이다.
ROOT_TOKENS = {
    "--dialog-dim": "rgba(18, 24, 31, 0.38)",
    "--control-wash-faint": "rgba(127, 127, 127, 0.06)",
    "--control-wash-soft": "rgba(127, 127, 127, 0.08)",
    "--control-wash-strong": "rgba(127, 127, 127, .14)",
    "--control-wash-hover": "rgba(127, 127, 127, .16)",
    "--danger-wash-soft": "rgba(179, 38, 30, .14)",
    "--danger-wash-strong": "rgba(179, 38, 30, .16)",
}

#: glass 테마에서만 다른 값(#5666 공유 딤의 glass 변형).
GLASS_DIALOG_DIM = "rgba(22, 30, 38, 0.32)"

#: 바꾼 선언: (선택자, 치환 전 값, 치환 후 값). 공백은 정규화 비교.
#: .auth-dialog::backdrop만 대체값을 남긴다 — ::backdrop은 옛 브라우저
#: (Safari 17.4 미만 등)에서 html의 변수를 이어받지 않아 딤이 사라진다
#: (CTO 조건 1, #7963). 색 리터럴 +1은 승인된 바다.
CHANGED = [
    (".conversation-search-input", "rgba(127, 127, 127, 0.08)", "var(--control-wash-soft)"),
    (
        ".auth-dialog::backdrop",
        "rgba(18, 24, 31, 0.38)",
        "var(--dialog-dim, rgba(18, 24, 31, 0.38))",
    ),
    (".auth-google", "rgba(127, 127, 127, 0.08)", "var(--control-wash-soft)"),
    (".auth-handoff", "rgba(127, 127, 127, 0.06)", "var(--control-wash-faint)"),
    (".auth-form input", "rgba(127, 127, 127, 0.06)", "var(--control-wash-faint)"),
    (
        ".history-actions-menu .history-menu-action:is(:hover, :focus-visible)",
        "rgba(127, 127, 127, .16)",
        "var(--control-wash-hover)",
    ),
    (".history-rename-input", "rgba(127, 127, 127, .14)", "var(--control-wash-strong)"),
    (".history-action-status", "rgba(179, 38, 30, .16)", "var(--danger-wash-strong)"),
    (
        ".history-actions-menu .history-menu-delete:is(:hover, :focus-visible)",
        "rgba(179, 38, 30, .14)",
        "var(--danger-wash-soft)",
    ),
]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def test_root_tokens_hold_the_pre_change_literals() -> None:
    """토큰의 :root 값은 치환 전 리터럴과 문자 그대로 같다."""
    rules = parse_rules(TOKENS.read_text(encoding="utf-8"))
    root = next(r for r in rules if r.selectors == [":root"] and r.media is None)
    for name, literal in ROOT_TOKENS.items():
        assert declaration(root, name) == literal, name


def test_glass_theme_block_carries_the_glass_dim() -> None:
    """--dialog-dim의 glass 값은 history.css glass 배경 선언이 읽던 값이다."""
    rules = parse_rules(TOKENS.read_text(encoding="utf-8"))
    glass = [
        r for r in rules
        if r.media is None
        and rule_selector_list_contains(r, 'html[data-theme="padiem-glass"]')
        and "--dialog-dim" in r.declarations
    ]
    assert len(glass) == 1
    assert declaration(glass[0], "--dialog-dim") == GLASS_DIALOG_DIM


def test_changed_declarations_consume_the_tokens() -> None:
    """바뀐 선언은 토큰을 쓰고, 토큰을 원래 리터럴로 되돌리면 치환 전 값이다."""
    rules = parse_rules(HISTORY.read_text(encoding="utf-8"))
    for selector, old, new in CHANGED:
        blocks = [
            r for r in find_rules_with_selector(rules, selector)
            if r.media is None and declaration(r, "background") is not None
        ]
        assert len(blocks) == 1, selector
        assert declaration(blocks[0], "background") == new, selector
        swapped = new
        for name, literal in ROOT_TOKENS.items():
            # 대체값이 있는 var(--name, literal) 형태도 원래 리터럴로 되돌린다.
            swapped = swapped.replace(f"var({name}, {literal})", literal)
            swapped = swapped.replace(f"var({name})", literal)
        assert _norm(swapped) == _norm(old), selector


def test_glass_backdrop_rule_keeps_only_the_blur() -> None:
    """glass backdrop 규칙은 배경 선언을 지웠고 blur 덮어쓰기만 남는다."""
    rules = parse_rules(HISTORY.read_text(encoding="utf-8"))
    glass = [
        r for r in find_rules_with_selector(
            rules, 'html[data-theme="padiem-glass"] .auth-dialog::backdrop')
        if r.media is None
    ]
    assert len(glass) == 1
    assert "background" not in glass[0].declarations
    assert declaration(glass[0], "backdrop-filter") == "blur(8px)"


def test_left_out_backgrounds_stay_literal() -> None:
    """이번에 안 바꾼 바탕 색은 그대로다(다음 라운드가 이 고정을 갱신한다).

    유일한 예외: .auth-dialog::backdrop의 대체값 리터럴. ::backdrop은 옛
    브라우저(Safari 17.4 미만 등)에서 html의 변수를 이어받지 않아 대체값이
    없으면 딤이 사라진다 — 토큰 값과 같은 리터럴을 fallback으로 남긴다
    (CTO 조건 1, #7963; 색 리터럴 +1 승인됨).
    """
    rules = parse_rules(HISTORY.read_text(encoding="utf-8"))
    # auth-primary base: polish의 glass·dark 덮어쓰기와 prefers-color-scheme
    # 블록이 얽혀 이번 PR 밖.
    primary = [
        r for r in find_rules_with_selector(rules, ".auth-primary")
        if r.media is None and declaration(r, "background") is not None
    ]
    assert [declaration(r, "background") for r in primary] == ["#111"]
    # 흰색 hover 배경: #7187 베일 라운드 소재.
    delete_hover = [
        r for r in find_rules_with_selector(rules, ".history-delete:hover")
        if r.media is None
    ]
    assert len(delete_hover) == 1
    assert declaration(delete_hover[0], "background") == "rgba(255, 255, 255, 0.08)"
    # skeleton: 이미 !important와 사유 주석이 있는 지역 결정(베일 라운드 소재).
    skeleton = [
        r for r in find_rules_with_selector(
            rules, "html body .app-shell .sidebar .history-row.history-skeleton")
        if r.media is None
    ]
    assert len(skeleton) == 1
    skeleton_bg = declaration(skeleton[0], "background")
    assert skeleton_bg.startswith("linear-gradient(90deg, rgba(255, 255, 255, .10)")
    assert skeleton_bg.endswith("!important")


def test_history_consumers_load_the_token_file() -> None:
    """history.css 를 로드하는 모든 페이지는 padiem-tokens.css 도 로드한다."""
    for page in sorted(STATIC.rglob("*.html")):
        html = page.read_text(encoding="utf-8")
        links = re.findall(r"<link[^>]*?href=[\"']([^\"']+\.css)[^\"']*[\"']", html)
        if any(h.endswith("history.css") for h in links):
            assert any(h.endswith("padiem-tokens.css") for h in links), page
