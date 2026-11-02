"""2026-11-02 owner decision: the deleted ``b14/auto`` id may not return.

Executable source (``.py``, ``.js``/``.mjs``, ``.yml``/``.yaml``) must not
carry the literal again. The only exceptions are this guard and the single
rejection test that has to name the id to exercise the refusal.
"""

from __future__ import annotations

import os
from pathlib import Path

TARGET = "b14/auto"
ROOT = Path(__file__).resolve().parents[3]
SCANNED_SUFFIXES = {".py", ".js", ".mjs", ".yml", ".yaml"}
SKIP_DIRECTORIES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
}
ALLOWED = {
    Path(__file__).resolve(),
    (Path(__file__).resolve().parent / "test_b14_auto_is_rejected.py").resolve(),
}


def _executable_sources() -> list[Path]:
    found: list[Path] = []
    for directory, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRECTORIES]
        for filename in filenames:
            path = Path(directory) / filename
            if path.suffix in SCANNED_SUFFIXES:
                found.append(path)
    return found


def test_no_executable_source_names_the_deleted_route() -> None:
    offenders = sorted(
        str(path.relative_to(ROOT)).replace("\\", "/")
        for path in _executable_sources()
        if path.resolve() not in ALLOWED
        and TARGET in path.read_text(encoding="utf-8", errors="replace")
    )

    assert offenders == []
