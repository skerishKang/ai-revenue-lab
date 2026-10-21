"""#5015 — one run may stage several trusted tool-call PC dispatches.

047 declared ``UNIQUE (user_id, run_id)`` while
``HistoryStore.create_oracle_mesh_dispatch`` keys a trusted file tool call by
``(user_id, run_id, tool_request_ref)``. A run that lists a directory and then
reads a file therefore found no row for the second call and the INSERT was
refused by the one-per-run constraint.

These guards run the real migration files and the real store SQL. The pre-062
schema must reproduce the refusal, 062 must keep every existing row (id, state,
nonce, result digest) byte-for-byte, and both dispatch scopes must stay
protected afterwards: one legacy command per run, one dispatch per trusted tool
call inside a run.
"""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import oracle_mesh_read_return_routes as routes
from app.history import D1HistoryStore, HistoryError, HistoryForbidden

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
FORWARD = "062_oracle_mesh_dispatch_tool_call_scope.sql"
USER = "usr_" + "a" * 32
OTHER_USER = "usr_" + "b" * 32
RUN = "chat_pcq_" + "c" * 32
CONVERSATION = "chat_" + "d" * 32
WORKSPACE = "ws_" + "e" * 12
HASH = "a" * 64
ROOT = "C:/Users/limone/AppData/Local/Padiem/MeshCentralTrial"
LIST_CALL = "call_list_" + "1" * 20
READ_CALL = "call_read_" + "2" * 20
LEGACY_REF = "oracle_mesh_tool_" + "3" * 32
OTHER_LEGACY_REF = "oracle_mesh_tool_" + "4" * 32

DISPATCH_COLUMNS = (
    "dispatch_id", "user_id", "run_id", "command_id", "tool_request_ref",
    "request_id", "revision_ref", "evidence_ref", "request_fingerprint",
    "account_ref", "workspace_ref", "device_id", "binding_ref", "node_ref",
    "root_ref", "path_relative", "file_path", "nonce_sha256", "state",
    "result_sha256", "result_bytes", "expires_at", "created_at", "kind",
    "command_text", "termination", "exit_code",
)


class _DB:
    """The minimal D1 statement surface ``D1HistoryStore`` actually uses."""

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


def _database(*, with_forward: bool) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    for path in sorted(MIGRATIONS.glob("*.sql")):
        if path.name == FORWARD and not with_forward:
            continue
        connection.executescript(path.read_text(encoding="utf-8"))
    for user in (USER, OTHER_USER):
        connection.execute(
            "INSERT INTO users (id,auth_provider,provider_subject,email,created_at,updated_at) "
            "VALUES (?,'google',?,'owner@example.test','2026-01-01','2026-01-01')",
            (user, "subject-" + user),
        )
    connection.execute(
        "INSERT INTO conversations (id,user_id,title,created_at,updated_at) "
        "VALUES (?,?,'title','2026-01-01','2026-01-01')",
        (CONVERSATION, USER),
    )
    connection.execute(
        "INSERT INTO claw_run_history (id,user_id,run_id,channel,action,title,status,"
        "created_at,updated_at,conversation_id,workspace_id) "
        "VALUES ('rh',?,?,'telegram','run','title','completed',"
        "'2026-01-01','2026-01-01',?,?)",
        (USER, RUN, CONVERSATION, WORKSPACE),
    )
    connection.commit()
    return connection


def _apply_forward(connection: sqlite3.Connection) -> None:
    connection.executescript((MIGRATIONS / FORWARD).read_text(encoding="utf-8"))
    connection.commit()


def _expires(*, minutes: int = 5) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")


def _tool_call_arguments(
    call_ref: str, *, command: str = "Get-ChildItem -LiteralPath x",
    device_id: str = "device-1", workspace_ref: str = "connector-ws-1",
) -> dict:
    suffix = call_ref[-4:]
    return {
        "user_id": USER, "run_id": RUN,
        "command_id": "oracle_mesh_cmd_" + suffix,
        "tool_request_ref": call_ref,
        "request_id": "oracle_mesh_req_" + suffix,
        "revision_ref": "oracle_mesh_rev_" + suffix,
        "evidence_ref": None,
        "request_fingerprint": HASH,
        "account_ref": "account-1", "workspace_ref": workspace_ref,
        "device_id": device_id, "binding_ref": None, "node_ref": "node-1",
        "root_ref": routes._COMMAND_ROOT_REF,
        "path_relative": routes._COMMAND_PATH_RELATIVE,
        "file_path": routes._COMMAND_FILE_SENTINEL,
        "expires_at": _expires(),
        "kind": "command", "command_text": command,
        "tool_call_ref": call_ref,
    }


