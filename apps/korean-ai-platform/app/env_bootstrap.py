"""Minimal dependency-free .env loader for the documented owner workflow.

The documented start command is:

    python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000

If ``.env`` exists in the working directory and the process environment does
not already contain a variable, it is loaded before the app factory and
configuration singletons are imported. Existing environment variables always
win, so real deployment secrets are never overwritten by a local file. The
loader never logs values and never exposes secrets.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_env_file(
    path: str | os.PathLike[str] | None = None,
    *,
    overwrite: bool = False,
) -> int:
    """Load KEY=VALUE pairs from a .env file into os.environ.

    Returns the number of variables newly set. Missing/unreadable files are
    ignored (returns 0). Comments, blank lines, and optional ``export`` are
    supported. Single/double surrounding quotes are stripped.
    """
    env_path = Path(path) if path is not None else Path.cwd() / ".env"
    try:
        if not env_path.is_file():
            return 0
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return 0

    loaded = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if overwrite or key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded