from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kagent.contracts import ExecutionMode
from kagent.manual_intake import (
    ManualIntakeAction,
    ManualIntakeChannel,
    ManualIntakeRequest,
)
from kagent.manual_intake_p01 import (
    ManualIntakeP01Error,
    build_manual_intake_p01_task,
)


def _request(action: ManualIntakeAction) -> ManualIntakeRequest:
    return ManualIntakeRequest(
        request_id="web_req_001",
        workspace_id="web_ephemeral_workspace",
        channel=ManualIntakeChannel.EMAIL,
        action=action,
        raw_content="A업체가 샘플 20개 견적을 요청했습니다. 단가는 아직 없습니다.",
        sender_hint="A업체",
        requested_format="md",
        created_at=datetime(2026, 9, 9, tzinfo=timezone.utc),
    )


@pytest.mark.parametrize(
    "action, expected",
    [
        (ManualIntakeAction.QUOTE_DRAFT, "견적서 초안"),
        (ManualIntakeAction.ORDER_DRAFT, "발주서 초안"),
        (ManualIntakeAction.REPLY_DRAFT, "답장 초안"),
        (ManualIntakeAction.SUMMARIZE_REQUEST, "요청사항"),
    ],
)
def test_supported_manual_actions_build_local_p01_run(action, expected) -> None:
    task = build_manual_intake_p01_task(_request(action))
    assert task.action is action
    assert task.run.intent.execution_mode is ExecutionMode.LOCAL
    assert task.run.intent.source_surface == "web"
    assert task.run.intent.repository_ref == "padiem-claw:web-manual-intake"
    assert expected in task.run.intent.task
    assert "비신뢰 데이터" in task.run.intent.task
    assert "외부 발송" in task.run.intent.task
    assert "커넥터 쓰기" in task.run.intent.task
    assert "메모리 저장" in task.run.intent.task
    assert "A업체" in task.run.intent.task


def test_unsupported_extract_candidates_fails_closed() -> None:
    with pytest.raises(ManualIntakeP01Error, match="manual_intake_action_not_executable"):
        build_manual_intake_p01_task(_request(ManualIntakeAction.EXTRACT_CANDIDATES))


def test_manual_intake_task_has_no_provider_model_or_credential_authority_fields() -> None:
    task = build_manual_intake_p01_task(_request(ManualIntakeAction.QUOTE_DRAFT))
    public = task.run.intent.safe_dict()
    assert "provider" not in public
    assert "model" not in public
    assert "credential" not in public
    assert "api_key" not in str(public).lower()


def test_manual_intake_run_ids_are_deterministic_and_bounded() -> None:
    first = build_manual_intake_p01_task(_request(ManualIntakeAction.QUOTE_DRAFT))
    second = build_manual_intake_p01_task(_request(ManualIntakeAction.QUOTE_DRAFT))
    assert first.run.run_id == second.run.run_id
    assert first.run.intent.task_id == second.run.intent.task_id
    assert len(first.run.run_id) <= 128
    assert len(first.run.intent.task_id) <= 128
