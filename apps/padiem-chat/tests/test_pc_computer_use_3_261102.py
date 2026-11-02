"""#6460 step 3 — the screen-driven loop, its progress steps and the owner's stop.

Every test here uses injected fakes: no real PC, no real queue, no provider.
The loop itself runs on the Engine side; this file proves the Chat contract it
depends on — one dispatch per step, a typed value that never enters the record,
a stop that is authoritative for every later send, and a per-step result that
never seals the run.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from app import claw_general_routes as general                       # noqa: E402
from app import oracle_mesh_read_return_routes as routes            # noqa: E402
import app.pc_file_exchange_routes as exchange                       # noqa: E402

import test_4139_mesh_desktop as desktop                             # noqa: E402

OWNER = desktop.OWNER
RUN = desktop.RUN
DEVICE = desktop.DEVICE
SECRET = "s" * 32
# A date-shaped value that can never collide with a real timestamp: the row
# legitimately stores expires_at with today's calendar date, so a real date
# here would make the no-leak assertion fail on that one day (seen 2026-11-02).
TYPED = "2026-13-45"


# ── the task intent ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("text", [
    "메모장 열어서 오늘 날짜 적고 저장해 줘",
    "지금 커서 위치에 주소 입력해 줘",
    "계산기 실행해 줘",
    "내 PC 화면에서 메모장 열어 줘",
])
def test_a_screen_driven_task_selects_the_loop(text):
    assert general._requested_desktop_task(text) is True


@pytest.mark.parametrize("text", [
    # Other lanes own these outright.
    "내 PC 화면 보여줘",
    "내 PC에서 파일 찾아줘",
    "내 PC 드라이브 목록 보여줘",
    "브라우저 열어서 로그인해 줘",
    "엑셀 파일 열어 줘",
    "COM1 화면을 캡처해줘 `capture`",
    # Ordinary chat names no action on the PC.
    "오늘 날씨 어때",
    "메모장이 뭐야?",
])
def test_other_turns_never_enter_the_loop(text):
    assert general._requested_desktop_task(text) is False


# ── the signed Engine route ─────────────────────────────────────────────────


def _state(**overrides):
    state = desktop._state()
    state.control_plane_identity_authority = desktop.EngineIdentity()
    state.claw_engine_desktop_secret = SECRET
    for name, value in overrides.items():
        setattr(state, name, value)
    return state


def _signed(state, payload, *, subject_id="sub_verified", secret=SECRET):
    request = desktop.Request({**payload, "subject_id": subject_id}, state)
    timestamp = str(int(time.time()))
    request.headers["X-Claw-Engine-Time"] = timestamp
    request.headers["X-Claw-Engine-Proof"] = hmac.new(
        secret.encode(), timestamp.encode() + b"." + request._data,
        hashlib.sha256,
    ).hexdigest()
    return request


class Queue:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.calls = []

    async def call(self, method, **arguments):
        self.calls.append((method, arguments))
        if self.fail:
            raise RuntimeError("queue unreachable")
        return True


class CancelledRunHistory(desktop.History):
    async def get_claw_run(self, user_id, run_id):
        row = await super().get_claw_run(user_id, run_id)
        if row is not None:
            row = {**row, "status": "cancelled"}
        return row


def test_run_status_answers_the_owners_stop_and_nothing_else():
    state = _state()
    response = asyncio.run(routes.oracle_mesh_engine_desktop_call(
        _signed(state, {"run_id": RUN, "mode": "run_status"})
    ))
    body = json.loads(response.body)
    assert response.status_code == 200, body
    assert body["run"]["run_id"] == RUN
    # The fake run row is not stopped; a foreign subject never resolves.
    assert body["run"]["state"] == "waiting"
    foreign = asyncio.run(routes.oracle_mesh_engine_desktop_call(
        _signed(state, {"run_id": RUN, "mode": "run_status"},
                subject_id="sub_foreign")
    ))
    assert foreign.status_code == 401


def test_a_stopped_run_dispatches_no_new_action():
    state = _state()
    state.history_store = CancelledRunHistory()
    response = asyncio.run(routes.oracle_mesh_engine_desktop_call(
        _signed(state, {"run_id": RUN, "device_id": None,
                        "desktop_op": "desktop:keys\nctrl+s",
                        "call_ref": "desktop-step-2"})
    ))
    assert response.status_code == 409
    assert json.loads(response.body)["error"]["code"] == "oracle_mesh_run_stopped"
    assert state.history_store.rows == {}


def test_a_loop_step_is_one_tool_call_and_the_value_never_enters_the_row():
    queue = Queue()
    state = _state(queue_client=queue)
    response = asyncio.run(routes.oracle_mesh_engine_desktop_call(
        _signed(state, {"run_id": RUN, "device_id": None,
                        "desktop_op": "desktop:type",
                        "desktop_text": TYPED,
                        "call_ref": "desktop-step-4"})
    ))
    body = json.loads(response.body)
    assert response.status_code == 200, body
    assert queue.calls and queue.calls[0][0] == "deposit_desktop_text"
    assert queue.calls[0][1]["text"] == TYPED
    ref = queue.calls[0][1]["ref"]
    row = state.history_store.rows[body["dispatch"]["dispatch_id"]]
    digest = hashlib.sha256(TYPED.encode("utf-8")).hexdigest()[:8]
    assert row["command_text"] == "desktop:type\n#%d:%s:%s" % (
        len(TYPED), digest, ref)
    assert TYPED not in json.dumps(row, ensure_ascii=False)
    # The step's own scope: a loop run holds one dispatch per step.
    assert row["tool_call_ref"] == "desktop-step-4"
    assert row["tool_request_ref"] == "desktop-step-4"


def test_a_typed_value_without_the_type_op_or_the_channel_is_refused():
    state = _state(queue_client=Queue())
    wrong_op = asyncio.run(routes.oracle_mesh_engine_desktop_call(
        _signed(state, {"run_id": RUN, "device_id": None,
                        "desktop_op": "desktop:keys\nctrl+s",
                        "desktop_text": TYPED, "call_ref": "desktop-step-1"})
    ))
    assert wrong_op.status_code == 422
    assert state.history_store.rows == {}

    unreachable = _state(queue_client=Queue(fail=True))
    failed = asyncio.run(routes.oracle_mesh_engine_desktop_call(
        _signed(unreachable, {"run_id": RUN, "device_id": None,
                              "desktop_op": "desktop:type",
                              "desktop_text": TYPED,
                              "call_ref": "desktop-step-1"})
    ))
    assert failed.status_code == 503
    assert unreachable.history_store.rows == {}


def test_the_engine_body_rejects_unknown_keys():
    state = _state(queue_client=Queue())
    response = asyncio.run(routes.oracle_mesh_engine_desktop_call(
        _signed(state, {"run_id": RUN, "device_id": None,
                        "desktop_op": "desktop:capture",
                        "call_ref": "desktop-step-1",
                        "extra": "x"})
    ))
    assert response.status_code == 400
    assert state.history_store.rows == {}


@pytest.mark.parametrize("combo", [
    "alt+tab", "f5", "ctrl+shift+esc", "win+r", "alt+f4",
])
def test_the_chat_gate_accepts_the_reviewed_key_vocabulary(combo):
    assert routes._parse_desktop_op_text("desktop:keys\n" + combo) == ("keys", combo)


@pytest.mark.parametrize("combo", [
    "control+alt+delete", "ctrl+alt+del", "hyper+a", "ctrl+ctrl+a", "ctrl+",
])
def test_the_chat_gate_refuses_unknown_names_and_the_sas_chord(combo):
    assert routes._parse_desktop_op_text("desktop:keys\n" + combo) is None


def test_a_large_typed_value_fits_the_signed_envelope_and_an_oversized_one_does_not():
    queue = Queue()
    state = _state(queue_client=queue)
    # 12000 Korean characters escape to more than the old 8 KB proof envelope.
    text = "가" * 12000
    response = asyncio.run(routes.oracle_mesh_engine_desktop_call(
        _signed(state, {"run_id": RUN, "device_id": None,
                        "desktop_op": "desktop:type", "desktop_text": text,
                        "call_ref": "desktop-step-4"})
    ))
    body = json.loads(response.body)
    assert response.status_code == 200, body
    assert queue.calls[0][1]["text"] == text
    row = state.history_store.rows[body["dispatch"]["dispatch_id"]]
    assert text not in json.dumps(row, ensure_ascii=False)

    too_long = _state(queue_client=Queue())
    refused = asyncio.run(routes.oracle_mesh_engine_desktop_call(
        _signed(too_long, {"run_id": RUN, "device_id": None,
                           "desktop_op": "desktop:type",
                           "desktop_text": "가" * 20001,
                           "call_ref": "desktop-step-4"})
    ))
    assert refused.status_code == 400
    assert too_long.history_store.rows == {}


# ── a per-step result never seals the run ───────────────────────────────────


class StepHistory(desktop.History):
    def __init__(self):
        super().__init__()
        self.steps = []
        self.local_appends = []

    async def append_step_result_message(self, *, user_id, run_id, message_id, content):
        self.steps.append({"message_id": message_id, "content": content})
        return True

    async def append_local_task_result(self, **fields):
        self.local_appends.append(fields)
        return True


def test_a_loop_step_lands_as_a_message_not_as_the_run_outcome():
    state = _state()
    state.history_store = StepHistory()
    response = asyncio.run(routes.oracle_mesh_engine_desktop_call(
        _signed(state, {"run_id": RUN, "device_id": None,
                        "desktop_op": "desktop:keys\nctrl+s",
                        "call_ref": "desktop-step-2"})
    ))
    body = json.loads(response.body)
    assert response.status_code == 200, body
    row = state.history_store.rows[body["dispatch"]["dispatch_id"]]
    status, submitted, _ = desktop._submit(
        state, row, termination="acted", note="keys sent",
    )
    assert status == 200 and submitted["ok"] is True, submitted
    assert len(state.history_store.steps) == 1
    assert state.history_store.local_appends == []


def test_the_typed_step_shows_one_line_and_never_the_value():
    queue = Queue()
    state = _state(queue_client=queue)
    state.history_store = StepHistory()
    response = asyncio.run(routes.oracle_mesh_engine_desktop_call(
        _signed(state, {"run_id": RUN, "device_id": None,
                        "desktop_op": "desktop:type",
                        "desktop_text": TYPED,
                        "call_ref": "desktop-step-4"})
    ))
    body = json.loads(response.body)
    assert response.status_code == 200, body
    row = state.history_store.rows[body["dispatch"]["dispatch_id"]]
    status, submitted, _ = desktop._submit(
        state, row, termination="acted", note="typed",
    )
    assert status == 200 and submitted["ok"] is True, submitted
    message = state.history_store.steps[0]["content"]
    # One line of progress, never the value: the conversation keeps the action.
    assert "문자 입력" in message
    assert TYPED not in message


def test_the_capture_step_carries_its_screenshot_reference():
    state = _state()
    state.history_store = StepHistory()
    response = asyncio.run(routes.oracle_mesh_engine_desktop_call(
        _signed(state, {"run_id": RUN, "device_id": None,
                        "desktop_op": "desktop:capture",
                        "call_ref": "desktop-step-1"})
    ))
    body = json.loads(response.body)
    row = state.history_store.rows[body["dispatch"]["dispatch_id"]]
    status, submitted, _ = desktop._submit(
        state, row, termination="captured", note="captured", blob=desktop.JPEG,
    )
    assert status == 200 and submitted["ok"] is True, submitted
    message = state.history_store.steps[0]["content"]
    assert "화면 캡처 원문: GET /api/claw/connector/mesh-results/" in message


def test_the_composer_stop_reaches_the_server_with_the_run_id():
    source = Path(__file__).parents[1].joinpath("static/app.js").read_text("utf-8")
    start = source.index("function cancelActiveStream(")
    end = source.index("\n  function ", start + 1)
    body = source[start:end]
    assert "/api/pc/cancel" in body
    assert "activeClawRunId" in body
    assert "pc-stop-sent" in body and "pc-stop-failed" in body
    locale = Path(__file__).parents[1].joinpath("static/locale.js").read_text("utf-8")
    assert locale.count('"pc-stop-sent"') == 2
    assert locale.count('"pc-stop-failed"') == 2


# ── the owner's stop ────────────────────────────────────────────────────────


class CancelStore:
    def __init__(self, *, stopped=1, mark=True):
        self.stopped = stopped
        self.mark = mark
        self.statuses = []
        self.notices = []

    async def get_claw_run(self, user_id, run_id):
        if user_id != OWNER or run_id != "chat_pcq_" + "a" * 32:
            return None
        return {"run_id": run_id, "conversation_id": "chat_" + "c" * 32,
                "workspace_id": "tenant-ws-1", "status": "pending"}

    async def cancel_oracle_mesh_dispatches_for_run(self, *, user_id, run_id):
        del user_id, run_id
        return self.stopped

    async def update_claw_run_status(self, user_id, run_id, status):
        self.statuses.append((run_id, status))
        return self.mark

    async def append_step_result_message(self, *, user_id, run_id, message_id, content):
        self.notices.append({"message_id": message_id, "content": content})
        return True


class CancelRequest:
    def __init__(self, state, body):
        self.app = SimpleNamespace(state=state)
        self._raw = json.dumps(body).encode("utf-8")
        self.headers = {"content-type": "application/json"}

    async def body(self):
        return self._raw


def _cancel(monkeypatch, store, *, run_id="chat_pcq_" + "a" * 32):
    async def owner(request):
        del request
        return SimpleNamespace(session_id="s"), OWNER, "tenant-ws-1"

    async def read_body(request, keys, optional=frozenset()):
        raw = json.loads((await request.body()).decode("utf-8"))
        return raw if set(raw) == set(keys) else None

    monkeypatch.setattr(exchange, "_owner", owner)
    monkeypatch.setattr(exchange, "_read_body", read_body)
    state = SimpleNamespace(history_store=store)
    response = asyncio.run(exchange.pc_file_exchange_cancel(
        CancelRequest(state, {"run_id": run_id})
    ))
    return response.status_code, json.loads(response.body)


def test_the_stop_marks_the_run_and_records_its_time(monkeypatch):
    store = CancelStore()
    status, body = _cancel(monkeypatch, store)
    assert status == 200 and body["ok"] is True, body
    assert body["stopped"] == 1
    assert body["stopped_at"].endswith("Z")
    # The loop's own guard and the UI both read this one fact.
    assert store.statuses == [("chat_pcq_" + "a" * 32, "cancelled")]
    # The stop time itself is the record; no value is written anywhere.
    assert len(store.notices) == 1
    assert body["stopped_at"] in store.notices[0]["content"]
    assert "다시 보내지 않습니다" in store.notices[0]["content"]


def test_a_stop_between_dispatches_still_marks_the_run_and_records_its_time(monkeypatch):
    # Nothing was left in the queue, but the loop may still choose another
    # action: the run's own state is what stops it.
    store = CancelStore(stopped=0, mark=True)
    status, body = _cancel(monkeypatch, store)
    assert status == 200 and body["stopped"] == 0, body
    assert store.statuses == [("chat_pcq_" + "a" * 32, "cancelled")]
    assert len(store.notices) == 1
    assert body["stopped_at"] in store.notices[0]["content"]


def test_a_run_that_can_no_longer_be_stopped_writes_no_notice(monkeypatch):
    # A completed run refuses the guarded status write, so nothing is claimed.
    store = CancelStore(stopped=0, mark=False)
    status, body = _cancel(monkeypatch, store)
    assert status == 200 and body["stopped"] == 0, body
    assert store.notices == []
