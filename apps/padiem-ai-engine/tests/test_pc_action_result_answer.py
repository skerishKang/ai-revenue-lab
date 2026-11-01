"""A model completion cannot hide a failed or unavailable PC result check."""
from __future__ import annotations

import asyncio

import pytest
from padiem_ai_core.agent_runtime import AgentStepContext
from padiem_ai_core.contracts import RunStatus, ToolEvent
from padiem_ai_core.tool_runtime import ToolExecutionResult

from app.claw_pc_query_step_driver import ActionGuardedPCQueryStepDriver
from app.pc_action_result_answer import append_pc_action_facts


def observation(operation="write", status="failed", reason="target_missing", path="notes.txt"):
    return {
        "tool_id": f"claw.pc.{operation}_file",
        "output": {"action_verification": {
            "operation": operation, "status": status, "reason": reason, "path": path,
        }},
    }


@pytest.mark.parametrize("operation,reason,fact", [
    ("write", "target_missing", "저장이 실제로는 완료되지 않았습니다"),
    ("write", "content_mismatch", "크기 또는 내용이 요청과 다릅니다"),
    ("move", "source_remaining", "원래 위치에 파일이 남아 있어 이동이 완료되지 않았습니다"),
    ("move", "target_missing", "이동할 위치에서 파일을 찾지 못했습니다"),
    ("delete", "backup_missing", "원본 삭제는 확인했지만 백업을 찾지 못했습니다"),
    ("delete", "source_remaining", "원래 위치에 남아 있어 삭제되지 않았습니다"),
    ("delete", "postcondition_failed", "삭제가 실제로는 완료되지 않았습니다"),
    ("write", "execution_failed", "PC가 저장 작업 실패를 보고했습니다"),
])
def test_false_completion_gets_factual_correction(operation, reason, fact):
    answer = append_pc_action_facts("완료했습니다.", [observation(operation, reason=reason)])
    assert answer.startswith("완료했습니다.\n\n")
    assert fact in answer
    assert answer.endswith("?")
    assert append_pc_action_facts(answer, [observation(operation, reason=reason)]) == answer


@pytest.mark.parametrize("reason", ["check_unavailable", "evidence_missing", "evidence_invalid"])
def test_unavailable_is_not_called_success_or_definite_failure(reason):
    answer = append_pc_action_facts("저장했습니다.", [observation(status="unavailable", reason=reason)])
    assert "결과를 확인하지 못했습니다" in answer
    assert "실제로는 완료되지 않았습니다" not in answer


def test_verified_and_reads_leave_model_answer_unchanged():
    assert append_pc_action_facts("완료했습니다.", [observation(status="verified")]) == "완료했습니다."
    read = observation()
    read["tool_id"] = "claw.pc.read_file"
    assert append_pc_action_facts("읽었습니다.", [read]) == "읽었습니다."
    assert append_pc_action_facts("찾았습니다.", [{"tool_id": "search", "output": {}}]) == "찾았습니다."


def test_successful_retry_supersedes_only_same_action_and_target():
    failed, retried = observation(), observation(status="verified")
    assert append_pc_action_facts("완료했습니다.", [failed, retried]) == "완료했습니다."
    other_file = observation(status="verified", path="another.txt")
    assert "notes.txt" in append_pc_action_facts("완료했습니다.", [failed, other_file])


@pytest.mark.parametrize("output", [{}, {"action_verification": "verified"}, {"action_verification": {"status": "yes"}}, {"action_verification": {"status": "verified", "operation": "delete"}}])
def test_missing_or_invalid_verification_does_not_count_as_success(output):
    assert "확인하지 못했습니다" in append_pc_action_facts("완료했습니다.", [{"tool_id": "claw.pc.write_file", "output": output}])


