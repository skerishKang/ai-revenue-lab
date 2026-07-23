"""Deterministic mock execution engine.

Simulates the worker/validator pipeline and the human-approval gate without
any real AI call, Git operation, or container run. State transitions are
explicit and guarded; illegal transitions raise ``IllegalTransition``.
"""

from __future__ import annotations

import hashlib

from app import mock_data
from app.domain import (
    CostLine,
    Finding,
    ModelSpec,
    RunArtifact,
    StepState,
    StepStatus,
    Task,
    TaskStatus,
    TimelineEvent,
    Verdict,
    _now,
    evaluate_path_policy,
    model_cost_krw,
    path_matches,
)


class IllegalTransition(ValueError):
    pass


WORKER_TOKENS_IN = 1850
WORKER_TOKENS_OUT = 2400
VALIDATOR_TOKENS_IN = 3100
VALIDATOR_TOKENS_OUT = 420


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]


def _denied_violations(task: Task) -> list[str]:
    out: list[str] = []
    for file in mock_data.CHANGED_FILES:
        for pattern in task.denied_paths:
            if pattern.strip() and path_matches(pattern, file.path):
                out.append(
                    f"'{file.path}' 파일은 수정 금지 경로('{pattern}')에 포함됩니다."
                )
    return out


def _outside_violations(task: Task) -> list[str]:
    allow = [a for a in task.allowed_paths if a.strip()]
    if not allow:
        return []
    out: list[str] = []
    for file in mock_data.CHANGED_FILES:
        if not any(path_matches(a, file.path) for a in allow):
            out.append(
                f"'{file.path}' 파일은 수정 허용 경로({', '.join(allow)}) 밖에 있습니다."
            )
    return out


def _security_notes(task: Task, models: dict[str, ModelSpec]) -> list[str]:
    notes: list[str] = []
    involved = [models.get(task.worker_model_id), models.get(task.validator_model_id)]
    overseas = [m for m in involved if m is not None and not m.is_domestic]
    if task.external_policy.value == "restrict" and overseas:
        names = ", ".join(sorted({m.name for m in overseas}))
        notes.append(
            "외부 전송 제한 정책이 선택되었지만 해외 전송 모델("
            f"{names})이 사용됩니다. 데이터 처리 위치를 확인하세요."
        )
    for model in involved:
        if model is not None and model.requires_byok:
            notes.append(
                f"'{model.name}' 모델은 사용자 API 키(BYOK)가 필요합니다. "
                "설정에서 키 등록 여부를 확인하세요. (Demo)"
            )
    return notes


