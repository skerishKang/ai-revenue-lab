"""Keep a PC answer honest about independently checked mutation results.

This reads only the Engine's top-level verification envelope for mutation
tools, never file contents or a model-supplied completion claim.
"""
from __future__ import annotations

from collections.abc import Mapping
import json


_MUTATIONS = {
    "claw.pc.write_file": "write",
    "claw.pc.move_file": "move",
    "claw.pc.delete_file": "delete",
}
_ACTION_NAMES = {"write": "저장", "move": "이동", "delete": "삭제"}


def _fact(operation: str, status: str, reason: str) -> str:
    action = _ACTION_NAMES[operation]
    if status == "unavailable":
        return f"{action} 결과를 확인하지 못했습니다. 실제로 완료됐는지 다시 확인할까요?"
    if operation == "delete" and reason == "backup_missing":
        return "원본 삭제는 확인했지만 백업을 찾지 못했습니다. 백업 상태를 다시 확인할까요?"
    if operation == "move" and reason == "source_remaining":
        return "원래 위치에 파일이 남아 있어 이동이 완료되지 않았습니다. 다시 확인할까요?"
    if reason == "content_mismatch":
        return "저장된 파일의 크기 또는 내용이 요청과 다릅니다. 다시 시도할까요?"
    if reason == "target_missing" and operation == "move":
        return "이동할 위치에서 파일을 찾지 못했습니다. 다시 확인할까요?"
    if reason == "source_remaining" and operation == "delete":
        return "파일이 원래 위치에 남아 있어 삭제되지 않았습니다. 다시 시도할까요?"
    if reason == "execution_failed":
        return f"PC가 {action} 작업 실패를 보고했습니다. 다시 확인할까요?"
    particle = "가" if operation == "delete" else "이"
    return f"{action}{particle} 실제로는 완료되지 않았습니다. 다시 시도할까요?"


def append_pc_action_facts(answer: str, observations) -> str:
    """Append unresolved facts even if the model omits or contradicts them.

    A later verified retry for the same action and exact target supersedes its
    earlier failure. Outcomes without target identity remain distinct so a
    success on another file cannot hide an unverified action.
    """
    latest = {}
    pending_jobs = {}

    def remember(tool_id, verification, index):
        operation = _MUTATIONS.get(tool_id)
        if operation is None:
            return
        if not isinstance(verification, Mapping):
            verification = {"status": "unavailable", "reason": "evidence_missing"}
        status = verification.get("status")
        reason = verification.get("reason")
        if not isinstance(status, str) or status not in {"verified", "failed", "unavailable"} or verification.get("operation", operation) != operation:
            status, reason = "unavailable", "evidence_invalid"
        path, destination = verification.get("path"), verification.get("destination")
        identity = (
            (operation, path, destination if isinstance(destination, str) else None)
            if isinstance(path, str) and path else (operation, index)
        )
        latest[identity] = (operation, status, reason, path)

    for index, observation in enumerate(observations):
        if not isinstance(observation, Mapping):
            continue
        tool_id = observation.get("tool_id")
        output = observation.get("output")
        output = output if isinstance(output, Mapping) else {}
        if tool_id in _MUTATIONS:
            remember(tool_id, output.get("action_verification"), index)
        elif tool_id == "claw.pc.batch":
            # Only canonical-handler attestations copied to the wrapper's
            # top-level fields count. Never parse a result string or summary.
            verifications = output.get("action_verifications")
            covered = set()
            if isinstance(verifications, (list, tuple)):
                for child_index, child in enumerate(verifications):
                    if not isinstance(child, Mapping):
                        continue
                    source = child.get("tool_id")
                    if isinstance(source, str) and source in _MUTATIONS:
                        covered.add(source)
                        remember(source, child.get("action_verification"), (index, child_index))
            sources = output.get("source_tool_ids")
            if isinstance(sources, (list, tuple)):
                for child_index, source in enumerate(sources):
                    if isinstance(source, str) and source in _MUTATIONS and source not in covered:
                        remember(source, None, (index, "missing", child_index))
        elif tool_id in {"claw.pc.start_job", "claw.pc.job_status", "claw.pc.job_output"}:
            job_id = output.get("job_id")
            identity = job_id if isinstance(job_id, str) and job_id else ("missing", index)
            state = output.get("state")
            if state in {"done", "failed"} and tool_id != "claw.pc.start_job":
                pending_jobs.pop(identity, None)
                remember(output.get("source_tool_id"), output.get("action_verification"), (index, "job"))
            else:
                # A receipt/poll cannot become completion because the model
                # says so. Only the same job's terminal record clears it.
                pending_jobs[identity] = True

    notes = []
    for operation, status, reason, path in latest.values():
        if status == "verified":
            continue
        fact = _fact(operation, status, reason)
        if isinstance(path, str) and path:
            fact = f"파일 {json.dumps(path, ensure_ascii=False)}: {fact}"
        if fact not in answer and fact not in notes:
            notes.append(fact)
    pending_note = "PC 작업은 아직 진행 중입니다. 완료 여부는 작업 상태에서 확인할 수 있습니다."
    if pending_jobs and pending_note not in answer:
        notes.append(pending_note)
    return answer if not notes else answer.rstrip() + "\n\n" + "\n".join(notes)
