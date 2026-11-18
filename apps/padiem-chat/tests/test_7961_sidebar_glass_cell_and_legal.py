"""#7961 대표 결정(11-18 08:38) — 유리 테마의 한 칸 원칙과 약관 줄 계약.

1. 대화·프로젝트 행은 위쪽 사이드바 메뉴(유틸·캘린더 등)와 **같은 선언·값**의
   유리 셀을 쓴다(같은 배경 토큰, 같은 흰 글자 토큰). 어두운 var(--sidebar)
   덮음은 다시 들어오지 못한다. 대비가 4.5:1 미만이어도 대표가 받아들인다.
2. 약관(개인정보처리방침·이용약관) 줄은 계정 단추 바로 아래 상시 한 줄이다 —
   게스트·로그인·만료 모두 같은 자리. 프로필 메뉴 안에는 약관 링크가 없다.
"""

from __future__ import annotations

from pathlib import Path

from css_rules import declaration, parse_rules

STATIC = Path(__file__).resolve().parents[1] / "static"
GLASS_CSS = (STATIC / "padiem-glass.css").read_text(encoding="utf-8")
TOKENS_CSS = (STATIC / "padiem-tokens.css").read_text(encoding="utf-8")
UTILITY_CSS = (STATIC / "sidebar-utility.css").read_text(encoding="utf-8")
DARK_CSS = (STATIC / "padiem-dark-contrast.css").read_text(encoding="utf-8")
SCROLL_CSS = (STATIC / "sidebar-history-scroll.css").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")

ROW_BASE = (
    'html[data-theme="padiem-glass"] body .app-shell .sidebar '
    ":is(.project-row, .history-row)"
)
ROW_HOVER = ROW_BASE + ":is(:hover, :focus-within)"
CELL_SELECTOR = 'html[data-theme="padiem-glass"] .recent-item'
CELL_HOVER_SELECTOR = 'html[data-theme="padiem-glass"] .recent-item:hover'
UNIFIED_CSS = (STATIC / "sidebar-unified.css").read_text(encoding="utf-8")


def _only(rules: list, predicate, label: str):
    matched = [rule for rule in rules if predicate(rule)]
    assert len(matched) == 1, f"{label}: 기대한 규칙 1개, 실제 {len(matched)}개"
    return matched[0]


def _value(rule, prop: str) -> str:
    raw = declaration(rule, prop)
    assert raw is not None, f"{prop} 선언이 없다"
    return raw.replace("!important", "").strip()


def _row_rule(rules: list, selectors: list[str], label: str):
    return _only(rules, lambda rule: rule.selectors == selectors, label)


def _selected_row_rule(rules: list):
    return _only(
        rules,
        lambda rule: any(":has(.history-item[aria-current=\"page\"])" in s for s in rule.selectors),
        "선택된 최근 대화 행",
    )


def test_glass_history_row_reuses_the_upper_menu_cell_declaration() -> None:
    rules = parse_rules(GLASS_CSS)
    cell = _only(rules, lambda rule: CELL_SELECTOR in rule.selectors, "위 메뉴 유리 칸")
    cell_hover = _only(
        rules, lambda rule: CELL_HOVER_SELECTOR in rule.selectors, "위 메뉴 유리 칸 호버"
    )
    row = _row_rule(rules, [ROW_BASE], "대화 행 유리 칸")
    row_hover = _row_rule(rules, [ROW_HOVER], "대화 행 호버")
    row_selected = _selected_row_rule(rules)

    # 같은 배경: 행이 위 메뉴 칸과 완전히 같은 선언·값을 쓴다.
    assert _value(row, "background") == _value(cell, "background") == "var(--glass-cell-bg)"
    assert _value(row_hover, "background") == _value(cell_hover, "background")
    assert _value(row_hover, "background") == "var(--glass-cell-bg-active)"
    # 테두리·입체감도 위 칸과 같은 토큰.
    assert _value(row, "border") == "1px solid var(--glass-cell-border)"
    assert _value(cell, "border-color") == "var(--glass-cell-border)"
    assert _value(row, "box-shadow") == _value(cell, "box-shadow") == "var(--glass-cell-inset)"

    # 호버·선택은 셀 색만 같은 방식으로 바꾼다.
    assert _value(row_selected, "background") == _value(row_hover, "background")
    assert _value(row_selected, "border-color") == _value(row_hover, "border-color")

    # 어두운 덮음(var(--sidebar))은 어떤 행 상태에도 돌아오지 않는다.
    for rule in (row, row_hover, row_selected):
        for value in rule.declarations.values():
            assert "var(--sidebar)" not in value, "어두운 사이드바 덮음이 다시 들어왔다"


