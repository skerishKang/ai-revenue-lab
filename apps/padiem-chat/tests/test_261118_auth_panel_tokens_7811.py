"""#7811 C2b — 로그인 창(auth-panel·auth-primary) 색을 쓰임새 토큰으로.

history.css의 .auth-panel/.auth-primary 색 선언을 padiem-tokens.css의
--auth-panel-*·--auth-primary-* 토큰으로 옮긴다. 값은 치환 전 사용처 리터럴
그대로이고, :root 기본값 + dark·glass 테마 블록 덮기만 쓴다.

prefers-color-scheme 분기는 토큰 파일의 @media 블록에서 :root에만 값을 둔다.
html[data-theme="dark"|"padiem-glass"] (특이성 0,1,1)가 :root(0,1,0)를 이기므로
dark·glass는 시스템 다크에서도 자기 값을 유지하고, light·cinematic·padiem-home만
시스템 다크 값을 받는다 — history.css가 원래 브라우저에서 하던 일 그대로다.

접근성 핀(padiem-chat-ui-polish.css)은 이 파일에서 건드리지 않는다. glass는
불투명 그라디언트(#f6f9fb → #dfe6ea) + var(--text), dark는 var(--panel) +
#edf5fc로 대비를 고정한다. 이 시험은 그 핀이 보장하던 대비(AA 4.5:1)가 토큰
치환 전후 같은 값으로 유지되는지 계산해 확인한다.

죽은 선언: history.css의 glass .auth-panel 배경·테두리 선언은 polish의 불투명
그라디언트(같은 특이성, 뒤 로드)가 덮는다. CTO 지시대로 지우지 않고, 토큰의
glass 값이 그 값을 소유한다는 사실만 여기서 고정한다.
"""
from __future__ import annotations

import re
from pathlib import Path

from css_rules import declaration, find_rules_with_selector, parse_rules

# #8060: the raw sheet read lives in _support; parsed declarations stay here.
from _support import auth_panel_tokens_source as sheets

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
TOKENS = STATIC / "padiem-tokens.css"
HISTORY = STATIC / "history.css"
POLISH = STATIC / "padiem-chat-ui-polish.css"

THEMES = ("light", "dark", "padiem-glass", "cinematic", "padiem-home")

#: :root 기본값 — 치환 전 history.css 리터럴 그대로. 이 문자열이 계약이다.
ROOT_TOKENS = {
    "--auth-panel-bg": "var(--panel)",
    "--auth-panel-text": "var(--text)",
    "--auth-panel-border": "rgba(127, 127, 127, 0.24)",
    "--auth-primary-bg": "#111",
    "--auth-primary-text": "#fff",
}

#: glass 테마만 덮는 값(history.css glass 규칙이 읽던 값 그대로).
GLASS_TOKENS = {
    "--auth-panel-bg": (
        "linear-gradient(160deg, rgba(246, 249, 251, 0.76), "
        "rgba(216, 224, 229, 0.56))"
    ),
    "--auth-panel-text": "var(--text)",
    "--auth-panel-border": "rgba(255, 255, 255, 0.66)",
}

#: dark 테마만 덮는 값(history.css dark 규칙이 읽던 값 그대로).
DARK_TOKENS = {
    "--auth-panel-bg": "var(--panel)",
    "--auth-panel-text": "#edf5fc",
    "--auth-panel-border": "#4b6478",
    "--auth-primary-bg": "#a2d5f5",
    "--auth-primary-text": "#132637",
}

#: 시스템 다크(history.css @media 블록을 옮긴 값). :root에만 둔다.
MEDIA_DARK_TOKENS = {
    "--auth-panel-bg": "#17191c",
    "--auth-panel-text": "#f3f4f6",
    "--auth-primary-bg": "#f3f4f6",
    "--auth-primary-text": "#111",
}

#: 테마 블록의 --panel/--text 실제 값(다른 테스트가 이미 고정한 값).
THEME_PANEL = {
    "light": "#ffffff",
    "dark": "#1a232d",
    "padiem-glass": "rgba(235, 239, 242, .46)",
    "cinematic": "rgba(10,14,22,.72)",
    "padiem-home": "rgba(255,255,255,.72)",
}
THEME_TEXT = {
    "light": "#19191d",
    "dark": "#edf4fa",
    "padiem-glass": "#17202a",
    "cinematic": "#f7f8fa",
    "padiem-home": "#1a2230",
}

