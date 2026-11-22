"""Parsed views for the admin-models browser contract (#8060 50차).

The single shipped-asset read lives here (reusing ``claw_static.sheet``); the
browser test serves the text through its mock and asserts on parsed numeric
color/length values and DOM behavior instead of raw CSS text substrings.
"""
from __future__ import annotations

import re

from _support.claw_static import sheet


def static_asset(url_path: str) -> str:
    """Text of one shipped static asset, addressed by its browser URL path."""
    return sheet(url_path.removeprefix("/"))


def rgb(value: str | None) -> tuple[int, int, int] | None:
    """First color in a CSS value as numeric RGB (hex or rgb/rgba, gradients included)."""
    text = (value or "").strip()
    if text.startswith("#"):
        digits = text[1:]
        if len(digits) == 3:
            digits = "".join(character * 2 for character in digits)
        if len(digits) >= 6 and all(c in "0123456789abcdefABCDEF" for c in digits[:6]):
            return tuple(int(digits[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    match = re.search(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:[,/]\s*[\d.]+\s*)?\)", text)
    return tuple(int(part) for part in match.groups()) if match else None  # type: ignore[return-value]


def rgba(value: str | None) -> tuple[int, int, int, float] | None:
    """An rgba() color as numeric RGB plus alpha."""
    match = re.search(
        r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)", value or ""
    )
    if not match:
        return None
    red, green, blue = (int(part) for part in match.groups()[:3])
    return red, green, blue, float(match.group(4))


def blur_px(value: str | None) -> float | None:
    match = re.search(r"blur\(\s*([\d.]+)\s*px\s*\)", value or "")
    return float(match.group(1)) if match else None


def px(value: str | None) -> float | None:
    match = re.fullmatch(r"\s*([\d.]+)\s*px\s*", value or "")
    return float(match.group(1)) if match else None


def is_transparent(value: str | None) -> bool:
    text = (value or "").strip().lower()
    if text in ("transparent", "rgba(0, 0, 0, 0)", "rgba(0,0,0,0)"):
        return True
    color = rgba(value)
    return color is not None and color[3] == 0


def has_shadow(value: str | None) -> bool:
    return bool(value) and value.strip().lower() != "none"
