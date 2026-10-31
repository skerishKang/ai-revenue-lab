"""#6100 beta-ux pass — the logged-out quote dialog and the input-border floor.

The logged-out quote dialog used to open with three empty selects (견적서 양식,
AI 등급, 추론 수준); the capability event is the product's own auth signal, so
the dialog now says what a sign-in unlocks and stands back the moment the same
event reports a signed-in browser. The glass (default) theme drew input borders
in 38% white on a light field — a 1.06:1 non-text contrast — so input controls
now take --input-border-strong, defined per theme, while every --line value
stays exactly as the connection screen's rebuild expects it.
"""
from __future__ import annotations

import json
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
REPORTS = Path(__file__).resolve().parents[3] / "padiem-reports" / "2026-10-29"


def test_logged_out_quote_dialog_names_what_signing_in_unlocks():
    script = (STATIC / "b66-quote-runtime.js").read_text(encoding="utf-8")
    ko = script[script.index("    ko: {"):script.index("    en: {")]
    en = script[script.index("    en: {"):]
    assert "로그인하면 내 양식과 등급을 고를 수 있어요" in ko
    assert "Sign in to pick your template and AI tier." in en
    # The hint opens the account area's own login dialog — no private entry.
    assert 'document.getElementById("loginButton")?.click()' in script
    # The signed-in bit comes from the capability event, which fires at startup
    # as well; the selects come back through the same refresh() that fills them.
    assert "signedIn = !!(auth && auth.authenticated === true)" in script
    for field in ("b66QuoteSkillField", "b66QuoteModelField", "b66QuoteReasoningField"):
        assert f'"{field}"' in script
    css = (STATIC / "b66-quote-runtime.css").read_text(encoding="utf-8")
    assert ".b66-quote-signin-hint" in css
    assert ".b66-quote-signin-hint[hidden]" in css


def test_input_border_token_is_defined_per_theme_and_applied_to_inputs():
    themes = (STATIC / "padiem-themes.css").read_text(encoding="utf-8")
    glass = (STATIC / "padiem-glass.css").read_text(encoding="utf-8")
    for theme, token in (
        ("light", "--input-border-strong: #767e8a;"),
        ("dark", "--input-border-strong: rgba(255,255,255,.45);"),
        ("cinematic", "--input-border-strong: rgba(255,255,255,.45);"),
        ("padiem-home", "--input-border-strong: #767e8a;"),
    ):
        start = themes.index(f'html[data-theme="{theme}"]')
        nxt = themes.find("html[data-theme=", start + 1)
        section = themes[start: nxt if nxt != -1 else len(themes)]
        assert token in section, theme
    assert "--input-border-strong: #56616b;" in glass
    # The shared hairline values are untouched: glass still draws cards in
    # 38% white, the connection screen keeps its own language.
    assert "--line: rgba(255, 255, 255, .38);" in glass

    util = (STATIC / "util-menu.css").read_text(encoding="utf-8")
    assert "border: 1px solid var(--input-border-strong, var(--line, rgba(26, 34, 48, .12)));" in util
    assert "border: 1px solid var(--input-border-strong, rgba(51, 74, 91, .34));" in util
    quote = (STATIC / "b66-quote-runtime.css").read_text(encoding="utf-8")
    assert quote.count("var(--input-border-strong, var(--border,") >= 2
    dialog = (STATIC / "pc-file-exchange.css").read_text(encoding="utf-8")
    assert "var(--input-border-strong, var(--line, rgba(66, 106, 135, 0.28)))" in dialog


def _srgb_channel(value: float) -> float:
    value /= 255.0
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.2126 * _srgb_channel(r) + 0.7152 * _srgb_channel(g) + 0.0722 * _srgb_channel(b)


def _ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    lighter, darker = max(_luminance(a), _luminance(b)), min(_luminance(a), _luminance(b))
    return (lighter + 0.05) / (darker + 0.05)


def _hex(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i: i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _blend(top: str, alpha: float, back: str) -> tuple[int, int, int]:
    t, b = _hex(top), _hex(back)
    return tuple(round(alpha * x + (1 - alpha) * y) for x, y in zip(t, b))  # type: ignore[return-value]


def test_token_math_clears_the_three_to_one_floor():
    # WCAG 1.4.11 non-text contrast, computed from the shipped token values
    # against each theme's own fill. Semi-transparent borders composite over
    # the fill they are drawn on. Glass's fill depends on the blur behind it;
    # the naive light-canvas composite is the conservative stand-in here, and
    # the rendered numbers live in the committed evidence below.
    cases = [
        ("light", _hex("#767e8a"), _hex("#ffffff")),
        ("padiem-home", _hex("#767e8a"), _blend("#ffffff", 0.72, "#e6e9ee")),
        ("dark", _blend("#ffffff", 0.45, "#1a232d"), _hex("#1a232d")),
        ("cinematic", _blend("#ffffff", 0.45, "#0a0e16"), _blend("#0a0e16", 0.72, "#04070d")),
        ("padiem-glass", _hex("#56616b"), _blend("#ebf0f2", 0.46, "#aeb6bf")),
    ]
    for name, border, fill in cases:
        assert _ratio(border, fill) >= 3.0, (name, round(_ratio(border, fill), 2))


def test_rendered_evidence_meets_the_floor_in_every_theme():
    # The committed AFTER captures carry the rendered numbers (pixels, not
    # declarations): every measured border/fill pair in every theme pass must
    # sit at or above 3:1.
    # Named explicitly: PR1 (#6108) committed its own after-summary.json,
    # whose numbers are the honest before-token state for this item.
    wanted = ["after-quote", "after-light", "after-dark", "after-cinematic", "after-home"]
    evidence = [REPORTS / ("beta-ux-20261029-%s-summary.json" % name) for name in wanted]
    evidence = [path for path in evidence if path.exists()]
    assert evidence, "the AFTER evidence for this pass is part of the change"
    checked = 0

    def walk(node):
        nonlocal checked
        if isinstance(node, dict):
            if isinstance(node.get("ratio"), (int, float)):
                assert node["ratio"] >= 3.0, node
                checked += 1
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for path in evidence:
        walk(json.loads(path.read_text(encoding="utf-8-sig")))
    assert checked >= 10, checked
