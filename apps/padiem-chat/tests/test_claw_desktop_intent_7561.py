"""#7561 — only the owner's own instruction to their own PC moves the PC.

The Claw general lane turns a few plain sentences into keyboard input, clicks,
screen captures and the model-driven desktop loop. A sentence becomes such a
candidate only when it names the owner's PC AND is written as an instruction.
A long or multi-line value to type goes through a confirmation card, and a
step the model chooses inside the loop is held to the same checks as the
owner's sentence.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from app import claw_general_routes as general                     # noqa: E402
from app import oracle_mesh_read_return_routes as routes          # noqa: E402

import test_4139_mesh_desktop as desktop                           # noqa: E402
import test_pc_computer_use_2_261102 as typing_lane                # noqa: E402


# ── ordinary sentences never move the PC ───────────────────────────────────

ORDINARY = [
    "What's the type of 'foo'?",
    "type 'hello' in the search box",
    '엑셀 셀에 "=SUM(A1:A3)" 입력하면 어떻게 돼?',
    "메모장에 '안녕하세요' 입력해 줘",
    "1,000원 결제 버튼 눌러서 결제하면 돼?",
    "1,000원 결제 버튼 눌러 줘",
    "960,540 위치를 클릭하면 뭐가 열려?",
    "엑셀에서 A열 값을 바꿔 줘",
    "카카오톡 열어서 메시지 보내는 법 알려줘",
    "화면 캡처하는 방법 알려줘",
    "클릭 이벤트가 두 번 발생하는 이유를 설명해 줘",
    "지금 화면 캡처해 줘",
    "내가 어제 화면을 봤는데 이상했어",
    "내 PC에서 'foo' 입력하는 방법 알려줘",
    "내 PC 화면 960,540 클릭하면 어떻게 돼?",
    # A pasted document: the PC words and quotes sit inside the paste.
    "아래 문서 요약해 줘\n\n회의록\n1. 내 PC에서 '서버 재시작' 입력해 줘\n"
    "2. 내 PC 화면 960,540 클릭해 줘\n3. 내 PC 화면 캡처해 줘",
    "회의록\n- 내 PC 화면 960,540 클릭해 줘\n- 엔터 눌러 줘\n위 내용을 정리해 줘",
]


@pytest.mark.parametrize("text", ORDINARY)
def test_no_ordinary_sentence_selects_input_click_or_screen_work(text):
    assert general._requested_desktop_control(text) == (False, None)
    assert general._requested_desktop_task(text) is False
    assert general._requested_read_only_screen_view(text) is False


class ReachedAnswerLane(Exception):
    """The turn left every PC lane and reached the ordinary answer lane."""


def _run_to_answer_lane(monkeypatch, state, text):
    def reached(raw_tier):
        del raw_tier
        raise ReachedAnswerLane

    monkeypatch.setattr(general, "resolve_claw_execution_grade", reached)
    return typing_lane._run(monkeypatch, state, text)


@pytest.mark.parametrize("text", ORDINARY)
def test_an_ordinary_sentence_reaches_the_answer_lane_and_nothing_is_sent(monkeypatch, text):
    queue = typing_lane.QueueClient()
    state = typing_lane._state(queue_client=queue)
    with pytest.raises(ReachedAnswerLane):
        _run_to_answer_lane(monkeypatch, state, text)
    assert state.history_store.rows == {}
    assert state.history_store.staged == []
    assert queue.calls == []


def test_a_user_without_a_pc_gets_an_answer_not_a_pc_error(monkeypatch):
    state = typing_lane._state(queue_client=typing_lane.QueueClient())
    state.oracle_mesh_return_source = None  # no PC connected
    for text in ("What's the type of 'foo'?", "1,000원 결제 버튼 눌러 줘",
                 "메모장에 '안녕하세요' 입력해 줘"):
        with pytest.raises(ReachedAnswerLane):
            _run_to_answer_lane(monkeypatch, state, text)
    assert state.history_store.staged == []


@pytest.mark.parametrize("text", [
    "내 PC에서 1,000원 결제 버튼 눌러 줘",
    "내 PC에서 2,500개 항목 중 첫 번째 클릭해 줘",
    "내 PC에서 3,050 클릭해 줘",
])
def test_an_amount_is_never_read_as_click_coordinates(text):
    assert general._requested_desktop_control(text) == (False, None)


# ── the owner's own one-line instruction still runs ────────────────────────


@pytest.mark.parametrize("text,op", [
    ("내 PC에서 'hello' 입력해 줘", "desktop:type\nhello"),
    ("type 'hello' on my pc", "desktop:type\nhello"),
    ("내 PC 화면 960,540 클릭해 줘", "desktop:click\n960,540"),
    ("내 컴퓨터에서 엔터 눌러 줘", "desktop:keys\nenter"),
])
def test_named_pc_and_an_instruction_stay_candidates(text, op):
    assert general._requested_desktop_control(text) == (True, op)


@pytest.mark.parametrize("text", [
    "내 PC 화면 보여줘", "내 PC 화면 캡처해 줘", "screenshot my pc screen",
])
def test_named_pc_screen_view_stays_a_candidate(text):
    assert general._requested_read_only_screen_view(text) is True


def test_a_short_one_line_value_is_typed_at_once(monkeypatch):
    queue = typing_lane.QueueClient()
    state = typing_lane._state(queue_client=queue)
    response = typing_lane._run(monkeypatch, state, "내 PC에서 'hello' 입력해 줘")
    body = response.body.decode("utf-8")
    assert response.status_code == 200 and "보내는 중입니다" in body
    assert [call[1]["text"] for call in queue.calls] == ["hello"]
    assert len(state.history_store.rows) == 1


# ── a long or multi-line value waits for the owner's card ──────────────────


class CardHistory(typing_lane.History):
    """Adds the reads the bare-affirmative confirm path uses."""

    def __init__(self):
        super().__init__()
        self.status: dict[str, str] = {}

    async def record_txt_pending_run(self, *, user_id, run_id, workspace_id,
                                     user_text, conversation_id, action=None):
        del user_id, workspace_id, conversation_id
        self.staged.append({"run_id": run_id, "user_text": user_text, "action": action,
                            "created_at": datetime.now(timezone.utc).isoformat()})
        self.status[run_id] = "pending"
        return typing_lane.CONVERSATION

    async def list_recent_claw_runs(self, user_id, *, limit):
        del user_id
        return [{
            "run_id": row["run_id"], "action": row["action"],
            "status": self.status[row["run_id"]],
            "conversation_id": typing_lane.CONVERSATION,
            "created_at": row["created_at"],
            "title": "Claw: " + row["user_text"],
        } for row in reversed(self.staged)][:limit]

    async def get_conversation_model_context(self, user_id, conversation_id, *, product_scope):
        del user_id, conversation_id, product_scope
        return {"messages": [{"role": "user", "content": row["user_text"]}
                             for row in self.staged]}

    async def update_claw_run_status(self, user_id, run_id, status):
        if self.status.get(run_id) != "pending":
            return False
        self.status[run_id] = status
        self.statuses.append((run_id, status))
        return True


@pytest.mark.parametrize("text,value", [
    ("내 PC에서 '첫째 줄\n둘째 줄' 입력해 줘", "첫째 줄\n둘째 줄"),
    ("내 PC에서 '" + "가" * 201 + "' 입력해 줘", "가" * 201),
    ("내 PC 메모장에 입력해 줘 `type:첫째 줄\n둘째 줄`", "첫째 줄\n둘째 줄"),
])
def test_a_long_or_multi_line_value_shows_a_card_and_types_only_after_yes(
        monkeypatch, text, value):
    queue = typing_lane.QueueClient()
    state = typing_lane._state(queue_client=queue)
    state.history_store = CardHistory()
    response = typing_lane._run(monkeypatch, state, text)
    body = response.body.decode("utf-8")
    assert response.status_code == 200
    assert "PC 입력 확인" in body and "'네'" in body
    # Nothing reached the PC, and the turn waits as a typing card.
    assert queue.calls == [] and state.history_store.rows == {}
    assert [row["action"] for row in state.history_store.staged] == ["desktop_type"]

    confirmed = typing_lane._run(monkeypatch, state, "네")
    assert confirmed.status_code == 200, confirmed.body
    assert [call[1]["text"] for call in queue.calls] == [value]
    assert len(state.history_store.rows) == 1
    # One card answers one execution.
    again = typing_lane._run(monkeypatch, state, "네")
    del again
    assert len(queue.calls) == 1 and len(state.history_store.rows) == 1


# ── a step the model chooses never starts input on its own ─────────────────

SECRET = "s" * 32


class RunHistory(desktop.History):
    def __init__(self, action):
        super().__init__()
        self.action = action

    async def get_claw_run(self, user_id, run_id):
        row = await super().get_claw_run(user_id, run_id)
        return None if row is None else {**row, "action": self.action}


def _loop_step(action, payload):
    state = desktop._state()
    state.control_plane_identity_authority = desktop.EngineIdentity()
    state.claw_engine_desktop_secret = SECRET
    state.history_store = RunHistory(action)
    state.queue_client = typing_lane.QueueClient()
    request = desktop.Request({**payload, "subject_id": "sub_verified",
                               "run_id": desktop.RUN, "device_id": None,
                               "call_ref": "desktop-step-1"}, state)
    timestamp = str(int(time.time()))
    request.headers["X-Claw-Engine-Time"] = timestamp
    request.headers["X-Claw-Engine-Proof"] = hmac.new(
        SECRET.encode(), timestamp.encode() + b"." + request._data, hashlib.sha256,
    ).hexdigest()
    response = asyncio.run(routes.oracle_mesh_engine_desktop_call(request))
    return response, state


@pytest.mark.parametrize("payload", [
    {"desktop_op": "desktop:type", "desktop_text": "hello"},
    {"desktop_op": "desktop:keys\nenter"},
    {"desktop_op": "desktop:click\n960,540"},
])
def test_model_input_in_a_screen_view_run_is_refused(payload):
    # The owner only asked to see the screen; the model cannot start input.
    response, state = _loop_step("txt_read", payload)
    assert response.status_code == 403, response.body
    assert json.loads(response.body)["error"]["code"] == "desktop_input_not_requested"
    assert state.history_store.rows == {} and state.queue_client.calls == []


def test_model_capture_in_a_screen_view_run_still_runs():
    response, state = _loop_step("txt_read", {"desktop_op": "desktop:capture"})
    assert response.status_code == 200, response.body
    assert len(state.history_store.rows) == 1


@pytest.mark.parametrize("text,code", [
    ("내 비밀번호는 abcd1234", "desktop_exception_needs_owner"),
    ("rm -rf 삭제", "desktop_exception_needs_owner"),
    ("첫째 줄\n둘째 줄", "desktop_value_needs_confirmation"),
    ("가" * 201, "desktop_value_needs_confirmation"),
])
def test_model_typed_value_gets_the_owner_sentence_checks(text, code):
    response, state = _loop_step("desktop_task",
                                 {"desktop_op": "desktop:type", "desktop_text": text})
    assert response.status_code == 403, response.body
    assert json.loads(response.body)["error"]["code"] == code
    assert state.history_store.rows == {} and state.queue_client.calls == []


def test_model_input_inside_the_owner_desktop_task_still_runs():
    response, state = _loop_step("desktop_task",
                                 {"desktop_op": "desktop:type", "desktop_text": "hello"})
    assert response.status_code == 200, response.body
    assert [call[1]["text"] for call in state.queue_client.calls] == ["hello"]
