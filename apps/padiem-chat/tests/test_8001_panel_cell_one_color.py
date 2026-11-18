"""#8001 대표 결정(11-18 08:38) — 첫 묶음 3판의 한 판 원칙 계약.

설정 창 · 모델·등급 선택 · 대화 행 ⋮ 메뉴: 판 안 칸 배경은 그 판의 토큰 하나
(--card-bg), 호버는 판의 한 단계(--control-wash-hover) 하나다. 선택
(aria-pressed) 칸은 호버 때도 선택 상태를 유지하며, 삭제 칸의 위험 표시는
글자·아이콘 색이 담당한다(칸 배경 호버는 한 단계로 통일).

실측 근거(261119, 5테마 × 계산 색): 설정 창 호버는 배경이 변하지 않았고
(ID 규칙이 테마 호버를 이김), 모델 선택 호버는 rgba(255,255,255,.84)라
어두운 테마에서 흰 낙도·glass에서 선택 칸과 같은 색이었으며, ⋮ 메뉴 삭제 칸만
--danger-wash-soft(빨강)로 갈라져 있었다.
"""

from __future__ import annotations

from pathlib import Path

from css_rules import declaration, parse_rules, rule_selector_list_contains

STATIC = Path(__file__).resolve().parents[1] / "static"
SETTINGS_CSS = (STATIC / "padiem-settings.css").read_text(encoding="utf-8")
DARK_CSS = (STATIC / "padiem-dark-contrast.css").read_text(encoding="utf-8")
MODE_CSS = (STATIC / "mode-presentation.css").read_text(encoding="utf-8")
HISTORY_CSS = (STATIC / "history.css").read_text(encoding="utf-8")
GLASS_FRAME_CSS = (STATIC / "shared-six-panel-frame.css").read_text(encoding="utf-8")
TOKENS_CSS = (STATIC / "padiem-tokens.css").read_text(encoding="utf-8")

CHOICE_HOVER = '#settingsDialog .settings-choice:not([aria-pressed="true"]):hover'
SECONDARY_HOVER = "#settingsDialog .settings-action-secondary:hover"
CLOSE_HOVER = "#settingsDialog .settings-close:hover"
MODE_HOVER = '.mode-option:not(:disabled):not([aria-pressed="true"]):hover'
MENU_ACTION_HOVER = ".history-actions-menu .history-menu-action:is(:hover, :focus-visible)"
MENU_DELETE_HOVER = ".history-actions-menu .history-menu-delete:is(:hover, :focus-visible)"
GLASS_ACTION_HOVER = (
    'html[data-theme="padiem-glass"] body .sidebar .history-actions-menu '
    ".history-menu-action:is(:hover,:focus-visible)"
)
GLASS_DELETE_HOVER = (
    'html[data-theme="padiem-glass"] body .sidebar .history-actions-menu '
    ".history-menu-delete:is(:hover,:focus-visible)"
)
GLASS_OPEN_ROW = (
    'html[data-theme="padiem-glass"] body .app-shell .sidebar '
    ".history-row:has(.history-actions[open])"
)


def _rules(css: str):
    return parse_rules(css)


def _one(rules: list, selector: str, label: str):
    matched = [rule for rule in rules if rule.selectors == [selector]]
    assert len(matched) == 1, f"{label}: 기대한 규칙 1개, 실제 {len(matched)}개"
    return matched[0]


def _value(rule, prop: str) -> str:
    raw = declaration(rule, prop)
    assert raw is not None, f"{prop} 선언이 없다"
    return raw.replace("!important", "").strip()


def test_settings_dialog_cells_share_one_background_token() -> None:
    rules = _rules(SETTINGS_CSS)
    choice = _one(rules, "#settingsDialog .settings-choice", "설정 칸")
    assert _value(choice, "background") == "var(--card-bg, #fafafa)"
    close = _one(rules, ".settings-close", "닫기 단추")
    assert _value(close, "background") == "var(--card-bg)"

    # 테마별 배경 덮음은 닫기 단추에서 내려간다 — 칸 바탕은 --card-bg 하나.
    glass_rules = [rule for rule in rules if any(
        'html[data-theme="padiem-glass"]' in s and s.endswith(".settings-close")
        for s in rule.selectors
    )]
    assert len(glass_rules) == 1, f"glass 닫기 규칙 {len(glass_rules)}개"
    assert declaration(glass_rules[0], "background") is None, (
        "glass 닫기 단추 배경 덮음이 남아 있다"
    )

    dark_close = _one(
        _rules(DARK_CSS),
        'html[data-theme="dark"] body .app-shell .settings-dialog .settings-close',
        "dark 닫기 단추",
    )
    assert declaration(dark_close, "background") is None, (
        "dark 닫기 단추 배경 덮음이 남아 있다"
    )


