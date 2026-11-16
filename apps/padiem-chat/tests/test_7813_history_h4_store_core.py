"""T3 H4 회귀 — StoreCore(L)·ApprovalHandoffStore(Q) 조합으로 같은 결과를 낸다 (#7813).

공개 메서드 이름 집합은 이동 전 main의 `D1HistoryStore`에서 뽑은 값 그대로
여기에 적는다. 상속까지 포함한 비교라 앞으로 H5~H7에서도 그대로 쓴다.
지역·모의만 사용한다(운영 DB·로그인·답변 생성 없음).
"""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import history as history_entry
from app import history_store_core as core_module
from app import history_store_handoff as handoff_module
from app.history import D1HistoryStore, HistoryError

# 이동 전 main에서 dir(D1HistoryStore) 중 "_"로 시작하지 않는 이름 집합.
PUBLIC_NAMES = {
    'LANE_STATUS_NODE_LIMIT', 'append_command_result', 'append_exchange',
    'append_local_task_result', 'append_step_result_message',
    'begin_chat_stream_turn', 'cancel_oracle_mesh_dispatches_for_run',
    'claim_claw_approval_handoff', 'claim_oracle_mesh_dispatch',
    'consume_claw_approval_handoff', 'consume_oracle_mesh_dispatch',
    'consume_pc_command_confirmation', 'consume_service_id',
    'create_oracle_mesh_dispatch', 'create_project',
    'create_web_xlsx_p01_run', 'delete_conversation', 'delete_project',
    'ensure_claw_automation_conversation',
    'expire_stale_confirmation_cards', 'finalize_claw_approval_claim',
    'find_pass' 'word_credential', 'find_pass' 'word_credential_by_user_id',
    'finish_chat_stream_turn', 'finish_oracle_mesh_dispatch',
    'get_claw_run', 'get_claw_run_for_artifact_document',
    'get_claw_run_result', 'get_claw_run_result_message',
    'get_conversation', 'get_conversation_model_context',
    'get_local_task_correlation', 'get_oracle_mesh_dispatch_for_owner',
    'get_oracle_mesh_dispatch_pin', 'get_oracle_mesh_run_command',
    'get_oracle_mesh_run_correlation', 'get_oracle_mesh_run_open_state',
    'get_owner_conversation_artifact', 'get_pc_run_scope',
    'get_pc_run_scope_notice', 'get_project', 'get_user',
    'increment_pass' 'word_failures', 'list_conversations',
    'list_owner_conversation_artifacts', 'list_project_conversations',
    'list_projects', 'list_projects_page', 'list_recent_claw_runs',
    'load_claw_approval_handoff', 'lock_pass' 'word_credential',
    'mark_oracle_mesh_store_failed', 'oldest_pending_oracle_mesh_dispatch',
    'oracle_mesh_dispatch_cancellation', 'oracle_mesh_lane_status',
    'oracle_mesh_node_live_claims', 'pin_pc_run_scope',
    'promote_chat_stream_pc_run', 'read_oracle_mesh_original',
    'read_pc_session_confirmation_turn', 'record_chat_pc_drive_run',
    'record_claw_approval_handoff', 'record_claw_run',
    'record_local_task_correlation', 'record_oracle_mesh_first_result',
    'record_pass' 'word_failure', 'record_txt_pending_run',
    'register_owner_conversation_artifact', 'register_pass' 'word_user',
    'release_claw_approval_claim', 'renew_oracle_mesh_claim',
    'reset_pass' 'word_failures', 'restart_pass' 'word_failures_after_lapsed_lock',
    'seal_run_terminal', 'search_conversations', 'set_dispatch_authority',
    'settle_unredeliverable_oracle_mesh_claims',
    'store_oracle_mesh_command_result', 'store_oracle_mesh_original',
    'store_oracle_mesh_original_bytes', 'update_claw_run_status',
    'update_conversation', 'update_pass' 'word_credential', 'update_project',
    'upsert_google_user', 'upsert_shared_user', 'user_row_exists',
    'verify_owner_conversation_artifacts',
}

OWNER = "usr_" + "7" * 32
OTHER = "usr_" + "8" * 32
RUN = "run-h4-1"
FUTURE = "2099-01-01T00:00:00+00:00"
PAST = "2020-01-01T00:00:00+00:00"


def test_public_method_names_are_fixed() -> None:
    actual = {name for name in dir(D1HistoryStore) if not name.startswith("_")}
    assert actual == PUBLIC_NAMES


def test_reexport_names_are_the_same_objects() -> None:
    assert history_entry.StoreCore is core_module.StoreCore
    assert history_entry.ApprovalHandoffStore is handoff_module.ApprovalHandoffStore
    assert issubclass(D1HistoryStore, core_module.StoreCore)
    assert issubclass(handoff_module.ApprovalHandoffStore, core_module.StoreCore)


