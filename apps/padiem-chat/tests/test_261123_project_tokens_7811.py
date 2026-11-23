"""#7811 C2 — projects.css의 색 리터럴을 쓰임새 토큰으로.

projects.css의 색 리터럴 32개 선언을 padiem-tokens.css의 쓰임새 토큰으로
옮긴다. 값은 치환 전 리터럴 그대로이고 다섯 테마에서 같은 값이므로 :root에만
둔다.
"""
from __future__ import annotations

import re

from css_rules import declaration, parse_rules, strip_comments
from _support.project_tokens_source import SHEET_TEXT, TOKEN_RULES

COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")

ROOT_TOKENS = {
    "--project-muted-text": "#5f6368",
    "--project-subtle-wash": "rgba(24, 24, 27, 0.06)",
    "--project-error-text": "#a23434",
    "--project-hairline": "rgba(24, 24, 27, 0.1)",
    "--project-panel-bg": "rgba(255, 255, 255, 0.94)",
    "--project-secondary-text": "#8a8f98",
    "--project-border": "rgba(24, 24, 27, 0.12)",
    "--project-solid-bg": "#fff",
    "--project-on-ink-text": "#fff",
    "--project-strong-text": "#4d5156",
    "--project-shadow": "rgba(24, 24, 27, 0.2)",
    "--project-dim": "rgba(20, 20, 24, 0.34)",
    "--project-hover-border": "rgba(24, 24, 27, 0.14)",
    "--project-focus-outline": "rgba(24, 24, 27, 0.16)",
    "--project-note-text": "#777c85",
    "--project-danger-text": "#b3261e",
    "--project-ink": "#18181b",
    "--project-danger-border": "rgba(179, 38, 30, 0.25)",
    "--project-select-text": "#101828",
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
    assert COLOR.search(strip_comments(SHEET_TEXT)) is None
    for name in ROOT_TOKENS:
        assert f"var({name})" in SHEET_TEXT, name


def test_nested_surface_fallback_uses_the_token() -> None:
    rules = parse_rules(SHEET_TEXT)
    values = [v for r in rules for v in r.declarations.values()
              if "var(--surface," in v]
    assert len(values) == 2
    assert all("var(--project-solid-bg)" in v for v in values)


def test_tokens_are_defined_only_in_the_token_file() -> None:
    for name in ROOT_TOKENS:
        assert f"{name}:" not in SHEET_TEXT, name
