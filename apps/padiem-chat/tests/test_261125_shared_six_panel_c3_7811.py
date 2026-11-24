"""#7811 C3: preserve the six-panel visual contract after priority removal."""
from __future__ import annotations

from pathlib import Path

import pytest

from css_rules import parse_rules
from _support.calendar_palette import root_token_families

STATIC = Path(__file__).resolve().parents[1] / "static"
FRAME = STATIC / "shared-six-panel-frame.css"
TOKENS = STATIC / "padiem-tokens.css"
EXPECTED = {
    "--shared-six-panel-frame-bg": "linear-gradient(155deg, rgba(248,250,251,.88), rgba(233,238,241,.84))",
    "--shared-six-panel-frame-shadow": "0 24px 70px rgba(28,36,44,.16), inset 0 1px 0 rgba(255,255,255,.72)",
    "--shared-six-panel-frame-edge": "rgba(255,255,255,.70)",
    "--shared-six-panel-frame-narrow-bg": "rgba(242, 245, 247, .90)",
    "--shared-six-panel-frame-narrow-edge": "rgba(255, 255, 255, .58)",
}


def test_paint_values_are_pinned_and_family_contract_is_exact():
    source = TOKENS.read_text(encoding="utf-8")
    roots = [r for r in parse_rules(source) if r.selectors == [":root"] and r.media is None]
    assert len(roots) == 1
    assert {k: roots[0].declarations.get(k) for k in EXPECTED} == EXPECTED
    assert root_token_families(source)["--shared-six-panel-frame"] == set(EXPECTED)


def test_glass_frame_consumes_tokens_without_themed_importants():
    rules = parse_rules(FRAME.read_text(encoding="utf-8"))
    themed = [value for rule in rules
              if any("data-theme" in selector for selector in rule.selectors)
              for value in rule.declarations.values()]
    assert themed
    assert not any("!important" in value for value in themed)
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
    source = TOKENS.read_text(encoding="utf-8")
    needle = "--shared-six-panel-frame-narrow-bg:"
    assert source.count(needle) == 1
    broken = source.replace(needle, "" if mutation == "delete"
                            else "--shared-six-panel-frame-narrow-bg-typo:", 1)
    with pytest.raises(AssertionError):
        root_token_families(broken)