def build_run_artifact(
    task: Task,
    models: dict[str, ModelSpec],
    run_number: int,
) -> RunArtifact:
    worker = models[task.worker_model_id]
    validator = models[task.validator_model_id]

    denied = _denied_violations(task)
    outside = _outside_violations(task)
    path_violations = denied + outside
    security_notes = _security_notes(task, models)
    tests = mock_data.base_tests()

    if denied:
        verdict = Verdict.REJECT
    elif outside or security_notes:
        verdict = Verdict.CAUTION
    else:
        verdict = Verdict.APPROVE

    findings: list[Finding] = []
    for message in denied:
        findings.append(Finding(level="warning", text=message))
    for message in outside:
        findings.append(Finding(level="warning", text=message))
    for message in security_notes:
        findings.append(Finding(level="caution", text=message))
    findings.append(
        Finding(
            level="info",
            text=(
                "작업자는 '모든 테스트 통과'라고 보고했으나, 실제 실행에서는 "
                f"{tests.total}건 중 {tests.skipped}건이 건너뛰어졌습니다. "
                "보고와 증거를 구분해 확인하세요."
            ),
        )
    )

    worker_krw = model_cost_krw(worker, WORKER_TOKENS_IN, WORKER_TOKENS_OUT)
    validator_krw = model_cost_krw(validator, VALIDATOR_TOKENS_IN, VALIDATOR_TOKENS_OUT)
    cost_lines = [
        CostLine(
            model_id=worker.id,
            model_name=worker.name,
            role="작업자",
            tokens_in=WORKER_TOKENS_IN,
            tokens_out=WORKER_TOKENS_OUT,
            krw=worker_krw,
        ),
        CostLine(
            model_id=validator.id,
            model_name=validator.name,
            role="검증자",
            tokens_in=VALIDATOR_TOKENS_IN,
            tokens_out=VALIDATOR_TOKENS_OUT,
            krw=validator_krw,
        ),
    ]
    cost_total = round(worker_krw + validator_krw, 2)
    over_budget = task.cost_limit_krw > 0 and cost_total > task.cost_limit_krw

    validator_step_status = (
        StepStatus.DONE if verdict == Verdict.APPROVE else StepStatus.WARNING
    )
    steps = [
        StepState(key="repo", label="저장소 확인", status=StepStatus.DONE,
                  detail="데모 저장소의 현재 상태를 확인했습니다. (Demo)"),
        StepState(key="plan", label="작업 계획 생성", status=StepStatus.DONE,
                  detail="작업자 모델이 수정 계획을 작성했습니다."),
        StepState(key="worker", label="작업자 모델 실행", status=StepStatus.DONE,
                  detail=f"{worker.name} 모델이 변경을 생성했습니다."),
        StepState(key="files", label="파일 변경", status=StepStatus.DONE,
                  detail=f"{len(mock_data.CHANGED_FILES)}개 파일이 변경되었습니다."),
        StepState(key="tests", label="테스트 실행", status=StepStatus.DONE,
                  detail=f"{tests.command} → {tests.passed} 통과, "
                         f"{tests.failed} 실패, {tests.skipped} 건너뜀"),
        StepState(key="validator", label="검증자 모델 검토", status=validator_step_status,
                  detail=f"{validator.name} 모델이 변경과 증거를 검토했습니다."),
    ]

    timeline = [
        TimelineEvent(at=_now(), label="실행 시작", detail=f"실행 #{run_number}"),
        TimelineEvent(at=_now(), label="작업자 완료", detail=worker.name),
        TimelineEvent(at=_now(), label="검증자 완료", detail=validator.name),
    ]

    plan_text = mock_data.PLAN_TEXT
    if task.rework_reasons:
        plan_text = (
            f"재작업 반영: {task.rework_reasons[-1]}\n\n" + plan_text
        )

    return RunArtifact(
        run_number=run_number,
        steps=steps,
        plan_text=plan_text,
        worker_claim=mock_data.WORKER_CLAIM,
        changed_files=list(mock_data.CHANGED_FILES),
        tests=tests,
        verdict=verdict,
        findings=findings,
        path_violations=path_violations,
        security_notes=security_notes,
        cost_lines=cost_lines,
        cost_total_krw=cost_total,
        over_budget=over_budget,
        timeline=timeline,
    )


def run_task(task: Task, models: dict[str, ModelSpec]) -> RunArtifact:
    if task.status not in (TaskStatus.READY, TaskStatus.REWORK):
        raise IllegalTransition(
            f"'{task.status.value}' 상태에서는 실행할 수 없습니다."
        )
    task.status = TaskStatus.RUNNING
    run_number = task.rework_count + 1
    artifact = build_run_artifact(task, models, run_number)
    task.run = artifact
    task.status = TaskStatus.AWAITING_APPROVAL
    return artifact


def request_rework(task: Task, reason: str, models: dict[str, ModelSpec]) -> None:
    if task.status != TaskStatus.AWAITING_APPROVAL:
        raise IllegalTransition(
            f"'{task.status.value}' 상태에서는 재작업을 요청할 수 없습니다."
        )
    if not reason.strip():
        raise ValueError("재작업 사유를 입력하세요.")
    task.rework_reasons.append(reason.strip())
    task.rework_count += 1
    task.status = TaskStatus.REWORK


def approve_task(task: Task, approver: str) -> None:
    if task.status != TaskStatus.AWAITING_APPROVAL:
        raise IllegalTransition(
            f"'{task.status.value}' 상태에서는 승인할 수 없습니다."
        )
    task.approver = approver or "검토자"
    task.commit_sha = "demo-" + _short_hash(task.id + ":commit")
    task.branch_name = f"feat/demo-{task.id}"
    task.completed_at = _now()
    task.status = TaskStatus.COMPLETED


def reject_task(task: Task, reason: str) -> None:
    if task.status != TaskStatus.AWAITING_APPROVAL:
        raise IllegalTransition(
            f"'{task.status.value}' 상태에서는 거절할 수 없습니다."
        )
    task.rejected_reason = reason.strip() or "사유 없음"
    task.status = TaskStatus.REJECTED


def data_regions(task: Task, models: dict[str, ModelSpec]) -> dict:
    involved = [models.get(task.worker_model_id), models.get(task.validator_model_id)]
    present = [m for m in involved if m is not None]
    regions = sorted({m.region_label for m in present})
    overseas = any(not m.is_domestic for m in present)
    return {
        "regions": regions,
        "overseas": overseas,
        "domestic_only": present and all(m.is_domestic for m in present),
    }
