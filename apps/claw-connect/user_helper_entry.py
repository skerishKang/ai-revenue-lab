"""#7108 PR-1 — PyInstaller entry point for the Pythonless user helper.

The helper implementation lives in :mod:`claw_connect.user_helper_service` and
is shared with the source-installed Connector. This file only adapts packaging:
it keeps the helper's standard streams usable in a windowed EXE and hides the
console of the child shells the helper starts.

A windowed parent does not hide a console child. ``powershell.exe`` and
``cmd.exe`` are console applications, so Windows would give each one its own
console window in the user's session. ``CREATE_NO_WINDOW`` is applied to every
child the helper starts through this seam, without changing the helper source
or its pipe/frame/nonce contract.
"""
from __future__ import annotations

import os
import subprocess
import sys

_ORIGINAL_POPEN = subprocess.Popen
_CREATE_NO_WINDOW = 0x08000000


def _popen_without_window(*args, **kwargs):
    """Start a child with no console window on Windows, preserving its argv."""
    if os.name == "nt":
        flags = int(kwargs.get("creationflags", 0) or 0)
        kwargs["creationflags"] = flags | getattr(
            subprocess, "CREATE_NO_WINDOW", _CREATE_NO_WINDOW
        )
    return _ORIGINAL_POPEN(*args, **kwargs)


def _install_child_console_guard() -> None:
    """Route every child started by the helper through the windowless seam."""
    if os.name == "nt":
        subprocess.Popen = _popen_without_window


def _ensure_standard_streams() -> None:
    """Make the helper's own stdout/stderr writes safe in a windowed EXE.

    PyInstaller windowed builds may leave ``sys.stdout``/``sys.stderr`` as
    ``None`` when there is no console. The helper's ``main`` prints one final
    counter line and a refusal reason, so those writes must not turn a served
    request into a crash.
    """
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


def main() -> int:
    _ensure_standard_streams()
    _install_child_console_guard()
    from claw_connect.user_helper_service import main as helper_main

    return helper_main()


if __name__ == "__main__":
    raise SystemExit(main())
