from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Protocol

from padiem_ai_core import ApprovalOutcome, VerifiedApprovalDecision

from .contracts import ContractError
from .sandbox_conformance import VerifiedDiffEvidence
from .security import redact_secrets


_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_EXACT_REVISION_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_CREDENTIAL_TEXT_RE = re.compile(
    r"(?i)(?:\b(?:api[_-]?key|token|secret|password)\s*[:=]\s*\S+|\bbearer\s+\S+|\bsk-(?:or-v1-)?[A-Za-z0-9._-]{8,}\b)"
)
_SUCCESS_TERMINAL_REASONS = frozenset({"completed", "run_completed", "success"})


def _id(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe identifier")
    return value.strip()


def _repository(value: str) -> str:
    if not isinstance(value, str) or not _REPOSITORY_RE.fullmatch(value.strip()):
        raise ContractError("repository must use bounded owner/repo syntax")
    value = value.strip()
    if redact_secrets(value) != value:
        raise ContractError("repository must not contain raw credential material")
    return value


def _text(value: str, field_name: str, *, limit: int) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    value = value.strip()
    if not value or len(value) > limit or any(ord(ch) < 32 and ch not in "\n\t" for ch in value):
        raise ContractError(f"{field_name} must be bounded and non-empty")
    if _CREDENTIAL_TEXT_RE.search(value) or redact_secrets(value) != value:
        raise ContractError(f"{field_name} must not contain raw credential material")
    return value


def _revision(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _EXACT_REVISION_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be an exact hexadecimal revision")
    return value.strip().lower()


def _sha256(value: str, field_name: str) -> str:
    value = value.strip().lower() if isinstance(value, str) else ""
    if not _SHA256_RE.fullmatch(value):
        raise ContractError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def server_head_branch(run_id: str) -> str:
    run_id = _id(run_id, "run_id")
    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:20]
    return f"claw/run-{digest}"


def _plan_fingerprint_payload(
    *,
    run_id: str,
    repository: str,
    base_branch: str,
    base_revision: str,
    head_branch: str,
    unified_diff_sha256: str,
    changed_files: tuple[str, ...],
    title: str,
    body: str,
) -> dict[str, Any]:
    return {
        "action": "create_github_draft_pr",
        "run_id": run_id,
        "repository": repository,
        "base_branch": base_branch,
        "base_revision": base_revision,
        "head_branch": head_branch,
        "unified_diff_sha256": unified_diff_sha256,
        "changed_files": list(changed_files),
        "title_sha256": hashlib.sha256(title.encode("utf-8")).hexdigest(),
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "draft": True,
        "auto_merge": False,
        "force_push": False,
        "deployment": False,
    }


def draft_pr_plan_fingerprint(plan: "DraftPullRequestPlan") -> str:
    payload = _plan_fingerprint_payload(
        run_id=plan.run_id,
        repository=plan.repository,
        base_branch=plan.base_branch,
        base_revision=plan.base_revision,
        head_branch=plan.head_branch,
        unified_diff_sha256=plan.unified_diff_sha256,
        changed_files=plan.changed_files,
        title=plan.title,
        body=plan.body,
    )
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class DraftPullRequestPlan:
    plan_id: str
    run_id: str
    repository: str
    base_branch: str
    base_revision: str
    head_branch: str
    unified_diff_sha256: str
    changed_files: tuple[str, ...]
    title: str
    body: str
    verification_command_id: str
    verification_output_sha256: str
    draft: bool = True
    auto_merge: bool = False
    force_push: bool = False
    deployment: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "plan_id", _id(self.plan_id, "plan_id"))
        object.__setattr__(self, "run_id", _id(self.run_id, "run_id"))
        object.__setattr__(self, "repository", _repository(self.repository))
        base_branch = _text(self.base_branch, "base_branch", limit=128)
        if base_branch != "main":
            raise ContractError("initial Draft PR output contract supports server-owned main base only")
        object.__setattr__(self, "base_branch", base_branch)
        object.__setattr__(self, "base_revision", _revision(self.base_revision, "base_revision"))
        expected_head = server_head_branch(self.run_id)
        if self.head_branch != expected_head:
            raise ContractError("head_branch must be server-derived from run_id")
        object.__setattr__(self, "unified_diff_sha256", _sha256(self.unified_diff_sha256, "unified_diff_sha256"))
        if not isinstance(self.changed_files, tuple) or not self.changed_files or len(self.changed_files) > 100:
            raise ContractError("changed_files must contain between 1 and 100 entries")
        normalized_files: list[str] = []
        for path in self.changed_files:
            if not isinstance(path, str) or not path.strip() or len(path.strip()) > 512 or any(ord(ch) < 32 for ch in path):
                raise ContractError("changed file path is invalid")
            normalized_files.append(path.strip())
        if len(normalized_files) != len(set(normalized_files)):
            raise ContractError("changed_files must be unique")
        object.__setattr__(self, "changed_files", tuple(normalized_files))
        object.__setattr__(self, "title", _text(self.title, "title", limit=200))
        object.__setattr__(self, "body", _text(self.body, "body", limit=5000))
        object.__setattr__(self, "verification_command_id", _id(self.verification_command_id, "verification_command_id"))
        object.__setattr__(self, "verification_output_sha256", _sha256(self.verification_output_sha256, "verification_output_sha256"))
        if self.draft is not True:
            raise ContractError("Padiem Claw GitHub output must create Draft PRs only")
        if self.auto_merge is not False or self.force_push is not False or self.deployment is not False:
            raise ContractError("auto-merge, force-push and deployment are outside Draft PR authority")

    @classmethod
    def from_verified_diff(
        cls,
        *,
        plan_id: str,
        evidence: VerifiedDiffEvidence,
        title: str,
        body: str,
        base_branch: str = "main",
    ) -> "DraftPullRequestPlan":
        if not isinstance(evidence, VerifiedDiffEvidence):
            raise ContractError("evidence must be VerifiedDiffEvidence")
        if evidence.verification_exit_code != 0:
            raise ContractError("Draft PR plan requires successful verification")
        if not evidence.changed_files:
            raise ContractError("Draft PR plan requires a non-empty verified diff")
        if evidence.terminal_reason not in _SUCCESS_TERMINAL_REASONS:
            raise ContractError("Draft PR plan requires a successful terminal reason")
        repository = _repository(evidence.repository_ref)
        return cls(
            plan_id=plan_id,
            run_id=evidence.run_id,
            repository=repository,
            base_branch=base_branch,
            base_revision=evidence.input_revision,
            head_branch=server_head_branch(evidence.run_id),
            unified_diff_sha256=evidence.unified_diff_sha256,
            changed_files=evidence.changed_files,
            title=title,
            body=body,
            verification_command_id=evidence.verification_command_id,
            verification_output_sha256=evidence.verification_output_sha256,
        )

    @property
    def fingerprint(self) -> str:
        return draft_pr_plan_fingerprint(self)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-github-draft-pr-plan.v1",
            "plan_id": self.plan_id,
            "run_id": self.run_id,
            "repository": self.repository,
            "base_branch": self.base_branch,
            "base_revision": self.base_revision,
            "head_branch": self.head_branch,
            "unified_diff_sha256": self.unified_diff_sha256,
            "changed_files": list(self.changed_files),
            "title": self.title,
            "body": self.body,
            "verification_command_id": self.verification_command_id,
            "verification_output_sha256": self.verification_output_sha256,
            "plan_fingerprint": self.fingerprint,
            "draft": True,
            "auto_merge": False,
            "force_push": False,
            "deployment": False,
            "raw_diff_in_plan": False,
            "raw_terminal_output_in_plan": False,
        }


