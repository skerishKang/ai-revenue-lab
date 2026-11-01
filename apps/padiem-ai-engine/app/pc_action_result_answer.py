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
    for index, observation in enumerate(observations):
        if not isinstance(observation, Mapping):
            continue
        operation = _MUTATIONS.get(observation.get("tool_id"))
        if operation is None:
            continue
        output = observation.get("output")
        verification = output.get("action_verification") if isinstance(output, Mapping) else None
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

    notes = []
    for operation, status, reason, path in latest.values():
        if status == "verified":
            continue
        fact = _fact(operation, status, reason)
        if isinstance(path, str) and path:
            fact = f"파일 {json.dumps(path, ensure_ascii=False)}: {fact}"
        if fact not in answer and fact not in notes:
            notes.append(fact)
    return answer if not notes else answer.rstrip() + "\n\n" + "\n".join(notes)
