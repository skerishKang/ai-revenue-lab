"""CENTRAL #4139: only canonical, bounded Windows TXT results reach Claw."""
from __future__ import annotations

import asyncio
import hashlib
import sys
from pathlib import Path
from dataclasses import replace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.claw_local_task_result_projection import (
    LocalRunnerTerminalObservation, LocalTaskCommandCorrelation, LocalTaskOrigin,
    LocalTaskResultError, decide_local_task_result,
    project_local_runner_terminal_result, verify_broker_file_text,
)

OBS = LocalRunnerTerminalObservation(
    command_id="cmd1", run_id="run1", tool_request_ref="tool1",
    request_id="req1", revision_ref="rev1", evidence_ref="ev1",
    request_fingerprint="a" * 64, sequence=1, state="acknowledged",
    termination="exited", exit_code=0,
)
ORIGIN = LocalTaskOrigin(
    user_id="user1", run_id="run1", conversation_id="chat_" + "c" * 32, workspace_id="ws1",
    correlation=LocalTaskCommandCorrelation(
        command_id="cmd1", tool_request_ref="tool1", request_id="req1",
        revision_ref="rev1", evidence_ref="ev1", request_fingerprint="a" * 64,
    ),
)

def receipt(text="오늘 PC의 실제 테스트 파일입니다.\n"):
    return {
        "ok": True, "available": True, "kind": "file_read_text",
        "account_ref": "user1", "workspace_ref": "ws1", "run_id": "run1",
        "command_id": "cmd1", "tool_request_ref": "tool1", "request_id": "req1",
        "revision_ref": "rev1", "evidence_ref": "ev1",
        "request_fingerprint": "a" * 64, "content_utf8": text,
        "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def test_verified_korean_text_is_in_original_conversation_message():
    state, text = verify_broker_file_text(receipt(), origin=ORIGIN, observation=OBS)
    assert state == "text"
    decision = decide_local_task_result(origin=ORIGIN, observation=OBS, verified_text=text)
    assert decision.append is True
    assert decision.status == "completed"
    assert text in decision.content
    assert "PC 파일 읽기 결과:" in decision.content
    assert "로컬 러너 작업이 종료" not in decision.content


@pytest.mark.parametrize("override", [
    {"account_ref": "another"},
    {"workspace_ref": "another"},
    {"run_id": "another"},
    {"command_id": "another"},
    {"tool_request_ref": "another"},
    {"request_id": "another"},
    {"revision_ref": "another"},
    {"evidence_ref": "another"},
    {"request_fingerprint": "b" * 64},
    {"kind": "other"},
    {"content_sha256": "0" * 64},
    {"content_utf8": "변조"},
    {"raw_stdout": "not trusted"},
])
def test_foreign_spoofed_corrupt_receipts_fail_closed(override):
    value = receipt()
    value.update(override)
    with pytest.raises(LocalTaskResultError):
        verify_broker_file_text(value, origin=ORIGIN, observation=OBS)


def test_oversize_or_control_payload_refused():
    for text in ("가" * 300, "bad\x00data"):
        with pytest.raises(LocalTaskResultError):
            verify_broker_file_text(receipt(text), origin=ORIGIN, observation=OBS)


def test_pending_does_not_claim_content():
    assert verify_broker_file_text(
        {"ok": True, "available": False, "kind": "file_read_text"},
        origin=ORIGIN, observation=OBS,
    ) == ("pending", None)
    assert verify_broker_file_text(
        {"ok": True, "available": False, "kind": "other"},
        origin=ORIGIN, observation=OBS,
    ) == ("other", None)


def test_never_add_text_to_failed_or_expired_command():
    for obs in (
        replace(OBS, exit_code=1),
        replace(OBS, termination="cancelled"),
        replace(OBS, state="expired", termination=None, exit_code=None),
    ):
        with pytest.raises(LocalTaskResultError):
            verify_broker_file_text(receipt(), origin=ORIGIN, observation=obs)
        with pytest.raises(LocalTaskResultError):
            decide_local_task_result(origin=ORIGIN, observation=obs, verified_text="text")


class FakeHistory:
    def __init__(self):
        self.calls = []
    async def get_claw_run(self, user_id, run_id):
        assert user_id == "user1" and run_id == "run1"
        return {"run_id": run_id, "conversation_id": "chat_" + "c" * 32, "workspace_id": "ws1"}
    async def get_local_task_correlation(self, user_id, run_id):
        assert user_id == "user1" and run_id == "run1"
        return {
            "command_id": "cmd1", "tool_request_ref": "tool1",
            "request_id": "req1", "revision_ref": "rev1",
            "evidence_ref": "ev1", "request_fingerprint": "a"*64,
        }
    async def append_local_task_result(self, **kwargs):
        self.calls.append(kwargs)
        return True

class FakePort:
    def __init__(self, result):
        self.result = result
    async def command_result(self, **kwargs):
        assert kwargs["workspace_id"] == "ws1"
        assert kwargs["owner_id"] == "user1"
        return OBS
    async def read_verified_file_text(self, **kwargs):
        assert kwargs == {
            "owner_id": "user1", "workspace_id": "ws1",
            "run_id": "run1", "command_id": "cmd1",
        }
        return self.result


@pytest.mark.asyncio
async def test_durable_original_conversation_text_append():
    history = FakeHistory()
    outcome = await project_local_runner_terminal_result(
        history=history, result_port=FakePort(receipt()),
        user_id="user1", run_id="run1", command_id="cmd1",
        expected_workspace_id="ws1",
    )
    assert outcome.append is True
    assert len(history.calls) == 1
    assert history.calls[0]["content"].endswith(receipt()["content_utf8"])
    assert history.calls[0]["user_id"] == "user1"


@pytest.mark.asyncio
async def test_pending_file_result_does_not_consume_exactly_once_id():
    history = FakeHistory()
    outcome = await project_local_runner_terminal_result(
        history=history,
        result_port=FakePort({"ok": True, "available": False, "kind": "file_read_text"}),
        user_id="user1", run_id="run1", command_id="cmd1",
        expected_workspace_id="ws1",
    )
    assert outcome.status == "pending"
    assert outcome.append is False
    assert history.calls == []


@pytest.mark.asyncio
async def test_other_command_keeps_legacy_terminal_only_message():
    history = FakeHistory()
    outcome = await project_local_runner_terminal_result(
        history=history,
        result_port=FakePort({"ok": True, "available": False, "kind": "other"}),
        user_id="user1", run_id="run1", command_id="cmd1",
        expected_workspace_id="ws1",
    )
    assert outcome.status == "completed"
    assert len(history.calls) == 1
    assert "로컬 러너 작업이 종료" in history.calls[0]["content"]


@pytest.mark.asyncio
async def test_bad_receipt_never_appends():
    history = FakeHistory()
    forged = receipt()
    forged["account_ref"] = "another"
    with pytest.raises(LocalTaskResultError):
        await project_local_runner_terminal_result(
            history=history, result_port=FakePort(forged),
            user_id="user1", run_id="run1", command_id="cmd1",
            expected_workspace_id="ws1",
        )
    assert history.calls == []


@pytest.mark.asyncio
async def test_private_broker_file_rpc_forwards_server_scope():
    from app.claw_local_task_result_composition import BrokerAuthorityLocalRunnerResultPort
    class Binding:
        def __init__(self):
            self.calls = []
        async def read_verified_file_text(self, data):
            self.calls.append(data)
            return receipt()
    b = Binding()
    port = BrokerAuthorityLocalRunnerResultPort(b)
    result = await port.read_verified_file_text(
        owner_id="user1", workspace_id="ws1", run_id="run1", command_id="cmd1",
    )
    assert result == receipt()
    assert b.calls == [{"account_ref":"user1", "workspace_ref":"ws1",
                        "run_id":"run1", "command_id":"cmd1"}]

@pytest.mark.asyncio
async def test_absent_new_broker_rpc_keeps_original_behavior():
    from app.claw_local_task_result_composition import BrokerAuthorityLocalRunnerResultPort
    port = BrokerAuthorityLocalRunnerResultPort(object())
    assert await port.read_verified_file_text(
        owner_id="user1", workspace_id="ws1", run_id="run1", command_id="cmd1",
    ) is None
