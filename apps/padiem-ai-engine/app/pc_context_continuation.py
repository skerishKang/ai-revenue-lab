"""A plain progress checkpoint when a PC turn cannot safely continue in context.

This is not an error projection: the turn has verified observations, and the
answer tells the owner what was checked, what is next, and how to resume. The
next conversation turn already contains this answer, so the same PC scope can
continue there without a new store or a hidden retry.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

_ACTION_LABELS = {
    "claw.pc.query_drives": "드라이브",
    "claw.pc.list_files": "폴더 목록",
    "claw.pc.search_files": "파일 이름 검색",
    "claw.pc.search_contents": "파일 내용 검색",
    "claw.pc.read_file": "파일 읽기",
    "claw.pc.read_file_chunk": "파일 구간 읽기",
    "claw.pc.read_output": "보관된 출력",
    "claw.pc.search_output": "보관된 출력 검색",
    "claw.pc.write_file": "파일 저장",
    "claw.pc.move_file": "파일 이동",
    "claw.pc.delete_file": "파일 삭제",
    "claw.pc.start_job": "백그라운드 작업",
    "claw.pc.job_status": "작업 상태",
    "claw.pc.job_output": "작업 출력",
    "claw.pc.batch": "여러 파일 작업",
    "claw.pc.recall_context": "이전 대화 원문",
}


def _path_of(output: Mapping) -> str:
    for key in ("path", "relative_path", "root", "destination"):
        value = output.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _status_of(observation: Mapping) -> str:
    output = observation.get("output")
    output = output if isinstance(output, Mapping) else {}
    if output.get("ok") is False:
        return "확인하지 못함"
    event = observation.get("event")
    if isinstance(event, Mapping):
        status = event.get("status")
        if isinstance(status, str) and status and status != "completed":
            return "확인하지 못함"
    return "완료"


def _next_step(observations: Sequence[Mapping]) -> str:
    for observation in reversed(observations):
        output = observation.get("output")
        output = output if isinstance(output, Mapping) else {}
        if output.get("next_offset") is not None and output.get("eof") is False:
            return "파일의 다음 구간을 이어서 읽기"
        if observation.get("tool_id") in {"claw.pc.search_files", "claw.pc.search_contents"}:
            return "검색 결과에서 고른 파일 읽기"
        if observation.get("tool_id") == "claw.pc.list_files":
            return "목록에서 고른 파일 읽기"
    return "남은 PC 작업 확인"


def checkpoint_answer(observations: Sequence[Mapping], *, reason: str) -> str:
    """A truthful, non-error progress answer with a next step and resume note."""
    facts: list[str] = []
    used = 0
    for observation in observations:
        if not isinstance(observation, Mapping):
            continue
        tool_id = observation.get("tool_id")
        if not isinstance(tool_id, str) or tool_id not in _ACTION_LABELS:
            continue
        output = observation.get("output")
        output = output if isinstance(output, Mapping) else {}
        path = _path_of(output)
        fact = _ACTION_LABELS[tool_id] + " " + _status_of(observation)
        if path:
            fact += ": " + path
        if fact not in facts:
            facts.append(fact)
            used += 1
        if used >= 5:
            break
    lines = ["여기까지 확인했습니다."]
    if facts:
        lines.extend("- " + fact for fact in facts)
    else:
        lines.append("- 아직 확인된 PC 결과가 없습니다.")
    lines.append("다음은 " + _next_step(observations) + "입니다.")
    lines.append("이어서 진행하려면 다음 메시지에 '계속'이라고 적어 주세요.")
    return "\n".join(lines)


__all__ = ["checkpoint_answer"]
