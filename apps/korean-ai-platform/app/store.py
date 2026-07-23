"""In-memory demo store.

Holds tasks, the model/project catalog, and the security settings for the
demo. State is deterministic and lives only in process memory. API keys are
never stored — only a boolean "registered" flag per BYOK model.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, Field

from app import mock_data
from app.domain import (
    BranchMode,
    ExternalPolicy,
    ModelSpec,
    Project,
    Task,
    contains_traversal,
)


class ByokState(BaseModel):
    registered: bool = False


class SecuritySettings(BaseModel):
    domestic_first: bool = True
    allow_external: bool = True
    block_on_secret: bool = True
    project_cost_limit_krw: float = 10000.0
    block_push_without_approval: bool = True
    byok: dict[str, ByokState] = Field(default_factory=dict)


class Store:
    def __init__(self, seed: bool = True) -> None:
        self.models: dict[str, ModelSpec] = mock_data.models_by_id()
        self.projects: dict[str, Project] = mock_data.projects_by_id()
        self.settings = SecuritySettings()
        self.tasks: dict[str, Task] = {}
        self._counter = 100
        if seed:
            for task in mock_data.build_seed_tasks():
                self.tasks[task.id] = task

    def list_tasks(self) -> list[Task]:
        return sorted(self.tasks.values(), key=lambda t: t.created_at, reverse=True)

    def get_task(self, task_id: str) -> Task | None:
        return self.tasks.get(task_id)

    def next_id(self) -> str:
        self._counter += 1
        return f"t-{self._counter:03d}"

    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for task in self.tasks.values():
            counts[task.status.value] = counts.get(task.status.value, 0) + 1
        return counts

    def monthly_estimated_krw(self) -> float:
        total = 0.0
        for task in self.tasks.values():
            if task.run is not None:
                total += task.run.cost_total_krw
        return round(total, 2)


def _split_paths(raw: str) -> list[str]:
    parts = raw.replace("\n", ",").split(",")
    return [p.strip() for p in parts if p.strip()]


def parse_cost_limit(raw: str) -> tuple[float | None, str | None]:
    """Parse a cost-limit form value.

    Empty/blank means "no limit" (0). Rejects non-numeric text, negative
    values, NaN, and Infinity so a malformed limit can never silently disable
    the budget warning or crash the request.
    """
    text = (raw or "").strip()
    if not text:
        return 0.0, None
    try:
        value = float(text)
    except ValueError:
        return None, "비용 한도는 숫자로 입력하세요."
    if not math.isfinite(value):
        return None, "비용 한도는 유한한 숫자로 입력하세요."
    if value < 0:
        return None, "비용 한도는 0 이상으로 입력하세요."
    return value, None


def validate_and_build_task(
    models: dict[str, ModelSpec],
    projects: dict[str, Project],
    settings: SecuritySettings,
    form: dict[str, str],
    next_id,
) -> tuple[Task | None, dict[str, str]]:
    """Validate a task form and build a Task without persisting it.

    Pure with respect to storage: it only calls ``next_id()`` (after all
    validation passes) to allocate the ID. Both the in-memory ``create_task``
    and the SQLite application service reuse this so validation rules stay
    identical across backends.
    """
    errors: dict[str, str] = {}

    title = form.get("title", "").strip()
    instruction = form.get("instruction", "").strip()
    project_id = form.get("project_id", "").strip()
    worker_model_id = form.get("worker_model_id", "").strip()
    validator_model_id = form.get("validator_model_id", "").strip()

    if not title:
        errors["title"] = "작업 제목을 입력하세요."
    if not instruction:
        errors["instruction"] = "작업 지시를 입력하세요."
    if project_id not in projects:
        errors["project_id"] = "프로젝트를 선택하세요."
    if worker_model_id not in models:
        errors["worker_model_id"] = "작업 모델을 선택하세요."
    if validator_model_id not in models:
        errors["validator_model_id"] = "검증 모델을 선택하세요."

    if errors:
        return None, errors

    # Global external-model policy: when external transmission is disabled,
    # block any overseas/non-domestic worker or validator model.
    if not settings.allow_external:
        worker = models[worker_model_id]
        validator = models[validator_model_id]
        if not worker.is_domestic:
            errors["worker_model_id"] = (
                f"외부 모델 전송이 허용되지 않았습니다. '{worker.name}'은(는) 해외 처리 모델입니다."
            )
        if not validator.is_domestic:
            errors["validator_model_id"] = (
                f"외부 모델 전송이 허용되지 않았습니다. '{validator.name}'은(는) 해외 처리 모델입니다."
            )
        if errors:
            return None, errors

    project = projects[project_id]
    allowed = _split_paths(form.get("allowed_paths", "")) or list(project.default_allowed)
    denied = _split_paths(form.get("denied_paths", "")) or list(project.default_denied)

    if any(contains_traversal(p) for p in allowed):
        errors["allowed_paths"] = "경로에 '..'를 사용할 수 없습니다."
    if any(contains_traversal(p) for p in denied):
        errors["denied_paths"] = "경로에 '..'를 사용할 수 없습니다."
    if errors:
        return None, errors

    # Cost limit: blank input falls back to the global project default; an
    # explicit value (including 0 = no limit) is parsed and validated.
    cost_raw = (form.get("cost_limit_krw") or "").strip()
    if cost_raw == "":
        cost_limit = settings.project_cost_limit_krw
    else:
        cost_limit, cost_error = parse_cost_limit(cost_raw)
        if cost_error is not None:
            errors["cost_limit_krw"] = cost_error
            return None, errors

    # Validate enum inputs explicitly so a manipulated value yields a field
    # error (form re-render) instead of an unhandled ValueError / HTTP 500.
    try:
        external_policy = ExternalPolicy(form.get("external_policy", "allow"))
    except ValueError:
        errors["external_policy"] = "외부 전송 정책 값이 올바르지 않습니다."
    try:
        branch_mode = BranchMode(form.get("branch_mode", "auto"))
    except ValueError:
        errors["branch_mode"] = "브랜치 생성 방식 값이 올바르지 않습니다."
    if errors:
        return None, errors

    task = Task(
        id=next_id(),
        title=title,
        instruction=instruction,
        project_id=project_id,
        worker_model_id=worker_model_id,
        validator_model_id=validator_model_id,
        allowed_paths=allowed,
        denied_paths=denied,
        cost_limit_krw=cost_limit,
        external_policy=external_policy,
        branch_mode=branch_mode,
    )
    return task, errors


def create_task(store: Store, form: dict[str, str]) -> tuple[Task | None, dict[str, str]]:
    task, errors = validate_and_build_task(
        store.models, store.projects, store.settings, form, store.next_id
    )
    if task is not None:
        store.tasks[task.id] = task
    return task, errors
