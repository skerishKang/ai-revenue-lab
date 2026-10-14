from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any

from padiem_ai_core import ApprovalOutcome, VerifiedApprovalDecision

from .contracts import ContractError
from .github_draft_pr import (
    DraftPrApprovalBinding,
    DraftPullRequestPlan,
    DraftPullRequestReceipt,
    GitHubDraftPullRequestPort,
    UnconfiguredGitHubDraftPullRequestPort,
)


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def _id(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe identifier")
    return value.strip()


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def github_pr_write_fingerprint(plan: DraftPullRequestPlan, binding: DraftPrApprovalBinding) -> str:
    if not isinstance(plan, DraftPullRequestPlan) or not isinstance(binding, DraftPrApprovalBinding):
        raise ContractError("plan and binding must use Draft PR contracts")
    payload = {
        "action": "create_github_draft_pr",
        "plan_id": plan.plan_id,
        "plan_fingerprint": plan.fingerprint,
        "repository": plan.repository,
        "base_revision": plan.base_revision,
        "base_branch": plan.base_branch,
        "head_branch": plan.head_branch,
        "binding_id": binding.binding_id,
        "pause_id": binding.pause_id,
        "binding_plan_fingerprint": binding.plan_fingerprint,
        "draft": True,
        "auto_merge": False,
        "force_push": False,
        "deployment": False,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class GitHubDraftPrOutboxState(str, Enum):
    PENDING = "pending"
    CREATED = "created"
    RECONCILIATION_REQUIRED = "reconciliation_required"


@dataclass(frozen=True, slots=True)
class GitHubDraftPrOutboxRecord:
    outbox_id: str
    plan_id: str
    run_id: str
    repository: str
    head_branch: str
    write_fingerprint: str
    state: GitHubDraftPrOutboxState
    created_at: datetime
    updated_at: datetime
    receipt_ref: str | None = None
    failure_code: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("outbox_id", "plan_id", "run_id"):
            object.__setattr__(self, field_name, _id(getattr(self, field_name), field_name))
        if not isinstance(self.repository, str) or "/" not in self.repository or len(self.repository) > 201:
            raise ContractError("repository must be bounded owner/repo")
        if not isinstance(self.head_branch, str) or not self.head_branch.startswith("claw/run-") or len(self.head_branch) > 128:
            raise ContractError("head_branch must be a bounded Claw branch")
        digest = self.write_fingerprint.strip().lower() if isinstance(self.write_fingerprint, str) else ""
        if not _SHA256_RE.fullmatch(digest):
            raise ContractError("write_fingerprint must be SHA-256")
        object.__setattr__(self, "write_fingerprint", digest)
        if not isinstance(self.state, GitHubDraftPrOutboxState):
            try:
                object.__setattr__(self, "state", GitHubDraftPrOutboxState(self.state))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid GitHub Draft PR outbox state") from exc
        created = _aware(self.created_at, "created_at")
        updated = _aware(self.updated_at, "updated_at")
        if updated < created:
            raise ContractError("updated_at cannot precede created_at")
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "updated_at", updated)
        if self.receipt_ref is not None:
            object.__setattr__(self, "receipt_ref", _id(self.receipt_ref, "receipt_ref"))
        if self.failure_code is not None:
            object.__setattr__(self, "failure_code", _id(self.failure_code, "failure_code"))
        if self.state is GitHubDraftPrOutboxState.CREATED and self.receipt_ref is None:
            raise ContractError("created outbox record requires receipt_ref")
        if self.state is GitHubDraftPrOutboxState.RECONCILIATION_REQUIRED and self.failure_code is None:
            raise ContractError("reconciliation record requires failure_code")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-github-draft-pr-outbox.v1",
            "outbox_id": self.outbox_id,
            "plan_id": self.plan_id,
            "run_id": self.run_id,
            "repository": self.repository,
            "head_branch": self.head_branch,
            "write_fingerprint": self.write_fingerprint,
            "state": self.state.value,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "updated_at": self.updated_at.isoformat().replace("+00:00", "Z"),
            "receipt_ref": self.receipt_ref,
            "failure_code": self.failure_code,
            "raw_diff": False,
            "raw_terminal_output": False,
            "auto_retry": False,
            "auto_merge": False,
        }


