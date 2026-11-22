"""#7811 C2 calendar(261122) — calendar.css 고정 팔레트 색을 쓰임새 토큰으로.

calendar.css의 무테마 색 선언(49개)을 padiem-tokens.css의 --calendar-*
토큰으로 옮긴다. 값은 치환 전 사용처 리터럴 그대로이고, 캘린더 화면은 모든
테마에서 같은 값으로 칠해져 온 고정 팔레트라 :root 하나로 충분하며
html[data-theme="…"] 블록에서 덮지 않는다(--dialog-dim처럼 예외만 두는
것과 같은 취지다).

var(--card-bg, #fafafa) 6곳은 --card-bg가 5테마 블록에 전부 정의되어
fallback이 실제로 쓰이지 않으므로 var(--card-bg)로 줄였다(토큰 파일의
소비 규칙 "fallback 없이"와 같다). var(--paper, #fff)는 --paper가
어디에도 정의되지 않은 이름이라 fallback이 실제 값이었고, --calendar-paper
의 :root 값으로 옮겼다.
"""
from __future__ import annotations

import re

from css_rules import find_rules_with_selector
from _support.calendar_palette import (
    THEMES,
    calendar_rules,
    calendar_source,
    glass_defines_card_bg,
    root_declarations,
    theme_declarations,
)

#: :root 값 — 치환 전 calendar.css 리터럴 그대로. 이 문자열이 계약이다.
ROOT_TOKENS = {
    "--calendar-paper": "#fff",
    "--calendar-error-border": "rgba(214, 108, 108, .38)",
    "--calendar-error-bg": "rgba(214, 108, 108, .08)",
    "--calendar-error-compact-bg": "rgba(214, 108, 108, .07)",
    "--calendar-error-compact-border": "rgba(214, 108, 108, .24)",
    "--calendar-error-text": "#a33737",
    "--calendar-status-invalid-text": "#d66c6c",
    "--calendar-delete-text": "#af423d",
    "--calendar-item-type-bg": "rgba(47, 111, 153, .14)",
    "--calendar-submit-bg": "rgba(121, 188, 231, .18)",
    "--calendar-nav-current-bg": "rgba(121, 188, 231, .22)",
    "--calendar-focus-outline": "#3c80ae",
    "--calendar-editor-outline": "#396e92",
    "--calendar-today-text": "#24658f",
    "--calendar-visual-border": "rgba(149,173,192,.30)",
    "--calendar-visual-bg": "rgba(255,255,255,.62)",
    "--calendar-weekday-bg": "rgba(222,233,241,.56)",
    "--calendar-weekday-border": "#d8e4ec",
    "--calendar-weekday-text": "#607483",
    "--calendar-grid-bg": "#d8e1e7",
    "--calendar-day-text": "#334758",
    "--calendar-day-outside-text": "#9aa6b0",
    "--calendar-event-bg": "#dae8f3",
    "--calendar-event-text": "#335873",
    "--calendar-worklog-bg": "#e3ebec",
    "--calendar-worklog-text": "#4a6467",
    "--calendar-alert-bg": "#f5e9de",
    "--calendar-alert-text": "#8b5b38",
    "--calendar-more-text": "#607789",
    "--calendar-week-date-text": "#405e75",
    "--calendar-allday-bg": "#edf3f7",
    "--calendar-allday-border": "#dbe5ec",
    "--calendar-allday-label-text": "#657c8c",
    "--calendar-hour-border": "#e4ebf0",
    "--calendar-hour-label-text": "#6b7d8d",
    "--calendar-overlay-border": "#bed1df",
    "--calendar-overlay-bg": "#f9fbfc",
    "--calendar-overlay-shadow": "0 18px 60px rgba(35,55,73,.29)",
    "--calendar-editor-border": "#cbdbe5",
    "--calendar-editor-bg": "#eef4f8",
    "--calendar-editor-text": "#385f79",
    "--calendar-unknown-type-bg": "rgba(120, 120, 130, .16)",
}