def test_settings_dialog_hover_is_one_step_and_skips_selected() -> None:
    rules = _rules(SETTINGS_CSS)
    for selector in (CHOICE_HOVER, SECONDARY_HOVER, CLOSE_HOVER):
        rule = _one(rules, selector, f"{selector} 호버")
        assert _value(rule, "background") == "var(--control-wash-hover)", selector
    # 선택 칸은 호버 때도 accent-soft를 유지한다(호버 규칙 대상에서 뺐다).
    assert ':not([aria-pressed="true"])' in CHOICE_HOVER
    # 예전의 변하지 않던 호버(배경 없음·같은 배경 재선언)는 돌아오지 않는다.
    old_secondary = _one(rules, SECONDARY_HOVER, "보조 단추 호버")
    assert _value(old_secondary, "border-color") == "var(--accent-strong)"


def test_mode_options_hover_is_one_step_and_skips_selected() -> None:
    rules = _rules(MODE_CSS)
    hover = _one([rule for rule in rules if rule.media is None], MODE_HOVER, "등급칸 호버")
    assert _value(hover, "background") == "var(--control-wash-hover)"
    assert _value(hover, "border-color") == "var(--accent)"
    # 터치(호버 없음) 되돌림도 같은 대상(선택 칸 제외)에만 맞춰진다.
    touch = [rule for rule in rules if rule.media == "(hover: none)" and
             rule.selectors == [MODE_HOVER]]
    assert len(touch) == 1, f"(hover: none) 되돌림 규칙 {len(touch)}개"
    # 흰 낙도 호버 리터럴은 등급칸(mode-option)의 어떤 호버 규칙에도 돌아오지
    # 않는다(트리거 model-pill 호버는 칸이 아니라 이 계약의 대상이 아니다).
    for rule in rules:
        if any(":hover" in s and ".mode-option" in s for s in rule.selectors):
            for value in rule.declarations.values():
                assert "rgba(255, 255, 255, .84)" not in value, (
                    f"흰 낙도 호버가 남아 있다: {rule.selectors}"
                )


def test_history_menu_hover_is_one_wash_for_every_cell() -> None:
    rules = _rules(HISTORY_CSS)
    action_hover = _one(rules, MENU_ACTION_HOVER, "⋮ 항목 호버")
    assert _value(action_hover, "background") == "var(--control-wash-hover)"
    delete_hover = _one(rules, MENU_DELETE_HOVER, "⋮ 삭제 호버")
    assert _value(delete_hover, "background") == "var(--control-wash-hover)"
    assert "--danger-wash-soft" not in (declaration(delete_hover, "background") or "")

    glass_rules = _rules(GLASS_FRAME_CSS)
    assert _value(_one(glass_rules, GLASS_ACTION_HOVER, "glass ⋮ 항목 호버"),
                  "background") == "var(--control-wash-hover)"
    assert _value(_one(glass_rules, GLASS_DELETE_HOVER, "glass ⋮ 삭제 호버"),
                  "background") == "var(--control-wash-hover)"


def test_glass_open_menu_row_is_lifted_above_sibling_rows() -> None:
    """유리 행은 자체 스태킹 문맥(blur)이라 열린 ⋮ 메뉴가 뒤 행 칸에 가려진다.

    실측(261119): 메뉴를 연 행이 형제 행·아래 도구 칸에 가려져 elementFromPoint가
    메뉴 대신 뒤 칸을 돌려줬다(호버·클릭 차단). 메뉴를 연 행만 위로 올린다.
    """
    rule = _one(_rules(GLASS_FRAME_CSS), GLASS_OPEN_ROW, "열린 ⋮ 행 끌어올림")
    assert _value(rule, "z-index") == "30"
    assert _value(rule, "position") == "relative"


def test_control_wash_hover_token_is_root_only_and_shared_by_all_themes() -> None:
    """판의 호버 한 단계는 :root 하나의 값 — 5테마 같은 값(테마 덮음 없음).

    #7811이 media 안의 :root(prefers-color-scheme dark의 auth 핀)를 추가했으므로
    기준 :root는 media 밖의 것으로 가리고, 이 토큰을 정의하는 규칙은 그 하나뿐
    임을 전체 시트로 단정한다.
    """
    rules = _rules(TOKENS_CSS)
    root_rules = [rule for rule in rules
                  if rule.media is None and rule.selectors == [":root"]]
    assert len(root_rules) == 1
    assert declaration(root_rules[0], "--control-wash-hover") == "rgba(127, 127, 127, .16)"
    for rule in rules:
        if rule is root_rules[0]:
            continue
        assert declaration(rule, "--control-wash-hover") is None, (
            f"다른 규칙이 호버 토큰을 정의하거나 덮는다: {rule.selectors} media={rule.media}"
        )
