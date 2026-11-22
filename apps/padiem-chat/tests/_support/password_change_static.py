"""#8060 — shipped password-change assets, read once here for parsed contracts."""
from __future__ import annotations

import re
from pathlib import Path

from _support.html_tags import tags_for_page

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "static"


def text(name: str) -> str:
    path = ROOT / name if name.startswith("migrations/") else STATIC / name
    return path.read_text(encoding="utf-8")


def role_migration_source() -> str:
    return text("migrations/052_platform_admin_roles.sql")


def index_tags() -> list[tuple[str, dict[str, str | None]]]:
    return tags_for_page("index.html")


def element(id_value: str) -> tuple[str, dict[str, str | None]] | None:
    return next(((tag, attrs) for tag, attrs in index_tags()
                 if attrs.get("id") == id_value), None)


def element_index(id_value: str) -> int:
    return next(i for i, (_tag, attrs) in enumerate(index_tags())
                if attrs.get("id") == id_value)


def account_module_source() -> str:
    return text("chat-account-module.js")


def locale_source() -> str:
    from locale_bundle import SOURCE
    return SOURCE.read_text(encoding="utf-8")


def locale_key_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in re.findall(r'"([A-Za-z0-9_-]+)"\s*:', locale_source()):
        counts[name] = counts.get(name, 0) + 1
    return counts
