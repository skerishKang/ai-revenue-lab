"""Source accessors for the conversation soft-delete guards (#8060).

Raw reads live here. The guards keep the same windows, markers and assertions.
"""
from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_APP_DIR = _REPO_ROOT / "apps" / "padiem-chat" / "app"


def ops_restore_script() -> str:
    return (_REPO_ROOT / "ops" / "restore_conversation.sh").read_text(encoding="utf-8")


def source_files() -> list[tuple[str, list[str]]]:
    return [
        (path.name, path.read_text(encoding="utf-8").splitlines())
        for path in sorted(_APP_DIR.glob("*.py"))
        if path.name != "__init__.py"
    ]
