"""#7841 — a PC tool turn ends with the fixed notice inside its own window.

The fake dispatch (the orchestration bridge) reports "claimed, no result": it
accepts the call and never returns. The turn's own remaining answer budget is
the wait bound, so no second number is introduced.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app import pc_dispatch_wait_window as window
from app.chat_pc_drive import CHAT_PC_QUERY_AGENT_ID, _execute_chat_pc_files_lane
from app.orchestration_bridge import B62EngineOrchestrationBridge
from app.orchestration_timing import OrchestrationTiming

DEVICE_ID = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
GUIDANCE = (
    "PC가 응답하지 않습니다. PC가 켜져 있고 PADIEM 연결 프로그램이 실행 중인지 확인한 뒤 다시 시도해 주세요."
)
PLAN = {
    "agent_id": CHAT_PC_QUERY_AGENT_ID,
    "steps": [{"step_id": "query", "tool_id": "claw.pc.query_drives"}],
}


class _Store:
    def __init__(self) -> None:
        self.records: list[dict] = []

    async def record_chat_pc_drive_run(self, **kwargs):
        return "chat_conv"

    async def get_claw_run(self, uid, run_id):
        return {"run_id": run_id, "conversation_id": "chat_conv", "result_summary": "pending"}

    async def append_local_task_result(self, **kwargs):
        self.records.append(kwargs)
        return True

    async def append_exchange(self, *args, **kwargs):
        return "chat_conv"


class _NoResultBridge(B62EngineOrchestrationBridge):
    """Claim succeeded, no result: the call never returns on its own."""

    def __init__(self) -> None:
        super().__init__(client=object(), store=object())

    async def start(self, **kwargs):
        await asyncio.sleep(30)


class _ResultBridge(B62EngineOrchestrationBridge):
    """The normal path: a result arrives inside the window."""

    def __init__(self, answer: str) -> None:
        super().__init__(client=object(), store=object())
        self._answer = answer

    async def start(self, **kwargs):
        return SimpleNamespace(
            orchestration={},
            answer=self._answer,
            user_text=kwargs["user_text"],
            conversation_id=kwargs["conversation_id"],
        )


def _request(bridge) -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(orchestration_bridge=bridge))
    )


@pytest.fixture(autouse=True)
def _no_delegation(monkeypatch):
    import app.pc_delegation_routes as delegation

    async def _none(request, uid):
        return None

    monkeypatch.setattr(delegation, "load_pc_delegation", _none)
    window.reset_wait_reason()


async def test_no_result_inside_the_window_answers_the_fixed_notice():
    store = _Store()
    result = await _execute_chat_pc_files_lane(
        _request(_NoResultBridge()), store=store,
        uid="usr_" + "1" * 32, subject_id="sub_1", workspace_id="ws_1",
        user_text="내 PC D드라이브 목록 보여줘",
        skill=SimpleNamespace(id="auto"), model_id="test/model",
        conversation_id=None, device_id=DEVICE_ID, agent_plan=PLAN,
        result_wait_seconds=0.02,
    )

    assert result == (GUIDANCE, "chat_conv")
    assert window.last_wait_reason() == window.PC_DISPATCH_NO_RESULT_CODE
    assert len(store.records) == 1
    assert store.records[0]["content"] == GUIDANCE
    assert store.records[0]["status"] == "failed"


async def test_no_result_notice_carries_no_english_code_or_dispatch_id():
    assert "PC" in GUIDANCE
    for forbidden in ("dispatch", "dsp_", "pc_dispatch", "timeout", "tool"):
        assert forbidden not in GUIDANCE


async def test_result_inside_the_window_keeps_the_existing_answer(monkeypatch):
    store = _Store()
    result = await _execute_chat_pc_files_lane(
        _request(_ResultBridge("정상 PC 결과")), store=store,
        uid="usr_" + "1" * 32, subject_id="sub_1", workspace_id="ws_1",
        user_text="내 PC D드라이브 목록 보여줘",
        skill=SimpleNamespace(id="auto"), model_id="test/model",
        conversation_id=None, device_id=DEVICE_ID, agent_plan=PLAN,
        result_wait_seconds=1.0,
    )

    assert result == ("정상 PC 결과", "chat_conv")
    assert window.last_wait_reason() == window.PC_DISPATCH_WAIT_NONE
    assert len(store.records) == 1
    assert store.records[0]["content"] == "정상 PC 결과"
    assert store.records[0]["status"] == "completed"


async def test_absent_wait_bound_keeps_the_older_wait():
    async def _answers():
        return "결과"

    completed, value = await window.await_pc_dispatch(_answers(), wait_seconds=None)
    assert completed is True
    assert value == "결과"
    assert window.last_wait_reason() == window.PC_DISPATCH_WAIT_NONE


def test_timing_line_carries_the_reason_only_when_it_happened():
    plain = OrchestrationTiming()
    assert " reason=" not in plain.line()

    timed_out = OrchestrationTiming()
    timed_out.set_reason(window.PC_DISPATCH_NO_RESULT_CODE)
    line = timed_out.line()
    assert f" reason={window.PC_DISPATCH_NO_RESULT_CODE} " in line
    assert line.rstrip().endswith("retried=unknown")


def test_unrelated_reason_is_not_written():
    timing = OrchestrationTiming()
    timing.set_reason("some_other_reason")
    assert " reason=" not in timing.line()
