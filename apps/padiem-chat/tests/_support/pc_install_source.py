"""Parsed-source boundary for the #6695 install-token contracts.

Raw ``read_text`` lives here; tests receive parsed migration statements and
named static views. No runtime file or workflow changes.
"""
from __future__ import annotations

from pathlib import Path

from _support.claw_static import locale_source, sheet

CHAT = Path(__file__).resolve().parents[2]
MIGRATION = CHAT / "migrations/093_pc_install_tokens.sql"


def migration_statements() -> list[str]:
    text = MIGRATION.read_text(encoding="utf-8")
    body = "\n".join(line for line in text.splitlines()
                     if not line.strip().startswith("--"))
    return [part.strip() for part in body.split(";") if part.strip()]


def card() -> str:
    return sheet("pc-pairing-card.js")


def locale() -> str:
    return locale_source()
