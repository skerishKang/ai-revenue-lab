"""B4-2 login-flow golden: run the shipped R5 auth harness against any static tree.

The harness itself is the one used by the step4 auth contract; this module only
parameterises the static directory so the same observation can be produced from
clean origin/main and from this branch. No expectation lives here.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from _r5_auth_module_harness import STRICT, _HARNESS, presentation_table


def login_golden(static_dir: Path) -> dict:
    node = shutil.which("node")
    if not node:
        raise AssertionError("node is required for the login-flow golden harness")
    static = Path(static_dir)
    modules = [static / "chat-auth-module.js", static / "chat-account-module.js"]
    dialog = static / "chat-login-dialog-module.js"
    with tempfile.TemporaryDirectory() as tmp:
        # The shared harness takes a fixed three-module argv. main has no dialog
        # module, so an empty placeholder keeps the argv shape identical.
        placeholder = Path(tmp) / "chat-login-dialog-placeholder.js"
        placeholder.write_text("", encoding="utf-8")
        modules.append(dialog if dialog.exists() else placeholder)
        harness = Path(tmp) / "harness.js"
        source = (
            STRICT + "\nconst SHIPPED_PRESENTATION = "
            + json.dumps(presentation_table(), ensure_ascii=False) + ";\n" + _HARNESS
        )
        # main has no dialog module: its dialog functions still live in the auth
        # module, so an empty dialog API keeps the merged surface identical.
        source = source.replace(
            'const dialogApi = ctx.window.PadiemChatLoginDialogModule.create(r5StrictDeps(deps, "step4.dialog.deps"));',
            'const dialogApi = ctx.window.PadiemChatLoginDialogModule'
            ' ? ctx.window.PadiemChatLoginDialogModule.create(r5StrictDeps(deps, "step4.dialog.deps")) : {};',
        )
        harness.write_text(source, encoding="utf-8", newline="\n")
        completed = subprocess.run(
            [node, str(harness), *(str(path) for path in modules)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(completed.stdout)
