"""Source accessor for the MCP client-groups UI contract (#8060).

The raw read lives here. The test keeps its parsed CSS and markup checks; it
never reads a shipped file itself.
"""
from __future__ import annotations

from pathlib import Path


def read(path: Path) -> str:
    # locale_bundle.SOURCE is a _Source object exposing read_text, not a Path.
    if hasattr(path, "read_text"):
        return path.read_text(encoding="utf-8")
    return Path(path).read_text(encoding="utf-8")
