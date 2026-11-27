"""#7841 계측: 결과 적재가 False 를 낸 이유와, 그 이유를 싣는 로그 줄.

동작은 바뀌지 않는다. `append_local_task_result`·`append_command_result` 의
반환값과 쓰기는 그대로이고, 어느 분기에서 끝났는지만 이름으로 남는다.

이유 코드
    already_completed  완료 `status != 'completed'` 가드에 걸린 집계 쓰기
    same_message       같은 message id 가 같은 본문으로 이미 있음
    summary_same       같은 턴이 같은 요약으로 이미 저장됨
    summary_guard      요약 가드에 걸린 쓰기 0행
    stored             저장됨
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

from _support.migrated_db_template import migrated_connection, fill_empty_connection
import sqlite3
from types import SimpleNamespace

from app.history import D1HistoryStore, is_multi_command_action
from app.history_append_reason import (
    APPEND_REASON_ALREADY_COMPLETED,
    APPEND_REASON_SAME_MESSAGE,
    APPEND_REASON_STORED,
    APPEND_REASON_SUMMARY_GUARD,
    APPEND_REASON_SUMMARY_SAME,
    last_append_reason,
)
from app.oracle_mesh_read_return_routes import log_pc_result_store_stage

OWNER = "usr_" + "a" * 32
WORKSPACE = "tenant_7841_reason"
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
WORD = re.compile(r"\A[a-z][a-z0-9_]{0,40}\Z")
DIRS_TEXT = "drive-a" + chr(10) + "drive-b"


class _Statement:
    def __init__(self, connection, sql, values=()):
        self.conn, self.sql, self.values = connection, sql, values

    def bind(self, *values):
        return _Statement(self.conn, self.sql, values)

    async def first(self):
        row = self.conn.execute(self.sql, self.values).fetchone()
        return dict(row) if row is not None else None

    async def run(self):
        cursor = self.conn.execute(self.sql, self.values)
        rows = [dict(row) for row in cursor.fetchall()]
        return SimpleNamespace(results=(rows or None),
                               meta={"rows_written": cursor.rowcount})


class _Sqlite:
    """The D1 shape: a non-RETURNING statement answers rows_written only."""

    def __init__(self, connection):
        self.connection = connection

    def prepare(self, sql):
        return _Statement(self.connection, sql)

    async def batch(self, statements):
        out = [await statement.run() for statement in statements]
        self.connection.commit()
        return out


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, fmt, *args):
        self.lines.append(fmt % args if args else fmt)


def _database():
    connection = migrated_connection(":memory:", MIGRATIONS,
        check_same_thread=False, isolation_level="", row_factory=sqlite3.Row)
    connection.execute(
        "INSERT INTO users(id,auth_provider,provider_subject,email,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?)",
        (OWNER, "google", OWNER, "reason-7841@example.com", "2026-11-16", "2026-11-16"),
    )
    connection.commit()
    return connection


def _dispatch(connection, *, run_id, command_id):
    connection.execute(
        "INSERT INTO oracle_mesh_dispatch (dispatch_id,user_id,run_id,command_id,"
        "tool_request_ref,request_id,revision_ref,evidence_ref,request_fingerprint,"
        "account_ref,workspace_ref,device_id,binding_ref,node_ref,root_ref,"
        "path_relative,file_path,nonce_sha256,state,result_sha256,result_bytes,"
        "expires_at,created_at,kind,command_text) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("dsp_" + "1" * 16, OWNER, run_id, command_id, "tool_req", "req", "rev_1",
         None, "fp", "acct", WORKSPACE, "dev", None, "node", "root", "p", "f", None,
         "done", None, None, "2099-01-01T00:00:00Z", "2026-11-16T12:00:00Z",
         "command", "dir"),
    )
    connection.commit()


def _stage(store, connection, *, action, run_id):
    conversation = asyncio.run(store.record_chat_pc_drive_run(
        user_id=OWNER, run_id=run_id, workspace_id=WORKSPACE,
        user_text="연결된 PC의 드라이브 목록만 알려 주세요", conversation_id=None,
        action=action, title_prefix="PC 탐색: ",
    ))
    _dispatch(connection, run_id=run_id, command_id="cmd_" + "3" * 12)
    return conversation


MULTI_RUN = "chat_pcq_" + "d" * 32
SINGLE_RUN = "chat_pcq_" + "e" * 32


async def _append_with_reason(store, **fields):
    """Append and read the reason in one task, as the request handler does."""

    appended = await store.append_local_task_result(**fields)
    return appended, last_append_reason()


def test_an_already_completed_multi_command_run_names_its_guard():
    connection = _database()
    store = D1HistoryStore(_Sqlite(connection))
    _stage(store, connection, action="pc_files_query", run_id=MULTI_RUN)
    asyncio.run(store.update_claw_run_status(OWNER, MULTI_RUN, "completed"))

    appended, reason = asyncio.run(_append_with_reason(
        store, user_id=OWNER, run_id=MULTI_RUN,
        message_id="msg_ltr_" + "2" * 40, summary="no_exit_code",
        content=DIRS_TEXT, status="completed", command_scope="cmd_" + "3" * 12,
    ))

    assert appended is False
    assert reason == APPEND_REASON_ALREADY_COMPLETED == "already_completed"
    connection.close()


def test_a_repeated_identical_command_result_names_the_same_message():
    connection = _database()
    store = D1HistoryStore(_Sqlite(connection))
    _stage(store, connection, action="pc_files_query", run_id=MULTI_RUN)
    fields = dict(
        user_id=OWNER, run_id=MULTI_RUN, message_id="msg_ltr_" + "4" * 40,
        summary="no_exit_code", content="C:\\\nD:\\", status="completed",
        command_scope="cmd_" + "3" * 12,
    )

    appended, reason = asyncio.run(_append_with_reason(store, **fields))
    assert (appended, reason) == (True, APPEND_REASON_STORED)
    appended, reason = asyncio.run(_append_with_reason(store, **fields))
    assert appended is False
    assert reason == APPEND_REASON_SAME_MESSAGE == "same_message"
    connection.close()


def test_a_repeated_identical_run_result_names_the_same_summary():
    connection = _database()
    store = D1HistoryStore(_Sqlite(connection))
    _stage(store, connection, action="pc_drive_query", run_id=SINGLE_RUN)
    fields = dict(
        user_id=OWNER, run_id=SINGLE_RUN, message_id="msg_ltr_" + "5" * 40,
        summary="no_exit_code", content="C:\\\nD:\\", status="completed",
    )

    appended, reason = asyncio.run(_append_with_reason(store, **fields))
    assert (appended, reason) == (True, APPEND_REASON_STORED)
    appended, reason = asyncio.run(_append_with_reason(store, **fields))
    assert appended is False
    assert reason == APPEND_REASON_SUMMARY_SAME == "summary_same"
    connection.close()


def test_a_message_id_taken_elsewhere_names_the_summary_guard():
    connection = _database()
    store = D1HistoryStore(_Sqlite(connection))
    conversation = _stage(store, connection, action="pc_drive_query", run_id=SINGLE_RUN)
    taken = "msg_ltr_" + "6" * 40
    other = "chat_" + "f" * 32
    connection.execute(
        "INSERT INTO conversations(id,user_id,title,created_at,updated_at,product_scope) "
        "VALUES (?,?,?,?,?,?)",
        (other, OWNER, "fixture", "2026-11-16", "2026-11-16", "b62-chat"),
    )
    connection.execute(
        "INSERT INTO messages(id,conversation_id,sequence_number,role,content,created_at) "
        "VALUES (?,?,?,?,?,?)", (taken, other, 0, "assistant", "다른 대화", "2026-11-16"),
    )
    connection.commit()
    assert conversation != other

    appended, reason = asyncio.run(_append_with_reason(
        store, user_id=OWNER, run_id=SINGLE_RUN, message_id=taken,
        summary="no_exit_code", content=DIRS_TEXT, status="completed",
    ))

    assert appended is False
    assert reason == APPEND_REASON_SUMMARY_GUARD == "summary_guard"
    connection.close()


def test_the_stored_line_keeps_its_exact_shape():
    log = _Log()

    log_pc_result_store_stage(
        log, stage="stored", run_hash="a" * 16, dispatch_id="dsp_example",
        reason="ignored_when_stored", run_action="other",
        run_status_before="other", scoped=True,
    )

    assert log.lines == ["pc_result stage=stored run_hash=" + "a" * 16
                         + " dispatch_id=dsp_example"]


def test_a_refused_line_carries_the_reason_and_the_row_words():
    log = _Log()

    log_pc_result_store_stage(
        log, stage="not_appended", run_hash="b" * 16, dispatch_id="dsp_example",
        reason=APPEND_REASON_ALREADY_COMPLETED, run_action="pc_files_query",
        run_status_before="completed", scoped=True,
    )

    line = log.lines[0]
    assert line.startswith("pc_result stage=not_appended run_hash=")
    assert " reason=already_completed run_action=pc_files_query " in line
    assert "run_status_before=completed scoped=1" in line
    for token in line.split():
        if "=" in token:
            value = token.split("=", 1)[1]
            if token.startswith(("reason=", "run_action=", "run_status_before=")):
                assert WORD.match(value), token


def test_unknown_words_are_reduced_to_other():
    log = _Log()

    log_pc_result_store_stage(
        log, stage="not_appended", run_hash="c" * 16, dispatch_id="dsp_example",
        reason="Not A Code", run_action="pc_secret_tool",
        run_status_before="waiting_approval", scoped=False,
    )

    line = log.lines[0]
    assert " reason=unknown run_action=other " in line
    assert "run_status_before=other scoped=0" in line


def test_the_scope_word_matches_the_action_kind():
    connection = _database()
    store = D1HistoryStore(_Sqlite(connection))
    _stage(store, connection, action="pc_files_query", run_id=MULTI_RUN)

    assert is_multi_command_action(
        asyncio.run(store.get_claw_run(OWNER, MULTI_RUN))["action"]
    ) is True
    connection.close()
