"""Domain models, enums, and pure policy helpers.

This is a deterministic demo. Nothing here calls a real AI provider, the
GitHub API, or a container runner. All values are synthetic and are labelled
as demo data in the UI.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

_DRIVE_SEGMENT = re.compile(r"^[A-Za-z]:$")


class TaskStatus(str, Enum):
    READY = "ready"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    REWORK = "rework"
    REJECTED = "rejected"


STATUS_LABELS: dict[TaskStatus, str] = {
    TaskStatus.READY: "실행 대기",
    TaskStatus.RUNNING: "진행 중",
    TaskStatus.AWAITING_APPROVAL: "승인 대기",
    TaskStatus.COMPLETED: "완료",
    TaskStatus.REWORK: "재작업",
    TaskStatus.REJECTED: "거절",
}


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    WARNING = "warning"
    FAILED = "failed"


class Verdict(str, Enum):
    APPROVE = "approve"
    CAUTION = "caution"
    REJECT = "reject"


VERDICT_LABELS: dict[Verdict, str] = {
    Verdict.APPROVE: "승인 권장",
    Verdict.CAUTION: "주의 필요",
    Verdict.REJECT: "권장하지 않음",
}


class ExternalPolicy(str, Enum):
    ALLOW = "allow"
    RESTRICT = "restrict"


class BranchMode(str, Enum):
    AUTO = "auto"
    MANUAL = "manual"


class ModelSpec(BaseModel):
    id: str
    provider: str
    name: str
    region_label: str
    hosting_label: str
    cost_class: str
    input_krw_per_1k: float
    output_krw_per_1k: float
    is_domestic: bool = False
    requires_byok: bool = False
    demo: bool = True


class Project(BaseModel):
    id: str
    name: str
    repo_label: str
    description: str
    default_allowed: list[str] = Field(default_factory=list)
    default_denied: list[str] = Field(default_factory=list)


class ChangedFile(BaseModel):
    path: str
    additions: int
    deletions: int
    language: str
    diff: str


class TestResult(BaseModel):
    name: str
    status: str
    detail: str = ""


class TestSummary(BaseModel):
    command: str
    total: int
    passed: int
    failed: int
    skipped: int
    results: list[TestResult] = Field(default_factory=list)


class StepState(BaseModel):
    key: str
    label: str
    status: StepStatus
    detail: str = ""


class Finding(BaseModel):
    level: str
    text: str


class CostLine(BaseModel):
    model_id: str
    model_name: str
    role: str
    tokens_in: int
    tokens_out: int
    krw: float


class TimelineEvent(BaseModel):
    at: str
    label: str
    detail: str = ""


class RunArtifact(BaseModel):
    run_number: int
    steps: list[StepState] = Field(default_factory=list)
    plan_text: str = ""
    worker_claim: str = ""
    changed_files: list[ChangedFile] = Field(default_factory=list)
    tests: Optional[TestSummary] = None
    verdict: Verdict = Verdict.APPROVE
    findings: list[Finding] = Field(default_factory=list)
    path_violations: list[str] = Field(default_factory=list)
    security_notes: list[str] = Field(default_factory=list)
    cost_lines: list[CostLine] = Field(default_factory=list)
    cost_total_krw: float = 0.0
    over_budget: bool = False
    timeline: list[TimelineEvent] = Field(default_factory=list)


class Task(BaseModel):
    id: str
    title: str
    instruction: str
    project_id: str
    worker_model_id: str
    validator_model_id: str
    allowed_paths: list[str] = Field(default_factory=list)
    denied_paths: list[str] = Field(default_factory=list)
    cost_limit_krw: float = 0.0
    external_policy: ExternalPolicy = ExternalPolicy.ALLOW
    branch_mode: BranchMode = BranchMode.AUTO
    status: TaskStatus = TaskStatus.READY
    created_at: str = Field(default_factory=lambda: _now())
    run: Optional[RunArtifact] = None
    rework_count: int = 0
    rework_reasons: list[str] = Field(default_factory=list)
    approver: Optional[str] = None
    commit_sha: Optional[str] = None
    branch_name: Optional[str] = None
    completed_at: Optional[str] = None
    rejected_reason: Optional[str] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def contains_traversal(raw: str) -> bool:
    """True if any path segment is exactly ``..`` (after backslash normalization).

    Encoded sequences such as ``%2e%2e`` are literal characters here (form
    input is decoded exactly once by the framework), so they are not treated
    as traversal.
    """
    return any(
        segment == ".."
        for segment in (raw or "").strip().replace("\\", "/").split("/")
    )


def normalize_path(raw: str) -> str | None:
    """Normalize a path for policy comparison, or return ``None`` if unsafe.

    A path containing a ``..`` segment is **rejected** (returns ``None``)
    rather than silently resolved. For a security input, refusing traversal
    outright is safer than clamping it to the root, which could otherwise turn
    ``apps/other/../../apps/allowed/file`` into ``apps/allowed/file``.

    Also converts backslashes to forward slashes, collapses duplicate slashes,
    drops ``.`` segments, strips a leading drive letter (``C:``), and removes a
    trailing ``*``/``**`` wildcard so prefix semantics apply. The result uses
    forward slashes with no leading or trailing slash; blank input yields ``""``.
    """
    text = (raw or "").strip().replace("\\", "/")
    if not text:
        return ""
    stack: list[str] = []
    for segment in text.split("/"):
        if segment == "" or segment == ".":
            continue
        if segment == "..":
            return None
        if _DRIVE_SEGMENT.match(segment):
            stack = []
            continue
        stack.append(segment)
    while stack and stack[-1] in ("*", "**"):
        stack.pop()
    return "/".join(stack)


def path_matches(pattern: str, path: str) -> bool:
    """Segment-boundary path match used for allow/deny policies.

    Both sides are normalized first. A pattern containing ``..`` never matches
    (it is rejected as traversal). Otherwise a pattern matches when it equals
    the path or is a whole-segment directory prefix of it: ``app`` matches
    ``app/services/x.py`` but never ``application/x.py`` or ``app-evil/x.py``.
    Backslashes, duplicate slashes, ``./`` prefixes, drive letters, and trailing
    wildcards are normalized so they cannot slip past the check.
    """
    normalized_pattern = normalize_path(pattern)
    normalized_path = normalize_path(path)
    if not normalized_pattern or normalized_path is None:
        return False
    return normalized_path == normalized_pattern or normalized_path.startswith(
        normalized_pattern + "/"
    )


def evaluate_path_policy(
    changed_files: list[ChangedFile],
    allowed: list[str],
    denied: list[str],
) -> list[str]:
    """Return human-readable violations for changed files.

    A file violates policy when it falls inside a denied path, or when an
    allow-list is present and the file is outside every allowed path.
    """
    violations: list[str] = []
    allow = [a for a in allowed if a.strip()]
    deny = [d for d in denied if d.strip()]
    for file in changed_files:
        for pattern in deny:
            if path_matches(pattern, file.path):
                violations.append(
                    f"'{file.path}' 파일은 수정 금지 경로('{pattern}')에 포함됩니다."
                )
        if allow and not any(path_matches(a, file.path) for a in allow):
            violations.append(
                f"'{file.path}' 파일은 수정 허용 경로({', '.join(allow)}) 밖에 있습니다."
            )
    return violations


def model_cost_krw(model: ModelSpec, tokens_in: int, tokens_out: int) -> float:
    return round(
        (tokens_in / 1000.0) * model.input_krw_per_1k
        + (tokens_out / 1000.0) * model.output_krw_per_1k,
        2,
    )
