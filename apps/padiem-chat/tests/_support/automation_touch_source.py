"""Parsed CSS rule views for the Claw automation touch contracts (#8060).

Raw file reads live here. Tests receive comment-stripped CSS rule bodies and
declaration booleans computed from them. The shared ``claw_static`` helper owns
the underlying static reads.
"""
from __future__ import annotations

import re

from _support.claw_static import sheet


def css_text(name: str) -> str:
    """A shipped sheet with comments removed, so prose cannot satisfy a guard."""
    return re.sub(r"/\*.*?\*/", "", sheet(name), flags=re.DOTALL)


def rule_body(css: str, header: str) -> str:
    """The declaration body of the rule whose selector contains ``header``."""
    match = re.search(re.escape(header), css)
    assert match is not None, f"rule not found: {header}"
    open_brace = css.index("{", match.start())
    return css[open_brace + 1 : css.index("}", open_brace)]


def declares(body: str, declaration: str) -> bool:
    """Whether a rule body declares the exact given declaration."""
    return re.search(rf"(?<![\w-]){re.escape(declaration)}(?![\w-])", body) is not None


def index_html() -> str:
    return sheet("index.html")
