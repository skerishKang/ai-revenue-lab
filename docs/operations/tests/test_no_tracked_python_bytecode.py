from __future__ import annotations

import subprocess


def test_repository_tracks_no_python_bytecode() -> None:
    tracked = subprocess.check_output(
        ["git", "ls-files", "-z"],
        text=False,
    ).decode("utf-8").split("\0")
    offenders = sorted(
        path
        for path in tracked
        if path and ("__pycache__/" in path or path.endswith((".pyc", ".pyo", ".pyd")))
    )
    assert offenders == [], (
        "Generated Python bytecode must never be tracked. "
        f"Remove these files from Git: {offenders}"
    )
