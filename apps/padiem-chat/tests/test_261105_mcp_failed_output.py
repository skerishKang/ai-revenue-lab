"""#6812 후속: 비0 종료한 PC 셸이 '연결 불가'로 보이지 않게 한다.

exit 1로 끝난 작업의 출력은 사용자에게 가장 중요한 정보입니다. 출력이 없거나
읽지 못한 경우에도 상태와 종료 코드는 남기고, 그 사실을 구분되는 코드로
알립니다. `unavailable`은 결과 자체를 받지 못한 경우에만 남깁니다.
"""
from __future__ import annotations

import asyncio

from types import SimpleNamespace

from app import mcp_gateway_shell as shell
from tests.test_mcp_pc_shell_261103 import (
    DEVICE,
    JOB_ID,
    SUBJECT,
    TOKEN,
    UID,
    CommonHistory,
    ReceiptStore,
    _request,
)


def _identity():
    return {"user_id": UID, "device_id": DEVICE, "token_id": TOKEN}


def _read(history, monkeypatch, original_text):
    if original_text is None:
        monkeypatch.setattr(shell, "_read_original", _none)
    else:
        async def _original(request, **kwargs):
            return original_text
        monkeypatch.setattr(shell, "_read_original", _original)
    receipts = ReceiptStore()
    receipts.job_id = JOB_ID
    receipts.identity = _identity()
    return asyncio.run(shell.execute_pc_shell_read(
        _request(history, receipts), identity=_identity(), subject_id=SUBJECT,
        arguments={"job_id": JOB_ID},
    ))


async def _none(request, **kwargs):
    return None


def test_nonzero_exit_keeps_status_exit_code_and_output(monkeypatch):
    history = CommonHistory()
    history.state, history.exit_code, history.termination = "failed", 1, "exited"
    history.output = "K_lipvoice\r\n"
    result = _read(history, monkeypatch, history.output)
    assert result["status"] == "failed"
    assert result["exit_code"] == 1
    assert result["output"] == "K_lipvoice\r\n"
    assert result["audit"] == {"exit_code": 1, "output_bytes": 12, "output_truncated": False}
    assert "unavailable" not in str(result)


def test_nonzero_exit_without_stored_output_is_not_a_connection_failure(monkeypatch):
    history = CommonHistory()
    history.state, history.exit_code, history.termination = "failed", 1, "exited"
    result = _read(history, monkeypatch, None)
    assert result["status"] == "failed"
    assert result["exit_code"] == 1
    assert result["output"] == ""
    assert result["code"] == "pc_output_unavailable"
    assert result["output_ref"] is None
    assert "PC 작업이 끝났지만" in result["answer"]


def test_output_read_failure_has_its_own_code(monkeypatch):
    history = CommonHistory()
    history.state, history.exit_code, history.termination = "failed", 1, "exited"
    history.output = "boom\n"

    async def _broken(**kwargs):
        raise RuntimeError("store read failed")

    history.read_pc_output = _broken
    result = _read(history, monkeypatch, history.output)
    assert result["status"] == "failed"
    assert result["exit_code"] == 1
    assert result["code"] == "pc_output_read_failed"
    assert "unavailable" not in str(result)


def test_clean_exit_is_still_completed(monkeypatch):
    history = CommonHistory()
    history.state, history.exit_code, history.termination = "done", 0, "exited"
    result = _read(history, monkeypatch, history.output)
    assert result["status"] == "completed"
    assert result["output"] == "hello world"
    assert result.get("code") is None


def test_unknown_job_stays_denied(monkeypatch):
    history = CommonHistory()
    result = asyncio.run(shell.execute_pc_shell_read(
        SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(history_store=history))),
        identity=_identity(), subject_id=SUBJECT,
        arguments={"job_id": "dsp_" + "9" * 32},
    ))
    assert result["status"] == "denied"