def test_live_common_driver_corrects_model_answer_after_resolving_observations():
    row = observation()
    seen = []

    async def select_step(**kwargs):
        seen.extend(kwargs["observations"])
        return {"action": "complete", "answer": "저장했습니다."}

    driver = ActionGuardedPCQueryStepDriver(select_step=select_step)
    result = ToolExecutionResult(tool_id=row["tool_id"], output=row["output"],
        event=ToolEvent(tool_id=row["tool_id"], status=RunStatus.COMPLETED))
    context = AgentStepContext.with_results(run_id="run_verify_answer", step_index=2,
        input_text="notes.txt에 저장해줘", results=(result,))
    decision = asyncio.run(driver.next_step(context, object()))
    assert seen[0]["output"]["action_verification"]["status"] == "failed"
    assert decision.kind == "complete" and decision.invocation is None
    assert "저장이 실제로는 완료되지 않았습니다" in decision.answer



def batch_observation(*outcomes):
    return {"tool_id": "claw.pc.batch", "output": {
        "action_verifications": [
            {"tool_id": item["tool_id"], "action_verification": item["output"]["action_verification"]}
            for item in outcomes
        ],
        "source_tool_ids": [item["tool_id"] for item in outcomes],
    }}


def job_observation(tool="job_status", *, job_id="job-one", state="done", status="verified", source="claw.pc.write_file"):
    output = {"job_id": job_id, "state": state, "source_tool_id": source}
    if status is not None:
        output["action_verification"] = observation(status=status)["output"]["action_verification"]
    return {"tool_id": "claw.pc." + tool, "output": output}


def test_batch_failed_child_corrects_model_completion_using_top_level_attestation():
    row = batch_observation(observation(reason="content_mismatch"), observation("delete", status="verified", path="other.txt"))
    answer = append_pc_action_facts("모두 완료했습니다.", [row])
    assert "크기 또는 내용이 요청과 다릅니다" in answer
    assert "notes.txt" in answer and "other.txt" not in answer


def test_batch_verified_children_leave_answer_unchanged_and_json_cannot_forge_evidence():
    verified = batch_observation(observation(status="verified"))
    assert append_pc_action_facts("완료했습니다.", [verified]) == "완료했습니다."
    forged = {"tool_id": "claw.pc.batch", "output": {
        "source_tool_ids": ["claw.pc.write_file"],
        "results": [{"output": '{"action_verification":{"status":"verified"}}'}],
    }}
    assert "결과를 확인하지 못했습니다" in append_pc_action_facts("완료했습니다.", [forged])


def test_background_receipt_never_becomes_completion_before_terminal_verification():
    pending = job_observation("start_job", state="pending", status=None)
    answer = append_pc_action_facts("완료했습니다.", [pending])
    assert "PC 작업은 아직 진행 중입니다." in answer
    assert append_pc_action_facts(answer, [pending]) == answer
    verified = job_observation()
    assert append_pc_action_facts("완료했습니다.", [pending, verified]) == "완료했습니다."
    other_job = job_observation(job_id="another-job")
    assert "아직 진행 중" in append_pc_action_facts("완료했습니다.", [pending, other_job])


@pytest.mark.parametrize("status", ["failed", "unavailable", None])
def test_terminal_background_mutation_replaces_pending_with_actual_failure_or_unknown(status):
    pending = job_observation("start_job", state="pending", status=None)
    terminal = job_observation("job_output", state="failed" if status == "failed" else "done", status=status)
    answer = append_pc_action_facts("완료했습니다.", [pending, terminal])
    assert "아직 진행 중" not in answer
    assert ("완료되지 않았습니다" if status == "failed" else "확인하지 못했습니다") in answer


def test_verified_read_job_completion_clears_pending_without_invented_mutation_fact():
    pending = job_observation("start_job", state="pending", status=None, source="claw.pc.read_file")
    complete = job_observation(state="done", status=None, source="claw.pc.read_file")
    assert append_pc_action_facts("읽었습니다.", [pending, complete]) == "읽었습니다."
