"""공용 시험 준비 — 다중 도구 결과 저장소(마이그레이션·스토어 더미).

test_5015_multi_tool_result_storage가 들고 있던 접두(상수·D1 더블·_stage)를
여기 옮겨 시험끼리 import가 없게 한다(#8061).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _support.migrated_db_template import migrated_connection, fill_empty_connection
from types import SimpleNamespace

import pytest

from app import oracle_mesh_read_return_routes as routes
from app.claw_routes import claw_pending_result
from app.history import D1HistoryStore, HistoryError, HistoryForbidden, PRODUCT_SCOPE_CHAT
from app.claw_local_task_result_projection import result_message_id

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"

OWNER = "usr_" + "a" * 32
OTHER_OWNER = "usr_" + "b" * 32
RUN = "chat_pcq_" + "c" * 32
LEGACY_RUN = "run_" + "f" * 24
CONVERSATION = "chat_" + "d" * 32
WORKSPACE = "ws_" + "e" * 12
HASH = "a" * 64
ACCOUNT = "account-1"
CONNECTOR_WS = "connector-ws-1"
TENANT_WS = "tenant-ws-1"
DEVICE = "device-1"
NODE = "node-1"
SECRET = "deployment-channel-secret-value-261021"

LIST_CALL = "call_list_" + "1" * 20
READ_CALL = "call_read_" + "2" * 20
LIST_TEXT = '[{"Name":"notes.txt","Length":12}]'
READ_TEXT = "PADIEM FILE BODY\nEND_OF_FILE\n"


# ---------------------------------------------------------------------------
# D1 double over one SQLite connection
# ---------------------------------------------------------------------------


class _Statement:
    def __init__(self, db: "_DB", sql: str, values: tuple = ()) -> None:
        self._db = db
        self._sql = sql
        self._values = values

    def bind(self, *values):
        return _Statement(self._db, self._sql, values)

    async def run(self):
        cursor = self._db.connection.execute(self._sql, self._values)
        self._db.connection.commit()
        return {"results": [dict(r) for r in cursor.fetchall()],
                "success": True, "meta": {"changes": cursor.rowcount}}

    async def first(self):
        row = self._db.connection.execute(self._sql, self._values).fetchone()
        return dict(row) if row is not None else None

    async def all(self):
        rows = self._db.connection.execute(self._sql, self._values).fetchall()
        return [dict(row) for row in rows]


class _DB:
    """The D1 statement surface ``D1HistoryStore`` actually uses."""

    def __init__(self, connection):
        self.connection = connection

    def prepare(self, sql):
        return _Statement(self, sql)

    async def batch(self, statements):
        """One atomic D1 transaction, with the same result contract."""

        results = []
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            for statement in statements:
                cursor = self.connection.execute(statement._sql, statement._values)
                columns = [item[0] for item in cursor.description] if cursor.description else []
                rows = [dict(zip(columns, row)) for row in cursor.fetchall()] if columns else []
                if columns:
                    results.append({"results": rows})
                else:
                    written = cursor.rowcount if cursor.rowcount >= 0 else 0
                    results.append({"meta": {"rows_written": written}})
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        return results


def _database() -> sqlite3.Connection:
    connection = migrated_connection(":memory:", MIGRATIONS,
        check_same_thread=False, isolation_level="", row_factory=sqlite3.Row)
    for user in (OWNER, OTHER_OWNER):
        connection.execute(
            "INSERT INTO users (id,auth_provider,provider_subject,email,created_at,updated_at) "
            "VALUES (?,'google',?,'owner@example.test','2026-01-01','2026-01-01')",
            (user, "subject-" + user),
        )
    connection.execute(
        "INSERT INTO conversations (id,user_id,title,created_at,updated_at,product_scope) "
        "VALUES (?,?,'title','2026-01-01','2026-01-01',?)",
        (CONVERSATION, OWNER, PRODUCT_SCOPE_CHAT),
    )
    connection.commit()
    return connection


class _PrivateR2:
    """The private full-context bucket double; keys stay server-derived."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, payload, **_kwargs):
        self.objects[key] = bytes(payload)

    async def get(self, key: str):
        data = self.objects.get(key)
        if data is None:
            return None
        return SimpleNamespace(size=len(data), arrayBuffer=lambda: data)


