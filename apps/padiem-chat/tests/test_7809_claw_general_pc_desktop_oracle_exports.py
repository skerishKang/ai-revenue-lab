"""#7809 10/13: Oracle Mesh entry must preserve its five public re-exports.

PC desktop refactors cannot silently change the Oracle dispatch entry seam.
This test imports only the registered modules; no PC command is dispatched.
"""
from __future__ import annotations

import importlib

import pytest

ORACLE_ENTRY_EXPORTS = (
    ("_parse_desktop_op_text", "oracle_mesh_desktop_ops"),
    ("dispatch_oracle_mesh_desktop_intent", "oracle_mesh_dispatch"),
    ("dispatch_oracle_mesh_command_intent", "oracle_mesh_dispatch"),
    ("dispatch_oracle_mesh_read_intent", "oracle_mesh_dispatch"),
    ("resolve_oracle_mesh_execution", "oracle_mesh_execution"),
)


@pytest.mark.parametrize(("name", "owner_module"), ORACLE_ENTRY_EXPORTS)
def test_oracle_mesh_entry_keeps_same_five_reexported_objects(
    name: str, owner_module: str,
) -> None:
    entry = importlib.import_module("app.oracle_mesh_read_return_routes")
    source = importlib.import_module(f"app.{owner_module}")
    assert getattr(entry, name) is getattr(source, name)
