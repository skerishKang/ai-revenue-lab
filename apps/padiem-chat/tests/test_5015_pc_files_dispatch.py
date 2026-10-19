"""#5015/#4976 — server-side PC file tools: scope, command, dispatch keying.

These tests exercise the real route helpers and the real
``HistoryStore.create_oracle_mesh_dispatch`` SQL against an in-memory SQLite
database; no live Mesh, Identity or Broker is involved.
"""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import oracle_mesh_read_return_routes as routes
from app.history import D1HistoryStore, HistoryError

ROOT = "C:/Users/limone/AppData/Local/Padiem/MeshCentralTrial"
OWNER = "usr_" + "a" * 32
RUN = "run_" + "b" * 24


def test_approved_root_is_the_mapped_file_parent():
    assert routes._pc_files_approved_root(ROOT + "/trial.txt") == ROOT
    assert routes._pc_files_approved_root(ROOT + "\\trial.txt") == ROOT
    assert routes._pc_files_approved_root("C:/trial.txt") is None
    assert routes._pc_files_approved_root("trial.txt") is None
    assert routes._pc_files_approved_root("C:") is None


def test_relative_path_refuses_traversal_and_absolute_forms():
    assert routes._pc_files_relative_path(".") == ""
    assert routes._pc_files_relative_path("notes.txt") == "notes.txt"
    assert routes._pc_files_relative_path("sub/notes.txt") == "sub/notes.txt"
    assert routes._pc_files_relative_path("sub\\notes.txt") == "sub/notes.txt"
    for bad in (
        "../secret.txt", "..\\secret.txt", "/etc/passwd", "C:/Windows/win.ini",
        "C:notes.txt", "a/../b", "a//b", "a/./b", "a\x00b",
    ):
        assert routes._pc_files_relative_path(bad) is None, bad


def test_file_commands_are_server_built_literals():
    list_command = routes._pc_files_command(
        op="list", root=ROOT, relative=".", limit=200,
    )
    assert "Get-ChildItem -LiteralPath $folder" in list_command
    assert "ConvertTo-Json" in list_command
    assert "relative_path" in list_command
    assert "\r" not in list_command and "\n" not in list_command

    read_command = routes._pc_files_command(
        op="read", root=ROOT, relative="notes.txt", limit=200,
    )
    assert "[IO.File]::ReadAllText" in read_command
    assert routes.PC_FILES_ERROR_PREFIX + "read_failed" in read_command
    assert ROOT + "/notes.txt" in read_command

    quoted = routes._pc_files_command(
        op="read", root=ROOT, relative="it's.txt", limit=200,
    )
    assert "it''s.txt" in quoted


class _DB:
    def __init__(self, connection):
        self.connection = connection

    def prepare(self, sql):
        connection = self.connection

        class _Statement:
            def __init__(self):
                self.sql = sql
                self.values = ()

            def bind(self, *values):
                self.values = values
                return self

            async def first(self):
                row = connection.execute(self.sql, self.values).fetchone()
                return dict(row) if row is not None else None

            async def run(self):
                cursor = connection.execute(self.sql, self.values)
                connection.commit()
                return SimpleNamespace(
                    results=[dict(row) for row in cursor.fetchall()],
                    meta={"changes": cursor.rowcount},
                )

        return _Statement()


def _store():
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.executescript(
        "CREATE TABLE claw_run_history (id TEXT PRIMARY KEY, run_id TEXT, user_id TEXT);"
        "CREATE TABLE oracle_mesh_dispatch ("
        "dispatch_id TEXT PRIMARY KEY, user_id TEXT, run_id TEXT, command_id TEXT, "
        "tool_request_ref TEXT, request_id TEXT, revision_ref TEXT, evidence_ref TEXT, "
        "request_fingerprint TEXT, account_ref TEXT, workspace_ref TEXT, device_id TEXT, "
        "binding_ref TEXT, node_ref TEXT, root_ref TEXT, path_relative TEXT, file_path TEXT, "
        "kind TEXT, command_text TEXT, nonce_sha256 TEXT, state TEXT, expires_at TEXT, "
        "created_at TEXT);"
    )
    connection.execute(
        "INSERT INTO claw_run_history VALUES (?,?,?)", ("row-1", RUN, OWNER),
    )
    connection.commit()
    return D1HistoryStore(_DB(connection)), connection


def _dispatch_arguments(suffix: str, command: str) -> dict:
    return {
        "user_id": OWNER, "run_id": RUN,
        "command_id": "oracle_mesh_cmd_" + suffix,
        "tool_request_ref": "call-" + suffix,
        "request_id": "oracle_mesh_req_" + suffix,
        "revision_ref": "oracle_mesh_rev_" + suffix,
        "evidence_ref": None,
        "request_fingerprint": "f" * 64,
        "account_ref": "account-1", "workspace_ref": "connector-ws-1",
        "device_id": "device-1", "binding_ref": None, "node_ref": "node-1",
        "root_ref": routes._COMMAND_ROOT_REF,
        "path_relative": routes._COMMAND_PATH_RELATIVE,
        "file_path": routes._COMMAND_FILE_SENTINEL,
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(minutes=5)
        ).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "kind": "command", "command_text": command,
        "tool_call_ref": "call-" + suffix,
    }


def test_two_tool_calls_in_one_run_stage_two_dispatches():
    store, connection = _store()
    try:
        first_args = _dispatch_arguments("a" * 32, "Get-ChildItem -LiteralPath x")
        first = asyncio.run(store.create_oracle_mesh_dispatch(**first_args))
        second = asyncio.run(store.create_oracle_mesh_dispatch(
            **_dispatch_arguments("b" * 32, "Get-Content -LiteralPath y"),
        ))
        assert first["dispatch_id"] != second["dispatch_id"]
        rows = connection.execute(
            "SELECT dispatch_id, tool_request_ref FROM oracle_mesh_dispatch ORDER BY rowid"
        ).fetchall()
        assert len(rows) == 2
        # An exact replay of the still-pending first call returns that row.
        replay = asyncio.run(store.create_oracle_mesh_dispatch(**first_args))
        assert replay["dispatch_id"] == first["dispatch_id"]
        assert len(connection.execute(
            "SELECT dispatch_id FROM oracle_mesh_dispatch"
        ).fetchall()) == 2
        # A terminal tool call refuses a second execution of the same call.
        connection.execute(
            "UPDATE oracle_mesh_dispatch SET state='done' WHERE dispatch_id=?",
            (first["dispatch_id"],),
        )
        connection.commit()
        with pytest.raises(HistoryError, match="already executed"):
            asyncio.run(store.create_oracle_mesh_dispatch(**first_args))
    finally:
        connection.close()


def test_tool_call_ref_must_be_bounded():
    store, connection = _store()
    try:
        arguments = _dispatch_arguments("c" * 32, "Get-ChildItem")
        arguments["tool_call_ref"] = "bad ref with spaces"
        with pytest.raises(HistoryError, match="tool_call_ref"):
            asyncio.run(store.create_oracle_mesh_dispatch(**arguments))
    finally:
        connection.close()
