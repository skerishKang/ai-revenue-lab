"""Temporary smoke check — the generated depth/recursive scripts run for real."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.oracle_mesh_read_return_routes import _pc_files_command

_PWSH = shutil.which("pwsh")


def _tree(root: Path) -> None:
    (root / "sub").mkdir()
    (root / "sub" / "deep").mkdir()
    (root / "sub" / "deep" / "target.txt").write_text("x")
    (root / "top.txt").write_text("y")
    (root / "hidden_dir").mkdir()
    (root / "hidden_dir" / "z.txt").write_text("z")
    os.system(f'attrib +H "{root / "hidden_dir"}"')
    os.symlink(r"C:\Windows", root / "escape")


def _run(script: str) -> dict:
    out = subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=120,
    )
    return json.loads(out.stdout)


def test_depth_two_walk_and_recursive_search_execute(pwsh_available):
    root = Path(tempfile.mkdtemp(prefix="padiem_pc_depth_"))
    try:
        _tree(root)
        parsed = _run(_pc_files_command(op="list", root=str(root), relative="", depth=2))
        rows = [(r["relative_path"], r["depth"]) for r in parsed["items"]]
        assert ("sub", 1) in rows and ("sub\\deep", 2) in rows
        assert ("top.txt", 1) in rows and ("escape", 1) in rows and ("hidden_dir", 1) in rows
        assert parsed["truncated"] is False and parsed["has_more"] is False
        assert not any("z.txt" in path for path, _ in rows)
        assert not any(path.startswith("escape\\") for path, _ in rows)

        parsed2 = _run(_pc_files_command(op="list", root=str(root), relative="",
                                         recursive=True, filter_term="target"))
        assert [r["relative_path"] for r in parsed2["items"]] == ["sub\\deep\\target.txt"]
        assert parsed2["has_more"] is False and parsed2["truncated"] is False
    finally:
        shutil.rmtree(root, ignore_errors=True)


import pytest


@pytest.fixture
def pwsh_available():
    if shutil.which("pwsh") is None:
        pytest.skip("pwsh is not on PATH (runs on the GitHub runners)")
    return True