#: 5테마 × 시스템 두 경우의 토큰 계층 값(치환 전 선언값 그대로).
#: glass 패널 배경은 polish의 불투명 핀이 덮으므로 이 값은 화면에 칠해지지
#: 않는다 — 실제로 칠해지는 값은 test_polish_accessibility_pin_*이 고정한다.
EXPECTED = {
    ("light", "light"): ("#ffffff", "#19191d", "rgba(127, 127, 127, 0.24)", "#111", "#fff"),
    ("dark", "light"): ("#1a232d", "#edf5fc", "#4b6478", "#a2d5f5", "#132637"),
    ("padiem-glass", "light"): (
        GLASS_TOKENS["--auth-panel-bg"], "#17202a",
        "rgba(255, 255, 255, 0.66)", "#111", "#fff",
    ),
    ("cinematic", "light"): (
        "rgba(10,14,22,.72)", "#f7f8fa",
        "rgba(127, 127, 127, 0.24)", "#111", "#fff",
    ),
    ("padiem-home", "light"): (
        "rgba(255,255,255,.72)", "#1a2230",
        "rgba(127, 127, 127, 0.24)", "#111", "#fff",
    ),
    ("light", "dark"): ("#17191c", "#f3f4f6", "rgba(127, 127, 127, 0.24)", "#f3f4f6", "#111"),
    ("dark", "dark"): ("#1a232d", "#edf5fc", "#4b6478", "#a2d5f5", "#132637"),
    ("padiem-glass", "dark"): (
        GLASS_TOKENS["--auth-panel-bg"], "#17202a",
        "rgba(255, 255, 255, 0.66)", "#f3f4f6", "#111",
    ),
    ("cinematic", "dark"): ("#17191c", "#f3f4f6", "rgba(127, 127, 127, 0.24)", "#f3f4f6", "#111"),
    ("padiem-home", "dark"): ("#17191c", "#f3f4f6", "rgba(127, 127, 127, 0.24)", "#f3f4f6", "#111"),
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _rules(path: Path):
    return parse_rules(sheets.sheet(path.name))


def _root_declarations(rules) -> dict[str, str]:
    roots = [r for r in rules if r.selectors == [":root"] and r.media is None]
    assert len(roots) == 1, "one :root block carries the defaults"
    return roots[0].declarations


def _theme_declarations(rules, theme: str) -> dict[str, str]:
    blocks = [
        r for r in rules
        if r.media is None
        and r.selectors == [f'html[data-theme="{theme}"]']
    ]
    assert len(blocks) == 1, theme
    return blocks[0].declarations


def _resolve(value: str, declarations: dict[str, str], theme: str) -> str:
    """Resolve the one-level var(--panel)/var(--text) references used here."""
    match = re.fullmatch(r"var\((--[a-z-]+)\)", _norm(value))
    if not match:
        return _norm(value)
    name = match.group(1)
    if name == "--panel":
        return _norm(THEME_PANEL[theme])
    if name == "--text":
        return _norm(THEME_TEXT[theme])
    return _norm(declarations.get(name, value))


def _effective(theme: str, scheme: str) -> dict[str, str]:
    """The cascade the browser applies: theme block (0,1,1) > media :root (0,1,0)."""
    rules = _rules(TOKENS)
    root = _root_declarations(rules)
    media_blocks = [
        r for r in rules
        if r.media == "(prefers-color-scheme: dark)" and r.selectors == [":root"]
    ]
    assert len(media_blocks) == 1
    media = media_blocks[0].declarations
    theme_block = _theme_declarations(rules, theme)

    out: dict[str, str] = {}
    for name in ROOT_TOKENS:
        value = root[name]
        if scheme == "dark" and name in media:
            value = media[name]
        if name in theme_block:
            value = theme_block[name]
        out[name] = _resolve(value, root | theme_block, theme)
    return out


# ---------------------------------------------------------------- token values


def test_root_tokens_hold_the_pre_change_literals() -> None:
    root = _root_declarations(_rules(TOKENS))
    for name, literal in ROOT_TOKENS.items():
        assert _norm(root.get(name, "")) == literal, name


def test_glass_theme_block_holds_the_old_glass_values() -> None:
    block = _theme_declarations(_rules(TOKENS), "padiem-glass")
    for name, literal in GLASS_TOKENS.items():
        assert _norm(block.get(name, "")) == _norm(literal), name


def test_dark_theme_block_holds_the_old_dark_values() -> None:
    block = _theme_declarations(_rules(TOKENS), "dark")
    for name, literal in DARK_TOKENS.items():
        assert _norm(block.get(name, "")) == _norm(literal), name


def test_media_dark_block_only_touches_root() -> None:
    rules = _rules(TOKENS)
    blocks = [r for r in rules if r.media == "(prefers-color-scheme: dark)"]
    assert len(blocks) == 1
    assert blocks[0].selectors == [":root"]
    for name, literal in MEDIA_DARK_TOKENS.items():
        assert _norm(blocks[0].declarations.get(name, "")) == _norm(literal), name


# ------------------------------------------------------------- cascade contract


def test_only_needed_themes_override_the_auth_tokens() -> None:
    """light·cinematic·padiem-home은 :root 기본값을 그대로 쓴다(불필요한 덮기 없음)."""
    rules = _rules(TOKENS)
    override_themes = set()
    for rule in rules:
        if rule.media is not None or rule.selectors == [":root"]:
            continue
        if not any(name.startswith("--auth-") for name in rule.declarations):
            continue
        assert len(rule.selectors) == 1
        match = re.fullmatch(r'html\[data-theme="([a-z-]+)"\]', rule.selectors[0])
        assert match, rule.selectors
        override_themes.add(match.group(1))
    assert override_themes == {"dark", "padiem-glass"}


def test_effective_token_values_match_the_pre_change_declarations() -> None:
    for (theme, scheme), expected in EXPECTED.items():
        values = _effective(theme, scheme)
        actual = (
            values["--auth-panel-bg"],
            values["--auth-panel-text"],
            values["--auth-panel-border"],
            values["--auth-primary-bg"],
            values["--auth-primary-text"],
        )
        assert tuple(_norm(v) for v in actual) == tuple(_norm(v) for v in expected), (theme, scheme)


def test_every_auth_token_used_by_history_has_a_root_default() -> None:
    root = _root_declarations(_rules(TOKENS))
    used = set()
    for rule in _rules(HISTORY):
        for name, value in rule.declarations.items():
            used.update(re.findall(r"var\((--auth-[a-z-]+)\)", value))
    assert used, "history.css must consume the auth tokens"
    for name in used:
        assert name in root, name


# ------------------------------------------------------------ history consumers


def test_history_panel_and_primary_consume_only_tokens() -> None:
    rules = _rules(HISTORY)
    panel = [
        r for r in rules
        if r.media is None
        and any(s == ".auth-panel" or s.endswith(" .auth-panel") for s in r.selectors)
        and declaration(r, "background") is not None
    ]
    assert len(panel) == 2, "base + glass"
    base = next(r for r in panel if r.selectors == [".auth-panel"])
    assert declaration(base, "background") == "var(--auth-panel-bg)"
    assert declaration(base, "color") == "var(--auth-panel-text)"
    assert declaration(base, "border") == "1px solid var(--auth-panel-border)"

    glass = next(
        r for r in panel
        if r.selectors == ['html[data-theme="padiem-glass"] .auth-panel']
    )
    # Dead against polish's opaque pin, kept on purpose (CTO 지시) — the value
    # lives in the token's glass block, not in this sheet.
    assert declaration(glass, "background") == "var(--auth-panel-bg)"
    assert declaration(glass, "border") == "1px solid var(--auth-panel-border)"

    primary = [
        r for r in find_rules_with_selector(rules, ".auth-primary")
        if r.media is None and declaration(r, "background") is not None
    ]
    assert len(primary) == 1
    assert declaration(primary[0], "background") == "var(--auth-primary-bg)"
    assert declaration(primary[0], "color") == "var(--auth-primary-text)"


def test_history_has_no_auth_color_literals_or_media_branch_left() -> None:
    rules = _rules(HISTORY)
    color_props = {"background", "background-color", "color", "border", "border-color"}
    for rule in rules:
        if not any(
            ".auth-panel" == s or ".auth-primary" == s
            or s.endswith(" .auth-panel") or s.endswith(" .auth-primary")
            for s in rule.selectors
        ):
            continue
        for prop, value in rule.declarations.items():
            if prop not in color_props:
                continue
            assert re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(", value) is None, (rule.selectors, prop)
    media = [r for r in rules if r.media and "prefers-color-scheme" in r.media
             and any(".auth-panel" in s or ".auth-primary" in s for s in r.selectors)]
    assert media == []


# --------------------------------------------------------------- 접근성 대비 고정


def _srgb(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.2126 * _srgb(r) + 0.7152 * _srgb(g) + 0.0722 * _srgb(b)


def _contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _rgb(value: str) -> tuple[int, int, int]:
    value = _norm(value).lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _over(fg: tuple[int, int, int], alpha: float, bg: tuple[int, int, int]) -> tuple[int, int, int]:
    return tuple(round(fg[i] * alpha + bg[i] * (1 - alpha)) for i in range(3))


def test_login_text_keeps_the_pinned_contrast() -> None:
    """지금 통과하던 값 그대로 AA(4.5:1)를 지킨다 — 핀 시트는 건드리지 않는다."""
    pairs = {
        "light panel": (_rgb("#19191d"), _rgb("#ffffff")),
        "dark panel": (_rgb("#edf5fc"), _rgb("#1a232d")),
        # polish의 불투명 glass 그라디언트 양 끝(접근성 핀).
        "glass bright": (_rgb("#17202a"), _rgb("#f6f9fb")),
        "glass deep": (_rgb("#17202a"), _rgb("#dfe6ea")),
        "os dark panel": (_rgb("#f3f4f6"), _rgb("#17191c")),
        # 반투명 패널은 페이지 바탕 + #5666 딤 위에 합성한 값으로 잰다.
        "cinematic panel": (
            _rgb("#f7f8fa"),
            _over(_rgb("#0a0e16"), 0.72, _over(_rgb("#12181f"), 0.38, _rgb("#04070d"))),
        ),
        "padiem-home panel": (
            _rgb("#1a2230"),
            _over(_rgb("#ffffff"), 0.72, _over(_rgb("#12181f"), 0.38, _rgb("#e6e9ee"))),
        ),
        "primary light": (_rgb("#ffffff"), _rgb("#111")),
        "primary dark": (_rgb("#132637"), _rgb("#a2d5f5")),
        "primary os dark": (_rgb("#111"), _rgb("#f3f4f6")),
    }
    for name, (fg, bg) in pairs.items():
        ratio = _contrast(fg, bg)
        assert ratio >= 4.5, (name, round(ratio, 2))
    # polish 주석이 기록한 glass 핀 값과 같은 값(반올림 0.1 이내).
    assert round(_contrast(_rgb("#17202a"), _rgb("#f6f9fb")), 1) == 15.6
    assert round(_contrast(_rgb("#17202a"), _rgb("#dfe6ea")), 1) == 13.0


def test_polish_accessibility_pin_still_owns_the_live_glass_and_dark_surfaces() -> None:
    """덮는 쪽(polish)이 그대로다 — 토큰 치환이 핀을 약화하지 않았다."""
    rules = _rules(POLISH)
    glass = [
        r for r in rules
        if r.selectors == ['html[data-theme="padiem-glass"] .auth-panel']
    ]
    assert len(glass) == 1
    assert declaration(glass[0], "background") == "linear-gradient(160deg, #f6f9fb, #dfe6ea)"
    assert declaration(glass[0], "color") == "var(--text)"
    assert declaration(glass[0], "backdrop-filter") == "none"
    dark = [
        r for r in rules
        if r.selectors == ['html[data-theme="dark"] .auth-panel']
    ]
    assert len(dark) == 1
    assert declaration(dark[0], "background") == "var(--panel)"
    assert declaration(dark[0], "color") == "#edf5fc"
