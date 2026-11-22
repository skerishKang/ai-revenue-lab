"""#7841: 허용 범위 밖 위치는 오류가 아니라 안내로 답한다.

운영 실측(c25d2e30, run 43853199977): 모델이 PC 도구를 골라 실행했고, 드라이브
최상위 목록 요청이 기존 경로 규칙에 걸려 `oracle_mesh_file_path_invalid` 로
끝났다. 그 위치를 여는 것은 권한 범위를 넓히는 일이므로, 대신 그 턴은 볼 수
있는 범위를 알려 주는 문장으로 답한다. 범위 규칙 자체는 그대로다.
"""
from __future__ import annotations

import asyncio

from app.chat_pc_drive import (
    PC_PATH_SCOPE_GUIDANCE,
    PC_PATH_SCOPE_REFUSALS,
    _execute_chat_pc_files_lane,
    chat_pc_plan_for_tool,
)
from app.orchestration_bridge import B62OrchestrationError

from _support.chat_pc_drive import _Bridge, _request


def _lane(bridge):
    request, _, _, store = _request(model_answers=[])
    request.app.state.orchestration_bridge = bridge
    return asyncio.run(_execute_chat_pc_files_lane(
        request,
        store=store,
        uid="usr_chat_1",
        subject_id="sub_" + "a" * 32,
        workspace_id="tenant-1",
        user_text="연결된 PC의 드라이브 최상위 목록만 알려 주세요",
        skill=None,
        model_id="model-x",
        conversation_id=None,
        device_id="dev_" + "a" * 32,
        agent_plan=chat_pc_plan_for_tool("query_drives"),
    ))


def test_a_place_outside_the_grant_answers_with_guidance():
    class Bridge(_Bridge):
        async def start(self, **fields):
            self.requests.append(fields)
            raise B62OrchestrationError(
                "pc_files_path_invalid", "요청한 경로를 사용할 수 없습니다.",
                status_code=422,
            )

    bridge = Bridge("unused")
    answer, conversation_id = _lane(bridge)

    assert answer == PC_PATH_SCOPE_GUIDANCE
    # The turn still lands in the conversation it was staged for.
    assert conversation_id and conversation_id.startswith("chat_")


def test_the_engine_spelling_of_the_same_refusal_is_recognised():
    class Bridge(_Bridge):
        async def start(self, **fields):
            raise B62OrchestrationError(
                "oracle_mesh_file_path_invalid", "요청한 경로를 사용할 수 없습니다.",
                status_code=422,
            )

    answer, _ = _lane(Bridge("unused"))

    assert answer == PC_PATH_SCOPE_GUIDANCE
    assert PC_PATH_SCOPE_REFUSALS == {
        "pc_files_path_invalid", "oracle_mesh_file_path_invalid",
    }


def test_an_allowed_folder_still_answers_from_the_engine():
    answer, _ = _lane(_Bridge("C: 드라이브가 있습니다."))

    assert answer == "C: 드라이브가 있습니다."
    assert answer != PC_PATH_SCOPE_GUIDANCE


def test_another_engine_failure_keeps_the_existing_error_card():
    class Bridge(_Bridge):
        async def start(self, **fields):
            raise B62OrchestrationError(
                "pc_files_run_unavailable", "AI 작업을 처리하지 못했습니다.",
                status_code=503,
            )

    request, _, _, store = _request(model_answers=[])
    request.app.state.orchestration_bridge = Bridge("unused")
    try:
        asyncio.run(_execute_chat_pc_files_lane(
            request, store=store, uid="usr_chat_1",
            subject_id="sub_" + "a" * 32, workspace_id="tenant-1",
            user_text="파일 목록 보여 줘", skill=None, model_id="model-x",
            conversation_id=None, device_id="dev_" + "a" * 32,
            agent_plan=chat_pc_plan_for_tool("query_drives"),
        ))
    except Exception as exc:  # the lane's own public error type
        assert getattr(exc, "code", None) == "chat_pc_engine_unavailable", exc
    else:  # pragma: no cover - the assertion above is the point
        raise AssertionError("an unrelated engine failure must stay an error")


def test_the_guidance_names_no_path_and_no_account_value():
    assert ":" not in PC_PATH_SCOPE_GUIDANCE.replace("C:", "")
    for token in ("dev_", "usr_", "chat_pcq_", "@", "/", "\\\\"):
        assert token not in PC_PATH_SCOPE_GUIDANCE, token