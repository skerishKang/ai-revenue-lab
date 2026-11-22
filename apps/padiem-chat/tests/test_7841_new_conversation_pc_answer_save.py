"""#7841: 새 대화 PC 도구 턴이 503 으로 뒤집히지 않고 답변·conversation_id 를 낸다.

운영 실측(a7cf7b46, canary run 43862546352): path=model_first_tool, forced=required,
tool_called=1, PC 디스패치·결과 기록·finish 200, `/api/orchestration` 200(16.5초)
인데 응답 스트림은 `chat_pc_store_unavailable` 로 끝났다. 같은 턴의 서버 줄은
`pc_result stage=not_appended` — 검증 결과가 실행 행에 붙지 않아 실행 행의
`result_summary` 가 비어 있었고, `_append_lane_answer` 가 그 상태를 "저장 거절"로
돌려주자 모델 우선 레인이 그것을 503 으로 바꿨다.

기존 PC 레인 SSE 경로(`finish_chat_stream_turn`)는 같은 거절을 오류로 만들지 않고
그 턴의 대화 id 를 그대로 돌려준다. 여기서 고정하는 것은 그 판정과 같아진 상태다:

1. 새 대화(conversation_id 없음) + 도구 1회: 답변이 저장되고 대화 id 가 반환된다.
2. 검증 결과가 실행 행에 없어 저장을 건너뛴 턴: 503 이 아니고, 답변과 대화 id 가
   그대로 반환된다(운영에서 관측된 상태).
3. 기존 대화의 턴: 그 대화 id 가 그대로 반환된다.
4. 저장소가 예외를 내는 진짜 장애: 종전과 같이 `chat_pc_store_unavailable` 이다.
"""
from __future__ import annotations

import asyncio

import pytest

from app.chat_pc_drive import (
    ChatPCDriveError,
    _execute_chat_pc_files_lane,
    chat_pc_plan_for_tool,
)

import _support.chat_pc_drive as legacy

ANSWER = "C 드라이브와 D 드라이브가 있습니다."
STAGED = "chat_" + "s" * 32
OWN = "usr_chat_1"


class _Store:
    """The run row the lane reads back, with the production states selectable.

    ``summary=None`` is the observed `pc_result stage=not_appended` state: the
    run exists in the conversation but carries no verified result to seal.
    """

    def __init__(self, *, summary="no_exit_code", raise_on_read: bool = False):
        self.summary = summary
        self.raise_on_read = raise_on_read
        self.staged = None
        self.appended = []

    async def record_chat_pc_drive_run(self, *, user_id, run_id, workspace_id,
                                       user_text, conversation_id, **extra):
        self.staged = {
            "user_id": user_id, "run_id": run_id,
            "workspace_id": workspace_id, "conversation_id": conversation_id,
            **extra,
        }
        return STAGED

    async def get_claw_run(self, uid, run_id):
        if self.raise_on_read:
            raise RuntimeError("store unavailable")
        row = {"run_id": run_id, "conversation_id": STAGED,
               "workspace_id": "tenant-1", "action": "pc_drive_query"}
        if self.summary is not None:
            row["result_summary"] = self.summary
        return row

    async def append_local_task_result(self, **fields):
        self.appended.append(fields)
        return True


class _Bridge(legacy._Bridge):
    def __init__(self, answer: str = ANSWER):
        super().__init__(answer)


def _lane(store, bridge, *, conversation_id=None):
    request, _, _, _ = legacy._request(model_answers=[])
    request.app.state.history_store = store
    request.app.state.orchestration_bridge = bridge
    return asyncio.run(_execute_chat_pc_files_lane(
        request,
        store=store,
        uid=OWN,
        subject_id="sub_" + "a" * 32,
        workspace_id="tenant-1",
        user_text="연결된 PC의 드라이브 목록만 알려 주세요",
        skill=None,
        model_id="model-x",
        conversation_id=conversation_id,
        device_id=None,
        run_id="chat_pcq_" + "d" * 32,
        agent_plan=chat_pc_plan_for_tool("query_drives"),
    ))


def test_a_new_conversation_tool_turn_saves_the_answer_and_returns_its_id():
    store = _Store()
    answer, conversation_id = _lane(store, _Bridge())

    assert answer == ANSWER
    assert conversation_id == STAGED
    assert store.staged["conversation_id"] is None
    # The answer lands in the conversation this turn staged.
    assert [row["message_id"] for row in store.appended] == ["chat_pcq_" + "d" * 32 + "_answer"]
    assert store.appended[0]["summary"] == "no_exit_code"


def test_a_turn_without_a_stored_verified_result_is_not_a_503():
    """The observed production state (`pc_result stage=not_appended`)."""

    store = _Store(summary=None)
    answer, conversation_id = _lane(store, _Bridge())

    assert answer == ANSWER
    assert conversation_id == STAGED
    # Nothing is invented as the run's terminal result.
    assert store.appended == []


def test_an_existing_conversation_keeps_receiving_the_answer():
    store = _Store()
    existing = "chat_" + "e" * 32
    answer, conversation_id = _lane(store, _Bridge(), conversation_id=existing)

    assert answer == ANSWER
    assert conversation_id == STAGED
    assert store.appended[0]["run_id"].startswith("chat_pcq_")


def test_a_store_that_raises_still_reports_the_store_as_unavailable():
    store = _Store(raise_on_read=True)

    with pytest.raises(ChatPCDriveError) as raised:
        _lane(store, _Bridge())

    assert raised.value.code == "chat_pc_store_unavailable"
