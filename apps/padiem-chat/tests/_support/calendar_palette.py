"""Parsed views for the calendar palette token contracts (#7811 C2 calendar).

The raw sheet reads live here (via claw_static); the contract tests receive
parsed rule/declaration values and assert on those, never on source text
directly.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from css_rules import find_rules_with_selector, parse_rules
from _support.claw_static import sheet as _sheet

THEMES = ("light", "dark", "padiem-glass", "cinematic", "padiem-home")


# A family contract lives next to its own declarations in padiem-tokens.css.
# This keeps independent C2 lanes out of the shared test-name roster.
_FAMILY_MARKER = re.compile(
    r"/\*\s*#7811 token-family (--[A-Za-z0-9_-]+) "
    r"sha256=([a-f0-9]{64})\s*\*/"
)


def root_token_families(css: str | None = None) -> dict[str, set[str]]:
    """Return the exact declared :root token groups, checking CSS-local rosters.

    The SHA-256 markers are pinned independently of declarations. Removing
    a declaration or renaming a token is rejected even if a consumer later
    stops referencing it. A new sheet extends only its own CSS-local marker.
    """
    css = _sheet("padiem-tokens.css") if css is None else css
    roots = [r for r in find_rules_with_selector(parse_rules(css), ":root")
             if r.media is None]
    assert len(roots) == 1, "exactly one root token block"
    names = {key for key in roots[0].declarations if key.startswith("--")}
    # The longest real sheet-name prefix wins (rich-response versus rich).
    # Names without a matching sheet retain their first role prefix.
    static = Path(__file__).resolve().parents[2] / "static"
    sheet_prefixes = sorted({
        "--" + sheet.stem.removeprefix("padiem-") + "-"
        for sheet in static.glob("*.css") if sheet.name != "padiem-tokens.css"
    }, key=len, reverse=True)
    groups: dict[str, set[str]] = {}
    for name in names:
        family = next(
            (prefix[:-1] for prefix in sheet_prefixes if name.startswith(prefix)),
            "--" + name[2:].split("-", 1)[0],
        )
        groups.setdefault(family, set()).add(name)

    # Read only markers physically within :root, not theme blocks or prose.
    root_start = css.index(":root {")
    root_end = css.index("\n}", root_start)
    markers = _FAMILY_MARKER.findall(css[root_start:root_end])
    markers_by_family = dict(markers)
    assert len(markers_by_family) == len(markers), "duplicate family marker"
    assert set(markers_by_family) == set(groups), (
        "family missing/extra", set(markers_by_family) ^ set(groups)
    )
    for family, members in groups.items():
        digest = hashlib.sha256(
            "\n".join(sorted(members)).encode("utf-8")
        ).hexdigest()
        assert markers_by_family[family] == digest, (
            "token family changed", family, sorted(members)
        )
    return groups


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


def search_sources_rules():
    return parse_rules(_sheet("search-sources.css"))
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


def pc_pairing_rules():
    return parse_rules(_sheet("pc-pairing-card.css"))


def pc_pairing_source() -> str:
    return _sheet("pc-pairing-card.css")


def answer_actions_rules():
    return parse_rules(_sheet("answer-actions.css"))


def answer_actions_source() -> str:
    return _sheet("answer-actions.css")


def claw_workspace_rules():
    return parse_rules(_sheet("claw-workspace.css"))


def claw_workspace_source() -> str:
    return _sheet("claw-workspace.css")


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


def unthemed_search_sources_literals() -> list[str]:
    return unthemed_literals(search_sources_rules())


def unthemed_standalone_literals() -> list[str]:
    return unthemed_literals(standalone_rules())


def unthemed_rich_literals() -> list[str]:
    return unthemed_literals(rich_rules())


def unthemed_rich_response_literals() -> list[str]:
    return unthemed_literals(rich_response_rules())


def unthemed_pc_pairing_literals() -> list[str]:
    return unthemed_literals(pc_pairing_rules())


def unthemed_answer_actions_literals() -> list[str]:
    return unthemed_literals(answer_actions_rules())


def unthemed_claw_workspace_literals() -> list[str]:
    return unthemed_literals(claw_workspace_rules())
