"""#7811 C2 — foundation 바탕·크롬의 남은 색 리터럴을 쓰임새 토큰으로.

padiem-foundation.css의 나머지 색 선언 33개를 padiem-tokens.css의 쓰임새
토큰으로 옮긴다. :root 팔레트 정의는 그대로 두고, 값은 치환 전 리터럴 그대로다.
"""
from __future__ import annotations

import re

from css_rules import declaration, strip_comments
from _support.foundation_remainder_source import SHEET_TEXT, TOKEN_RULES

COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")

ROOT_TOKENS = {
    "--foundation-subtle-wash": "rgba(255, 255, 255, .045)",
    "--foundation-body-stop-1": "#08090b",
    "--foundation-body-stop-2": "#0b0c0e",
    "--foundation-body-stop-3": "#030405",
    "--foundation-vignette": "rgba(0, 0, 0, .60)",
    "--foundation-scrim-top": "rgba(0, 0, 0, .24)",
    "--foundation-scrim-mid": "rgba(0, 0, 0, .02)",
    "--foundation-scrim-bottom": "rgba(0, 0, 0, .45)",
    "--foundation-body-spot-a": "rgba(255, 255, 255, .018)",
    "--foundation-body-spot-b": "rgba(255, 255, 255, .012)",
    "--foundation-top-rim": "rgba(255, 255, 255, .96)",
    "--foundation-top-rim-glow": "rgba(255, 255, 255, .08)",
    "--foundation-hairline": "rgba(255, 255, 255, .11)",
    "--foundation-sidebar-stop-1": "rgba(8, 9, 11, .93)",
    "--foundation-sidebar-stop-2": "rgba(6, 7, 9, .83)",
    "--foundation-sidebar-base": "rgba(6, 7, 9, .86)",
    "--foundation-sidebar-shadow": "rgba(0, 0, 0, .16)",
    "--foundation-strong-text": "#fff",
    "--foundation-mark-edge": "rgba(255, 255, 255, .18)",
    "--foundation-mark-base": "rgba(10, 11, 13, .72)",
    "--foundation-mark-shadow": "rgba(0, 0, 0, .22)",
    "--foundation-control-edge": "rgba(255, 255, 255, .17)",
    "--foundation-control-wash": "rgba(255, 255, 255, .075)",
    "--foundation-control-inset": "rgba(255, 255, 255, .05)",
    "--foundation-control-hover-edge": "rgba(255, 255, 255, .30)",
    "--foundation-control-hover-wash": "rgba(255, 255, 255, .115)",
    "--foundation-item-text": "rgba(242, 246, 251, .72)",
    "--foundation-item-hover-wash": "rgba(255, 255, 255, .07)",
    "--foundation-badge-edge": "rgba(255, 255, 255, .08)",
    "--foundation-badge-text": "rgba(238, 243, 249, .50)",
    "--foundation-preview-glow": "rgba(136, 201, 255, .56)",
    "--foundation-topbar-stop-1": "rgba(8, 9, 11, .62)",
    "--foundation-topbar-stop-2": "rgba(8, 9, 11, .12)",
    "--foundation-pill-text": "rgba(247, 250, 253, .82)",
    "--foundation-pill-hover-edge": "rgba(255, 255, 255, .32)",
    "--foundation-account-text": "rgba(255, 255, 255, .58)",
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
    assert "--accent: #88c9ff;" in SHEET_TEXT
    assert "--accent-soft: rgba(136, 201, 255, .055);" in SHEET_TEXT
    assert "--accent-strong: #d7ebfa;" in SHEET_TEXT
    assert strip_comments(SHEET_TEXT).count("--bg: #06080d;") == 1
