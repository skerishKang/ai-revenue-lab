"""261105: 파일 도구 거절도 분기 이름을 코드로 남긴다.

04:50 pc_list는 status=unavailable로 끝났지만, 실제로는 엔진 승인 단계가
`entitlement_unavailable`로 거절한 것이었고 큐에는 디스패치가 없었다.
dispatch는 ChatPCDriveError를 받으면 사유를 자유 문장 deny_reason에만 두어
클라이언트가 "PC가 꺼졌다"와 "엔진 승인이 실패했다"를 구분할 수 없었다.
"""
from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace

from app import mcp_gateway_dispatch as gateway_dispatch
from app import mcp_gateway_execution as gateway_execution
from app.chat_pc_drive import ChatPCDriveError

UID = "usr_" + "a" * 32
NODE = "k0pVCZx5VqYn8P9FW23CaqTNZWHGSlLASVKF1tqJTPRjRGBOhcTfgZbmfi$D62t1"


class _Store:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def audit(self, **kwargs):
        self.rows.append(kwargs)

    async def consume_matching_approval(self, **kwargs):
        return None


def _dispatch(executor):
    store = _Store()
    state = SimpleNamespace(mcp_gateway_store=store, mcp_gateway_executor=executor)
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    principal = {"owner_id": UID, "device_id": NODE, "token_id": "mcp_" + "b" * 32}
    outcome = asyncio.run(gateway_dispatch.dispatch_mcp_tool(
        request, principal, "pc_list", {"path": "D:\\"}))
    return outcome, store


def _refusing_engine(code="entitlement_unavailable"):
    async def executor(request, principal, tool_name, arguments, *, approval=None):
        raise ChatPCDriveError("chat_pc_engine_unavailable",
                               "PC 파일 작업을 완료하지 못했습니다.",
                               503, cause=code)
    return executor


def test_engine_refusal_with_a_branch_code_is_failed_and_named():
    outcome, store = _dispatch(_refusing_engine())
    assert outcome["status"] == "failed"
    assert outcome["code"] == "entitlement_unavailable"
    assert outcome["deny_reason"] == "entitlement_unavailable"
    assert outcome["answer"] == "PC 파일 작업을 완료하지 못했습니다."
    assert store.rows[-1]["status"] == "failed"


def test_engine_error_without_a_named_branch_stays_unavailable():
    async def executor(request, principal, tool_name, arguments, *, approval=None):
        raise ChatPCDriveError("chat_pc_files_unavailable",
                               "PC 파일 도구를 현재 사용할 수 없습니다.")

    outcome, _ = _dispatch(executor)
    assert outcome["status"] == "unavailable"
    assert outcome["code"] == "chat_pc_files_unavailable"


def test_operation_event_carries_the_refusal_code(caplog):
    # request_telemetry disables propagation on this logger, so attach the
    # handler directly instead of reading through the root logger.
    audit_logger = logging.getLogger("padiem_chat.request")
    audit_logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger="padiem_chat.request")
    _dispatch(_refusing_engine())
    events = [json.loads(record.message) for record in caplog.records
              if record.message.startswith("{")]
    final = [event for event in events if event.get("status") == "failed"]
    assert final and final[-1]["code"] == "entitlement_unavailable"
    assert final[-1]["tool"] == "pc_list"


def test_a_completed_file_answer_keeps_its_status():
    async def executor(request, principal, tool_name, arguments, *, approval=None):
        return {"status": "completed", "output": {"entries": []}}

    outcome, _ = _dispatch(executor)
    assert outcome["status"] == "completed"
    assert "code" not in outcome


def test_a_broken_engine_answer_names_its_branch():
    answer = gateway_execution._invalid_engine_answer()
    assert answer["status"] == "unavailable"
    assert answer["code"] == "pc_engine_result_invalid"
    assert answer["answer"] == "PC 작업 결과를 확인하지 못했습니다."
