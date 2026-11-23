"""#7811 C2 — settings의 테마 밖 색 리터럴을 쓰임새 토큰으로.

padiem-settings.css의 data-theme 범위 밖 색 리터럴 30개 선언을 토큰으로 옮긴다.
같은 값이라도 테마별 덮개가 있는 기존 토큰(--dialog-dim 등)은 재사용하지 않는다.
"""
from __future__ import annotations

import re

from css_rules import declaration, parse_rules, strip_comments
from _support.settings_tokens_source import SHEET_TEXT, TOKEN_RULES

COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")

ROOT_TOKENS = {
    "--settings-selected-text": "#fff",
    "--settings-selected-shadow": "rgba(0,0,0,.12)",
    "--settings-dialog-dim": "rgba(18, 24, 31, .38)",
    "--settings-panel-edge": "rgba(255, 255, 255, .72)",
    "--settings-panel-bg": "rgba(247, 250, 252, .94)",
    "--settings-panel-shadow": "rgba(17, 25, 33, .24)",
    "--settings-header-edge": "rgba(70, 83, 95, .12)",
    "--settings-label-text": "#65717c",
    "--settings-close-edge": "rgba(55, 68, 80, .14)",
    "--settings-close-text": "#2a3741",
    "--settings-section-edge": "rgba(70, 83, 95, .10)",
    "--settings-heading-text": "#1b2730",
    "--settings-choice-fallback": "#fafafa",
    "--settings-switch-track": "rgba(127, 127, 127, .24)",
    "--settings-switch-knob": "#fff",
    "--settings-switch-knob-shadow": "rgba(0, 0, 0, .24)",
    "--settings-primary-text": "#fff",
    "--settings-action-edge": "rgba(62, 76, 88, .14)",
    "--settings-action-bg": "rgba(255, 255, 255, .58)",
    "--settings-action-text": "#33424e",
    "--settings-focus-outline": "#587c97",
    "--settings-danger-desc-text": "#5b4a44",
    "--settings-input-edge": "rgba(62, 76, 88, .22)",
    "--settings-input-bg": "rgba(255, 255, 255, .8)",
    "--settings-action-hover-bg": "rgba(255, 255, 255, .86)",
    "--settings-action-hover-edge": "rgba(42, 57, 69, .24)",
    "--settings-guide-bg": "rgba(255, 255, 255, .2)",
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def test_root_tokens_hold_the_pre_change_literals() -> None:
    roots = [r for r in TOKEN_RULES if r.selectors == [":root"] and r.media is None]
    assert len(roots) == 1
    for name, literal in ROOT_TOKENS.items():
        assert _norm(declaration(roots[0], name)) == _norm(literal), name


def test_tokens_are_theme_invariant() -> None:
    for rule in TOKEN_RULES:
        if rule.media is not None or not rule.selectors:
            continue
        if not rule.selectors[0].startswith("html[data-theme="):
            continue
        for name in ROOT_TOKENS:
            assert declaration(rule, name) is None, (rule.selectors[0], name)


def test_unthemed_declarations_have_no_raw_colors() -> None:
    for rule in parse_rules(SHEET_TEXT):
        for prop, value in rule.declarations.items():
            if rule.selectors and rule.selectors[0].startswith("html[data-theme="):
                continue
            assert COLOR.search(value) is None, (rule.selectors, prop, value)
    for name in ROOT_TOKENS:
        assert f"var({name})" in SHEET_TEXT, name


def test_theme_varying_tokens_are_not_reused() -> None:
    for name in ("--dialog-dim", "--auth-panel-border"):
        assert f"var({name})" not in SHEET_TEXT, name


def test_tokens_are_defined_only_in_the_token_file() -> None:
    for name in ROOT_TOKENS:
        assert f"{name}:" not in SHEET_TEXT, name
