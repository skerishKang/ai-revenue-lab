"""#7603 — a confirmation card that nobody answers must end, not wait forever.

The card's confirm window is ``PENDING_PC_COMMAND_MAX_AGE_SECONDS`` measured from
the run row's ``created_at``. Before this change only the selector checked the
window, so an unanswered row stayed ``waiting_approval`` and the history screen
kept showing "승인 필요"; the consume itself had no time condition, so a
selection made just before expiry could still dispatch after it.

These tests drive the real ``D1HistoryStore`` SQL over every committed
migration. Time is injected by moving the row's ``created_at``; nothing sleeps.
"""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import chat_pc_command as lane
from app import oracle_mesh_read_return_routes as mesh_routes
from app.d1_sqlite import SqliteD1
from app.history import D1HistoryStore
from app.local_cpython import apply_migrations
from app.pc_command_confirmation import (
    STATUS_AWAITING_CONFIRMATION,
    STATUS_EXPIRED,
)

UID = "usr_" + "8" * 32
WORKSPACE = "ws-7603"
PC_CONTEXT = {"workspace_id": WORKSPACE, "pc_tools": {"device_id": "device-1"}}
CARD_TURN = "문서 초안입니다.\n내 PC에서 `Remove-Item C:/tmp/a.txt` 실행해"
CARD_COMMAND = "Remove-Item C:/tmp/a.txt"
TYPE_TURN = "내 PC에서 '첫째 줄\n둘째 줄' 입력해 줘"


class _Bucket:
    """Private full-text store stand-in (put/get/delete by key)."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key, body, httpMetadata=None):
        self.objects[key] = bytes(body)

    def delete(self, key):
        self.objects.pop(key, None)

    def get(self, key):
        return self.objects.get(key)


def _fixture(tmp_path):
    connection = sqlite3.connect(str(tmp_path / "chat.sqlite3"), isolation_level=None)
    connection.row_factory = sqlite3.Row
    apply_migrations(connection)
    connection.execute(
        "INSERT INTO users (id, auth_provider, provider_subject, email, display_name, "
        "picture_url, created_at, updated_at) VALUES (?, 'google', 'sub_7603', "
        "'owner@example.test', '', '', '2026-11-12T00:00:00Z', '2026-11-12T00:00:00Z')",
        (UID,),
    )
    store = D1HistoryStore(SqliteD1(connection), full_context_bucket=_Bucket())
    return store, connection


def _age(connection, run_id: str, seconds: int) -> None:
    """Move the card's created_at into the past; the tests never sleep."""

    stamp = (datetime.now(timezone.utc) - timedelta(seconds=seconds))
    value = stamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    connection.execute(
        "UPDATE claw_run_history SET created_at=? WHERE run_id=? AND user_id=?",
        (value, run_id, UID),
    )


async def _stage(store, run_id: str, *, action: str, user_text: str) -> str:
    return await store.record_txt_pending_run(
        user_id=UID, run_id=run_id, workspace_id=WORKSPACE,
        user_text=user_text, conversation_id=None, action=action,
        status=STATUS_AWAITING_CONFIRMATION,
    )


async def _chat_turn(store, text: str, conversation_id: str):
    """The Chat orchestration route's PC command step, in its own order."""
    confirmed = await lane.resolve_confirmed_pc_command(store, UID, text, conversation_id)
    if confirmed is not None:
        return await lane.dispatch_chat_pc_command(
            SimpleNamespace(state=SimpleNamespace(), headers={}),
            uid=UID, raw={}, user_text=text, command=confirmed,
            pc_context=PC_CONTEXT, conversation_id=conversation_id, store=store,
        )
    return None


def _status(connection, run_id: str) -> str:
    row = connection.execute(
        "SELECT status FROM claw_run_history WHERE run_id=? AND user_id=?",
        (run_id, UID),
    ).fetchone()
    return str(row["status"])


