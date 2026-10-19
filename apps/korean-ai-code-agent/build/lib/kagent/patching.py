from __future__ import annotations

from dataclasses import dataclass
import difflib


@dataclass(frozen=True, slots=True)
class PendingPatch:
    """Pure proposed-change value object; performs no filesystem writes."""

    relative_path: str
    original_text: str
    proposed_text: str

    def unified_diff(self) -> str:
        return "".join(
            difflib.unified_diff(
                self.original_text.splitlines(keepends=True),
                self.proposed_text.splitlines(keepends=True),
                fromfile=f"a/{self.relative_path}",
                tofile=f"b/{self.relative_path}",
            )
        )
