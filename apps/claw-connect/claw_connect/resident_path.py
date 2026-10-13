"""Where the supervised kagent Resident lives.

Claw Connect supervises **exactly one** existing local runner
(``kagent.local_agent_resident_process``). There is no second executor, and the
placeholder ``python -c`` command used during S1 bring-up is never selected for
an operational run.

The location of the kagent source tree is supplied by the deployment (the
installer or the developer checkout through ``CLAW_RESIDENT_SRC``); it is never
guessed from a remote source and never invented here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

#: Canonical naming; keep the legacy variable for existing installations.
AGENT_SRC_ENV_VAR = "PADIEM_AGENT_SRC"
RESIDENT_SRC_ENV_VAR = "CLAW_RESIDENT_SRC"
#: Per-user file the installer may write to pin the Resident source root.
RESIDENT_CONFIG_FILENAME = "resident.json"
_RESIDENT_CONFIG_KEYS = frozenset({"src_root"})


def resident_src_root(*, state_dir: str | os.PathLike[str] | None = None) -> str | None:
    """The kagent ``src`` root, or ``None`` when the deployment did not pin one.

    ``None`` is an honest answer: the caller then uses the canonical module name
    and lets the interpreter resolve it, rather than inventing a path.
    """
    preferred = (os.environ.get(AGENT_SRC_ENV_VAR) or "").strip()
    legacy = (os.environ.get(RESIDENT_SRC_ENV_VAR) or "").strip()
    if preferred and legacy and Path(preferred).expanduser().resolve() != Path(legacy).expanduser().resolve():
        raise ValueError("PADIEM Agent source environment values disagree")
    if preferred or legacy:
        return preferred or legacy
    if state_dir is None:
        return None
    config = Path(state_dir).expanduser() / RESIDENT_CONFIG_FILENAME
    if not config.is_file():
        return None
    try:
        raw = config.read_text(encoding="utf-8")
        data: Any = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if type(data) is not dict or set(data) != _RESIDENT_CONFIG_KEYS:
        return None
    value = data["src_root"]
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def write_resident_config(
    state_dir: str | os.PathLike[str], src_root: str
) -> Path:
    """Pin the Resident source root for the current user. Called by the installer."""
    if not isinstance(src_root, str) or not src_root.strip():
        raise ValueError("resident src_root must be a non-empty path")
    base = Path(state_dir).expanduser()
    base.mkdir(parents=True, exist_ok=True)
    config = base / RESIDENT_CONFIG_FILENAME
    config.write_text(
        json.dumps({"src_root": src_root.strip()}, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return config


__all__ = [
    "RESIDENT_CONFIG_FILENAME",
    "AGENT_SRC_ENV_VAR",
    "RESIDENT_SRC_ENV_VAR",
    "resident_src_root",
    "write_resident_config",
]
