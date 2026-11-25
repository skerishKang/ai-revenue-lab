"""#7811 C3 Glass portrait: token scope, priority removal, and mutation contracts."""
from __future__ import annotations

import pytest

from css_rules import parse_rules
from _support.calendar_palette import root_declarations, root_token_families
from _support.claw_static import sheet

TOKEN = "--glass-portrait-answer-action-ink"


def test_glass_portrait_token_family_is_exact_and_value_preserved():
    assert root_declarations()[TOKEN] == "#53606c"
    assert root_token_families()["--glass-portrait"] == {TOKEN}


def test_portrait_themed_overrides_have_no_priority_and_keep_glass_effects():
    rules = parse_rules(sheet("padiem-glass-portrait.css"))
    themed = [
        (rule, prop, value) for rule in rules
        if any("data-theme" in selector for selector in rule.selectors)
        for prop, value in rule.declarations.items()
    ]
    assert themed
    assert all("!important" not in value for _, _, value in themed)
    assert any(
        prop == "background-color" and value == "var(--glass-card-surface)"
        for _, prop, value in themed
    )
    for prop in ("backdrop-filter", "-webkit-backdrop-filter"):
        assert any(
            prop == name and value == "none" and any(
                ".assistant-content > p" in selector for selector in rule.selectors
            ) for rule, name, value in themed
        )
    assert any(
        prop == "color" and value == f"var({TOKEN})" and any(
            ".answer-actions .answer-action" in selector for selector in rule.selectors
        ) for rule, prop, value in themed
    )


@pytest.mark.parametrize("mutation", ("delete", "rename"))
def test_glass_portrait_family_contract_catches_name_mutation(mutation):
    source = sheet("padiem-tokens.css")
    needle = TOKEN + ":"
    assert source.count(needle) == 1
    replacement = "" if mutation == "delete" else TOKEN + "-mistyped:"
    with pytest.raises(AssertionError):
        root_token_families(source.replace(needle, replacement, 1))
