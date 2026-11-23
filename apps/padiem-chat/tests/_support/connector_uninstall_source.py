"""Source accessors for the PC connector uninstall contract (#8060).

Raw reads live here. The test keeps its code-anchored uninstall claims; it never
reads a shipped file itself.
"""
from __future__ import annotations

from _support import claw_static


def connect_cs() -> str:
    return claw_static.repo_source("scripts/pc_pairing/connect-exe/PadiemPcConnect.cs")


def install_html() -> str:
    return claw_static.sheet("install.html")


def doc() -> str:
    return claw_static.repo_source("docs/operations/PC_CONNECT_EXE_20261028.md")


def menu_model() -> str:
    return claw_static.repo_source("apps/claw-connect/claw_connect/menu_model.py")


def runtime() -> str:
    return claw_static.repo_source("apps/claw-connect/claw_connect/runtime.py")


def asset() -> str:
    return claw_static.server_source("pc_pairing_connect_exe_asset")
