"""Shipped-source accessors for file preview contracts (#8060).

Raw reads live here. The tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

import locale_bundle

_STATIC = Path(__file__).resolve().parents[2] / "static"


def read(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def project_module_js() -> str:
    return (_STATIC / "chat-project-module.js").read_text(encoding="utf-8")


def project_drive_folder_js() -> str:
    return (_STATIC / "project-drive-folder.js").read_text(encoding="utf-8")


def projects_css() -> str:
    return (_STATIC / "projects.css").read_text(encoding="utf-8")


def history_module_js() -> str:
    return (_STATIC / "chat-history-module.js").read_text(encoding="utf-8")


def run_history_module_js() -> str:
    return (_STATIC / "chat-run-history-module.js").read_text(encoding="utf-8")


def pdf_preview_js() -> str:
    return (_STATIC / "claw-pdf-preview.js").read_text(encoding="utf-8")


def claw_run_module_js() -> str:
    return (_STATIC / "chat-claw-run-module.js").read_text(encoding="utf-8")


def claw_form_module_js() -> str:
    return (_STATIC / "chat-claw-form-module.js").read_text(encoding="utf-8")


def claw_session_js() -> str:
    return (_STATIC / "claw-session.js").read_text(encoding="utf-8")


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def claw_workspace_css() -> str:
    return (_STATIC / "claw-workspace.css").read_text(encoding="utf-8")