def _legacy_arguments(*, tool_request_ref: str = LEGACY_REF, command: str = "whoami"):
    return {
        "user_id": USER, "run_id": RUN,
        "command_id": "oracle_mesh_cmd_legacy",
        "tool_request_ref": tool_request_ref,
        "request_id": "oracle_mesh_req_legacy",
        "revision_ref": "oracle_mesh_rev_legacy",
        "evidence_ref": None,
        "request_fingerprint": HASH,
        "account_ref": "account-1", "workspace_ref": "connector-ws-1",
        "device_id": "device-1", "binding_ref": None, "node_ref": "node-1",
        "root_ref": routes._COMMAND_ROOT_REF,
        "path_relative": routes._COMMAND_PATH_RELATIVE,
        "file_path": routes._COMMAND_FILE_SENTINEL,
        "expires_at": _expires(),
        "kind": "command", "command_text": command,
    }


def _insert_dispatch(connection: sqlite3.Connection, **overrides) -> dict:
    now = "2026-10-21T05:39:16.000Z"
    row = {
        "dispatch_id": "dsp_" + "1" * 32,
        "user_id": USER, "run_id": RUN,
        "command_id": "oracle_mesh_cmd_live",
        "tool_request_ref": LEGACY_REF,
        "request_id": "oracle_mesh_req_live",
        "revision_ref": "oracle_mesh_rev_live",
        "evidence_ref": None,
        "request_fingerprint": HASH,
        "account_ref": "account-1", "workspace_ref": "connector-ws-1",
        "device_id": "device-1", "binding_ref": None, "node_ref": "node-1",
        "root_ref": routes._COMMAND_ROOT_REF,
        "path_relative": routes._COMMAND_PATH_RELATIVE,
        "file_path": routes._COMMAND_FILE_SENTINEL,
        "nonce_sha256": "n" * 64,
        "state": "done",
        "result_sha256": "e" * 64,
        "result_bytes": 1515,
        "expires_at": _expires(),
        "created_at": now,
        "kind": "command",
        "command_text": "Get-ChildItem -LiteralPath x",
        "termination": "no_exit_code",
        "exit_code": None,
    }
    row.update(overrides)
    columns = [name for name in row if name != "tool_call_ref"]
    connection.execute(
        "INSERT INTO oracle_mesh_dispatch (" + ",".join(columns) + ") "
        "VALUES (" + ",".join("?" for _ in columns) + ")",
        tuple(row[name] for name in columns),
    )
    connection.commit()
    return row


def _store(connection: sqlite3.Connection) -> D1HistoryStore:
    return D1HistoryStore(_DB(connection))


def _row(connection: sqlite3.Connection, dispatch_id: str) -> dict:
    row = connection.execute(
        "SELECT * FROM oracle_mesh_dispatch WHERE dispatch_id=?", (dispatch_id,),
    ).fetchone()
    return dict(row)


def _count(connection: sqlite3.Connection) -> int:
    return connection.execute(
        "SELECT COUNT(*) FROM oracle_mesh_dispatch"
    ).fetchone()[0]


def test_pre_062_schema_refuses_the_second_call_of_one_run():
    """The confirmed production shape: the DB, not the lane, refuses row two."""
    connection = _database(with_forward=False)
    try:
        _insert_dispatch(connection, state="done", result_sha256="e" * 64)
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            connection.execute(
                "INSERT INTO oracle_mesh_dispatch (dispatch_id,user_id,run_id,command_id,"
                "tool_request_ref,request_id,revision_ref,evidence_ref,request_fingerprint,"
                "account_ref,workspace_ref,device_id,binding_ref,node_ref,root_ref,"
                "path_relative,file_path,nonce_sha256,state,result_sha256,result_bytes,"
                "expires_at,created_at,kind,command_text,termination,exit_code) "
                "VALUES ('dsp_second',?,?,?,'call_read_' || '2',?,'rev',NULL,?,'account-1',"
                "'connector-ws-1','device-1',NULL,'node-1',?,'command','command',NULL,"
                "'pending',NULL,NULL,?,'2026-10-21T05:40:00.000Z','read',NULL,NULL,NULL)",
                (
                    USER, RUN, "cmd_second", "req_second", HASH,
                    routes._COMMAND_ROOT_REF, _expires(),
                ),
            )
    finally:
        connection.close()


def test_new_store_refuses_to_stage_before_062_is_applied():
    """Deploy order: a Worker ahead of the migration writes no row at all."""
    connection = _database(with_forward=False)
    try:
        store = _store(connection)
        with pytest.raises(sqlite3.OperationalError, match="tool_call_ref"):
            asyncio.run(store.create_oracle_mesh_dispatch(
                **_tool_call_arguments(LIST_CALL),
            ))
        assert _count(connection) == 0
    finally:
        connection.close()