def test_glass_row_text_keeps_the_sidebar_white_token() -> None:
    """행 글자는 사이드바 글자 토큰을 그대로 이어받는다(유리 테마 흰색)."""
    unified_rules = parse_rules(UNIFIED_CSS)
    row_item = _only(
        unified_rules,
        lambda rule: any(
            ":is(.project-row, .history-row) > :is(.project-item, .history-item)" in s
            for s in rule.selectors
        ),
        "행 글자 규칙",
    )
    assert _value(row_item, "color") == "var(--sidebar-text, var(--text))"
    token_rules = parse_rules(TOKENS_CSS)
    glass = _only(
        token_rules, lambda rule: rule.selectors == ['html[data-theme="padiem-glass"]'], "유리 토큰"
    )
    # 유리 테마의 사이드바 글자는 흰색 계열이다(#f7f9fb).
    assert _value(glass, "--sidebar-text") == "#f7f9fb"


def test_the_shared_cell_token_keeps_the_previously_shipped_value() -> None:
    """토큰화는 값을 바꾸지 않는다 — 위 칸이 쓰던 리터럴 그대로다."""
    token_rules = parse_rules(TOKENS_CSS)
    glass = _only(
        token_rules, lambda rule: rule.selectors == ['html[data-theme="padiem-glass"]'], "유리 토큰"
    )
    assert _value(glass, "--glass-cell-bg") == "rgba(241, 245, 248, .12)"
    assert _value(glass, "--glass-cell-bg-active") == "rgba(248, 250, 252, .20)"
    assert _value(glass, "--glass-cell-border") == "rgba(255, 255, 255, .20)"
    assert _value(glass, "--glass-cell-border-active") == "rgba(255, 255, 255, .32)"
    assert _value(glass, "--glass-cell-inset") == "inset 0 1px 0 rgba(255, 255, 255, .08)"


def test_the_legal_line_is_a_permanent_sibling_under_the_account_cell() -> None:
    # 메뉴 밖, 계정 단추 바로 아래: 숨김 속성 없는 항상 보이는 한 줄.
    assert '<p class="sidebar-legal">' in HTML
    assert 'class="profile-menu-legal"' not in HTML
    sidebar_bottom = HTML[HTML.index('class="sidebar-bottom"'):HTML.index("</aside>")]
    legal_at = sidebar_bottom.index('class="sidebar-legal"')
    menu_start = sidebar_bottom.index('id="profileMenu"')
    menu_close = sidebar_bottom.index("</div>", menu_start)
    assert menu_start < menu_close < legal_at
    legal_line = sidebar_bottom[legal_at:sidebar_bottom.index("</p>", legal_at)]
    assert 'href="./privacy.html" data-locale-key="legal-privacy"' in legal_line
    assert 'href="./terms.html" data-locale-key="legal-terms"' in legal_line
    # 계정 셀(로그인/서명 상태) 뒤에 온다 — 상태별로 다른 자리가 아니다.
    account_start = sidebar_bottom.index('class="sidebar-account account-controls"')
    account_close = sidebar_bottom.index("</div>", menu_close)
    assert account_start < account_close < legal_at

    # 글자색은 사이드바 글자 토큰(게스트·로그인 공통).
    utility_rules = parse_rules(UTILITY_CSS)
    legal_rule = _only(
        utility_rules, lambda rule: ".sidebar-legal" in rule.selectors, "약관 줄"
    )
    assert _value(legal_rule, "color") == "var(--sidebar-menu-text, var(--sidebar-text, var(--text)))"
    assert ".profile-menu-legal" not in UTILITY_CSS
    # 11px 글자라도 링크 터치 영역은 24×24 (a11y 최소 목표 크기).
    link_rule = _only(
        utility_rules, lambda rule: rule.selectors == [".sidebar-legal a"], "약관 링크"
    )
    assert _value(link_rule, "min-height") == "24px"

    # 어떤 스크립트도 이 줄을 상태에 따라 숨기지 않는다.
    for script in STATIC.glob("*.js"):
        assert "sidebar-legal" not in script.read_text(encoding="utf-8"), script.name


