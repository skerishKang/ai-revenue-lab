"""#7811 C3: preserve the six-panel visual contract after priority removal."""
from __future__ import annotations

import pytest

from _support.calendar_palette import root_token_families, root_declarations
from _support.six_panel_c3_source import frame_rules, tampered_token_sheet
EXPECTED = {
    "--shared-six-panel-frame-bg": "linear-gradient(155deg, rgba(248,250,251,.88), rgba(233,238,241,.84))",
    "--shared-six-panel-frame-shadow": "0 24px 70px rgba(28,36,44,.16), inset 0 1px 0 rgba(255,255,255,.72)",
    "--shared-six-panel-frame-edge": "rgba(255,255,255,.70)",
    "--shared-six-panel-frame-narrow-bg": "rgba(242, 245, 247, .90)",
    "--shared-six-panel-frame-narrow-edge": "rgba(255, 255, 255, .58)",
}


def test_paint_values_are_pinned_and_family_contract_is_exact():
    root = root_declarations()
    assert {k: root.get(k) for k in EXPECTED} == EXPECTED
    assert root_token_families()["--shared-six-panel-frame"] == set(EXPECTED)


def test_glass_frame_consumes_tokens_without_themed_importants():
    rules = frame_rules()
    themed = [value for rule in rules
              if any("data-theme" in selector for selector in rule.selectors)
              for value in rule.declarations.values()]
    assert themed
    # Nine declarations still outrank later theme/layout rules. Their computed
    # values changed in Claw or Calendar when the priority was removed.
    priority = [(name, value) for rule in rules
                if any("data-theme" in selector for selector in rule.selectors)
                for name, value in rule.declarations.items() if "!important" in value]
    assert len(priority) == 9
    # The later reading stylesheet lowers body::after opacity to .025.
    # Keep this priority so the home atmospheric grid stays at .10.
    noise = [r for r in rules if any(
        'data-glass-mode="reading"' in selector and 'body::after' in selector
        for selector in r.selectors
    )]
    assert len(noise) == 1
    assert noise[0].declarations["opacity"] == ".10 !important"
    assert {name for name, _ in priority} == {
        "height", "min-height", "max-height", "border-radius",
        "background", "box-shadow", "overflow-y", "padding", "opacity",
    }
    unthemed_priority = [value for rule in rules
                         if not any("data-theme" in sel for sel in rule.selectors)
                         for value in rule.declarations.values()
                         if "!important" in value]
    assert len(unthemed_priority) == 2
    consumed = {v for rule in rules for v in rule.declarations.values()}
    for name in EXPECTED:
        assert any(f"var({name})" in v for v in consumed), name


@pytest.mark.parametrize("mutation", ("delete", "rename"))
def test_family_contract_detects_missing_or_misspelled_name(mutation):
    with pytest.raises(AssertionError):
        root_token_families(tampered_token_sheet(mutation))
