"""#8359 E — the maintenance consent key comes from a server-owned record.

The deployment ownership map is deliberately not consulted here: production's
copy is stale, while a dispatch row pairs the consent key the human screen
used with the Mesh node under the owner and the exact connector scope.
"""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from app.d1_sqlite import SqliteD1
from app.history import D1HistoryStore

OWNER = "usr_fixture"
NODE = "node//fixture"
KEY = "connector_fixture"
ACCOUNT = "account_fixture"
WORKSPACE = "workspace_fixture"

COLUMNS = (
    "dispatch_id,user_id,run_id,command_id,tool_request_ref,request_id,revision_ref,"
    "request_fingerprint,account_ref,workspace_ref,device_id,node_ref,root_ref,"
    "path_relative,file_path,expires_at,created_at,state"
)


def _store(rows):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    sql = (Path(__file__).resolve().parents[1] / "migrations" / "047_oracle_mesh_dispatch.sql")
    conn.executescript(sql.read_text(encoding="utf-8"))
    for index, row in enumerate(rows):
        values = (
            f"dispatch-{index}", OWNER, f"run-{index}", f"cmd-{index}",
            f"tool-{index}", f"req-{index}", f"rev-{index}", f"fp-{index}",
            row["account_ref"], row["workspace_ref"], row["device_id"],
            row["node_ref"], "root-fixture", "fixture.txt", "C:/fixture.txt",
            "2030-01-01T00:00:00.000Z", f"2026-11-24T00:00:{index:02d}.000Z", "done",
        )
        placeholders = ",".join("?" for _ in values)
        conn.execute(f"INSERT INTO oracle_mesh_dispatch ({COLUMNS}) VALUES ({placeholders})", values)
    return conn, D1HistoryStore(SqliteD1(conn))


def _read(store, *, user_id=OWNER, node_ref=NODE,
          account_ref=ACCOUNT, workspace_ref=WORKSPACE):
    return asyncio.run(store.consent_key_for_owner_node(
        user_id=user_id, node_ref=node_ref,
        account_ref=account_ref, workspace_ref=workspace_ref))


def test_record_yields_the_consent_key_unchanged():
    conn, store = _store([{"account_ref": ACCOUNT, "workspace_ref": WORKSPACE,
                           "device_id": KEY, "node_ref": NODE}])
    try:
        assert _read(store) == (KEY, "observed")
    finally:
        conn.close()


def test_foreign_account_or_owner_is_refused():
    conn, store = _store([{"account_ref": ACCOUNT, "workspace_ref": WORKSPACE,
                           "device_id": KEY, "node_ref": NODE}])
    try:
        assert _read(store, account_ref="account_other")[1] == "consent_key_scope_mismatch"
        assert _read(store, workspace_ref="workspace_other")[1] == "consent_key_scope_mismatch"
        assert _read(store, user_id="usr_other")[1] == "consent_key_record_missing"
    finally:
        conn.close()


def test_no_record_keeps_the_closed_missing_code():
    conn, store = _store([])
    try:
        assert _read(store) == (None, "consent_key_record_missing")
    finally:
        conn.close()


def test_row_that_only_names_the_mesh_node_has_no_consent_key():
    conn, store = _store([{"account_ref": ACCOUNT, "workspace_ref": WORKSPACE,
                           "device_id": NODE, "node_ref": NODE}])
    try:
        assert _read(store) == (None, "consent_key_unpinned")
    finally:
        conn.close()


def test_competing_or_invalid_keys_fail_closed():
    conn, store = _store([
        {"account_ref": ACCOUNT, "workspace_ref": WORKSPACE,
         "device_id": KEY, "node_ref": NODE},
        {"account_ref": ACCOUNT, "workspace_ref": WORKSPACE,
         "device_id": "connector_other", "node_ref": NODE},
    ])
    try:
        assert _read(store) == (None, "consent_key_ambiguous")
    finally:
        conn.close()
    conn, store = _store([{"account_ref": ACCOUNT, "workspace_ref": WORKSPACE,
                           "device_id": "node/bad", "node_ref": NODE}])
    try:
        assert _read(store) == (None, "consent_key_invalid")
    finally:
        conn.close()


@pytest.mark.parametrize("kwargs", [
    {"user_id": ""}, {"node_ref": "node/bad"}, {"account_ref": ""}, {"workspace_ref": ""},
])
def test_invalid_request_has_its_own_code(kwargs):
    conn, store = _store([])
    try:
        assert _read(store, **kwargs) == (None, "consent_key_invalid_request")
    finally:
        conn.close()
