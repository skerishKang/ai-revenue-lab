"""#7566 — one confirmation card runs its command at most once.

Two ways the same PC command ran twice:

1. A short one-line command runs straight away and records a ``pc_command`` run
   as ``pending`` — the same action and status a confirmation card used. A later
   "네" in that conversation found that row, re-derived the command from the turn
   before it and ran it again.
2. Two "네" for one real card (double click, retry) both consumed the card: the
   consume was ``update_claw_run_status``, whose only condition is
   ``status<>'completed'``, so an already consumed (``cancelled``) card matched a
   second time.

These tests drive the real Chat lane functions in the order the orchestration
route calls them, against the real ``D1HistoryStore`` SQL. Only the PC dispatch
itself is replaced, by a counter: nothing reaches a PC.
"""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app import chat_pc_command as lane
from app import oracle_mesh_read_return_routes as mesh_routes
from app.d1_sqlite import SqliteD1
from app.history import D1HistoryStore
from app.local_cpython import apply_migrations
from app.pc_command_confirmation import (
    STATUS_AWAITING_CONFIRMATION,
    direct_command_eligible,
    select_pending_command_row,
)

UID = "usr_" + "7" * 32
WORKSPACE = "ws-7566"
PC_CONTEXT = {"workspace_id": WORKSPACE, "pc_tools": {"device_id": "device-1"}}
DIRECT_TURN = "내 PC에서 `whoami` 실행해"
CARD_TURN = "문서 초안입니다.\n내 PC에서 `Remove-Item C:/tmp/a.txt` 실행해"
CARD_COMMAND = "Remove-Item C:/tmp/a.txt"


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


def fixture(tmp_path):
    """The real store over every committed migration, as the host runs it."""
    connection = sqlite3.connect(str(tmp_path / "chat.sqlite3"), isolation_level=None)
    connection.row_factory = sqlite3.Row
    apply_migrations(connection)
    connection.execute(
        "INSERT INTO users (id, auth_provider, provider_subject, email, display_name, "
        "picture_url, created_at, updated_at) VALUES (?, 'google', 'sub_7566', "
        "'owner@example.test', '', '', '2026-11-12T00:00:00Z', '2026-11-12T00:00:00Z')",
        (UID,),
    )
    return D1HistoryStore(SqliteD1(connection), full_context_bucket=_Bucket()), None


@pytest.fixture()
def dispatched(monkeypatch):
    sent: list[str] = []

    async def count(request, *, command, wire, **_kwargs):
        sent.append(command)
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(mesh_routes, "dispatch_oracle_mesh_command_intent", count)
    return sent


def _request():
    return SimpleNamespace(state=SimpleNamespace(), headers={})


async def _chat_turn(store, text, conversation_id):
    """The orchestration route's PC command step, in its own order."""
    confirmed = await lane.resolve_confirmed_pc_command(store, UID, text, conversation_id)
    if confirmed is not None:
        return await lane.dispatch_chat_pc_command(
            _request(), uid=UID, raw={}, user_text=text, command=confirmed,
            pc_context=PC_CONTEXT, conversation_id=conversation_id, store=store,
        )
    command = lane.chat_pc_command_for_turn(text)
    if command is None:
        return None
    if direct_command_eligible(text, command):
        return await lane.dispatch_chat_pc_command(
            _request(), uid=UID, raw={}, user_text=text, command=command,
            pc_context=PC_CONTEXT, conversation_id=conversation_id, store=store,
        )
    return await lane.stage_pc_command_confirmation(
        _request(), uid=UID, user_text=text, command=command,
        pc_context=PC_CONTEXT, conversation_id=conversation_id, store=store,
    )


def _conversation(response) -> str:
    import json

    return json.loads(response.body)["conversation_id"]


def test_yes_after_a_command_that_ran_straight_away_runs_nothing(tmp_path, dispatched):
    store, _bucket = fixture(tmp_path)
    first = asyncio.run(_chat_turn(store, DIRECT_TURN, None))
    assert first.status_code == 200 and dispatched == ["whoami"]

    # "네" to the "실행하는 중입니다" notice while the result is still on its way.
    asyncio.run(_chat_turn(store, "네", _conversation(first)))

    assert dispatched == ["whoami"]
    runs = asyncio.run(store.list_recent_claw_runs(UID, limit=10))
    # The running command's own row is untouched by the "네".
    assert [(run["action"], run["status"]) for run in runs] == [("pc_command", "pending")]


