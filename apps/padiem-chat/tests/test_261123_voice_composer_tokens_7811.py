"""#7811 C2 — composer의 색 리터럴을 쓰임새 토큰으로.

voice-composer.css의 색 리터럴 32개 선언을 토큰으로 옮긴다. 마이크 기본·호버
값은 voice UI와 같은 역할이라 기존 --voice-* 토큰을 재사용하고, 나머지는
새 쓰임새 토큰으로 옮긴다. 값은 치환 전 리터럴 그대로다.
"""
from __future__ import annotations

import re

from css_rules import declaration, parse_rules, strip_comments
from _support.voice_composer_tokens_source import SHEET_TEXT, TOKEN_RULES

COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")

ROOT_TOKENS = {
    "--voice-mic-active-bg": "#d94b43",
    "--voice-mic-active-edge": "#c43d36",
    "--voice-mic-active-ring": "rgba(217, 75, 67, .16)",
    "--voice-mic-active-hover-bg": "#c63d35",
    "--voice-mic-active-hover-edge": "#b9342f",
    "--composer-send-text": "#fff",
    "--composer-send-shadow": "rgba(34, 72, 104, .15)",
    "--composer-send-hover-shadow": "rgba(34, 72, 104, .22)",
    "--composer-send-disabled-bg": "#c9d3dc",
    "--composer-send-disabled-edge": "#b9c7d2",
    "--voice-interim-text": "#6b6c75",
    "--voice-notice-text": "#a04139",
    "--voice-inline-hint-text": "#bd4a40",
    "--starter-toggle-edge": "#d9e1e8",
    "--starter-toggle-bg": "rgba(247,250,253,.94)",
    "--starter-toggle-text": "#596c7b",
    "--starter-toggle-hover-bg": "#edf3f9",
    "--starter-panel-bg": "#fff",
    "--starter-panel-text": "#293d50",
    "--starter-panel-edge": "#d2dfe7",
    "--starter-panel-shadow": "rgba(29,48,64,.17)",
}

REUSED = (
    "--voice-control-border", "--voice-accent", "--voice-btn-idle-bg",
    "--voice-btn-idle-shadow", "--voice-btn-hover-text",
    "--voice-btn-hover-bg", "--voice-btn-hover-border",
    "--voice-btn-active-text",
)


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


def test_sheet_consumes_new_and_reused_tokens_without_raw_colors() -> None:
    assert COLOR.search(strip_comments(SHEET_TEXT)) is None
    for name in tuple(ROOT_TOKENS) + REUSED:
        assert f"var({name})" in SHEET_TEXT, name


def test_existing_important_declaration_keeps_its_strength() -> None:
    rules = parse_rules(SHEET_TEXT)
    matches = [r for r in rules
               if any(s.endswith(".send-button:not(:disabled)") for s in r.selectors)
               and any(v.endswith("!important") for v in r.declarations.values())]
    assert len(matches) == 1
    assert matches[0].declarations["color"] == "var(--composer-send-text) !important"
    assert matches[0].declarations["background"] == "var(--primary-bg) !important"


def test_tokens_are_defined_only_in_the_token_file() -> None:
    for name in ROOT_TOKENS:
        assert f"{name}:" not in SHEET_TEXT, name
