"""Source accessors for claw transport, route table and identity tests (#8060).

Raw reads live here. The contract tests keep their assertions and receive
shipped text or stable paths through these accessors.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"
_TESTS = Path(__file__).resolve().parents[1]
_APPS = Path(__file__).resolve().parents[3]


def sheet(name: str) -> str:
    return claw_static.sheet(name)


def source(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def repo_source(relative: str) -> str:
    return (_APPS / relative).read_text(encoding="utf-8")


def support_source(name: str) -> str:
    return (_TESTS / name).read_text(encoding="utf-8")


def js_paths() -> list[Path]:
    return sorted(_STATIC.rglob("*.js"))


def static_root() -> Path:
    return _STATIC