@dataclass(frozen=True, slots=True)
class DraftPrApprovalBinding:
    binding_id: str
    pause_id: str
    plan_id: str
    plan_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_id", _id(self.binding_id, "binding_id"))
        object.__setattr__(self, "pause_id", _id(self.pause_id, "pause_id"))
        object.__setattr__(self, "plan_id", _id(self.plan_id, "plan_id"))
        object.__setattr__(self, "plan_fingerprint", _sha256(self.plan_fingerprint, "plan_fingerprint"))

    @classmethod
    def bind(cls, *, binding_id: str, pause_id: str, plan: DraftPullRequestPlan) -> "DraftPrApprovalBinding":
        if not isinstance(plan, DraftPullRequestPlan):
            raise ContractError("plan must be DraftPullRequestPlan")
        return cls(
            binding_id=binding_id,
            pause_id=pause_id,
            plan_id=plan.plan_id,
            plan_fingerprint=plan.fingerprint,
        )


@dataclass(frozen=True, slots=True)
class DraftPullRequestReceipt:
    plan_id: str
    repository: str
    pr_ref: str
    head_branch: str
    draft: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "plan_id", _id(self.plan_id, "plan_id"))
        object.__setattr__(self, "repository", _repository(self.repository))
        object.__setattr__(self, "pr_ref", _id(self.pr_ref, "pr_ref"))
        if not isinstance(self.head_branch, str) or not self.head_branch.startswith("claw/run-"):
            raise ContractError("receipt head_branch is not a Claw server-derived branch")
        if self.draft is not True:
            raise ContractError("receipt must represent a Draft PR")


