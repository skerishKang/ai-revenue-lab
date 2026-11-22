"""Cross-app answer-copy wiring accessors (#8060).

Raw reads live here. Tests assert on token presence, ordering and byte
equality. The shared ``claw_static`` helper is untouched.
"""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]
_WORKFLOWS = _ROOT / ".github" / "workflows"
_CANONICAL = _ROOT / "packages" / "padiem-conversation-ui" / "answer-copy.js"


def read_text(relative: str) -> str:
    return (_ROOT / relative).read_text(encoding="utf-8")


def read_bytes(relative: str) -> bytes:
    return (_ROOT / relative).read_bytes()


def has(relative: str, needle: str) -> bool:
    return needle in read_text(relative)


def count(relative: str, needle: str) -> int:
    return read_text(relative).count(needle)


def before(relative: str, first: str, second: str) -> bool:
    text = read_text(relative)
    return text.index(first) < text.index(second)


def canonical_text() -> str:
    return _CANONICAL.read_text(encoding="utf-8")


def canonical_bytes() -> bytes:
    return _CANONICAL.read_bytes()


def workflow_text(name: str) -> str:
    return (_WORKFLOWS / name).read_text(encoding="utf-8")
