"""Parsed views for the saved-output dialog / connector-card contrast repair.

The raw sheet reads live here (via ``claw_static``); the contract test receives
parsed declarations and resolved colours and never asserts on source text.

``resolve(theme, value)`` follows ``var()`` chains the way one theme computes
them: the theme block's declaration wins over ``:root``. It understands the
colour spellings these tokens use (``#rgb``/``#rrggbb``, ``rgb()``/``rgba()``)
and returns ``(r, g, b, alpha)``.
"""
from __future__ import annotations

import re

from css_rules import declaration, find_rules_with_selector, parse_rules
from _support.claw_static import sheet as _sheet

THEMES = ("light", "dark", "padiem-glass", "cinematic", "padiem-home")

_VAR = re.compile(r"var\(\s*(--[A-Za-z0-9_-]+)\s*(?:,\s*(.+))?\)\s*$", re.DOTALL)


def _token_rules():
    return parse_rules(_sheet("padiem-tokens.css"))


def root_declarations() -> dict:
    roots = [r for r in find_rules_with_selector(_token_rules(), ":root") if r.media is None]
    assert len(roots) == 1
    return roots[0].declarations


def theme_declarations(theme: str) -> dict:
    blocks = [r for r in find_rules_with_selector(_token_rules(), f'html[data-theme="{theme}"]')
              if r.media is None]
    assert len(blocks) == 1, theme
    return blocks[0].declarations


def token(theme: str, name: str) -> str | None:
    """The declaration one theme computes for a token (theme block over :root)."""
    themed = theme_declarations(theme)
    if name in themed:
        return themed[name]
    return root_declarations().get(name)


def _parse_color(value: str) -> tuple[float, float, float, float]:
    value = value.strip()
    if value.startswith("#"):
        raw = value[1:]
        if len(raw) in (3, 4):
            raw = "".join(ch * 2 for ch in raw)
        channels = [int(raw[i:i + 2], 16) for i in (0, 2, 4)]
        alpha = int(raw[6:8], 16) / 255 if len(raw) == 8 else 1.0
        return (channels[0], channels[1], channels[2], alpha)
    match = re.fullmatch(r"rgba?\(([^()]+)\)", value)
    assert match, value
    parts = [part.strip() for part in re.split(r"[,/]", match.group(1))]
    assert len(parts) in (3, 4), value
    alpha = float(parts[3]) if len(parts) == 4 else 1.0
    return (float(parts[0]), float(parts[1]), float(parts[2]), alpha)


def resolve(theme: str, value: str, _depth: int = 0) -> tuple[float, float, float, float]:
    """A declared colour value as this theme computes it."""
    assert _depth < 12, value
    value = value.strip()
    match = _VAR.match(value)
    if not match:
        return _parse_color(value)
    declared = token(theme, match.group(1))
    if declared is None:
        assert match.group(2) is not None, f"{theme}: {match.group(1)} is not defined"
        return resolve(theme, match.group(2), _depth + 1)
    return resolve(theme, declared, _depth + 1)


def over(top, bottom) -> tuple[float, float, float, float]:
    """``top`` painted over an opaque ``bottom``."""
    alpha = top[3]
    return tuple(top[i] * alpha + bottom[i] * (1 - alpha) for i in range(3)) + (1.0,)


def _luminance(color) -> float:
    def channel(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(color[0]) + 0.7152 * channel(color[1]) + 0.0722 * channel(color[2])


def contrast(ink, surface) -> float:
    """WCAG contrast of ``ink`` (alpha honoured) painted on an opaque surface."""
    painted = over(ink, surface)
    lighter, darker = sorted((_luminance(painted), _luminance(surface)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def rule_declaration(sheet_name: str, selector: str, prop: str) -> str:
    """The single un-themed, un-mediated declaration a selector carries."""
    matches = [r for r in find_rules_with_selector(parse_rules(_sheet(sheet_name)), selector)
               if r.media is None and declaration(r, prop) is not None]
    assert len(matches) == 1, (sheet_name, selector, prop, len(matches))
    return declaration(matches[0], prop)


def rule_declarations(sheet_name: str, selector: str) -> dict:
    """Every declaration of the one un-mediated rule whose list is exactly ``selector``."""
    matches = [r for r in parse_rules(_sheet(sheet_name))
               if r.media is None and r.selectors == [selector]]
    assert len(matches) == 1, (sheet_name, selector, len(matches))
    return matches[0].declarations
