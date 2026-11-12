"""#7561 + #7566 — the typed-value card is a card to the real store too.

The typed-value confirmation card (``desktop_type``) reuses the PC command
card's rules: staged as ``waiting_approval``, taken exactly once by one
conditional update. These tests run the real ``D1HistoryStore`` SQL so the two
changes cannot drift apart again: a card staged as ``pending`` was never
selectable once #7566 landed, and a consume through ``update_claw_run_status``
let two racing "네" both win.
"""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone

import pytest

from app.d1_sqlite import SqliteD1
from app.history import D1HistoryStore, HistoryError
from app.local_cpython import apply_migrations
from app.pc_command_confirmation import (
    ACTION_PC_COMMAND,
    STATUS_AWAITING_CONFIRMATION,
    select_pending_command_row,
)

UID = "usr_" + "5" * 32
WORKSPACE = "ws-7561"


class _Bucket:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key, body, httpMetadata=None):
        self.objects[key] = bytes(body)

    def delete(self, key):
        self.objects.pop(key, None)

    def get(self, key):
        return self.objects.get(key)


def _store(tmp_path) -> D1HistoryStore:
    connection = sqlite3.connect(str(tmp_path / "chat.sqlite3"), isolation_level=None)
    connection.row_factory = sqlite3.Row
    apply_migrations(connection)
    connection.execute(
        "INSERT INTO users (id, auth_provider, provider_subject, email, display_name, "
        "picture_url, created_at, updated_at) VALUES (?, 'google', 'sub_7561', "
        "'owner@example.test', '', '', '2026-11-12T00:00:00Z', '2026-11-12T00:00:00Z')",
        (UID,),
    )
    return D1HistoryStore(SqliteD1(connection), full_context_bucket=_Bucket())


async def _stage(store, run_id, *, action, status):
    return await store.record_txt_pending_run(
        user_id=UID, run_id=run_id, workspace_id=WORKSPACE,
        user_text="내 PC에서 '첫째 줄\n둘째 줄' 입력해 줘", conversation_id=None,
        action=action, status=status,
    )


def test_a_typed_value_card_is_staged_waiting_and_taken_exactly_once(tmp_path):
    async def scenario():
        store = _store(tmp_path)
        conversation = await _stage(
            store, "run_type_card", action="desktop_type", status=STATUS_AWAITING_CONFIRMATION,
        )
        # The route reads the card back through the same selector as a command
        # card, after renaming the action; the real row must be selectable.
        rows = [
            {**row, "action": ACTION_PC_COMMAND}
            for row in await store.list_recent_claw_runs(UID, limit=10)
            if row.get("action") == "desktop_type"
        ]
        selected = select_pending_command_row(
            rows, conversation_id=conversation, now=datetime.now(timezone.utc),
        )
        assert selected is not None and selected["run_id"] == "run_type_card"
        # A command-card consume never takes a typed-value card.
        assert await store.consume_pc_command_confirmation(UID, "run_type_card") is False
        first, second = await asyncio.gather(
            store.consume_pc_command_confirmation(UID, "run_type_card", action="desktop_type"),
            store.consume_pc_command_confirmation(UID, "run_type_card", action="desktop_type"),
        )
        assert sorted([first, second]) == [False, True]
        assert await store.consume_pc_command_confirmation(
            UID, "run_type_card", action="desktop_type") is False

    asyncio.run(scenario())


def test_a_command_card_is_not_taken_as_a_typed_value_card(tmp_path):
    async def scenario():
        store = _store(tmp_path)
        await _stage(store, "run_command_card", action="pc_command",
                     status=STATUS_AWAITING_CONFIRMATION)
        assert await store.consume_pc_command_confirmation(
            UID, "run_command_card", action="desktop_type") is False
        assert await store.consume_pc_command_confirmation(UID, "run_command_card") is True

    asyncio.run(scenario())


def test_only_card_actions_may_wait_or_be_consumed(tmp_path):
    async def scenario():
        store = _store(tmp_path)
        with pytest.raises(HistoryError):
            await _stage(store, "run_task", action="desktop_task",
                         status=STATUS_AWAITING_CONFIRMATION)
        # A typed value that ran straight away is ``pending`` and is no card.
        await _stage(store, "run_typed_now", action="desktop_type", status="pending")
        assert await store.consume_pc_command_confirmation(
            UID, "run_typed_now", action="desktop_type") is False
        assert await store.consume_pc_command_confirmation(
            UID, "run_typed_now", action="desktop_task") is False

    asyncio.run(scenario())