#: calendar.css가 읽어야 하는 토큰(소비 선언). 값의 출처는 토큰 파일 한 곳뿐이다.
CONSUMERS = {
    ".calendar-record-field input": ("background", "var(--calendar-paper)"),
    ".calendar-record-field textarea": ("background", "var(--calendar-paper)"),
    ".calendar-error": ("background", "var(--calendar-error-bg)"),
    ".calendar-item-type": ("background", "var(--calendar-item-type-bg)"),
    '.calendar-item[data-item-type="unknown"] .calendar-item-type': (
        "background", "var(--calendar-unknown-type-bg)"),
    ".calendar-record-submit": ("background", "var(--calendar-submit-bg)"),
    '#calendarNavButton[aria-current="page"]': (
        "background", "var(--calendar-nav-current-bg)"),
    ".calendar-visual": ("background", "var(--calendar-visual-bg)"),
    ".calendar-visual-weekdays": ("background", "var(--calendar-weekday-bg)"),
    ".calendar-visual-weekday": ("color", "var(--calendar-weekday-text)"),
    ".calendar-month-grid": ("background", "var(--calendar-grid-bg)"),
    ".calendar-visual-day": ("color", "var(--calendar-day-text)"),
    ".calendar-visual-day.is-outside": ("color", "var(--calendar-day-outside-text)"),
    ".calendar-visual-event": ("background", "var(--calendar-event-bg)"),
    '.calendar-visual-event[data-event-type="work_log"]': (
        "background", "var(--calendar-worklog-bg)"),
    '.calendar-visual-event[data-event-type="alert"]': (
        "background", "var(--calendar-alert-bg)"),
    ".calendar-visual-more": ("color", "var(--calendar-more-text)"),
    ".calendar-week-grid": ("background", "var(--calendar-grid-bg)"),
    ".calendar-week-date": ("color", "var(--calendar-week-date-text)"),
    ".calendar-day-all-day": ("background", "var(--calendar-allday-bg)"),
    ".calendar-day-all-day-label": ("color", "var(--calendar-allday-label-text)"),
    ".calendar-day-hour-label": ("color", "var(--calendar-hour-label-text)"),
}

COLOR_RX = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\s*\(|hsla?\s*\(")


def test_root_carries_the_fixed_calendar_palette() -> None:
    decls = root_declarations()
    for name, value in ROOT_TOKENS.items():
        assert decls.get(name) == value, name


def test_theme_blocks_do_not_override_the_calendar_palette() -> None:
    """고정 팔레트: 어느 테마 블록에서도 --calendar-*를 덮지 않는다."""
    for theme in THEMES:
        for prop in theme_declarations(theme):
            assert not prop.startswith("--calendar-"), (theme, prop)


def test_calendar_consumes_tokens_and_keeps_no_unthemed_literal() -> None:
    rules = calendar_rules()
    for selector, (prop, value) in CONSUMERS.items():
        matched = find_rules_with_selector(rules, selector)
        assert matched, selector
        values = [r.declarations[prop] for r in matched if prop in r.declarations]
        assert value in values, (selector, prop, values)
    for rule in rules:
        if any("data-theme" in s for s in rule.selectors):
            continue
        for prop, value in rule.declarations.items():
            if prop.startswith("--"):
                continue
            assert not COLOR_RX.search(value), (rule.selectors, prop, value)


def test_card_bg_fallback_is_gone_but_value_is_kept() -> None:
    """--card-bg는 5테마에 전부 정의되어 fallback이 쓰이지 않았다."""
    src = calendar_source()
    assert "var(--card-bg, #fafafa)" not in src
    assert src.count("var(--card-bg)") >= 6
    for theme in ("light", "dark", "cinematic", "padiem-home"):
        assert "--card-bg" in theme_declarations(theme), theme
    # glass는 토큰 파일이 아니라 padiem-glass.css가 --card-bg를 소유한다
    # (토큰 파일 앞부분 주석의 유일한 예외). 그 값도 정의되어 있다.
    assert glass_defines_card_bg()