class InMemoryGitHubDraftPrOutbox:
    def __init__(self, port: GitHubDraftPullRequestPort | None = None) -> None:
        self.port = port or UnconfiguredGitHubDraftPullRequestPort()
        self._records: dict[str, GitHubDraftPrOutboxRecord] = {}

    @staticmethod
    def _validate_approval(plan: DraftPullRequestPlan, binding: DraftPrApprovalBinding, decision: VerifiedApprovalDecision) -> None:
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

    @staticmethod
    def _validate_receipt(plan: DraftPullRequestPlan, receipt: DraftPullRequestReceipt) -> None:
        if not isinstance(receipt, DraftPullRequestReceipt):
            raise ContractError("GitHub writer returned invalid receipt")
        if receipt.plan_id != plan.plan_id:
            raise ContractError("Draft PR receipt plan correlation mismatch")
        if receipt.repository != plan.repository:
            raise ContractError("Draft PR receipt repository correlation mismatch")
        if receipt.head_branch != plan.head_branch:
            raise ContractError("Draft PR receipt head correlation mismatch")
        if receipt.draft is not True:
            raise ContractError("Draft PR receipt must remain draft")

    def submit(
        self,
        *,
        outbox_id: str,
        plan: DraftPullRequestPlan,
        binding: DraftPrApprovalBinding,
        decision: VerifiedApprovalDecision,
        now: datetime,
    ) -> GitHubDraftPrOutboxRecord:
        outbox_id = _id(outbox_id, "outbox_id")
        now = _aware(now, "now")
        self._validate_approval(plan, binding, decision)
        fingerprint = github_pr_write_fingerprint(plan, binding)
        existing = self._records.get(outbox_id)
        if existing is not None:
            if existing.write_fingerprint != fingerprint:
                raise ContractError("conflicting GitHub Draft PR outbox replay")
            if existing.state is GitHubDraftPrOutboxState.CREATED:
                return existing
            if existing.state is GitHubDraftPrOutboxState.RECONCILIATION_REQUIRED:
                raise ContractError("ambiguous Draft PR write requires reconciliation before retry")
            raise ContractError("Draft PR write is already pending")

        pending = GitHubDraftPrOutboxRecord(
            outbox_id=outbox_id,
            plan_id=plan.plan_id,
            run_id=plan.run_id,
            repository=plan.repository,
            head_branch=plan.head_branch,
            write_fingerprint=fingerprint,
            state=GitHubDraftPrOutboxState.PENDING,
            created_at=now,
            updated_at=now,
        )
        self._records[outbox_id] = pending
        try:
            receipt = self.port.create_draft(plan)
            self._validate_receipt(plan, receipt)
        except Exception:
            ambiguous = replace(
                pending,
                state=GitHubDraftPrOutboxState.RECONCILIATION_REQUIRED,
                updated_at=now,
                failure_code="ambiguous_github_write",
            )
            self._records[outbox_id] = ambiguous
            raise

        created = replace(
            pending,
            state=GitHubDraftPrOutboxState.CREATED,
            updated_at=now,
            receipt_ref=receipt.pr_ref,
        )
        self._records[outbox_id] = created
        return created

    def get(self, outbox_id: str) -> GitHubDraftPrOutboxRecord:
        outbox_id = _id(outbox_id, "outbox_id")
        try:
            return self._records[outbox_id]
        except KeyError as exc:
            raise ContractError("GitHub Draft PR outbox record not found") from exc


AMBIGUOUS_GITHUB_WRITE_AUTO_RETRY_SUPPORTED = False
REAL_GITHUB_OUTBOX_RECONCILIATION_CONFIGURED = False
