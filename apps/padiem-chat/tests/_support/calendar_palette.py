"""Parsed views for the calendar palette token contracts (#7811 C2 calendar).

The raw sheet reads live here (via claw_static); the contract tests receive
parsed rule/declaration values and assert on those, never on source text
directly.
"""
from __future__ import annotations

from css_rules import find_rules_with_selector, parse_rules
from _support.claw_static import sheet as _sheet

THEMES = ("light", "dark", "padiem-glass", "cinematic", "padiem-home")


def _blocks():
    return parse_rules(_sheet("padiem-tokens.css"))


def root_declarations() -> dict:
    roots = [r for r in find_rules_with_selector(_blocks(), ":root") if r.media is None]
    assert len(roots) == 1
    return roots[0].declarations


def theme_declarations(theme: str) -> dict:
    blocks = find_rules_with_selector(_blocks(), f'html[data-theme="{theme}"]')
    assert len(blocks) == 1, theme
    return blocks[0].declarations


def calendar_rules():
    return parse_rules(_sheet("calendar.css"))


def calendar_source() -> str:
    return _sheet("calendar.css")


def glass_defines_card_bg() -> bool:
    glass = parse_rules(_sheet("padiem-glass.css"))
    return any("--card-bg" in r.declarations for r in glass)


def tokens() -> tuple[dict, set]:
    """(:root token values, token names redeclared in any theme block)."""
    root = root_declarations()
    overridden = set()
    for theme in THEMES:
        overridden.update(theme_declarations(theme))
    return root, overridden


def editorial_rules():
    return parse_rules(_sheet("padiem-editorial.css"))


def outputs_rules():
    return parse_rules(_sheet("outputs.css"))


def capability_nav_rules():
    return parse_rules(_sheet("capability-nav.css"))


def attachments_rules():
    return parse_rules(_sheet("attachments.css"))


def documents_rules():
    return parse_rules(_sheet("documents.css"))


def b66_quote_rules():
    return parse_rules(_sheet("b66-quote-runtime.css"))
def surfaces_rules():
    return parse_rules(_sheet("padiem-surfaces.css"))


def surfaces_source() -> str:
    return _sheet("padiem-surfaces.css")


def standalone_rules():
    return parse_rules(_sheet("standalone-views.css"))


def rich_rules():
    return parse_rules(_sheet("padiem-rich.css"))


def rich_response_rules():
    return parse_rules(_sheet("rich-response.css"))


def rich_response_source() -> str:
    return _sheet("rich-response.css")


def unthemed_literals(rules) -> list[str]:
    """Non-custom-property color literals outside html[data-theme] rules."""
    import re

    color_rx = re.compile(
        r"#[0-9a-fA-F]{3,8}(?![0-9a-fA-F])|rgba?\([^()]*\)|hsla?\([^()]*\)",
        re.IGNORECASE,
    )
    themed_selector = re.compile(r'html\[data-theme="[^"]+"\]')
    found = []
    for rule in rules:
        if any(themed_selector.search(s) for s in rule.selectors):
            continue
        for prop, value in rule.declarations.items():
            if prop.startswith("--"):
                continue
            if color_rx.search(value):
                found.append(f"{rule.selectors} {prop}: {value}")
    return found


def unthemed_editorial_literals() -> list[str]:
    return unthemed_literals(editorial_rules())


def unthemed_outputs_literals() -> list[str]:
    return unthemed_literals(outputs_rules())


def unthemed_capability_nav_literals() -> list[str]:
    return unthemed_literals(capability_nav_rules())


def unthemed_attachments_literals() -> list[str]:
    return unthemed_literals(attachments_rules())


def unthemed_documents_literals() -> list[str]:
    return unthemed_literals(documents_rules())


def unthemed_b66_quote_literals() -> list[str]:
    return unthemed_literals(b66_quote_rules())


def unthemed_standalone_literals() -> list[str]:
    return unthemed_literals(standalone_rules())


def unthemed_rich_literals() -> list[str]:
    return unthemed_literals(rich_rules())


def unthemed_rich_response_literals() -> list[str]:
    return unthemed_literals(rich_response_rules())