def test_forward_migration_preserves_every_existing_row():
    connection = _database(with_forward=False)
    try:
        _insert_dispatch(connection)
        before = _row(connection, "dsp_" + "1" * 32)
        assert before["state"] == "done"
        _apply_forward(connection)
        after = _row(connection, "dsp_" + "1" * 32)
        assert _count(connection) == 1
        for column in DISPATCH_COLUMNS:
            assert after[column] == before[column], column
        assert after["tool_call_ref"] is None
        assert after["result_sha256"] == "e" * 64 and after["result_bytes"] == 1515
        assert after["nonce_sha256"] == "n" * 64
        assert after["termination"] == "no_exit_code"
        index_names = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND tbl_name='oracle_mesh_dispatch'"
            ).fetchall()
        }
        assert {
            "idx_oracle_mesh_dispatch_state_expiry",
            "idx_oracle_mesh_dispatch_run_scope",
            "idx_oracle_mesh_dispatch_tool_call",
        } <= index_names
    finally:
        connection.close()


def test_one_run_stages_the_list_and_the_read_call():
    connection = _database(with_forward=True)
    try:
        store = _store(connection)
        listed = asyncio.run(store.create_oracle_mesh_dispatch(
            **_tool_call_arguments(LIST_CALL, command="Get-ChildItem -LiteralPath ."),
        ))
        read = asyncio.run(store.create_oracle_mesh_dispatch(
            **_tool_call_arguments(READ_CALL, command="Get-Content -LiteralPath notes.txt"),
        ))
        assert listed["dispatch_id"] != read["dispatch_id"]
        assert _count(connection) == 2
        assert _row(connection, listed["dispatch_id"])["tool_call_ref"] == LIST_CALL
        assert _row(connection, read["dispatch_id"])["tool_call_ref"] == READ_CALL
    finally:
        connection.close()


def test_the_same_tool_call_never_stages_twice():
    connection = _database(with_forward=True)
    try:
        store = _store(connection)
        arguments = _tool_call_arguments(LIST_CALL)
        first = asyncio.run(store.create_oracle_mesh_dispatch(**arguments))
        replay = asyncio.run(store.create_oracle_mesh_dispatch(**arguments))
        assert replay["dispatch_id"] == first["dispatch_id"]
        assert _count(connection) == 1
        connection.execute(
            "UPDATE oracle_mesh_dispatch SET state='done', result_sha256=?, result_bytes=1515 "
            "WHERE dispatch_id=?",
            ("e" * 64, first["dispatch_id"]),
        )
        connection.commit()
        with pytest.raises(HistoryError, match="already executed"):
            asyncio.run(store.create_oracle_mesh_dispatch(**arguments))
        assert _count(connection) == 1
    finally:
        connection.close()


def test_legacy_single_command_keeps_its_one_per_run_guard():
    connection = _database(with_forward=True)
    try:
        store = _store(connection)
        first = asyncio.run(store.create_oracle_mesh_dispatch(**_legacy_arguments()))
        assert _row(connection, first["dispatch_id"])["tool_call_ref"] is None
        # The legacy lane mints a fresh random tool_request_ref per attempt;
        # the run scope is what must still refuse the second staging.
        with pytest.raises(HistoryError, match="already dispatched"):
            asyncio.run(store.create_oracle_mesh_dispatch(
                **_legacy_arguments(tool_request_ref=OTHER_LEGACY_REF),
            ))
        assert _count(connection) == 1
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            _insert_dispatch(
                connection, dispatch_id="dsp_legacy_second",
                tool_request_ref=OTHER_LEGACY_REF, state="pending",
                nonce_sha256=None, result_sha256=None, result_bytes=None,
            )
    finally:
        connection.close()


def test_failed_and_uncertain_dispatches_are_never_restaged():
    connection = _database(with_forward=True)
    try:
        store = _store(connection)
        failed = asyncio.run(store.create_oracle_mesh_dispatch(**_legacy_arguments()))
        connection.execute(
            "UPDATE oracle_mesh_dispatch SET state='failed', termination='no_reply', "
            "result_sha256=?, result_bytes=19 WHERE dispatch_id=?",
            ("f" * 64, failed["dispatch_id"]),
        )
        connection.commit()
        with pytest.raises(HistoryError, match="already executed"):
            asyncio.run(store.create_oracle_mesh_dispatch(**_legacy_arguments()))
        assert _count(connection) == 1

        # A command that was handed to the executor and then expired may
        # already have run: no restart may execute it again.
        connection.execute(
            "UPDATE oracle_mesh_dispatch SET state='pending', termination=NULL, "
            "nonce_sha256=?, expires_at='2026-10-21T00:00:00.000Z' WHERE dispatch_id=?",
            ("n" * 64, failed["dispatch_id"]),
        )
        connection.commit()
        with pytest.raises(HistoryError, match="execution is uncertain"):
            asyncio.run(store.create_oracle_mesh_dispatch(**_legacy_arguments()))
        assert _row(connection, failed["dispatch_id"])["state"] == "pending"
    finally:
        connection.close()