def test_the_account_menu_carries_no_legal_links() -> None:
    sidebar_bottom = HTML[HTML.index('class="sidebar-bottom"'):HTML.index("</aside>")]
    menu_start = sidebar_bottom.index('id="profileMenu"')
    menu = sidebar_bottom[menu_start:sidebar_bottom.index("</div>", menu_start)]
    assert "legal-privacy" not in menu
    assert "legal-terms" not in menu
    assert "privacy.html" not in menu
    assert "terms.html" not in menu


def test_dark_theme_leaves_account_menu_cells_unpainted() -> None:
    for rule in parse_rules(DARK_CSS):
        for selector in rule.selectors:
            assert ".sidebar-bottom :is(.home-link, .settings-button)" not in selector
            assert ".profile-menu" not in selector
    menu_cell = _only(
        parse_rules(UTILITY_CSS),
        lambda rule: rule.selectors == [
            ".sidebar-account .profile-menu :is(.settings-button, .side-item, .home-link, .profile-menu-logout)"
        ],
        "계정 메뉴 칸",
    )
    assert _value(menu_cell, "background") == "transparent"
    assert _value(menu_cell, "border-color") == "transparent"


def test_legal_links_share_the_upper_menu_text_token() -> None:
    link = _only(
        parse_rules(UTILITY_CSS),
        lambda rule: rule.selectors == [".sidebar-legal a"],
        "약관 링크",
    )
    assert _value(link, "color") == "var(--sidebar-menu-text, var(--sidebar-text, var(--text)))"
    token_rules = parse_rules(TOKENS_CSS)
    for theme in ("light", "dark", "cinematic", "padiem-home", "padiem-glass"):
        block = _only(
            token_rules,
            lambda rule: rule.selectors == [f'html[data-theme="{theme}"]'],
            f"{theme} 토큰",
        )
        assert _value(block, "--sidebar-menu-text"), f"{theme}: 메뉴 글자 토큰 없음"
        assert _value(block, "--sidebar-solid"), f"{theme}: 불투명 바탕 토큰 없음"


def test_every_width_pins_account_and_legal_together() -> None:
    bottom = _only(
        parse_rules(UTILITY_CSS),
        lambda rule: rule.selectors == ["html body .app-shell .sidebar .sidebar-bottom"]
        and rule.media is None,
        "전체 너비 하단 고정 영역",
    )
    assert _value(bottom, "position") == "sticky"
    assert _value(bottom, "bottom") == "0"
    assert _value(bottom, "background-color") == "var(--sidebar-solid)"
    assert _value(bottom, "background-image") == "inherit"
    assert _value(bottom, "border-top") == "1px solid var(--line)"
    narrow = [
        rule
        for rule in parse_rules(SCROLL_CSS)
        if rule.selectors == ["html body .app-shell .sidebar .sidebar-bottom"]
        and rule.media == "(max-width: 920px)"
    ]
    assert all("position" not in rule.declarations for rule in narrow)


def test_utility_buttons_scroll_outside_the_pinned_area() -> None:
    tools_start = HTML.index('class="sidebar-bottom-tools"')
    pinned_start = HTML.index('class="sidebar-bottom"', tools_start)
    tools = HTML[tools_start:pinned_start]
    for button_id in ("newsButton", "feedbackButton", "helpNavLink"):
        assert f'id="{button_id}"' in tools
    assert "sidebar-account" not in tools
    assert 'class="sidebar-legal"' not in tools