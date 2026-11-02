"""#6460 step 3 — the real store keeps a loop's steps apart from its outcome.

The measured contract, on the real D1 schema: one dispatch per step is really
read back (``tool_call_ref`` survives the claim), a step's message lands in the
conversation without writing the run's terminal result, and the verified
answer that follows can still be stored as that terminal.
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.history import D1HistoryStore, PRODUCT_SCOPE_CHAT          # noqa: E402
from test_claw_local_task_result_projection import (                # noqa: E402
    _SqliteD1, _Statement,
)


class _ChangesStatement(_Statement):
    """The guarded claim reads D1's ``meta.changes``, not index write counts."""

    async def run(self):
        cursor = self._connection.execute(self._sql, self._values)
        columns = [item[0] for item in cursor.description] if cursor.description else []
        if columns:
            rows = cursor.fetchall()
            return {"results": [dict(zip(columns, row)) for row in rows],
                    "meta": {"rows_written": 0, "changes": 0}}
        changed = max(0, cursor.rowcount)
        return {"results": [], "meta": {"rows_written": changed, "changes": changed}}


class _ChangesD1(_SqliteD1):
    def prepare(self, sql):
        self.statements.append(sql)
        return _ChangesStatement(self._connection, sql)


def _open(path, *, migrate=True):
    db = _ChangesD1(path)
    if migrate:
        for migration in sorted(
            (Path(__file__).parents[1] / "migrations").glob("*.sql")
        ):
            db._connection.executescript(migration.read_text(encoding="utf-8"))
    return db

OWNER_SUBJECT = "owner-6460-store"


def _iso_after(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def _staged(tmp_path):
    path = tmp_path / "chat.sqlite3"
    store = D1HistoryStore(_open(path))
    owner = asyncio.run(store.upsert_google_user(
        OWNER_SUBJECT, "loop-store@example.test", "owner", "",
    )).id
    run_id = "run_" + "d" * 24
    conversation_id = asyncio.run(store.record_txt_pending_run(
        user_id=owner, run_id=run_id, workspace_id="tenant.6460.store",
        user_text="메모장 열어서 오늘 날짜 적고 저장해 줘",
        conversation_id=None, action="desktop_task",
    ))
    dispatch = asyncio.run(store.create_oracle_mesh_dispatch(
        user_id=owner, run_id=run_id,
        command_id="oracle_mesh_cmd_store", tool_request_ref="desktop-step-2",
        request_id="oracle_mesh_req_store", revision_ref="oracle_mesh_rev_store",
        evidence_ref=None, request_fingerprint="f" * 64,
        account_ref="account-store", workspace_ref="connector-ws-store",
        device_id="device-store", binding_ref=None, node_ref="node-store",
        root_ref="command", path_relative="command", file_path="command",
        expires_at=_iso_after(600), kind="desktop",
        command_text="desktop:keys\nctrl+s", tool_call_ref="desktop-step-2",
    ))
    store.db.close()
    return path, owner, run_id, conversation_id, dispatch["dispatch_id"]


def test_the_claimed_step_still_carries_its_own_call_scope(tmp_path):
    path, owner, run_id, _conversation, dispatch_id = _staged(tmp_path)
    store = D1HistoryStore(_open(path, migrate=False))
    try:
        nonce = "n" * 32
        claim = asyncio.run(store.claim_oracle_mesh_dispatch(
            dispatch_id=dispatch_id,
            nonce_sha256=hashlib.sha256(nonce.encode()).hexdigest(),
        ))
        assert claim is True
        claimed = asyncio.run(store.consume_oracle_mesh_dispatch(
            dispatch_id=dispatch_id, nonce=nonce,
        ))
    finally:
        store.db.close()
    assert claimed is not None
    assert claimed["tool_call_ref"] == "desktop-step-2"


def test_a_step_message_never_becomes_the_runs_terminal_result(tmp_path):
    path, owner, run_id, conversation_id, _dispatch = _staged(tmp_path)
    store = D1HistoryStore(_open(path, migrate=False))
    try:
        asyncio.run(store.append_step_result_message(
            user_id=owner, run_id=run_id, message_id="msg_step_2",
            content="COM1 데스크톱 키 입력\n동작: 키 입력 (ctrl+s)",
        ))
        after_step = asyncio.run(store.get_claw_run(owner, run_id))
        assert after_step["status"] == "pending"
        assert after_step["result_summary"] is None
        # The verified answer still lands and owns the run's terminal.
        stored = asyncio.run(store.append_local_task_result(
            user_id=owner, run_id=run_id, message_id="msg_answer",
            summary="날짜를 적고 저장했습니다.",
            content="날짜를 적고 저장했습니다.", status="completed",
        ))
        final = asyncio.run(store.get_claw_run(owner, run_id))
        conversation = asyncio.run(store.get_conversation(
            owner, conversation_id, product_scope=PRODUCT_SCOPE_CHAT,
        ))
    finally:
        store.db.close()
    assert stored is True
    assert final["status"] == "completed"
    assert final["result_summary"] == "날짜를 적고 저장했습니다."
    assert [message["role"] for message in conversation["messages"]] == [
        "user", "assistant", "assistant",
    ]
    assert "ctrl+s" in conversation["messages"][1]["content"]