@pytest.mark.parametrize("action", ["pc_command", "desktop_type"])
def test_an_unanswered_card_is_not_waiting_after_the_history_is_read(tmp_path, action):
    async def scenario():
        store, connection = _fixture(tmp_path)
        run_id = "run_expire_list_" + action
        await _stage(store, run_id, action=action,
                     user_text=CARD_TURN if action == "pc_command" else TYPE_TURN)
        _age(connection, run_id, 601)

        runs = await store.list_recent_claw_runs(UID, limit=10)

        row = next(run for run in runs if run["run_id"] == run_id)
        assert row["status"] == STATUS_EXPIRED
        assert row["status"] != STATUS_AWAITING_CONFIRMATION
        assert _status(connection, run_id) == STATUS_EXPIRED

    asyncio.run(scenario())


@pytest.mark.parametrize("action", ["pc_command", "desktop_type"])
def test_a_yes_after_the_window_runs_nothing_and_retires_the_card(
    tmp_path, action, monkeypatch,
):
    sent: list[str] = []

    async def count(request, *, command, wire, **_kwargs):
        sent.append(command)
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(mesh_routes, "dispatch_oracle_mesh_command_intent", count)

    async def scenario():
        store, connection = _fixture(tmp_path)
        run_id = "run_expired_yes_" + action
        conversation = await _stage(
            store, run_id, action=action,
            user_text=CARD_TURN if action == "pc_command" else TYPE_TURN,
        )
        _age(connection, run_id, 601)

        if action == "pc_command":
            assert await _chat_turn(store, "네", conversation) is None
        else:
            assert await store.consume_pc_command_confirmation(
                UID, run_id, action="desktop_type",
            ) is False
        assert sent == []
        assert _status(connection, run_id) == STATUS_EXPIRED

    asyncio.run(scenario())


def test_a_young_card_is_taken_once_and_a_second_yes_does_nothing(tmp_path, monkeypatch):
    sent: list[str] = []

    async def count(request, *, command, wire, **_kwargs):
        sent.append(command)
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(mesh_routes, "dispatch_oracle_mesh_command_intent", count)

    async def scenario():
        store, connection = _fixture(tmp_path)
        run_id = "run_young_pc_command"
        conversation = await _stage(
            store, run_id, action="pc_command", user_text=CARD_TURN,
        )
        _age(connection, run_id, 599)

        assert await _chat_turn(store, "네", conversation) is not None
        assert await _chat_turn(store, "네", conversation) is None
        assert sent == [CARD_COMMAND]
        assert _status(connection, run_id) == "cancelled"

    asyncio.run(scenario())


def test_a_young_typed_value_card_is_taken_once(tmp_path):
    async def scenario():
        store, connection = _fixture(tmp_path)
        run_id = "run_young_desktop_type"
        await _stage(store, run_id, action="desktop_type", user_text=TYPE_TURN)
        _age(connection, run_id, 599)

        assert await store.consume_pc_command_confirmation(
            UID, run_id, action="desktop_type",
        ) is True
        assert await store.consume_pc_command_confirmation(
            UID, run_id, action="desktop_type",
        ) is False
        assert _status(connection, run_id) == "cancelled"

    asyncio.run(scenario())


def test_staging_the_next_card_retires_the_old_unanswered_one(tmp_path):
    async def scenario():
        store, connection = _fixture(tmp_path)
        old = "run_old_card"
        new = "run_new_card"
        await _stage(store, old, action="pc_command", user_text=CARD_TURN)
        _age(connection, old, 601)

        await _stage(store, new, action="desktop_type", user_text=TYPE_TURN)

        assert _status(connection, old) == STATUS_EXPIRED
        assert _status(connection, new) == STATUS_AWAITING_CONFIRMATION

    asyncio.run(scenario())


def test_two_expiry_writers_change_the_row_once(tmp_path):
    async def scenario():
        store, connection = _fixture(tmp_path)
        run_id = "run_expire_race"
        await _stage(store, run_id, action="pc_command", user_text=CARD_TURN)
        _age(connection, run_id, 601)

        changes = await asyncio.gather(
            store.expire_stale_confirmation_cards(UID),
            store.expire_stale_confirmation_cards(UID),
        )

        assert sorted(changes) == [0, 1]
        assert _status(connection, run_id) == STATUS_EXPIRED

    asyncio.run(scenario())
