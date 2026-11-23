"""#7811 C2 — styles.css 남은 바탕·크롬 색 리터럴을 쓰임새 토큰으로.

styles.css의 색 선언 40개를 padiem-tokens.css의 쓰임새 토큰으로 옮긴다.
:root 팔레트 정의는 그대로 두고, 값은 치환 전 리터럴 그대로다.
"""
from __future__ import annotations

import re

from css_rules import declaration, strip_comments
from _support.styles_tokens_source import SHEET_TEXT, TOKEN_RULES

COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")

ROOT_TOKENS = {
    "--styles-button-focus": "3px solid rgba(101, 87, 232, .24)",
    "--styles-brand-mark-text": "#fff",
    "--styles-brand-mark-bg": "linear-gradient(135deg, #7768ee, #4f40ce)",
    "--styles-brand-mark-shadow": "0 6px 18px rgba(85,70,214,.18)",
    "--styles-new-chat-bg": "#fff",
    "--styles-new-chat-shadow": "0 3px 10px rgba(33,33,49,.03)",
    "--styles-side-item-bg": "rgba(255,255,255,.72)",
    "--styles-mini-badge-bg": "rgba(255,255,255,.72)",
    "--styles-preview-dot-bg": "#8b7ff0",
    "--styles-topbar-bg": "rgba(248,248,251,.86)",
    "--styles-model-pill-bg": "rgba(255,255,255,.78)",
    "--styles-model-pill-text": "#50515a",
    "--styles-login-button-bg": "#fff",
    "--styles-starter-bg": "rgba(255,255,255,.74)",
    "--styles-starter-edge": "#ccc9e9",
    "--styles-starter-bg-2": "#fff",
    "--styles-message-bubble-bg": "#eae8f7",
    "--styles-demo-label-bg": "#f1f0f7",
    "--styles-assistant-content-text": "#2f3037",
    "--styles-source-card-bg": "#fff",
    "--styles-error-box-edge": "1px solid #e6caca",
    "--styles-error-box-bg": "#fff8f8",
    "--styles-retry-button-edge": "1px solid #debdbd",
    "--styles-retry-button-bg": "#fff",
    "--styles-typing-i-bg": "#aaa7b9",
    "--styles-composer-edge": "1px solid #d9d9e2",
    "--styles-composer-bg": "#fff",
    "--styles-composer-edge-2": "#b9b3e9",
    "--styles-composer-shadow": "0 14px 40px rgba(55,50,95,.10), 0 0 0 3px rgba(101,87,232,.07)",
    "--styles-composer-textarea-text": "#9b9ca5",
    "--styles-tool-button-text": "#55565f",
    "--styles-tool-button-bg": "#f5f5f8",
    "--styles-send-button-text": "#fff",
    "--styles-attachment-chip-bg": "#fff",
    "--styles-attachment-chip-shadow": "0 5px 16px rgba(40,40,60,.05)",
    "--styles-attachment-chip-file-icon-bg": "#f3f2f8",
    "--styles-composer-note-text": "#888993",
    "--styles-sidebar-scrim-bg": "rgba(16,16,24,.28)",
    "--styles-sidebar-shadow": "18px 0 40px rgba(20,20,30,.12)",
    "--styles-topbar-bg-2": "rgba(248,248,251,.94)",
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


def test_usage_declarations_have_no_raw_colors() -> None:
    from css_rules import parse_rules

    for rule in parse_rules(SHEET_TEXT):
        if rule.selectors == [":root"]:
            continue
        for prop, value in rule.declarations.items():
            assert COLOR.search(value) is None, (rule.selectors, prop, value)
    for name in ROOT_TOKENS:
        assert f"var({name})" in SHEET_TEXT, name


def test_root_palette_definitions_are_untouched() -> None:
    assert "--accent: #6557e8;" in SHEET_TEXT
    assert "--accent-soft: #efedff;" in SHEET_TEXT
    assert strip_comments(SHEET_TEXT).count("--bg: #f8f8fb;") == 1

