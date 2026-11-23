"""Source accessor for the deployed parity audit contract (#8060).

The raw read lives here. The test keeps its credential-absence checks; it never
reads a shipped file itself.
"""
from __future__ import annotations

from pathlib import Path


def load_source(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")