def test_internal_helpers_stay_reachable_on_the_instance() -> None:
    for name in (
        "_first", "_run", "_all", "_dispatch", "_verified", "_context_key",
        "_put_full_message", "_delete_full_keys", "_delete_orphan_full_keys",
        "_read_full_message",
    ):
        assert hasattr(D1HistoryStore, name), name
        assert hasattr(core_module.StoreCore, name), name
    assert hasattr(core_module.StoreCore, "get_conversation_model_context")
    for name in (
        "record_claw_approval_handoff", "load_claw_approval_handoff",
        "claim_claw_approval_handoff", "release_claw_approval_claim",
        "finalize_claw_approval_claim", "consume_claw_approval_handoff",
    ):
        assert hasattr(handoff_module.ApprovalHandoffStore, name), name


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
        return SimpleNamespace(
            results=[dict(row) for row in cursor.fetchall()],
            meta={"changes": cursor.rowcount},
        )


class _D1:
    def __init__(self, connection):
        self.connection = connection

    def prepare(self, sql):
        return _Statement(self.connection, sql)


def _store() -> tuple[D1HistoryStore, sqlite3.Connection]:
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.row_factory = sqlite3.Row
    migrations = Path(__file__).resolve().parents[1] / "migrations"
    for name in ("016_claw_approval_handoff.sql", "017_claw_approval_handoff_consumption.sql"):
        db.executescript((migrations / name).read_text(encoding="utf8"))
    db.commit()
    return D1HistoryStore(_D1(db)), db


def _trusted() -> dict:
    return {
        "app_id": "b54-padiem-claw",
        "messages": [{"role": "user", "content": "테스트 견적 요청."}],
        "session_id": "run-h4-1",
    }


def _record(store, **overrides):
    fields = {
        "user_id": OWNER, "run_id": RUN, "continuation_ref": "cont-1",
        "pause_id": "pause-1", "pause_expires_at": FUTURE,
        "trusted_request": _trusted(), "workspace_id": "ws-1",
    }
    fields.update(overrides)
    return asyncio.run(store.record_claw_approval_handoff(**fields))


def test_q_record_load_claim_finalize_consume_same_rows() -> None:
    store, db = _store()
    _record(store)
    loaded = asyncio.run(store.load_claw_approval_handoff(OWNER, RUN, "ws-1"))
    assert loaded is not None
    assert loaded["run_id"] == RUN and loaded["pause_id"] == "pause-1"
    assert loaded["trusted_request"] == _trusted()
    assert loaded["trusted_request_fingerprint"]
    token = asyncio.run(store.claim_claw_approval_handoff(
        user_id=OWNER, run_id=RUN, workspace_id="ws-1", continuation_ref="cont-1",
        pause_id="pause-1", trusted_request_fingerprint=loaded["trusted_request_fingerprint"],
    ))
    assert token is not None and token.startswith("decision_claim:")
    assert asyncio.run(store.finalize_claw_approval_claim(
        user_id=OWNER, run_id=RUN, workspace_id="ws-1", claim_token=token,
    )) is True
    assert asyncio.run(store.load_claw_approval_handoff(OWNER, RUN, "ws-1")) is None
    db.close()


def test_q_replay_idempotent_and_cross_owner_hidden() -> None:
    store, db = _store()
    _record(store)
    _record(store)  # exact replay: no error, still one row
    count = db.execute("SELECT COUNT(*) AS n FROM claw_approval_handoff").fetchone()["n"]
    assert count == 1
    assert asyncio.run(store.load_claw_approval_handoff(OTHER, RUN, "ws-1")) is None
    assert asyncio.run(store.load_claw_approval_handoff(OWNER, RUN, "ws-other")) is None
    db.close()


def test_q_expired_and_bad_inputs_fail_closed() -> None:
    store, db = _store()
    _record(store, pause_expires_at=PAST)
    assert asyncio.run(store.load_claw_approval_handoff(OWNER, RUN, "ws-1")) is None
    with pytest.raises(HistoryError, match="pause_expires_at"):
        _record(store, run_id="run-2", pause_expires_at="not-a-date")
    assert asyncio.run(store.consume_claw_approval_handoff("", RUN)) is False
    assert asyncio.run(store.release_claw_approval_claim(
        user_id=OWNER, run_id=RUN, workspace_id="ws-1", claim_token="bad",
    )) is False
    db.close()


def test_q_claim_release_reclaim_order() -> None:
    store, db = _store()
    _record(store)
    loaded = asyncio.run(store.load_claw_approval_handoff(OWNER, RUN, "ws-1"))
    fp = loaded["trusted_request_fingerprint"]
    first = asyncio.run(store.claim_claw_approval_handoff(
        user_id=OWNER, run_id=RUN, workspace_id="ws-1", continuation_ref="cont-1",
        pause_id="pause-1", trusted_request_fingerprint=fp,
    ))
    assert first is not None
    second = asyncio.run(store.claim_claw_approval_handoff(
        user_id=OWNER, run_id=RUN, workspace_id="ws-1", continuation_ref="cont-1",
        pause_id="pause-1", trusted_request_fingerprint=fp,
    ))
    assert second is None  # already claimed: no second winner
    assert asyncio.run(store.release_claw_approval_claim(
        user_id=OWNER, run_id=RUN, workspace_id="ws-1", claim_token=first,
    )) is True
    third = asyncio.run(store.claim_claw_approval_handoff(
        user_id=OWNER, run_id=RUN, workspace_id="ws-1", continuation_ref="cont-1",
        pause_id="pause-1", trusted_request_fingerprint=fp,
    ))
    assert third is not None and third != first
    db.close()
