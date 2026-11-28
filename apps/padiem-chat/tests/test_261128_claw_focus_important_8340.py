"""#8340: claw-focus-layout.css carries no priority flag, and gets none back.

Parsed structure only (the shared audit parser through theme_sheets) -- no raw
stylesheet text is asserted.

The sheet used to win its fights with 18 priority flags. Sixteen of them beat
nothing that is still in the cascade (their opponents are lower-specificity and
unflagged), two beat a later phone-width declaration in the same sheet that has
never painted, and two beat nothing but a same-selector, same-value twin in
connector-pages.css that has never painted either. The never-painted
declarations were deleted, so every remaining value is the one that always
rendered.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

from _support import theme_sheets

SHEET = "claw-focus-layout.css"
CONNECTOR_SHEET = "connector-pages.css"

# sha256 of the rule selector list. Adding an html/body prefix, repeating a
# class or changing any selector to out-win a neighbour changes it.
SELECTOR_SHA256 = "75a38008a06c16454322be2d230cbbc1df183ee2a67405d897a4d6bb8370c40c"

PREFIX = '.app-shell[data-state="claw"] .claw-workspace[data-view="general"] ~ .conversation'
CARD = f"{PREFIX} .claw-home-card"
STARTER = f"{CARD} > .claw-workspace-starter"
TOGGLE = f"{CARD} > .claw-connection-toggle"


def _values(sheet: str, selector: str, prop: str) -> list[str]:
    return [
        decl.value.replace("!important", "").strip()
        for rule in theme_sheets.rules(sheet)
        if rule.selector.strip() == selector
        for decl in rule.decls
        if decl.prop == prop
    ]


def test_selector_structure_does_not_gain_strength():
    """No selector may be strengthened to win without a flag."""
    selectors = [rule.selector.strip() for rule in theme_sheets.rules(SHEET)]
    actual = hashlib.sha256(
        json.dumps(selectors, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    assert actual == SELECTOR_SHA256, "Claw focus selector structure changed"


def test_sheet_has_no_priority_flag():
    flags = [
        (rule.selector.strip(), decl.prop)
        for rule in theme_sheets.rules(SHEET)
        for decl in rule.decls
        if decl.important
    ]
    assert flags == []


def test_never_painted_declarations_stay_deleted():
    """Declarations that lost every fight must not return.

    Re-adding one is invisible while a flag covers it and changes the screen the
    day the flag is dropped, which is how they stayed hidden in the first place.
    """
    # The phone-width starter min-height 134px lost to the flagged 0 at every width.
    assert _values(SHEET, STARTER, "min-height") == ["0"]
    # The phone-width toggle padding 4px 10px lost to the flagged 2px 5px; the
    # 2px 5px value is the one that has always been painted.
    assert _values(SHEET, TOGGLE, "padding") == ["2px 5px"]
    # The starter's phone-width align-items lives in connector-pages.css only.
    assert _values(SHEET, STARTER, "align-items") == []
    # One decision, one rule: the same-selector twins in connector-pages.css never
    # won against this sheet (later, same specificity) and are gone.
    assert _values(CONNECTOR_SHEET, STARTER, "min-height") == []
    assert _values(CONNECTOR_SHEET, CARD, "overflow") == []
    # The values they duplicated are declared here.
    assert "hidden" in _values(SHEET, CARD, "overflow")


def _audit_metrics():
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "chat_8340_claw_focus_structure", root / "tools" / "chat_structure_audit.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    metric = module.css_metrics()
    return metric[0] if isinstance(metric, tuple) else metric


def test_css_audit_no_new_flags_or_colors():
    """Shared audit parser, not test-specific source-text matching."""
    metric = _audit_metrics()
    assert metric["css_important"] <= 160
    assert metric["css_color_literals"] <= 836
    assert metric["css_important_by_file"][SHEET] == 0
