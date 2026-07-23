"""User-facing helpers for the workspace demo.

Plain-language status and action labels shown only on the user workspace.
The existing operator labels in ``domain.STATUS_LABELS`` are unchanged.
"""

from __future__ import annotations

from app.domain import Task, TaskStatus

USER_STATUS_LABELS: dict[str, str] = {
    "ready": "시작할 준비가 됐습니다",
    "running": "AI가 작업하고 있습니다",
    "awaiting_approval": "확인이 필요합니다",
    "rework": "요청한 내용을 다시 작업 중입니다",
    "completed": "작업이 완료됐습니다",
    "rejected": "작업이 중단됐습니다",
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
    "ready": "작업을 시작할 준비가 됐습니다.",
    "running": "AI가 요청을 분석하고 결과를 만들고 있습니다.",
    "awaiting_approval": (
        "결과가 준비됐습니다. 내용을 확인한 후 "
        "승인하거나 수정 요청을 할 수 있습니다."
    ),
    "rework": "수정 요청을 반영해 다시 작업하고 있습니다.",
    "completed": "검토가 완료됐습니다.",
    "rejected": "검토 과정에서 작업이 중단됐습니다.",
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
    """Short plain-language result summary for the user view."""
    if task.run is None:
        return "아직 실행되지 않았습니다."
    files = len(task.run.changed_files)
    tests = task.run.tests
    parts: list[str] = []
    if files > 0:
        parts.append(f"파일 {files}개 변경")
    if tests is not None:
        parts.append(f"테스트 {tests.passed}개 통과")
    if task.run.over_budget:
        parts.append("비용 한도 초과")
    if task.run.path_violations:
        parts.append("경로 위반 감지")
    return " · ".join(parts) if parts else "실행 완료"