def test_uncertain_tool_call_is_not_restaged_inside_its_run():
    connection = _database(with_forward=True)
    try:
        store = _store(connection)
        arguments = _tool_call_arguments(LIST_CALL)
        first = asyncio.run(store.create_oracle_mesh_dispatch(**arguments))
        connection.execute(
            "UPDATE oracle_mesh_dispatch SET nonce_sha256=?, "
            "expires_at='2026-10-21T00:00:00.000Z' WHERE dispatch_id=?",
            ("n" * 64, first["dispatch_id"]),
        )
        connection.commit()
        with pytest.raises(HistoryError, match="execution is uncertain"):
            asyncio.run(store.create_oracle_mesh_dispatch(**arguments))
        assert _count(connection) == 1
    finally:
        connection.close()


def test_owner_pc_and_workspace_are_never_mixed():
    connection = _database(with_forward=True)
    try:
        store = _store(connection)
        arguments = _tool_call_arguments(LIST_CALL)
        staged = asyncio.run(store.create_oracle_mesh_dispatch(**arguments))
        # Another account can never borrow the owner's run.
        with pytest.raises(HistoryForbidden):
            asyncio.run(store.create_oracle_mesh_dispatch(
                **{**arguments, "user_id": OTHER_USER},
            ))
        # The same trusted call on a different PC or workspace is a different
        # request, never a silent retarget of the staged dispatch.
        for overrides in (
            {"device_id": "device-2"}, {"workspace_ref": "connector-ws-2"},
        ):
            with pytest.raises(HistoryError, match="already dispatched"):
                asyncio.run(store.create_oracle_mesh_dispatch(
                    **{**arguments, **overrides},
                ))
        row = _row(connection, staged["dispatch_id"])
        assert row["device_id"] == "device-1"
        assert row["workspace_ref"] == "connector-ws-1"
        assert _count(connection) == 1
    finally:
        connection.close()


def _race(store: D1HistoryStore, winner: dict) -> dict:
    """Let a competing request INSERT between this request's read and INSERT."""
    real_first = store._first
    raced = {"armed": True}

    async def first(sql, *values):
        if raced["armed"] and "FROM oracle_mesh_dispatch" in sql:
            raced["armed"] = False
            await store.create_oracle_mesh_dispatch(**winner)
            return None
        return await real_first(sql, *values)

    store._first = first
    return raced


def test_concurrent_staging_of_one_tool_call_creates_one_row():
    connection = _database(with_forward=True)
    try:
        store = _store(connection)
        arguments = _tool_call_arguments(LIST_CALL)
        raced = _race(store, arguments)
        outcome = asyncio.run(store.create_oracle_mesh_dispatch(**arguments))
        assert not raced["armed"]
        assert _count(connection) == 1
        assert outcome["dispatch_id"] == _row(
            connection, outcome["dispatch_id"],
        )["dispatch_id"]
        assert outcome["state"] == "pending"
    finally:
        connection.close()


def test_concurrent_staging_never_borrows_a_different_call():
    connection = _database(with_forward=True)
    try:
        store = _store(connection)
        arguments = _tool_call_arguments(LIST_CALL)
        _race(store, {**arguments, "device_id": "device-2"})
        with pytest.raises(HistoryError, match="already dispatched"):
            asyncio.run(store.create_oracle_mesh_dispatch(**arguments))
        assert _count(connection) == 1
        assert connection.execute(
            "SELECT device_id FROM oracle_mesh_dispatch"
        ).fetchone()[0] == "device-2"
    finally:
        connection.close()


def test_concurrent_legacy_staging_creates_one_row():
    connection = _database(with_forward=True)
    try:
        store = _store(connection)
        _race(store, _legacy_arguments())
        with pytest.raises(HistoryError, match="already dispatched"):
            asyncio.run(store.create_oracle_mesh_dispatch(
                **_legacy_arguments(tool_request_ref=OTHER_LEGACY_REF),
            ))
        assert _count(connection) == 1
    finally:
        connection.close()
