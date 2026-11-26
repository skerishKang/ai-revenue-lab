"""#7811: preserve the Glass frame and its paint tokens without priority overrides."""
from __future__ import annotations

import pytest

from css_rules import find_rules_with_selector, rules_for_sheet

from _support.calendar_palette import root_token_families, root_declarations
from _support.six_panel_c3_source import frame_rules, tampered_token_sheet


EXPECTED = {
    "--shared-six-panel-frame-bg": "linear-gradient(155deg, rgba(248,250,251,.88), rgba(233,238,241,.84))",
    "--shared-six-panel-frame-shadow": "0 24px 70px rgba(28,36,44,.16), inset 0 1px 0 rgba(255,255,255,.72)",
    "--shared-six-panel-frame-edge": "rgba(255,255,255,.70)",
    "--shared-six-panel-frame-grain-opacity": ".10",
    "--shared-six-panel-frame-narrow-bg": "rgba(242, 245, 247, .90)",
    "--shared-six-panel-frame-narrow-edge": "rgba(255, 255, 255, .58)",
}


def test_paint_values_are_pinned_and_family_contract_is_exact():
    root = root_declarations()
    assert {k: root.get(k) for k in EXPECTED} == EXPECTED
    assert root_token_families()["--shared-six-panel-frame"] == set(EXPECTED)


def test_shared_frame_and_glass_layout_have_no_priority_overrides():
    frame = frame_rules()
    layout = rules_for_sheet("padiem-glass-panel-layout.css")
    assert frame and layout
    assert all(
        selector.startswith('html[data-theme="padiem-glass"]')
        for rule in layout for selector in rule.selectors
    )
    assert all(
        "!important" not in value
        for rule in frame + layout for value in rule.declarations.values()
    )


def test_frame_paint_and_atmospheric_grid_read_the_pinned_tokens():
    frame_values = [value for rule in frame_rules() for value in rule.declarations.values()]
    grain_token = "--shared-six-panel-frame-grain-opacity"
    for name in EXPECTED.keys() - {grain_token}:
        assert any(f"var({name})" in value for value in frame_values), name

    grain, = find_rules_with_selector(
        rules_for_sheet("padiem-glass.css"), 'html[data-theme="padiem-glass"] body::after',
    )
    assert grain.declarations["opacity"] == f"var({grain_token})"


@pytest.mark.parametrize("mutation", ("delete", "rename"))
def test_family_contract_detects_missing_or_misspelled_name(mutation):
    with pytest.raises(AssertionError):
        root_token_families(tampered_token_sheet(mutation))
