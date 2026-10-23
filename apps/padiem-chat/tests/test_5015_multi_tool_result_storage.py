"""#5015 — one PC turn may store several tool-call results in the same run.

The confirmed production failure was a run whose first command (the folder
listing) had already sealed the run row, so the second command (the file read)
could not store its own result: the run-level single terminal refused the
second outcome, the dispatch was parked as ``store_failed``, the failure never
reached the conversation, and the run still read as completed.

These guards run the real migration files, the real store SQL and the real
result route. They prove:

* every command of a multi-tool-call run stores its own result;
* an individual command completion never seals the run — that stays the run
  owner's own decision;
* a failed command is stored and keeps the run failed, never completed;
* the identical resend of one command result is inert and a contradictory one
  is refused;
* the legacy single-command lane keeps its single terminal exactly;
* the canonical ``chat_pcq_`` run resolves through the pending-result route
  under the unchanged owner check.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import oracle_mesh_read_return_routes as routes
from app.claw_routes import claw_pending_result
from app.history import D1HistoryStore, HistoryError, HistoryForbidden, PRODUCT_SCOPE_CHAT
from app.claw_local_task_result_projection import result_message_id

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"

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
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    for path in sorted(MIGRATIONS.glob("*.sql")):
        connection.executescript(path.read_text(encoding="utf-8"))
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


def test_every_command_of_one_run_stores_its_own_result():
    """The list and the read of one turn are both durable, side by side."""
    connection = _database()
    try:
        _stage_run(connection)
        store = _store(connection)
        _stage_command(store, "list")
        _stage_command(store, "read")
        list_id = _command_message_id("oracle_mesh_cmd_list", "oracle_mesh_rev_list")
        read_id = _command_message_id("oracle_mesh_cmd_read", "oracle_mesh_rev_read")

        assert asyncio.run(store.append_local_task_result(
            user_id=OWNER, run_id=RUN, message_id=list_id,
            command_scope="oracle_mesh_cmd_list",
            summary="no_exit_code", content="listing body", status="completed",
        )) is True
        assert asyncio.run(store.append_local_task_result(
            user_id=OWNER, run_id=RUN, message_id=read_id,
            command_scope="oracle_mesh_cmd_read",
            summary="no_exit_code", content="file body", status="completed",
        )) is True

        bodies = [row["content"] for row in _messages(connection)]
        assert bodies == ["listing body", "file body"]
        # The aggregate carries both command outcomes, in order.
        assert _run_row(connection)["result_summary"] == "no_exit_code"
    finally:
        connection.close()


def test_an_individual_command_completion_never_seals_the_run():
    """The first command's success is not the whole work's completion."""
    connection = _database()
    try:
        _stage_run(connection)
        store = _store(connection)
        _stage_command(store, "list")
        asyncio.run(store.append_local_task_result(
            user_id=OWNER, run_id=RUN,
            message_id=_command_message_id("oracle_mesh_cmd_list", "oracle_mesh_rev_list"),
            command_scope="oracle_mesh_cmd_list",
            summary="no_exit_code", content="listing body", status="completed",
        ))
        row = _run_row(connection)
        assert row["status"] == "running", row
        assert row["status"] != "completed"
    finally:
        connection.close()


def test_the_run_owner_seals_the_overall_completion():
    """Only the run owner may seal the aggregate, and the seal is terminal."""
    connection = _database()
    try:
        _stage_run(connection)
        store = _store(connection)
        for suffix in ("list", "read"):
            _stage_command(store, suffix)
            asyncio.run(store.append_local_task_result(
                user_id=OWNER, run_id=RUN,
                message_id=_command_message_id(
                    "oracle_mesh_cmd_" + suffix, "oracle_mesh_rev_" + suffix,
                ),
                command_scope="oracle_mesh_cmd_" + suffix,
                summary="no_exit_code", content=suffix + " body", status="completed",
            ))
            _finish_command(connection, suffix)
        assert asyncio.run(store.seal_run_terminal(
            user_id=OWNER, run_id=RUN, message_id=RUN + "_final",
            summary="no_exit_code", content="the composed answer", status="completed",
        )) is True
        assert _run_row(connection)["status"] == "completed"
        assert "the composed answer" in [
            row["content"] for row in _messages(connection)
        ]
        # The first terminal of a completed run is never rewritten.
        assert asyncio.run(store.seal_run_terminal(
            user_id=OWNER, run_id=RUN, message_id=RUN + "_final",
            summary="no_exit_code", content="another answer", status="completed",
        )) is False
        assert _run_row(connection)["status"] == "completed"
    finally:
        connection.close()


def test_a_failed_command_is_stored_and_keeps_the_run_failed():
    """The read that never answered is stored, and the run is not a success."""
    connection = _database()
    try:
        _stage_run(connection)
        store = _store(connection)
        _stage_command(store, "list")
        _stage_command(store, "read")
        asyncio.run(store.append_local_task_result(
            user_id=OWNER, run_id=RUN,
            message_id=_command_message_id("oracle_mesh_cmd_list", "oracle_mesh_rev_list"),
            command_scope="oracle_mesh_cmd_list",
            summary="no_exit_code", content="listing body", status="completed",
        ))
        _finish_command(connection, "list")
        assert asyncio.run(store.append_local_task_result(
            user_id=OWNER, run_id=RUN,
            message_id=_command_message_id("oracle_mesh_cmd_read", "oracle_mesh_rev_read"),
            command_scope="oracle_mesh_cmd_read",
            summary="no_reply", content="the read never answered", status="failed",
        )) is True
        _finish_command(connection, "read", outcome="failed")
        row = _run_row(connection)
        assert row["status"] == "failed", row
        assert "the read never answered" in [
            message["content"] for message in _messages(connection)
        ]
        # A run that carries a failed command can never be sealed completed.
        with pytest.raises(HistoryError, match="failed command"):
            asyncio.run(store.seal_run_terminal(
                user_id=OWNER, run_id=RUN, message_id=RUN + "_final",
                summary="no_reply", content="the composed answer", status="completed",
            ))
        assert _run_row(connection)["status"] == "failed"
    finally:
        connection.close()


def test_a_pending_command_blocks_the_completed_seal():
    """The run cannot read as completed while one command is still open."""
    connection = _database()
    try:
        _stage_run(connection)
        store = _store(connection)
        _stage_command(store, "list")
        asyncio.run(store.append_local_task_result(
            user_id=OWNER, run_id=RUN,
            message_id=_command_message_id("oracle_mesh_cmd_list", "oracle_mesh_rev_list"),
            command_scope="oracle_mesh_cmd_list",
            summary="no_exit_code", content="listing body", status="completed",
        ))
        _finish_command(connection, "list")
        # The read command was staged and is still open.
        staged = asyncio.run(store.create_oracle_mesh_dispatch(
            **_dispatch_arguments(READ_CALL, suffix="read", command="Get-Content"),
        ))
        assert staged["state"] == "pending"
        with pytest.raises(HistoryError, match="without a terminal result"):
            asyncio.run(store.seal_run_terminal(
                user_id=OWNER, run_id=RUN, message_id=RUN + "_final",
                summary="no_exit_code", content="the composed answer", status="completed",
            ))
        assert _run_row(connection)["status"] == "running"
    finally:
        connection.close()


def test_the_identical_command_resend_is_inert():
    """An exact retry adds no second message and changes no state."""
    connection = _database()
    try:
        _stage_run(connection)
        store = _store(connection)
        _stage_command(store, "list")
        message_id = _command_message_id("oracle_mesh_cmd_list", "oracle_mesh_rev_list")
        first = asyncio.run(store.append_local_task_result(
            user_id=OWNER, run_id=RUN, message_id=message_id,
            command_scope="oracle_mesh_cmd_list",
            summary="no_exit_code", content="listing body", status="completed",
        ))
        repeated = asyncio.run(store.append_local_task_result(
            user_id=OWNER, run_id=RUN, message_id=message_id,
            command_scope="oracle_mesh_cmd_list",
            summary="no_exit_code", content="listing body", status="completed",
        ))
        assert first is True
        assert repeated is False
        assert len(_messages(connection)) == 1
        assert _run_row(connection)["status"] == "running"
    finally:
        connection.close()


def test_a_contradictory_command_resend_is_refused():
    """One command can never carry two different terminal outcomes."""
    connection = _database()
    try:
        _stage_run(connection)
        store = _store(connection)
        _stage_command(store, "list")
        message_id = _command_message_id("oracle_mesh_cmd_list", "oracle_mesh_rev_list")
        asyncio.run(store.append_local_task_result(
            user_id=OWNER, run_id=RUN, message_id=message_id,
            command_scope="oracle_mesh_cmd_list",
            summary="no_exit_code", content="listing body", status="completed",
        ))
        with pytest.raises(HistoryError, match="different terminal result"):
            asyncio.run(store.append_local_task_result(
                user_id=OWNER, run_id=RUN, message_id=message_id,
                command_scope="oracle_mesh_cmd_list",
                summary="no_exit_code", content="a different body", status="completed",
            ))
        assert [row["content"] for row in _messages(connection)] == ["listing body"]
    finally:
        connection.close()


def test_another_owner_can_never_append_to_a_run():
    connection = _database()
    try:
        _stage_run(connection)
        store = _store(connection)
        _stage_command(store, "list")
        with pytest.raises(HistoryForbidden):
            asyncio.run(store.append_local_task_result(
                user_id=OTHER_OWNER, run_id=RUN,
                message_id=_command_message_id("oracle_mesh_cmd_list", "oracle_mesh_rev_list"),
                command_scope="oracle_mesh_cmd_list",
                summary="no_exit_code", content="foreign body", status="completed",
            ))
        assert _messages(connection) == []
    finally:
        connection.close()


def test_the_legacy_single_command_lane_keeps_its_single_terminal():
    """A run without a command scope is unchanged: one terminal, one outcome."""
    connection = _database()
    try:
        _stage_run(connection, run_id=LEGACY_RUN, action="pc_drive_query")
        store = _store(connection)
        assert asyncio.run(store.append_local_task_result(
            user_id=OWNER, run_id=LEGACY_RUN, message_id="msg_" + "1" * 32,
            summary="no_exit_code", content="one body", status="completed",
        )) is True
        row = _run_row(connection, LEGACY_RUN)
        assert row["status"] == "completed"
        assert row["result_summary"] == "no_exit_code"
        # The single terminal of the legacy lane is never rewritten.
        with pytest.raises(HistoryError, match="different terminal result"):
            asyncio.run(store.append_local_task_result(
                user_id=OWNER, run_id=LEGACY_RUN, message_id="msg_" + "2" * 32,
                summary="no_reply", content="another body", status="failed",
            ))
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# The real result route
# ---------------------------------------------------------------------------


class _Request:
    def __init__(self, data, state, *, secret: str = SECRET):
        self.app = SimpleNamespace(state=state)
        raw = json.dumps(data).encode("utf-8")
        self.headers = {
            "content-type": "application/json",
            "content-length": str(len(raw)),
            routes.ORACLE_MESH_CHANNEL_HEADER: secret,
        }
        self._data = raw

    async def body(self):
        return self._data


def _call(handler, request):
    response = asyncio.run(handler(request))
    return response.status_code, json.loads(response.body), response.headers


def _state(history_store, *, identity=None):
    return SimpleNamespace(
        oracle_mesh_return_source=routes.build_oracle_mesh_return_source(
            [{
                "account_ref": ACCOUNT, "device_id": DEVICE, "node_ref": NODE,
                "root_ref": "meshcentral_private_trial",
                "path_relative": "meshcentral-padiem-trial.txt",
                "file_path": "C:/meshcentral-padiem-trial.txt",
                "command_exec": True,
            }],
            SECRET, routes.EXECUTION_MODE_MESH,
        ),
        control_plane_identity_authority=identity,
        history_store=history_store,
    )


def _setup_route(monkeypatch, *, owner: str = OWNER):
    async def _verified(request):
        del request
        return SimpleNamespace(session_id="session.canonical.owner.1"), None

    async def _workspace(request, uid):
        del request, uid
        return TENANT_WS

    monkeypatch.setattr(routes, "current_user_id", lambda request: owner)
    monkeypatch.setattr(routes, "_verified_owner_request", _verified)
    monkeypatch.setattr(routes, "_resolve_memory_workspace", _workspace)


def _result_body(dispatch_id: str, nonce: str, text: str, **overrides) -> dict:
    raw = text.encode("utf-8")
    payload = {
        "dispatch_id": dispatch_id, "nonce": nonce,
        "termination": "no_exit_code", "exit_code": None,
        "content_utf8": text, "content_sha256": hashlib.sha256(raw).hexdigest(),
        "content_bytes": len(raw),
    }
    payload.update(overrides)
    return payload


def _stage_and_claim(store, call_ref: str, *, suffix: str, command: str,
                      nonce: str) -> str:
    """Stage one trusted tool call and hand it to the executor."""

    staged = asyncio.run(store.create_oracle_mesh_dispatch(
        **_dispatch_arguments(call_ref, suffix=suffix, command=command),
    ))
    claimed = asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=staged["dispatch_id"],
        nonce_sha256=hashlib.sha256(nonce.encode("utf-8")).hexdigest(),
    ))
    assert claimed is True
    return staged["dispatch_id"]


def test_the_real_result_route_stores_both_commands_of_one_run(monkeypatch):
    """The confirmed production shape, through the real route and store."""
    _setup_route(monkeypatch)
    connection = _database()
    try:
        _stage_run(connection)
        store = _store(connection)
        list_nonce = "nonce-list-5015"
        read_nonce = "nonce-read-5015"
        list_dispatch = _stage_and_claim(
            store, LIST_CALL, suffix="list",
            command="Get-ChildItem -LiteralPath .", nonce=list_nonce,
        )
        read_dispatch = _stage_and_claim(
            store, READ_CALL, suffix="read",
            command="Get-Content -LiteralPath notes.txt", nonce=read_nonce,
        )

        status, body, _ = _call(routes.oracle_mesh_read_result,
                                _Request(
                                    _result_body(list_dispatch, list_nonce, LIST_TEXT),
                                    _state(store),
                                ))
        assert status == 200, body
        assert body["appended"] is True
        # The first command never seals the run: the work is still going.
        assert _run_row(connection)["status"] == "running"

        # The second command answers with no reply at all: a failure.
        status, body, _ = _call(routes.oracle_mesh_read_result,
                                _Request(
                                    _result_body(read_dispatch, read_nonce, "", termination="no_reply"),
                                    _state(store),
                                ))
        assert status == 200, body
        assert body["status"] == "failed"
        row = _run_row(connection)
        assert row["status"] == "failed", row
        assert row["status"] != "completed"
        # Both command results reached the conversation.
        contents = [message["content"] for message in _messages(connection)]
        assert len(contents) == 2, contents
        assert any("no_reply" in content or "답" in content for content in contents)
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# The lane that owns the run
# ---------------------------------------------------------------------------


def _lane_request():
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))


def test_the_lane_seals_the_multi_command_run():
    """The lane's final answer is the run's overall completion."""
    from app import chat_pc_drive

    connection = _database()
    try:
        _stage_run(connection)
        store = _store(connection)
        for suffix in ("list", "read"):
            _stage_command(store, suffix)
            asyncio.run(store.append_local_task_result(
                user_id=OWNER, run_id=RUN,
                message_id=_command_message_id(
                    "oracle_mesh_cmd_" + suffix, "oracle_mesh_rev_" + suffix,
                ),
                command_scope="oracle_mesh_cmd_" + suffix,
                summary="no_exit_code", content=suffix + " body", status="completed",
            ))
            _finish_command(connection, suffix)
        sealed = asyncio.run(chat_pc_drive._append_lane_answer(
            _lane_request(), store, uid=OWNER, run_id=RUN,
            content="the composed answer",
        ))
        assert sealed is True
        assert _run_row(connection)["status"] == "completed"
        assert any(
            row["id"] == RUN + "_final" for row in _messages(connection)
        )
    finally:
        connection.close()


def test_the_lane_notice_keeps_a_failed_run_failed():
    """A failed command is never turned into an overall success."""
    from app import chat_pc_drive

    connection = _database()
    try:
        _stage_run(connection)
        store = _store(connection)
        _stage_command(store, "read")
        asyncio.run(store.append_local_task_result(
            user_id=OWNER, run_id=RUN,
            message_id=_command_message_id("oracle_mesh_cmd_read", "oracle_mesh_rev_read"),
            command_scope="oracle_mesh_cmd_read",
            summary="no_reply", content="the read never answered", status="failed",
        ))
        _finish_command(connection, "read", outcome="failed")
        saved = asyncio.run(chat_pc_drive._append_lane_notice(
            _lane_request(), store, uid=OWNER, run_id=RUN,
            content="PC 파일 작업을 완료하지 못했습니다.", status="failed",
        ))
        assert saved is True
        row = _run_row(connection)
        assert row["status"] == "failed", row
        assert any(
            row["id"] == RUN + "_notice" for row in _messages(connection)
        )
    finally:
        connection.close()


def test_a_late_command_result_never_reopens_a_completed_run():
    """The first terminal of a completed run is never rewritten."""
    connection = _database()
    try:
        _stage_run(connection)
        store = _store(connection)
        _stage_command(store, "list")
        asyncio.run(store.append_local_task_result(
            user_id=OWNER, run_id=RUN,
            message_id=_command_message_id("oracle_mesh_cmd_list", "oracle_mesh_rev_list"),
            command_scope="oracle_mesh_cmd_list",
            summary="no_exit_code", content="listing body", status="completed",
        ))
        _finish_command(connection, "list")
        asyncio.run(store.seal_run_terminal(
            user_id=OWNER, run_id=RUN, message_id=RUN + "_final",
            summary="no_exit_code", content="the composed answer", status="completed",
        ))
        _stage_command(store, "late")
        asyncio.run(store.append_local_task_result(
            user_id=OWNER, run_id=RUN,
            message_id=_command_message_id("oracle_mesh_cmd_late", "oracle_mesh_rev_late"),
            command_scope="oracle_mesh_cmd_late",
            summary="no_exit_code", content="a late body", status="completed",
        ))
        assert _run_row(connection)["status"] == "completed"
    finally:
        connection.close()


def _read_dispatch_arguments(call_ref: str, *, suffix: str) -> dict:
    """One trusted file read row on the same kind=read lane the route stages."""

    arguments = _dispatch_arguments(call_ref, suffix=suffix, command="")
    arguments.update({
        "kind": "read", "command_text": None,
        "root_ref": routes._PC_FILES_READ_ROOT_REF,
        "path_relative": "notes.txt",
        "file_path": r"C:\Users\limone\AppData\Local\PADIEM\MeshCentralTrial\notes.txt",
    })
    return arguments


def _stage_read(store, suffix: str, *, call_ref: str) -> str:
    asyncio.run(store.create_oracle_mesh_dispatch(
        **_read_dispatch_arguments(call_ref, suffix=suffix),
    ))
    return "oracle_mesh_cmd_" + suffix


def test_a_kind_read_failure_keeps_the_run_failed_and_never_completed():
    """List success is not the work's completion; a failed read stays failed."""

    connection = _database()
    try:
        _stage_run(connection)
        store = _store(connection)
        _stage_command(store, "list")
        read_call = RUN + ":read_file:" + "a" * 24
        read_id = _stage_read(store, "read", call_ref=read_call)

        asyncio.run(store.append_local_task_result(
            user_id=OWNER, run_id=RUN,
            message_id=_command_message_id("oracle_mesh_cmd_list", "oracle_mesh_rev_list"),
            command_scope="oracle_mesh_cmd_list",
            summary="no_exit_code", content="listing body", status="completed",
        ))
        _finish_command(connection, "list")
        # A list result alone never seals the overall run.
        assert _run_row(connection)["status"] == "running"
        with pytest.raises(HistoryError, match="without a terminal result"):
            asyncio.run(store.seal_run_terminal(
                user_id=OWNER, run_id=RUN, message_id=RUN + "_final",
                summary="no_exit_code", content="premature answer",
                status="completed",
            ))

        marker = "PADIEM_PC_FILE_ERROR:too_large"
        digest = hashlib.sha256(marker.encode("utf-8")).hexdigest()
        dispatch_id = connection.execute(
            "SELECT dispatch_id FROM oracle_mesh_dispatch WHERE command_id=?",
            (read_id,),
        ).fetchone()[0]
        asyncio.run(store.record_oracle_mesh_first_result(
            dispatch_id=dispatch_id,
            content_sha256=digest, content_bytes=len(marker.encode("utf-8")),
            termination="exited", exit_code=1,
        ))
        asyncio.run(store.store_oracle_mesh_command_result(
            user_id=OWNER, dispatch_id=dispatch_id,
            conversation_id=CONVERSATION,
            message_id=_command_message_id(read_id, "oracle_mesh_rev_read"),
            raw=marker, expected_sha256=digest,
            expected_bytes=len(marker.encode("utf-8")),
        ))
        stored = asyncio.run(store.read_oracle_mesh_original(
            user_id=OWNER, dispatch_id=dispatch_id,
            conversation_id=CONVERSATION,
            message_id=_command_message_id(read_id, "oracle_mesh_rev_read"),
        ))
        assert stored is not None and stored[0] == marker.encode("utf-8")

        assert asyncio.run(store.append_local_task_result(
            user_id=OWNER, run_id=RUN,
            message_id=_command_message_id(read_id, "oracle_mesh_rev_read"),
            command_scope=read_id,
            summary="exited/1", content=marker, status="failed",
        )) is True
        _finish_command(connection, "read", outcome="failed")
        assert _run_row(connection)["status"] == "failed"
        with pytest.raises(HistoryError, match="failed command"):
            asyncio.run(store.seal_run_terminal(
                user_id=OWNER, run_id=RUN, message_id=RUN + "_final",
                summary="exited/1", content="a false success",
                status="completed",
            ))
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# The canonical Chat PC run id
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


