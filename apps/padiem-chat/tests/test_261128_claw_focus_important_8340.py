"""#8340: parsed CSS structure ratchet. No raw stylesheet string assertions."""
from __future__ import annotations

import hashlib
import json

from _support import theme_sheets

SHEET = "claw-focus-layout.css"
SELECTOR_SHA256 = "75a38008a06c16454322be2d230cbbc1df183ee2a67405d897a4d6bb8370c40c"
EXPECTED_REMAINING = 9


def test_selector_structure_does_not_gain_strength():
    """Any added html/body prefix, duplicated class or changed selector fails."""
    selectors = [rule.selector.strip() for rule in theme_sheets.rules(SHEET)]
    actual = hashlib.sha256(
        json.dumps(selectors, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    assert actual == SELECTOR_SHA256, "Claw focus selector structure changed"


def test_important_ratcheted_down_to_nine():
    flags = [
        (rule.selector, decl.prop)
        for rule in theme_sheets.rules(SHEET)
        for decl in rule.decls
        if "!important" in decl.value
    ]
    assert len(flags) <= EXPECTED_REMAINING, flags
    assert {prop for _, prop in flags} <= {
        "width", "margin-left", "margin-right", "left", "min-height", "padding"
    }


def test_css_audit_no_new_flags_or_colors():
    """Shared audit parser, not test-specific source-text matching."""
    from pathlib import Path
    import importlib.util

    root = Path(__file__).resolve().parents[3]
    path = root / "tools" / "chat_structure_audit.py"
    spec = importlib.util.spec_from_file_location("chat_8340_structure", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    metric, _ = module.css_metrics()
    assert metric["css_important"] <= 169
    assert metric["css_color_literals"] <= 836
    assert metric["css_important_by_file"][SHEET] <= EXPECTED_REMAINING
