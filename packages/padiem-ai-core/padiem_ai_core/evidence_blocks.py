"""The grounded evidence block format, and trimming it by rank (#4379, #6842).

Grounding preparation writes one line per source: ``[n] {"source":n, ...}``.
A dispatcher that only learns the model's input budget at dispatch time needs to
end the set the same way preparation does, so the format and its lowest-rank
trim live in this dependency-free module: B14 stages it without the rest of the
grounding runtime.
"""

from __future__ import annotations

import re

#: The evidence block this package writes: ``[n] {"source":n, ...}``.
EVIDENCE_BLOCK_PREFIX = re.compile(r"^\[(\d+)\] \{\"source\":\1,")


def trim_evidence_text(text: str, *, max_chars: int) -> tuple[str, int]:
    """Drop the lowest-ranked evidence blocks until the text fits the budget.

    The highest citation number goes first, so the remaining blocks keep their
    original [1]..[k] numbering and every claim that still cites one cites a
    block that is present. Prose outside the blocks is never removed. Returns
    the trimmed text and how many blocks were dropped.
    """
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    if isinstance(max_chars, bool) or not isinstance(max_chars, int):
        raise ValueError("max_chars must be an integer")
    lines = text.splitlines()
    blocks = [
        index for index, line in enumerate(lines) if EVIDENCE_BLOCK_PREFIX.match(line)
    ]
    dropped = 0
    while blocks and len("\n".join(lines)) > max_chars:
        # Blocks appear in rank order, so the last one is the lowest-ranked.
        lines.pop(blocks.pop())
        dropped += 1
    return "\n".join(lines), dropped
