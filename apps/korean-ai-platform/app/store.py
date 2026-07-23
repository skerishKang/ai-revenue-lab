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


def create_task(store: Store, form: dict[str, str]) -> tuple[Task | None, dict[str, str]]:
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
    if project_id not in store.projects:
        errors["project_id"] = "프로젝트를 선택하세요."
    if worker_model_id not in store.models:
        errors["worker_model_id"] = "작업 모델을 선택하세요."
    if validator_model_id not in store.models:
        errors["validator_model_id"] = "검증 모델을 선택하세요."

    if errors:
        return None, errors

    project = store.projects[project_id]
    allowed = _split_paths(form.get("allowed_paths", "")) or list(project.default_allowed)
    denied = _split_paths(form.get("denied_paths", "")) or list(project.default_denied)

    cost_limit, cost_error = parse_cost_limit(form.get("cost_limit_krw", ""))
    if cost_error is not None:
        errors["cost_limit_krw"] = cost_error
        return None, errors

    task = Task(
        id=store.next_id(),
        title=title,
        instruction=instruction,
        project_id=project_id,
        worker_model_id=worker_model_id,
        validator_model_id=validator_model_id,
        allowed_paths=allowed,
        denied_paths=denied,
        cost_limit_krw=cost_limit,
        external_policy=ExternalPolicy(form.get("external_policy", "allow")),
        branch_mode=BranchMode(form.get("branch_mode", "auto")),
    )
    store.tasks[task.id] = task
    return task, errors
