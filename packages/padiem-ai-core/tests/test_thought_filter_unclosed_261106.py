"""The thought filter must say when it had to drop prose with an unclosed block."""
from __future__ import annotations

import pytest

from padiem_ai_core.thought_filter import strip_thought_blocks, strip_thought_blocks_ex


@pytest.mark.parametrize("raw,expected", [
    ("<thought>private</thought>visible answer", "visible answer"),
    ("answer start <thought>never closed", "answer start "),
    ("<thinking>x</thinking> after", " after"),
    ("no tags at all", "no tags at all"),
    ("<thought>only reasoning, nothing visible", ""),
])
def test_reported_variant_returns_the_same_text_as_the_public_helper(raw, expected):
    stripped, _ = strip_thought_blocks_ex(raw)
    assert stripped == strip_thought_blocks(raw) == expected


@pytest.mark.parametrize("raw,cut", [
    # Prose sat after a tag the model never closed, so it was dropped with the block.
    ("answer start <thought>never closed", True),
    ("<thought>private</thought>visible answer", False),
    ("no tags at all", False),
    ("<thought>only reasoning, nothing visible", True),
    ("a <thought>b</thought> c <thought> tail", True),
])
def test_unclosed_block_is_reported_without_changing_the_visible_text(raw, cut):
    assert strip_thought_blocks_ex(raw)[1] is cut
