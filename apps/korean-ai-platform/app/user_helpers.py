"""User-facing helpers for the workspace demo.

Plain-language status and action labels shown only on the user workspace.
The existing operator labels in ``domain.STATUS_LABELS`` are unchanged.
"""

from __future__ import annotations

import re

from app.domain import Task, TaskStatus


def generate_title_from_instruction(instruction: str) -> str:
    """Generate a short safe title from user instruction.

    Rules:
    1. Normalize all consecutive whitespace to single space
    2. Strip leading/trailing whitespace
    3. Max 40 characters
    4. Append '…' if truncated
    5. Empty instruction returns empty string
    """
    if not instruction:
        return ""
    normalized = re.sub(r"\s+", " ", instruction).strip()
    if not normalized:
        return ""
    if len(normalized) <= 40:
        return normalized
    return normalized[:40] + "…"

USER_STATUS_LABELS: dict[str, str] = {
    "ready": "Demo 실행을 시작할 수 있습니다",
    "running": "Demo 실행 중입니다",
    "awaiting_approval": "Demo 결과 확인이 필요합니다",
    "rework": "Demo 재작업 중입니다",
    "completed": "Demo 작업이 완료됐습니다",
    "rejected": "Demo 작업이 중단됐습니다",
}

USER_ACTION_LABELS: dict[str, str] = {
    "ready": "작업 시작",
    "running": "진행 상황 보기",
    "awaiting_approval": "결과 확인",
    "rework": "진행 상황 보기",
    "completed": "결과 열기",
    "rejected": "중단 사유 보기",
}

USER_STATUS_SUMMARY: dict[str, str] = {
    "ready": "입력 내용을 확인한 후 Demo 실행을 시작할 수 있습니다.",
    "running": "Demo 실행이 요청을 처리하고 예시 결과를 만들고 있습니다.",
    "awaiting_approval": (
        "Demo 결과가 준비됐습니다. 내용을 확인한 후 "
        "승인하거나 수정 요청을 할 수 있습니다."
    ),
    "rework": "수정 요청을 반영한 Demo 결과를 준비하고 있습니다.",
    "completed": "Demo 검토와 승인 절차가 완료됐습니다.",
    "rejected": "Demo 검토 과정에서 작업이 중단됐습니다.",
}


def user_status_label(status_value: str) -> str:
    return USER_STATUS_LABELS.get(status_value, status_value)


def user_action_label(status_value: str) -> str:
    return USER_ACTION_LABELS.get(status_value, "자세히 보기")


def user_status_summary(status_value: str) -> str:
    return USER_STATUS_SUMMARY.get(status_value, "")


def user_risk_warnings(task: Task) -> list[str]:
    """Return plain-language risk warnings that must stay visible.

    These are shown outside the technical disclosure so the user always
    sees critical issues before approving.
    """
    warnings: list[str] = []
    if task.run is None:
        return warnings
    if task.run.path_violations:
        warnings.append(
            "허용되지 않은 파일이 변경됐습니다. "
            "승인 전에 변경 범위를 확인하세요."
        )
    if task.run.over_budget:
        warnings.append("예상 비용이 설정한 한도를 초과했습니다.")
    if task.run.security_notes:
        for note in task.run.security_notes:
            if "해외" in note or "외부" in note:
                warnings.append("데이터가 해외로 전송될 수 있습니다.")
                break
    if task.run.verdict.value == "reject":
        warnings.append(
            "검증 결과 승인이 권장되지 않습니다. "
            "운영자 화면에서 상세 근거를 확인하세요."
        )
    return warnings


def user_cost_summary(task: Task) -> str:
    """Plain-language cost summary for the user view."""
    if task.run is None:
        return ""
    total = task.run.cost_total_krw
    if total <= 0:
        return "예상 비용: 자체 GPU 사용 (추가 비용 없음)"
    return f"예상 비용: {total:,.0f}원"


def user_result_summary(task: Task) -> str:
    """Short plain-language result summary for the user view.

    Returns status-focused plain language. Technical details like file counts
    and test counts are only shown in the disclosure section.
    """
    status = task.status.value
    if status == "ready":
        return "아직 Demo 실행 전입니다."
    if status == "running":
        return "Demo 실행 중입니다."
    if status == "awaiting_approval":
        return "예시 결과와 검토 내용이 준비됐습니다."
    if status == "rework":
        return "수정 요청을 반영하고 있습니다."
    if status == "completed":
        return "검토가 완료된 Demo 결과입니다."
    if status == "rejected":
        return "중단 사유를 확인할 수 있습니다."
    return ""
