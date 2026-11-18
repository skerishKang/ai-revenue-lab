"""#7811 C2 — foundation 바탕·크롬 색을 쓰임새 토큰으로.

padiem-foundation.css의 색 선언 가운데 실제로 칠해지는 10개를
padiem-tokens.css 토큰으로 옮긴다. :root 값은 치환 전 foundation 리터럴
그대로이고, 테마 블록은 다섯 테마 --computed 실측에서 foundation 선언이
실제로 칠해지는 값만 덮는다.

이 시트의 나머지 색 선언은 뒤에 로드되는 테마/표면 시트가 전부 덮는다.
그 선언은 소유 시트와 함께 C3/C6에서 정리해야 하므로 여기서 토큰화하지
않는다(같은 값을 두 곳이 소유하는 것을 피한다).
"""
from __future__ import annotations

import re
from pathlib import Path

from css_rules import declaration, find_rules_with_selector, parse_rules

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
TOKENS = STATIC / "padiem-tokens.css"
FOUNDATION = STATIC / "padiem-foundation.css"

COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")

ROOT_TOKENS = {
    "--app-root-bg": "#06080d",
    "--app-grid-line": "rgba(255, 255, 255, .025)",
    "--app-grid-fade": "linear-gradient(to bottom, rgba(0, 0, 0, .72), transparent 76%)",
    "--app-selection-text": "#fff",
    "--app-selection-bg": "rgba(136, 201, 255, .28)",
    "--app-focus-outline": "rgba(136, 201, 255, .7)",
    "--brand-mark-glow": "rgba(136, 201, 255, .68)",
    "--side-icon-text": "rgba(255, 255, 255, .68)",
    "--sidebar-footer-border": "rgba(255, 255, 255, .08)",
}

THEME_TOKENS = {
    '"light"': {
        "--side-icon-text": "#6f7079",
        "--sidebar-footer-border": "rgba(101, 87, 232, .06)",
    },
    '"dark"': {},
    '"cinematic"': {},
    '"padiem-home"': {
        "--side-icon-text": "#5a6578",
    },
    '"padiem-glass"': {
        "--app-root-bg": "#aeb6bf",
        "--sidebar-footer-border": "rgba(255, 255, 255, .15)",
    },
}

CHANGED = [
    ("html", "background", "var(--app-root-bg)"),
    ("body::after", "mask-image", "var(--app-grid-fade)"),
    ("::selection", "color", "var(--app-selection-text)"),
    ("::selection", "background", "var(--app-selection-bg)"),
    ("button:focus-visible", "outline", "2px solid var(--app-focus-outline)"),
    (".brand-mark::after", "background", "var(--brand-mark-glow)"),
    (".side-icon", "color", "var(--side-icon-text)"),
    (".sidebar-footer", "border-top", "1px solid var(--sidebar-footer-border)"),
]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _rules(path: Path):
    return parse_rules(path.read_text(encoding="utf-8"))


def _root(rules):
    roots = [r for r in rules if r.selectors == [":root"] and r.media is None]
    assert len(roots) == 1
    return roots[0]


def test_root_tokens_hold_the_pre_change_literals() -> None:
    root = _root(_rules(TOKENS))
    for name, literal in ROOT_TOKENS.items():
        assert _norm(declaration(root, name)) == _norm(literal), name


def test_theme_tokens_hold_the_computed_values() -> None:
    rules = _rules(TOKENS)
    for theme, expected in THEME_TOKENS.items():
        selector = f"html[data-theme={theme}]"
        blocks = [
            r for r in rules
            if r.media is None and r.selectors == [selector]
        ]
        assert len(blocks) == 1, theme
        for name, value in expected.items():
            assert _norm(declaration(blocks[0], name)) == _norm(value), (theme, name)


def test_changed_declarations_consume_the_tokens() -> None:
    rules = _rules(FOUNDATION)
    for selector, prop, expected in CHANGED:
        blocks = [
            r for r in find_rules_with_selector(rules, selector)
            if r.media is None and declaration(r, prop) is not None
        ]
        assert len(blocks) == 1, selector
        assert _norm(declaration(blocks[0], prop)) == _norm(expected), selector


def test_grid_line_consumes_the_token_for_both_axes() -> None:
    rules = _rules(FOUNDATION)
    blocks = [
        r for r in find_rules_with_selector(rules, "body::after")
        if r.media is None and declaration(r, "background-image") is not None
    ]
    assert len(blocks) == 1
    value = declaration(blocks[0], "background-image")
    assert value.count("var(--app-grid-line)") == 2
    assert "rgba(255, 255, 255, .025)" not in value


def test_changed_declarations_have_no_raw_color_literals() -> None:
    rules = _rules(FOUNDATION)
    for selector, prop, _ in CHANGED:
        blocks = [
            r for r in find_rules_with_selector(rules, selector)
            if r.media is None and declaration(r, prop) is not None
        ]
        assert len(blocks) == 1, selector
        value = declaration(blocks[0], prop)
        assert COLOR.search(value) is None, (selector, prop, value)


def test_tokens_are_defined_only_in_the_token_file() -> None:
    foundation = FOUNDATION.read_text(encoding="utf-8")
    for name in ROOT_TOKENS:
        assert f"{name}:" not in foundation, name


def test_foundation_pages_load_tokens_before_foundation() -> None:
    for page in sorted(STATIC.rglob("*.html")):
        html = page.read_text(encoding="utf-8")
        links = re.findall(r"<link[^>]*?href=[\"']([^\"']+\.css)[^\"']*[\"']", html)
        if not any(h.endswith("padiem-foundation.css") for h in links):
            continue
        token_at = next(i for i, h in enumerate(links) if h.endswith("padiem-tokens.css"))
        foundation_at = next(i for i, h in enumerate(links) if h.endswith("padiem-foundation.css"))
        assert token_at < foundation_at, page