def test_a_card_answered_twice_at_once_runs_its_command_once(tmp_path, dispatched):
    store, _bucket = fixture(tmp_path)
    card = asyncio.run(_chat_turn(store, CARD_TURN, None))
    assert dispatched == []
    conversation = _conversation(card)

    # Both requests read the card before either consumes it: the order two
    # concurrent requests actually have.
    both_read = asyncio.Event()
    readers = 0
    real_list = store.list_recent_claw_runs

    async def list_then_wait(*args, **kwargs):
        nonlocal readers
        rows = await real_list(*args, **kwargs)
        readers += 1
        if readers >= 2:
            both_read.set()
        await asyncio.wait_for(both_read.wait(), timeout=5)
        return rows

    store.list_recent_claw_runs = list_then_wait

    async def two_yeses():
        return await asyncio.gather(
            lane.resolve_confirmed_pc_command(store, UID, "네", conversation),
            lane.resolve_confirmed_pc_command(store, UID, "네", conversation),
        )

    confirmed = [command for command in asyncio.run(two_yeses()) if command is not None]
    assert confirmed == [CARD_COMMAND]


def test_a_card_runs_once_and_a_later_yes_runs_nothing(tmp_path, dispatched):
    store, _bucket = fixture(tmp_path)
    card = asyncio.run(_chat_turn(store, CARD_TURN, None))
    conversation = _conversation(card)
    asyncio.run(_chat_turn(store, "네", conversation))
    assert dispatched == [CARD_COMMAND]
    # A retried "네" after the card was consumed.
    asyncio.run(_chat_turn(store, "네", conversation))
    assert dispatched == [CARD_COMMAND]


def test_the_card_row_is_the_only_row_a_yes_can_select(tmp_path, dispatched):
    store, _bucket = fixture(tmp_path)
    card = asyncio.run(_chat_turn(store, CARD_TURN, None))
    runs = asyncio.run(store.list_recent_claw_runs(UID, limit=10))
    assert [(run["action"], run["status"]) for run in runs] == [
        ("pc_command", STATUS_AWAITING_CONFIRMATION),
    ]
    row = select_pending_command_row(
        runs, conversation_id=_conversation(card), now=datetime.now(timezone.utc),
    )
    assert row is not None and row["run_id"] == runs[0]["run_id"]


def test_the_store_consumes_a_card_exactly_once(tmp_path):
    """The Claw card is staged by ``record_txt_pending_run``; same consume."""
    store, _bucket = fixture(tmp_path)
    run_id = "claw_run_7566"
    asyncio.run(store.record_txt_pending_run(
        user_id=UID, run_id=run_id, workspace_id=WORKSPACE, user_text=CARD_TURN,
        conversation_id=None, action="pc_command", status=STATUS_AWAITING_CONFIRMATION,
    ))

    async def race():
        return await asyncio.gather(
            store.consume_pc_command_confirmation(UID, run_id),
            store.consume_pc_command_confirmation(UID, run_id),
        )

    assert sorted(asyncio.run(race())) == [False, True]
    assert asyncio.run(store.consume_pc_command_confirmation(UID, run_id)) is False
    # Another owner can never consume it, and a running command never matches.
    other = "claw_run_7566_direct"
    asyncio.run(store.record_txt_pending_run(
        user_id=UID, run_id=other, workspace_id=WORKSPACE, user_text=DIRECT_TURN,
        conversation_id=None, action="pc_command",
    ))
    assert asyncio.run(store.consume_pc_command_confirmation(UID, other)) is False
    assert asyncio.run(store.consume_pc_command_confirmation("usr_someone_else", run_id)) is False


def test_only_a_pc_command_card_may_be_staged_as_awaiting_confirmation(tmp_path):
    from app.history import HistoryError

    store, _bucket = fixture(tmp_path)
    with pytest.raises(HistoryError):
        asyncio.run(store.record_txt_pending_run(
            user_id=UID, run_id="claw_run_7566_txt", workspace_id=WORKSPACE,
            user_text="파일 읽어줘", conversation_id=None, action="txt_read",
            status=STATUS_AWAITING_CONFIRMATION,
        ))
