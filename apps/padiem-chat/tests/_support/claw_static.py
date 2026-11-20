"""Read shipped static sheets for Claw UI contracts (#8060).

Keeps raw ``read_text`` out of test modules: the contract files receive the
text and assert on parsed rule/attribute values. The sheet paths stay here.
"""
from __future__ import annotations

from pathlib import Path

import locale_bundle

_STATIC = Path(__file__).resolve().parents[2] / "static"


def sheet(name: str) -> str:
    """One shipped static sheet as text (paths are fixed here, not in tests)."""
    return (_STATIC / name).read_text(encoding="utf-8")


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def source_of(path: str) -> str:
    """A test module's own source for its no-fixed-path self-check."""
    return Path(path).read_text(encoding="utf-8")
