"""#7975 — '명령 준비 안 됨' comes from one owner-scoped history query.

No PC command is issued here. The SQL reads only the dispatch metadata that
already exists (user_mode, termination, exit_code, created_at); command text,
nonce hashes and result bodies never appear in the list answer.
"""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.app_factory import create_app
from app.d1_sqlite import SqliteD1
from app.pc_device_pairing_routes import PC_PAIRING_PATH, _command_ready_view

sys_path = Path(__file__).resolve().parents[1]
import sys
if str(sys_path) not in sys.path:
    sys.path.insert(0, str(sys_path))

from test_5573_pc_device_pairing import ORIGIN, SESSION_SECRET  # noqa: E402
from test_7603_confirmation_card_expiry import _fixture  # noqa: E402

OWNER = "usr_" + "a" * 32
OTHER = "usr_" + "b" * 32
DEVICE = "node/meshdomain/qa-pc"
OTHER_DEVICE = "node/meshdomain/other-pc"
HELP = "PC 도우미를 다시 설치해 주세요"


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _store(tmp_path):
    store, db = _fixture(tmp_path)
    for index, user_id in enumerate((OWNER, OTHER)):
        db.execute(
            "INSERT INTO users (id, auth_provider, provider_subject, email, display_name, "
            "picture_url, created_at, updated_at) VALUES (?, 'google', ?, ?, '', '', ?, ?)",
            (user_id, "sub_7975_%d" % index, "qa%d@example.test" % index,
             _iso(datetime.now(timezone.utc)), _iso(datetime.now(timezone.utc))),
        )
    return store, db


def run(coro):
    return asyncio.run(coro)


async def _seed(store, *, user_id=OWNER, device_id=DEVICE, termination="not_executed",
                 exit_code=1, age_hours=1, user_mode=True, run_suffix="a"):
    run_id = "chat_pcq_" + (run_suffix * 32)[:32]
    await store.record_chat_pc_drive_run(
        user_id=user_id, run_id=run_id, workspace_id="ws",
        user_text="QA PC", conversation_id=None, action="pc_files_query",
    )
    row = await store.create_oracle_mesh_dispatch(
        user_id=user_id, run_id=run_id, command_id="cmd-1", tool_request_ref="t",
        request_id="r", revision_ref="rev", evidence_ref=None,
        request_fingerprint="f", account_ref="acct", workspace_ref="ws",
        device_id=device_id, binding_ref=None, node_ref=device_id, root_ref="mesh_terminal",
        path_relative="command", file_path="command",
        expires_at=_iso(datetime.now(timezone.utc) + timedelta(hours=1)),
        kind="command", command_text="a secret-looking command text", user_mode=user_mode,
    )
    stamp = _iso(datetime.now(timezone.utc) - timedelta(hours=age_hours))
    await store._run(
        "UPDATE oracle_mesh_dispatch SET termination=?, exit_code=?, created_at=? "
        "WHERE dispatch_id=?",
        termination, exit_code, stamp, row["dispatch_id"],
    )
    return stamp


def test_command_ready_view_maps_only_a_recent_not_executed_result():
    assert _command_ready_view({"termination": "not_executed", "exit_code": 1,
                                "created_at": "2026-11-18T01:00:00.000Z"}) == {
        "command_ready": "not_ready", "last_user_session_failure_at": "2026-11-18T01:00:00.000Z"
    }
    for result in (None, {}, {"termination": "exited", "exit_code": 0},
                   {"termination": "cancelled", "exit_code": 1}):
        assert _command_ready_view(result)["command_ready"] == "unknown", result
    assert _command_ready_view({"termination": "not_executed", "exit_code": 1,
                                "created_at": None})["last_user_session_failure_at"] is None


