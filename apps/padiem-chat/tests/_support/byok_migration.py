"""Parsed statements from the additive BYOK endpoint migration (#8060 16차).

Keeps the raw ``read_text`` out of the contract test; the harness applies the
same statements and the test can assert their additive shape.
"""
from __future__ import annotations

from pathlib import Path

MIGRATION = (Path(__file__).resolve().parents[4]
             / "apps/padiem-chat/migrations/064_chat_custom_provider_endpoints.sql")


def endpoint_migration_statements() -> list[str]:
    """Non-empty SQL statements, comments stripped, in application order."""

    text = MIGRATION.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if not line.strip().startswith("--")]
    body = "\n".join(lines)
    return [part.strip() for part in body.split(";") if part.strip()]