def _store(connection: sqlite3.Connection) -> D1HistoryStore:
    return D1HistoryStore(_DB(connection), full_context_bucket=_PrivateR2())


def _stage_run(connection: sqlite3.Connection, *, run_id: str = RUN,
               action: str = "pc_files_query", status: str = "pending") -> None:
    connection.execute(
        "INSERT INTO claw_run_history (id,user_id,run_id,channel,action,title,status,"
        "created_at,updated_at,conversation_id,workspace_id) "
        "VALUES (?,?,?,'web',?,'title',?,'2026-10-21','2026-10-21',?,?)",
        ("rh_" + run_id[-8:], OWNER, run_id, action, status, CONVERSATION, WORKSPACE),
    )
    connection.commit()


def _run_row(connection: sqlite3.Connection, run_id: str = RUN) -> dict:
    row = connection.execute(
        "SELECT status, result_summary FROM claw_run_history WHERE run_id=?",
        (run_id,),
    ).fetchone()
    return dict(row)


def _messages(connection: sqlite3.Connection) -> list[dict]:
    return [
        dict(row) for row in connection.execute(
            "SELECT id, role, content FROM messages WHERE conversation_id=? "
            "ORDER BY sequence_number",
            (CONVERSATION,),
        ).fetchall()
    ]


def _dispatch_arguments(call_ref: str, *, suffix: str, command: str) -> dict:
    return {
        "user_id": OWNER, "run_id": RUN,
        "command_id": "oracle_mesh_cmd_" + suffix,
        "tool_request_ref": call_ref,
        "request_id": "oracle_mesh_req_" + suffix,
        "revision_ref": "oracle_mesh_rev_" + suffix,
        "evidence_ref": None,
        "request_fingerprint": HASH,
        "account_ref": ACCOUNT, "workspace_ref": CONNECTOR_WS,
        "device_id": DEVICE, "binding_ref": None, "node_ref": NODE,
        "root_ref": routes._COMMAND_ROOT_REF,
        "path_relative": routes._COMMAND_PATH_RELATIVE,
        "file_path": routes._COMMAND_FILE_SENTINEL,
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(minutes=10)
        ).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "kind": "command", "command_text": command,
        "tool_call_ref": call_ref,
    }


def _command_message_id(command_id: str, revision_ref: str) -> str:
    return result_message_id(
        conversation_id=CONVERSATION,
        command_id=command_id, revision_ref=revision_ref,
    )


def _stage_command(store, suffix: str, *, call_ref: str | None = None) -> str:
    """Stage one trusted tool call of the run and return its command id."""

    call_ref = call_ref or ("call_" + suffix + "_" + "9" * 16)
    asyncio.run(store.create_oracle_mesh_dispatch(
        **_dispatch_arguments(
            call_ref, suffix=suffix,
            command="Get-ChildItem -LiteralPath ." if suffix == "list"
            else "Get-Content -LiteralPath notes.txt",
        ),
    ))
    return "oracle_mesh_cmd_" + suffix


def _finish_command(connection, suffix: str, *, outcome: str = "done") -> None:
    """Close the command's dispatch, the way the result route does."""

    connection.execute(
        "UPDATE oracle_mesh_dispatch SET state=? "
        "WHERE user_id=? AND run_id=? AND command_id=?",
        (outcome, OWNER, RUN, "oracle_mesh_cmd_" + suffix),
    )
    connection.commit()


# ---------------------------------------------------------------------------
# The storage contract
# ---------------------------------------------------------------------------


def _pending_request(run_id: str, history_store):
    from starlette.requests import Request

    scope = {
        "type": "http", "method": "GET",
        "path": f"/api/claw/runs/{run_id}/pending-result",
        "path_params": {"run_id": run_id}, "headers": [],
    }
    request = Request(scope)
    request.scope["app"] = SimpleNamespace(
        state=SimpleNamespace(history_store=history_store),
    )
    return request
