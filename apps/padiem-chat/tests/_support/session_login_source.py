"""Source accessors for the session and login screen contracts (#8060).

Raw reads live here. The contract tests keep their assertions and receive
shipped text or stable paths through these accessors.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"


def sheet(name: str) -> str:
    return claw_static.sheet(name)


def locale_js() -> str:
    return claw_static.locale_source()


def static_path(name: str) -> Path:
    return _STATIC / name


def static_root() -> Path:
    return _STATIC


def static_dir() -> str:
    return str(_STATIC)


def source(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def read_request(fileobj, length: int) -> bytes:
    return fileobj.read(length)
