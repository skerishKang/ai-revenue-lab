"""Parsed views for the #3933 first-turn grant contracts (#8060).

Raw migration/server/neighbour-app sources stay behind this helper (via the
shared ``claw_static`` readers). Contract tests receive parsed SQL facts, AST
assignment facts and file-set facts, and assert on those instead of pinning
shipped source spelling. No runtime file is changed.
"""
from __future__ import annotations

import ast
from pathlib import Path

from _support.claw_static import migration_source, server_source


_APP_DIR = Path(__file__).resolve().parents[2] / "app"
_REPO = Path(__file__).resolve().parents[4]
_MIGRATION = "043_claw_coding_conversation_grant.sql"


def grant_sql() -> str:
    """The additive grant migration, read only inside this helper."""
    return migration_source(_MIGRATION)


def migration_facts() -> dict:
    """Structural facts parsed from the additive migration source."""
    lowered = grant_sql().lower()
    return {
        "creates_grant_table": (
            "create table if not exists claw_coding_conversation_grant" in lowered
        ),
        "live_claim_where": "where state in ('reserved', 'active')" in lowered,
        "product_check": "check (product_id = 'b54-padiem-claw')" in lowered,
        "forbidden": {
            token for token in (
                "alter table", "drop table", "delete from",
                "create index claw_run_history", "references",
            ) if token in lowered
        },
    }


def _attribute_chain(node: ast.Attribute) -> str:
    if isinstance(node.value, ast.Name):
        return f"{node.value.id}.{node.attr}"
    if isinstance(node.value, ast.Attribute):
        return f"{_attribute_chain(node.value)}.{node.attr}"
    return node.attr


def attribute_assignments(module_name: str) -> set[tuple[str, str]]:
    """All ``a.b.c = value`` assignments in a server module, as parsed pairs."""
    source = server_source(module_name)
    result: set[tuple[str, str]] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Assign):
            continue
        value = " ".join((ast.get_source_segment(source, node.value) or "").split())
        for target in node.targets:
            if isinstance(target, ast.Attribute):
                result.add((_attribute_chain(target), value))
    return result


def app_files_containing(needle: str) -> list[str]:
    """Names of app/*.py modules whose source contains the given token."""
    return [
        path.name
        for path in sorted(_APP_DIR.glob("*.py"))
        if needle in path.read_text(encoding="utf-8")
    ]


def _imports_authority(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "claw_first_turn_authority" or module.endswith(
                ".claw_first_turn_authority"
            ):
                return True
            if module in {"", "app"} and any(
                alias.name == "claw_first_turn_authority" for alias in node.names
            ):
                return True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "claw_first_turn_authority" or alias.name.endswith(
                    ".claw_first_turn_authority"
                ):
                    return True
    return False


def authority_importers() -> list[str]:
    """App modules that import the first-turn authority (AST, not prose)."""
    return [
        path.name
        for path in sorted(_APP_DIR.glob("*.py"))
        if path.name != "claw_first_turn_authority.py"
        and _imports_authority(ast.parse(path.read_text(encoding="utf-8")))
    ]


def external_contains(parts: tuple[str, ...], needle: str) -> bool:
    """Whether a neighbour-app source file mentions the given token."""
    return needle in _REPO.joinpath(*parts).read_text(encoding="utf-8")