def test_pending_result_resolves_a_canonical_chat_pc_run(monkeypatch):
    """The canonical ``chat_pcq_`` run resolves under the unchanged owner check."""
    import app.claw_routes as claw_routes

    monkeypatch.setattr(claw_routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(claw_routes, "current_user_id", lambda request: OWNER)
    connection = _database()
    try:
        _stage_run(connection, status="running")
        store = _store(connection)
        response = asyncio.run(claw_pending_result(
            _pending_request(RUN, store)
        ))
        assert response.status_code == 200
        result = json.loads(response.body)["result"]
        assert result["run_id"] == RUN
        assert result["conversation_id"] == CONVERSATION
        assert result["status"] == "running"
    finally:
        connection.close()


def test_pending_result_recovers_final_answer_without_mistaking_scope_notice(monkeypatch):
    """#5567 GET recovery excludes the persisted <run_id>_scope message."""
    import app.claw_routes as claw_routes
    from app import chat_pc_drive

    monkeypatch.setattr(claw_routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(claw_routes, "current_user_id", lambda request: OWNER)
    connection = _database()
    try:
        _stage_run(connection, status="running")
        store = _store(connection)
        claim = {"version": 1, "requested": "files_list", "admitted": "files_list",
                 "source": "declared", "ops": ["list"], "app_id": "padiem-chat"}
        asyncio.run(store.pin_pc_run_scope(user_id=OWNER, run_id=RUN, claim=claim))
        notice = next(row for row in _messages(connection) if row["id"] == RUN + "_scope")
        assert notice["content"].startswith("목록만 조회합니다.")
        # A scope announcement alone is neither a terminal nor an answer.
        response = asyncio.run(claw_pending_result(_pending_request(RUN, store)))
        assert response.status_code == 200
        pending = json.loads(response.body)["result"]
        assert pending["status"] == "running" and "answer" not in pending

        _stage_command(store, "list")
        asyncio.run(store.append_local_task_result(
            user_id=OWNER, run_id=RUN,
            message_id=_command_message_id("oracle_mesh_cmd_list", "oracle_mesh_rev_list"),
            command_scope="oracle_mesh_cmd_list", summary="no_exit_code",
            content=LIST_TEXT, status="completed",
        ))
        _finish_command(connection, "list")
        final_answer = "승인된 폴더의 파일 목록을 확인했습니다."
        assert asyncio.run(chat_pc_drive._append_lane_answer(
            _lane_request(), store, uid=OWNER, run_id=RUN, content=final_answer,
        )) is True
        # Recreate the store to exercise persisted recovery after the POST
        # response was lost, rather than an in-memory answer cache.
        response = asyncio.run(claw_pending_result(_pending_request(RUN, _store(connection))))
        assert response.status_code == 200
        result = json.loads(response.body)["result"]
        assert result["run_id"] == RUN and result["conversation_id"] == CONVERSATION
        assert result["status"] == "completed"
        assert result["answer_source"] == "pc_command_result"
        assert result["answer"] == LIST_TEXT + "\n" + final_answer
        assert notice["content"] not in result["answer"]
        assert "목록만 조회합니다." not in result["answer"]
        assert "<!--pc_scope:" not in result["answer"]
        assert len(_messages(connection)) == 3
        assert connection.execute("SELECT COUNT(*) FROM oracle_mesh_dispatch").fetchone()[0] == 1
    finally:
        connection.close()


def test_pending_result_refuses_a_foreign_chat_pc_run(monkeypatch):
    """Another owner's canonical run is simply not found."""
    import app.claw_routes as claw_routes

    monkeypatch.setattr(claw_routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(claw_routes, "current_user_id", lambda request: OTHER_OWNER)
    connection = _database()
    try:
        _stage_run(connection, status="running")
        store = _store(connection)
        response = asyncio.run(claw_pending_result(
            _pending_request(RUN, store)
        ))
        assert response.status_code == 404
    finally:
        connection.close()


def test_pending_result_still_refuses_a_malformed_run_id(monkeypatch):
    """The accepted id set is the legacy grammar plus the canonical one."""
    import app.claw_routes as claw_routes

    monkeypatch.setattr(claw_routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(claw_routes, "current_user_id", lambda request: OWNER)
    connection = _database()
    try:
        store = _store(connection)
        for run_id in (
            "chat_pcq_" + "c" * 31,
            "chat_pcq_" + "c" * 33,
            "chat_pcq_" + "Z" * 32,
            "chat_pcq_" + "c" * 32 + "x",
            "run_short",
        ):
            response = asyncio.run(claw_pending_result(
                _pending_request(run_id, store)
            ))
            assert response.status_code == 404, run_id
    finally:
        connection.close()