class GitHubDraftPullRequestPort(Protocol):
    def create_draft(self, plan: DraftPullRequestPlan) -> DraftPullRequestReceipt:
        ...


class UnconfiguredGitHubDraftPullRequestPort:
    def create_draft(self, plan: DraftPullRequestPlan) -> DraftPullRequestReceipt:
        raise ContractError("GitHub Draft PR write adapter is not configured")


class DeterministicFakeGitHubDraftPullRequestPort:
    def __init__(self) -> None:
        self.created: list[DraftPullRequestPlan] = []

    def create_draft(self, plan: DraftPullRequestPlan) -> DraftPullRequestReceipt:
        if not isinstance(plan, DraftPullRequestPlan):
            raise ContractError("plan must be DraftPullRequestPlan")
        self.created.append(plan)
        digest = hashlib.sha256(f"{plan.repository}:{plan.fingerprint}".encode("utf-8")).hexdigest()[:20]
        return DraftPullRequestReceipt(
            plan_id=plan.plan_id,
            repository=plan.repository,
            pr_ref=f"fake_pr_{digest}",
            head_branch=plan.head_branch,
        )


class ApprovalGatedDraftPrWriter:
    def __init__(self, port: GitHubDraftPullRequestPort | None = None) -> None:
        self.port = port or UnconfiguredGitHubDraftPullRequestPort()

    def submit(
        self,
        *,
        plan: DraftPullRequestPlan,
        binding: DraftPrApprovalBinding,
        decision: VerifiedApprovalDecision,
    ) -> DraftPullRequestReceipt:
        if not isinstance(plan, DraftPullRequestPlan):
            raise ContractError("plan must be DraftPullRequestPlan")
        if not isinstance(binding, DraftPrApprovalBinding):
            raise ContractError("binding must be DraftPrApprovalBinding")
        if not isinstance(decision, VerifiedApprovalDecision):
            raise ContractError("decision must be canonical VerifiedApprovalDecision")
        if decision.outcome is not ApprovalOutcome.APPROVED:
            raise ContractError("GitHub Draft PR write requires approved canonical decision")
        if decision.pause_id != binding.pause_id:
            raise ContractError("approval decision does not belong to Draft PR binding")
        if binding.plan_id != plan.plan_id or binding.plan_fingerprint != plan.fingerprint:
            raise ContractError("Draft PR plan changed after approval binding")
        return self.port.create_draft(plan)


REAL_GITHUB_WRITE_CONFIGURED = False
AUTO_MERGE_SUPPORTED = False
FORCE_PUSH_SUPPORTED = False
DEPLOYMENT_FROM_DRAFT_PR_WRITER_SUPPORTED = False
