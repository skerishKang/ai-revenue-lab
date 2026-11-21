"""Shared fixture reads for the local CPython composition contracts (#8060 42차).

Keeps the raw ``read_text`` calls out of the composition contract tests: the
tests receive the parsed auth-verify vectors, the parsed worker lock, the
applied project-files migrations and the served-HTML reference sets. The file
paths stay here.
"""
from __future__ import annotations

import json
import re
import tomllib
from html.parser import HTMLParser
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
CHAT = REPO / "apps/padiem-chat"
AUTH_VERIFY = REPO / "packages/padiem-auth-verify"


def file_text(path) -> str:
    """One fixture file as text (the read call lives here, not in tests)."""
    return Path(path).read_text(encoding="utf-8")


def auth_verify_vectors() -> dict:
    """The pinned ES256 wire vectors of the auth-verify package."""
    return json.loads((AUTH_VERIFY / "tests" / "vectors.json").read_text(encoding="utf-8"))


def worker_lock_packages() -> list[dict]:
    """The parsed worker lock packages (pylock.toml)."""
    return tomllib.loads((CHAT / "pylock.toml").read_text(encoding="utf-8"))["packages"]


def apply_project_files_migrations(connection, migrations_dir) -> None:
    """Apply the project-files migrations 077 → 078 → 083 in order."""
    for name in (
        "077_project_files_text_byte_bound.sql",
        "078_project_files_doc_kind.sql",
        "083_project_files_hwpx.sql",
    ):
        connection.executescript((Path(migrations_dir) / name).read_text(encoding="utf-8"))


def html_refs(html: str) -> dict[str, set[str]]:
    """href/src attribute values per tag name, from served HTML text."""
    refs: dict[str, set[str]] = {}

    class _Refs(HTMLParser):
        def handle_starttag(self, tag, attrs):
            for name, value in attrs:
                if name in ("href", "src") and value is not None:
                    refs.setdefault(tag, set()).add(value)

        handle_startendtag = handle_starttag

    parser = _Refs()
    parser.feed(html)
    parser.close()
    return refs


def html_text(html: str) -> str:
    """The visible text of served HTML, tags stripped."""
    pieces: list[str] = []

    class _Text(HTMLParser):
        def handle_data(self, data):
            text = data.strip()
            if text:
                pieces.append(text)

    parser = _Text()
    parser.feed(html)
    parser.close()
    return "\n".join(pieces)
