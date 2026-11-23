"""#7811 C2 — voice UI의 색 리터럴을 쓰임새 토큰으로.

voice-ui.css의 색 리터럴 34개 선언을 padiem-tokens.css의 쓰임새 토큰으로
옮긴다. 값은 치환 전 리터럴 그대로이고 다섯 테마에서 같은 값이므로 :root에만
두며 테마 블록에서는 덮지 않는다.
"""
from __future__ import annotations

import re

from css_rules import declaration
from _support.voice_ui_tokens_source import SHEET_TEXT, TOKEN_RULES

COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")

ROOT_TOKENS = {
    "--voice-control-border": "#bed0dd",
    "--voice-accent": "#587c97",
    "--voice-btn-idle-bg": "#eaf2f7",
    "--voice-btn-idle-shadow": "rgba(36, 68, 92, .07)",
    "--voice-btn-hover-text": "#355d79",
    "--voice-btn-hover-bg": "#deebf3",
    "--voice-btn-hover-border": "#a7c0d2",
    "--voice-btn-active-text": "#fff",
    "--voice-btn-active-bg": "#2f7d61",
    "--voice-btn-active-border": "#2a6d55",
    "--voice-assistant-role-text": "#2a6d55",
    "--voice-btn-active-ring": "rgba(47, 125, 97, .16)",
    "--voice-unavailable-text": "#8aa2b3",
    "--voice-unavailable-bg": "#f1f5f8",
    "--voice-unavailable-border": "#d6e2ea",
    "--voice-panel-bg": "#ffffff",
    "--voice-menu-shadow": "rgba(0, 0, 0, .12)",
    "--voice-subtle-bg": "#f2f7fb",
    "--voice-menu-active-bg": "#eef4f9",
    "--voice-panel-shadow": "rgba(0, 0, 0, .16)",
    "--voice-danger": "#b3261e",
    "--voice-secondary-text": "#4a6576",
    "--voice-assistant-text": "#2b4453",
    "--voice-transcript-border": "#e4eaef",
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


def test_sheet_consumes_tokens_without_raw_colors() -> None:
    from css_rules import strip_comments

    assert COLOR.search(strip_comments(SHEET_TEXT)) is None
    for name in ROOT_TOKENS:
        assert f"var({name})" in SHEET_TEXT, name


def test_tokens_are_defined_only_in_the_token_file() -> None:
    for name in ROOT_TOKENS:
        assert f"{name}:" not in SHEET_TEXT, name
