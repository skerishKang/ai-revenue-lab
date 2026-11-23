"""#8020 — Claw 요청 말풍선 글자 대비.

`interaction-polish.css`가 Claw 요청 말풍선 글자를 `#111a22`로 고정해,
어두운 `padiem-home`·`cinematic` 말풍선 위에서 글자가 묻혔다. 글자와 배경을
토큰으로 옮기되, 나머지 세 테마(light·dark·glass)의 계산색은 바꾸지 않는다.
"""
from __future__ import annotations

import re

from css_rules import declaration, find_rules_with_selector, parse_rules
from _support import claw_bubble_card_source as sheets

COLOR_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(")


def _rules(name: str):
    return parse_rules(sheets.css_text(name))


def _root():
    roots = [r for r in _rules("padiem-tokens.css") if r.selectors == [":root"] and r.media is None]
    assert len(roots) == 1
    return roots[0]


def _theme(theme: str):
    selector = f'html[data-theme="{theme}"]'
    blocks = [
        r for r in _rules("padiem-tokens.css")
        if r.media is None and r.selectors == [selector]
    ]
    assert len(blocks) == 1, theme
    return blocks[0]


def _rgb(value: str):
    value = value.strip()
    if value.startswith("#"):
        raw = value[1:]
        if len(raw) == 3:
            raw = "".join(ch * 2 for ch in raw)
        return tuple(int(raw[i:i + 2], 16) for i in (0, 2, 4)) + (1.0,)
    match = re.fullmatch(r"rgba?\(([^)]+)\)", value)
    assert match, value
    parts = [part.strip() for part in match.group(1).split(",")]
    return tuple(int(float(part)) for part in parts[:3]) + (float(parts[3]) if len(parts) > 3 else 1.0,)


def _composite(fg, bg):
    alpha = fg[3]
    return tuple(round(fg[i] * alpha + bg[i] * (1 - alpha)) for i in range(3))


def _luminance(rgb):
    channels = [channel / 255 for channel in rgb]
    channels = [
        channel / 12.92 if channel <= 0.04045
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(fg, bg):
    lighter, darker = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def test_root_tokens_use_the_theme_user_bubble_roles() -> None:
    root = _root()
    assert declaration(root, "--claw-request-bubble-text") == "var(--user-bubble-text)"
    assert declaration(root, "--claw-request-bubble-bg") == "var(--user-bubble-bg)"
    # 테마별 글자 덮개를 두지 않는다. 각 테마의 --user-bubble-text가 그대로
    # 적용되고, dark는 기존 dark-contrast 규칙이 더 높은 특이성으로 이긴다.
    for theme in ("light", "dark", "cinematic", "padiem-home", "padiem-glass"):
        props = _theme(theme).declarations
        assert "--claw-request-bubble-text" not in props, theme
    for theme in ("light", "dark", "cinematic", "padiem-home"):
        assert "--claw-request-bubble-bg" not in _theme(theme).declarations, theme


def test_glass_keeps_its_original_bubble_background() -> None:
    props = _theme("padiem-glass").declarations
    assert props["--claw-request-bubble-bg"] == "rgba(31, 43, 54, .74)"
    assert "--claw-request-bubble-text" not in props
    glass_bubble = [
        r for r in find_rules_with_selector(
            _rules("padiem-glass.css"), 'html[data-theme="padiem-glass"] .message-bubble'
        )
        if r.media is None and declaration(r, "background") is not None
    ]
    assert len(glass_bubble) == 1
    assert declaration(glass_bubble[0], "background") == "var(--claw-request-bubble-bg)"


def test_the_claw_echo_consumes_both_tokens() -> None:
    selector = ".conversation .claw-request-echo .message-bubble"
    blocks = [
        r for r in find_rules_with_selector(_rules("interaction-polish.css"), selector)
        if r.media is None and declaration(r, "color") is not None
    ]
    assert len(blocks) == 1
    assert declaration(blocks[0], "background") == "var(--claw-request-bubble-bg)"
    assert declaration(blocks[0], "color") == "var(--claw-request-bubble-text)"
    for prop in ("background", "color"):
        value = declaration(blocks[0], prop)
        assert COLOR_LITERAL.search(value) is None, (prop, value)


def test_all_five_themes_clear_4_5_to_1() -> None:
    contrast = {}
    for theme in ("light", "dark", "cinematic", "padiem-home", "padiem-glass"):
        props = _theme(theme).declarations
        text = _rgb(props["--user-bubble-text"])
        bubble = _rgb(props["--user-bubble-bg"])
        if bubble[3] < 1:
            bubble = _composite(bubble, _rgb(props["--bg"]))
        else:
            bubble = bubble[:3]
        text = _composite(text, bubble)
        contrast[theme] = _contrast(text, bubble)
    assert all(value >= 4.5 for value in contrast.values()), contrast
    assert contrast["light"] >= 5.0, contrast
    assert contrast["padiem-glass"] >= 4.5, contrast