def test_store_reads_one_owner_latest_user_mode_result_per_device(tmp_path):
    store, _db = _store(tmp_path)

    async def scenario():
        old_stamp = await _seed(store, run_suffix="1", age_hours=5)
        new_stamp = await _seed(store, run_suffix="2", age_hours=1)
        await _seed(store, run_suffix="3", termination="exited", exit_code=0, age_hours=2,
                    device_id=OTHER_DEVICE)
        await _seed(store, run_suffix="4", user_mode=False, age_hours=0)
        await _seed(store, run_suffix="5", user_id=OTHER, age_hours=0)
        latest = await store.latest_user_mode_results_for_owner(
            user_id=OWNER, device_ids=[DEVICE, OTHER_DEVICE])
        assert latest[DEVICE]["termination"] == "not_executed"
        assert latest[DEVICE]["created_at"] == new_stamp
        assert new_stamp > old_stamp
        assert latest[OTHER_DEVICE]["termination"] == "exited"
        assert "secret-looking command text" not in str(latest)

    run(scenario())


def test_a_failure_outside_the_window_is_unknown(tmp_path):
    store, _db = _store(tmp_path)
    run(_seed(store, age_hours=25, run_suffix="6"))

    async def read():
        return await store.latest_user_mode_results_for_owner(
            user_id=OWNER, device_ids=[DEVICE], window_hours=24)

    assert run(read()) == {}


def test_another_accounts_dispatch_never_marks_this_owner(tmp_path):
    store, _db = _store(tmp_path)
    run(_seed(store, user_id=OTHER, device_id=DEVICE, age_hours=0, run_suffix="7"))

    async def read():
        return await store.latest_user_mode_results_for_owner(
            user_id=OWNER, device_ids=[DEVICE])

    assert run(read()) == {}


class _Pairing:
    async def list_links(self, **_values):
        return [{"link_id": "pclink_1", "mesh_node_id": DEVICE, "label": "QA PC",
                 "state": "active", "roots_json": "[]"}]

    async def list_codes(self, **_values):
        return []


class _CountingHistory:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def latest_user_mode_results_for_owner(self, **values):
        self.calls.append(values)
        return self.result


def _app(history):
    app = create_app(Settings(runtime_mode="mock", session_secret=SESSION_SECRET,
                              public_base_url=ORIGIN))
    app.state.pc_device_pairing_store = _Pairing()
    app.state.history_store = history
    return app


def _client(app, *, user_id=OWNER):
    token = create_session_token(app.state.settings, user_id,
                                 now=int(datetime.now(timezone.utc).timestamp()))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN,
                             headers={"Origin": ORIGIN}, cookies={SESSION_COOKIE: token})


def test_list_answer_marks_not_ready_with_one_query_and_no_secrets():
    history = _CountingHistory({
        DEVICE: {"termination": "not_executed", "exit_code": 1,
                 "created_at": "2026-11-18T01:00:00.000Z"},
    })

    async def scenario():
        async with _client(_app(history)) as session:
            return await session.get(PC_PAIRING_PATH)

    response = run(scenario())
    assert response.status_code == 200
    link = response.json()["links"][0]
    assert link["command_ready"] == "not_ready"
    assert link["last_user_session_failure_at"] == "2026-11-18T01:00:00.000Z"
    assert len(history.calls) == 1
    assert history.calls[0]["user_id"] == OWNER
    assert history.calls[0]["device_ids"] == [DEVICE]
    assert "secret-looking command text" not in response.text
    assert "nonce_sha256" not in response.text
    assert "result_sha256" not in response.text


def test_unknown_and_offline_links_are_left_alone():
    for history_result in ({}, {DEVICE: {"termination": "exited", "exit_code": 0,
                                         "created_at": "2026-11-18T01:00:00.000Z"}}):
        history = _CountingHistory(history_result)

        async def scenario():
            async with _client(_app(history)) as session:
                return await session.get(PC_PAIRING_PATH)

        link = run(scenario()).json()["links"][0]
        assert link["command_ready"] == "unknown"
        assert link["last_user_session_failure_at"] is None


def test_error_answer_keeps_the_code_and_adds_the_remedy():
    from app.mcp_gateway_session import _failure

    failed = _failure("user_session_unavailable")
    assert failed["code"] == "user_session_unavailable"
    assert HELP in failed["answer"]
    generic = _failure("user_helper_timeout")
    assert HELP not in generic["answer"]
