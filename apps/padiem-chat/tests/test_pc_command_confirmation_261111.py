"""PC terminal command confirmation gate (2026-11-11, internal audit H8 follow-up).

The explicit backtick lane used to execute every matched command without a
second step, including a command sitting inside a pasted document or a
multi-line body. The no-confirmation case is now a typed short one-liner;
everything else shows a one-line confirmation card, and the owner's next bare
affirmative turn re-derives the command from the SERVER-staged pending row —
never from a browser-provided card.

Claims verified here:
(a) a typed short one-liner stays on the direct path (existing behavior);
(b) a long paste or a multi-line body with a backtick command gets the card;
(c) "네" confirms the staged command exactly once, then the card is consumed;
(d) non-affirmative replies, another conversation, an aged card or a
    mismatched staged turn never confirm;
(e) with a stored delegation rule the PC file actions keep their existing
    behavior, and without one a write/move/delete defaults to asking.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import chat_pc_command as lane
from app.pc_command_confirmation import (
    DIRECT_COMMAND_MAX_CHARS,
    PENDING_PC_COMMAND_MAX_AGE_SECONDS,
    STATUS_AWAITING_CONFIRMATION,
    binds_row_to_turn,
    confirmation_card,
    direct_command_eligible,
    is_affirmative_reply,
    select_pending_command_row,
)

CONVERSATION = "chat_conversation_1"
SHORT_TURN = "내 PC에서 `whoami` 실행해"
SHORT_COMMAND = "whoami"
NOW = datetime.now(timezone.utc)


def _row(*, title="Chat: " + SHORT_TURN, conversation=CONVERSATION, created=None,
         action="pc_command", status=STATUS_AWAITING_CONFIRMATION, run_id="chat_pcq_card1"):
    return {
        "run_id": run_id,
        "action": action,
        "status": status,
        "title": title,
        "conversation_id": conversation,
        "created_at": (created or NOW).isoformat().replace("+00:00", "Z"),
    }


class _Store:
    """The three store surfaces the confirm flow touches."""

    def __init__(self, *, rows=(), messages=None):
        self.rows = list(rows)
        self.messages = messages if messages is not None else [
            {"role": "user", "content": SHORT_TURN},
        ]
        self.begun: list[dict] = []
        self.recorded: list[dict] = []
        self.statuses: list[tuple] = []

    async def list_recent_claw_runs(self, uid, limit=10, workspace_id=None):
        return list(self.rows)

    async def get_conversation_model_context(self, uid, conversation_id, *, product_scope):
        return {"id": conversation_id, "messages": list(self.messages)}

    async def begin_chat_stream_turn(self, **fields):
        self.begun.append(dict(fields))
        return "chat_conversation_1"

    async def record_claw_run(self, **fields):
        self.recorded.append(dict(fields))

    async def consume_pc_command_confirmation(self, uid, run_id):
        # The store's conditional update: only an unanswered card matches.
        self.statuses.append((uid, run_id, "cancelled"))
        for row in self.rows:
            if (row.get("run_id") == run_id and row.get("action") == "pc_command"
                    and row.get("status") == STATUS_AWAITING_CONFIRMATION):
                row["status"] = "cancelled"
                return True
        return False


# --- (a) the typed short one-liner keeps its direct path -------------------


def test_a_typed_short_one_liner_stays_direct():
    assert direct_command_eligible(SHORT_TURN, SHORT_COMMAND)
    assert direct_command_eligible(
        "내 PC에서 `Get-Process | Select-Object -First 20` 실행해",
        "Get-Process | Select-Object -First 20",
    )


def test_the_lane_still_recovers_the_command_from_the_short_one_liner():
    assert lane.chat_pc_command_for_turn(SHORT_TURN) == SHORT_COMMAND


@pytest.mark.parametrize("turn,command", [
    ("내 PC에서 `" + "Get-ChildItem -Recurse " * 30 + "` 실행해",
     ("Get-ChildItem -Recurse " * 30).strip()),
    ("문서 초안입니다.\n내 PC에서 `whoami` 실행해", "whoami"),
    ("내 PC에서 `Get-Process\nGet-Location` 실행해", "Get-Process\nGet-Location"),
], ids=["long-paste", "multi-line-turn", "multi-line-command"])
def test_pasted_or_multiline_commands_leave_the_direct_path(turn, command):
    assert lane.chat_pc_command_for_turn(turn) == command
    assert not direct_command_eligible(turn, command)


def test_the_cap_is_explicit_and_enforced():
    edge = "a" * DIRECT_COMMAND_MAX_CHARS
    assert direct_command_eligible("내 PC에서 `" + edge + "` 실행해", edge)
    assert not direct_command_eligible("내 PC에서 `" + edge + "b` 실행해", edge + "b")


# --- (b) the card ------------------------------------------------------------


def test_the_card_shows_the_exact_command_in_one_line():
    card = confirmation_card("whoami")
    assert "\n" not in card
    assert "whoami" in card and card.endswith("`whoami`")
    assert "네" in card


def test_affirmative_replies_are_bare_yes_only():
    for reply in ("네", "예", "yes", "OK", "진행해!"):
        assert is_affirmative_reply(reply)
    for reply in ("네 (첨부 확인)", "알겠어요", "그래요, 그리고 이것도 해줘", ""):
        assert not is_affirmative_reply(reply)


# --- the pending row selection ------------------------------------------------


def test_the_row_selection_binds_conversation_action_status_and_age():
    assert select_pending_command_row(
        [_row()], conversation_id=CONVERSATION, now=NOW) is not None
    assert select_pending_command_row(
        [_row()], conversation_id="other_conversation", now=NOW) is None
    assert select_pending_command_row(
        [_row(created=NOW - timedelta(seconds=PENDING_PC_COMMAND_MAX_AGE_SECONDS + 1))],
        conversation_id=CONVERSATION, now=NOW) is None
    assert select_pending_command_row(
        [_row(status="completed")], conversation_id=CONVERSATION, now=NOW) is None
    assert select_pending_command_row(
        [_row(action="txt_read")], conversation_id=CONVERSATION, now=NOW) is None
    # #7566: a command that ran straight away is "pending", never a card.
    assert select_pending_command_row(
        [_row(status="pending")], conversation_id=CONVERSATION, now=NOW) is None
    # Newest row wins.
    assert select_pending_command_row(
        [_row(), _row(run_id="chat_pcq_card2",
                      created=NOW - timedelta(seconds=30))],
        conversation_id=CONVERSATION, now=NOW).get("run_id") == "chat_pcq_card1"


def test_the_row_binding_rejects_a_different_staged_turn():
    assert binds_row_to_turn(_row(), SHORT_TURN)
    assert not binds_row_to_turn(_row(title="Chat: 다른 요청이었습니다"), SHORT_TURN)
    assert not binds_row_to_turn(_row(title="누가 만든 행"), SHORT_TURN)


# --- (c) stage and confirm through the Chat lane ------------------------------


def test_staging_shows_the_card_and_dispatches_nothing():
    store = _Store()
    response = asyncio.run(lane.stage_pc_command_confirmation(
        object(), uid="owner", user_text=SHORT_TURN, command=SHORT_COMMAND,
        pc_context={"workspace_id": "workspace_1"}, conversation_id=None,
        store=store,
    ))
    body = json.loads(response.body)
    assert response.status_code == 200
    assert body["decision_status"] == "pc_command_confirm"
    assert "whoami" in body["answer"] and "네" in body["answer"]
    assert body["conversation_id"] == "chat_conversation_1"
    assert store.begun[0]["user_text"] == SHORT_TURN
    assert store.recorded[0]["action"] == "pc_command"
    # #7566: a card is staged in its own status, apart from running commands.
    assert store.recorded[0]["status"] == STATUS_AWAITING_CONFIRMATION
    assert store.recorded[0]["title"].startswith("Chat: ")
    assert "dispatch" not in store.recorded[0]


def _confirm(store, *, reply="네", conversation=CONVERSATION):
    return asyncio.run(lane.resolve_confirmed_pc_command(
        store, "owner", reply, conversation))


def test_the_affirmative_turn_returns_the_staged_command_and_consumes_the_card():
    store = _Store(rows=[_row()])
    assert _confirm(store) == SHORT_COMMAND
    assert store.statuses == [("owner", "chat_pcq_card1", "cancelled")]
    # The consumed card answers exactly one execution.
    assert _confirm(store) is None


def test_a_second_command_request_replaces_the_consumed_card():
    store = _Store(rows=[_row(run_id="chat_pcq_card1")])
    assert _confirm(store) == SHORT_COMMAND
    store.rows = [_row(run_id="chat_pcq_card2", title="Chat: 내 PC에서 `hostname` 실행해")]
    store.messages = [{"role": "user", "content": "내 PC에서 `hostname` 실행해"}]
    assert _confirm(store) == "hostname"


def test_non_affirmative_or_cross_conversation_or_stale_never_confirm():
    assert _confirm(_Store(rows=[_row()]), reply="알겠어요") is None
    assert _confirm(_Store(rows=[_row()]), conversation="other_conversation") is None
    stale = _row(created=NOW - timedelta(seconds=PENDING_PC_COMMAND_MAX_AGE_SECONDS + 5))
    assert _confirm(_Store(rows=[stale])) is None
    assert _confirm(_Store(rows=[_row(status="failed")])) is None


def test_a_mismatched_staged_turn_never_confirms():
    store = _Store(
        rows=[_row()],
        messages=[{"role": "user", "content": "전혀 다른 질문입니다"}],
    )
    assert _confirm(store) is None


def test_a_broken_store_never_confirms():
    assert _confirm(_Store(rows=[], messages=[])) is None
