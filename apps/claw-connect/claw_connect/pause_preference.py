"""Per-user durable pause/disable preference; no secrets or binding state."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile


def is_paused(state_dir: Path) -> bool:
    path = state_dir / "user-pause.json"
    if not path.exists():
        return False
    try:
        if not path.is_file() or path.stat().st_size > 128:
            return True
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload["paused"] if type(payload) is dict and set(payload) == {"paused"} and type(payload["paused"]) is bool else True
    except (OSError, ValueError, KeyError, TypeError):
        return True


def set_paused(state_dir: Path, paused: bool) -> None:
    if type(paused) is not bool:
        raise ValueError("paused must be a boolean")
    state_dir.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".pause-", suffix=".json", dir=state_dir)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            json.dump({"paused": paused}, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, state_dir / "user-pause.json")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
