"""Provider-neutral external coding-agent contract and deterministic conformance boundary.

This module defines an adapter port only. It does not schedule work, approve
permissions, allocate sandboxes, resolve credentials, or write run history.
Those authorities remain in the existing Claw/P01 layers.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import RLock
from typing import Any, Protocol

from padiem_ai_core import (
    AgentContinuationState,
    ApprovalOutcome,
    ApprovalPause,
    ApprovalRequirement,
    ContinuationStatus,
    VerifiedApprovalDecision,
)
from padiem_ai_core.execution_context import request_fingerprint

from .contracts import (
    ClawRunStatus,
    ClawTaskIntent,
    ContractError,
    ExecutionMode,
    NetworkPolicy,
    SandboxLease,
    SandboxLeaseState,
    exact_commit_revision,
)
from .runs import ClawRun, RunStateError
from .security import contains_credential_material

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MAX_EVENTS = 4096
_MAX_POLL_EVENTS = 1000
_MAX_MESSAGE_CHARS = 1000
_MAX_TIMEOUT_SECONDS = 3600
_DEFAULT_CLOCK = datetime(2026, 9, 24, 0, 0, tzinfo=timezone.utc)


class ExternalCodingAgentError(ContractError):
    """A bounded external-runner contract failure."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _SAFE_ID_RE.fullmatch(code):
            raise ValueError("external coding-agent error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message


class ExternalCodingAgentStatusError(ExternalCodingAgentError):
    pass


class ExternalCodingAgentConformanceError(ExternalCodingAgentError):
    pass


def _safe_id(name: str, value: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise ExternalCodingAgentError("invalid_identifier", f"{name} must be a bounded safe identifier")
    return value


def _safe_ref(name: str, value: str, *, limit: int = 512) -> str:
    if not isinstance(value, str):
        raise ExternalCodingAgentError("invalid_reference", f"{name} must be a string")
    normalized = value.strip()
    if contains_credential_material(normalized):
        raise ExternalCodingAgentError("raw_credential_rejected", f"{name} must not contain credential material")
    if (
        not normalized
        or len(normalized) > limit
        or not _SAFE_REF_RE.fullmatch(normalized)
        or _CONTROL_RE.search(normalized)
    ):
        raise ExternalCodingAgentError("invalid_reference", f"{name} must be a bounded non-secret reference")
    return normalized


def _safe_text(name: str, value: str, *, limit: int) -> str:
    if not isinstance(value, str):
        raise ExternalCodingAgentError("invalid_text", f"{name} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > limit or _CONTROL_RE.search(normalized):
        raise ExternalCodingAgentError("invalid_text", f"{name} must be bounded non-control text")
    if contains_credential_material(normalized):
        raise ExternalCodingAgentError("raw_credential_rejected", f"{name} must not contain credential material")
    return normalized


def _safe_digest(name: str, value: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ExternalCodingAgentError("invalid_digest", f"{name} must be a lowercase SHA-256 digest")
    return value


def _aware(name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ExternalCodingAgentError("invalid_timestamp", f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


class ExternalCodingAgentTerminalReason(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    LOST_PROCESS = "lost_process"
    START_FAILED = "start_failed"
    RUNTIME_FAILED = "runtime_failed"
    REVISION_MISMATCH = "revision_mismatch"
    SANDBOX_MISMATCH = "sandbox_mismatch"
    WORKTREE_MISMATCH = "worktree_mismatch"
    PERMISSION_REQUIRED = "permission_required"
    UNKNOWN = "unknown"


class ExternalCodingAgentEventKind(str, Enum):
    STATUS_CHANGED = "status_changed"
    PERMISSION_REQUESTED = "permission_requested"
    PERMISSION_RESOLVED = "permission_resolved"
    PROCESS_LOST = "process_lost"
    TERMINAL_RESULT = "terminal_result"
    FAILURE = "failure"


_STATUS_ALIASES: dict[str, ClawRunStatus] = {
    "queued": ClawRunStatus.QUEUED,
    "starting": ClawRunStatus.PREPARING,
    "preparing": ClawRunStatus.PREPARING,
    "running": ClawRunStatus.RUNNING,
    "waiting_approval": ClawRunStatus.WAITING_APPROVAL,
    "approval_required": ClawRunStatus.WAITING_APPROVAL,
    "completed": ClawRunStatus.COMPLETED,
    "done": ClawRunStatus.COMPLETED,
    "failed": ClawRunStatus.FAILED,
    "error": ClawRunStatus.FAILED,
    "cancelled": ClawRunStatus.CANCELLED,
    "canceled": ClawRunStatus.CANCELLED,
    "lost": ClawRunStatus.FAILED,
    "lost_process": ClawRunStatus.FAILED,
}

_TERMINAL_REASON_BY_STATUS: dict[ClawRunStatus, ExternalCodingAgentTerminalReason] = {
    ClawRunStatus.COMPLETED: ExternalCodingAgentTerminalReason.COMPLETED,
    ClawRunStatus.FAILED: ExternalCodingAgentTerminalReason.FAILED,
    ClawRunStatus.CANCELLED: ExternalCodingAgentTerminalReason.CANCELLED,
}


def normalize_external_status(
    raw_status: str,
    *,
    terminal_reason: ExternalCodingAgentTerminalReason | str | None = None,
    sequence: int = 0,
    external_session_id: str | None = None,
    provider_opaque_ref: str | None = None,
    binding: ExternalCodingAgentBinding | None = None,
) -> ExternalCodingAgentStatus:
    """Translate one provider observation into the canonical Claw projection."""

    if not isinstance(raw_status, str) or not re.fullmatch(r"[a-z0-9_-]{1,64}", raw_status.strip().lower()):
        raise ExternalCodingAgentStatusError("unsupported_external_status", "provider status is not a bounded known value")
    key = raw_status.strip().lower()
    try:
        status = _STATUS_ALIASES[key]
    except KeyError as exc:
        raise ExternalCodingAgentStatusError("unsupported_external_status", "provider status is not supported") from exc
    reason: ExternalCodingAgentTerminalReason | None = None
    if key in {"lost", "lost_process"}:
        reason = ExternalCodingAgentTerminalReason.LOST_PROCESS
    if terminal_reason is not None:
        candidate = terminal_reason if isinstance(terminal_reason, ExternalCodingAgentTerminalReason) else ExternalCodingAgentTerminalReason(terminal_reason)
        if status not in _TERMINAL_REASON_BY_STATUS:
            raise ExternalCodingAgentStatusError("invalid_terminal_reason", "non-terminal status cannot carry a terminal reason")
        if key in {"lost", "lost_process"} and candidate is not ExternalCodingAgentTerminalReason.LOST_PROCESS:
            raise ExternalCodingAgentStatusError("invalid_terminal_reason", "lost status must use lost_process")
        reason = candidate
    if status in _TERMINAL_REASON_BY_STATUS and reason is None:
        reason = _TERMINAL_REASON_BY_STATUS[status]
    return ExternalCodingAgentStatus(
        status=status,
        terminal_reason=reason,
        sequence=sequence,
        external_session_id=external_session_id,
        provider_opaque_ref=provider_opaque_ref,
        binding=binding,
    )


@dataclass(frozen=True, slots=True)
class ExternalCodingAgentBinding:
    """Immutable source/worktree/sandbox identity observed by an adapter."""

    source_revision: str
    worktree_ref: str
    worktree_base_revision: str
    sandbox_lease_id: str

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "source_revision", exact_commit_revision(self.source_revision, "source_revision"))
            object.__setattr__(self, "worktree_base_revision", exact_commit_revision(self.worktree_base_revision, "worktree_base_revision"))
        except ContractError as exc:
            raise ExternalCodingAgentError("invalid_revision", str(exc)) from exc
        object.__setattr__(self, "worktree_ref", _safe_ref("worktree_ref", self.worktree_ref))
        object.__setattr__(self, "sandbox_lease_id", _safe_id("sandbox_lease_id", self.sandbox_lease_id))
        if self.source_revision != self.worktree_base_revision:
            raise ExternalCodingAgentError("worktree_mismatch", "worktree base revision must equal source revision")

    def matches(self, request: ExternalCodingAgentStartRequest) -> bool:
        return (
            self.source_revision == request.source_revision
            and self.worktree_base_revision == request.worktree_base_revision
            and self.worktree_ref == request.worktree_ref
            and self.sandbox_lease_id == request.sandbox_lease.lease_id
        )

    def safe_dict(self) -> dict[str, str]:
        return {
            "source_revision": self.source_revision,
            "worktree_ref": self.worktree_ref,
            "worktree_base_revision": self.worktree_base_revision,
            "sandbox_lease_id": self.sandbox_lease_id,
        }


@dataclass(frozen=True, slots=True)
class ExternalCodingAgentStatus:
    """Normalized status projection; the lifecycle enum remains Claw-owned."""

    status: ClawRunStatus
    terminal_reason: ExternalCodingAgentTerminalReason | None = None
    sequence: int = 0
    external_session_id: str | None = None
    provider_opaque_ref: str | None = None
    binding: ExternalCodingAgentBinding | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ClawRunStatus):
            try:
                object.__setattr__(self, "status", ClawRunStatus(self.status))
            except (TypeError, ValueError) as exc:
                raise ExternalCodingAgentStatusError("invalid_status", "status must be a canonical ClawRunStatus") from exc
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 0:
            raise ExternalCodingAgentStatusError("invalid_sequence", "sequence must be a non-negative integer")
        if self.terminal_reason is not None and not isinstance(self.terminal_reason, ExternalCodingAgentTerminalReason):
            try:
                object.__setattr__(self, "terminal_reason", ExternalCodingAgentTerminalReason(self.terminal_reason))
            except (TypeError, ValueError) as exc:
                raise ExternalCodingAgentStatusError("invalid_terminal_reason", "terminal_reason is not supported") from exc
        if self.status.terminal and self.terminal_reason is None:
            object.__setattr__(self, "terminal_reason", _TERMINAL_REASON_BY_STATUS[self.status])
        if not self.status.terminal and self.terminal_reason is not None:
            raise ExternalCodingAgentStatusError("invalid_terminal_reason", "non-terminal status cannot carry a terminal reason")
        if self.external_session_id is not None:
            object.__setattr__(self, "external_session_id", _safe_id("external_session_id", self.external_session_id))
        if self.provider_opaque_ref is not None:
            object.__setattr__(self, "provider_opaque_ref", _safe_ref("provider_opaque_ref", self.provider_opaque_ref))
        if self.binding is not None and not isinstance(self.binding, ExternalCodingAgentBinding):
            raise ExternalCodingAgentStatusError("invalid_binding", "binding must be ExternalCodingAgentBinding")

    @property
    def is_terminal(self) -> bool:
        return self.status.terminal

    @property
    def normalized_label(self) -> str:
        if self.status is ClawRunStatus.FAILED and self.terminal_reason is ExternalCodingAgentTerminalReason.LOST_PROCESS:
            return "lost"
        return self.status.value

    def assert_binding_matches(self, request: ExternalCodingAgentStartRequest) -> None:
        if self.binding is None:
            raise ExternalCodingAgentError("binding_missing", "normalized status must carry the observed binding")
        if self.binding.source_revision != request.source_revision:
            raise ExternalCodingAgentError("revision_mismatch", "observed source revision does not match the request")
        if self.binding.worktree_ref != request.worktree_ref or self.binding.worktree_base_revision != request.worktree_base_revision:
            raise ExternalCodingAgentError("worktree_mismatch", "observed worktree binding does not match the request")
        if self.binding.sandbox_lease_id != request.sandbox_lease.lease_id:
            raise ExternalCodingAgentError("sandbox_mismatch", "observed sandbox binding does not match the request")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "external-coding-agent-status.v1",
            "status": self.status.value,
            "normalized_label": self.normalized_label,
            "terminal_reason": self.terminal_reason.value if self.terminal_reason else None,
            "sequence": self.sequence,
            "external_session_id": self.external_session_id,
            "provider_opaque_ref": self.provider_opaque_ref,
            "binding": self.binding.safe_dict() if self.binding else None,
            "canonical_lifecycle": "claw_run_status",
            "raw_provider_response": False,
        }


@dataclass(frozen=True, slots=True)
class ExternalCodingAgentPermissionHandoff:
    """A provider permission request bound to an existing P01 approval pause."""

    permission_id: str
    external_run_id: str
    capability_ref: str
    approval_pause: ApprovalPause

    def __post_init__(self) -> None:
        object.__setattr__(self, "permission_id", _safe_id("permission_id", self.permission_id))
        object.__setattr__(self, "external_run_id", _safe_id("external_run_id", self.external_run_id))
        object.__setattr__(self, "capability_ref", _safe_ref("capability_ref", self.capability_ref))
        if not isinstance(self.approval_pause, ApprovalPause):
            raise ExternalCodingAgentError("approval_binding_required", "permission handoff requires a canonical ApprovalPause")

    def assert_matches(self, request: ExternalCodingAgentStartRequest, *, permission_id: str | None = None) -> None:
        if self.external_run_id != request.external_run_id or self.approval_pause.run_id != request.claw_run_id:
            raise ExternalCodingAgentError("permission_mismatch", "permission handoff does not match the external run")
        if permission_id is not None and permission_id != self.permission_id:
            raise ExternalCodingAgentError("permission_mismatch", "permission id does not match the handoff")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "external-coding-agent-permission.v1",
            "permission_id": self.permission_id,
            "external_run_id": self.external_run_id,
            "capability_ref": self.capability_ref,
            "approval_pause_id": self.approval_pause.pause_id,
            "invocation_sha256": self.approval_pause.invocation_sha256,
            "approval_authority": "p01",
            "raw_tool_arguments": False,
            "raw_credentials": False,
        }


@dataclass(frozen=True, slots=True)
class ExternalCodingAgentApprovalBinding:
    """Existing P01 pause, decision, and resumable state as one server binding."""

    pause: ApprovalPause
    decision: VerifiedApprovalDecision
    continuation: AgentContinuationState

    def __post_init__(self) -> None:
        if not isinstance(self.pause, ApprovalPause):
            raise ExternalCodingAgentError("approval_binding_required", "pause must be canonical ApprovalPause")
        if not isinstance(self.decision, VerifiedApprovalDecision):
            raise ExternalCodingAgentError("approval_binding_required", "decision must be canonical VerifiedApprovalDecision")
        if not isinstance(self.continuation, AgentContinuationState):
            raise ExternalCodingAgentError("approval_binding_required", "continuation must be canonical AgentContinuationState")
        if self.decision.pause_id != self.pause.pause_id:
            raise ExternalCodingAgentError("approval_mismatch", "approval decision does not belong to the pause")
        if self.decision.outcome is not ApprovalOutcome.APPROVED:
            raise ExternalCodingAgentError("approval_denied", "only an approved canonical decision can resume")
        if self.continuation.pause != self.pause or self.continuation.status is not ContinuationStatus.RESUMABLE:
            raise ExternalCodingAgentError("approval_not_resumable", "continuation is not canonical resumable state")
        if self.continuation.decision_id != self.decision.decision_id:
            raise ExternalCodingAgentError("approval_mismatch", "continuation decision does not match approval decision")

    def assert_matches(
        self,
        request: ExternalCodingAgentStartRequest,
        handoff: ExternalCodingAgentPermissionHandoff,
    ) -> None:
        handoff.assert_matches(request)
        if self.pause != handoff.approval_pause:
            raise ExternalCodingAgentError("permission_mismatch", "approval binding does not match permission handoff")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "external-coding-agent-approval-binding.v1",
            "pause_id": self.pause.pause_id,
            "decision_id": self.decision.decision_id,
            "decision_outcome": self.decision.outcome.value,
            "authority_ref": self.decision.authority_ref,
            "evidence_ref": self.decision.evidence_ref,
            "continuation_status": self.continuation.status.value,
            "approval_authority": "p01",
            "raw_tool_arguments": False,
            "raw_credentials": False,
        }


@dataclass(frozen=True, slots=True)
class ExternalCodingAgentStartRequest:
    """Server-owned request material accepted by a provider-neutral adapter."""

    external_run_id: str
    runner_kind: str
    runner_revision: str
    claw_run_id: str
    claw_task_id: str
    correlation_id: str
    task_ref: str
    repository_ref: str
    source_revision: str
    worktree_ref: str
    worktree_base_revision: str
    sandbox_lease: SandboxLease
    credential_refs: tuple[str, ...] = ()
    capability_grant_refs: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    approval_pause: ApprovalPause | None = None
    idempotency_key: str = "external-run-default"
    timeout_seconds: int = 900

    def __post_init__(self) -> None:
        for name in (
            "external_run_id",
            "runner_kind",
            "claw_run_id",
            "claw_task_id",
            "correlation_id",
            "idempotency_key",
        ):
            object.__setattr__(self, name, _safe_id(name, getattr(self, name)))
        try:
            object.__setattr__(self, "runner_revision", exact_commit_revision(self.runner_revision, "runner_revision"))
            object.__setattr__(self, "source_revision", exact_commit_revision(self.source_revision, "source_revision"))
            object.__setattr__(self, "worktree_base_revision", exact_commit_revision(self.worktree_base_revision, "worktree_base_revision"))
        except ContractError as exc:
            raise ExternalCodingAgentError("invalid_revision", str(exc)) from exc
        object.__setattr__(self, "task_ref", _safe_ref("task_ref", self.task_ref))
        object.__setattr__(self, "repository_ref", _safe_ref("repository_ref", self.repository_ref))
        object.__setattr__(self, "worktree_ref", _safe_ref("worktree_ref", self.worktree_ref))
        if self.source_revision != self.worktree_base_revision:
            raise ExternalCodingAgentError("worktree_mismatch", "worktree base revision must equal source revision")
        if not isinstance(self.sandbox_lease, SandboxLease):
            raise ExternalCodingAgentError("sandbox_binding_required", "sandbox_lease must be a canonical SandboxLease")
        if self.sandbox_lease.run_id != self.claw_run_id:
            raise ExternalCodingAgentError("sandbox_mismatch", "sandbox lease run does not match canonical Claw run")
        if self.sandbox_lease.execution_mode is not ExecutionMode.CLOUD:
            raise ExternalCodingAgentError("sandbox_mismatch", "external runner requires a cloud sandbox lease")
        if self.sandbox_lease.network_policy is not NetworkPolicy.OFF:
            raise ExternalCodingAgentError("sandbox_mismatch", "external runner requires network-off sandbox policy")
        if self.sandbox_lease.state is not SandboxLeaseState.RESERVED:
            raise ExternalCodingAgentError("sandbox_mismatch", "external runner requires a reserved sandbox lease")
        for name, values in (
            ("credential_refs", self.credential_refs),
            ("capability_grant_refs", self.capability_grant_refs),
            ("required_capabilities", self.required_capabilities),
        ):
            if not isinstance(values, tuple):
                object.__setattr__(self, name, tuple(values))
            normalized = tuple(_safe_ref(name, value, limit=256) for value in getattr(self, name))
            if len(set(normalized)) != len(normalized):
                raise ExternalCodingAgentError("invalid_reference", f"{name} must not contain duplicates")
            object.__setattr__(self, name, normalized)
        write_or_send = {value.lower() for value in self.required_capabilities} & {
            "write",
            "send",
            "repo_write",
            "repo_send",
            "filesystem_write",
            "connector_write",
            "connector_send",
        }
        if write_or_send and not self.capability_grant_refs:
            raise ExternalCodingAgentError("unauthorized_permission", "write/send capability requires a server grant reference")
        if self.approval_pause is not None:
            if not isinstance(self.approval_pause, ApprovalPause):
                raise ExternalCodingAgentError("approval_binding_required", "approval_pause must be canonical ApprovalPause")
            if self.approval_pause.run_id != self.claw_run_id:
                raise ExternalCodingAgentError("approval_mismatch", "approval pause does not match canonical Claw run")
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, int) or not 60 <= self.timeout_seconds <= _MAX_TIMEOUT_SECONDS:
            raise ExternalCodingAgentError("invalid_timeout", "timeout_seconds must be between 60 and 3600")

    @property
    def binding(self) -> ExternalCodingAgentBinding:
        return ExternalCodingAgentBinding(
            source_revision=self.source_revision,
            worktree_ref=self.worktree_ref,
            worktree_base_revision=self.worktree_base_revision,
            sandbox_lease_id=self.sandbox_lease.lease_id,
        )

    @property
    def fingerprint(self) -> str:
        return request_fingerprint(
            {
                "external_run_id": self.external_run_id,
                "runner_kind": self.runner_kind,
                "runner_revision": self.runner_revision,
                "claw_run_id": self.claw_run_id,
                "claw_task_id": self.claw_task_id,
                "correlation_id": self.correlation_id,
                "source_revision": self.source_revision,
                "worktree_ref": self.worktree_ref,
                "worktree_base_revision": self.worktree_base_revision,
                "sandbox_lease_id": self.sandbox_lease.lease_id,
                "credential_refs": list(self.credential_refs),
                "capability_grant_refs": list(self.capability_grant_refs),
                "required_capabilities": list(self.required_capabilities),
                "idempotency_key": self.idempotency_key,
            }
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "external-coding-agent-start.v1",
            "external_run_id": self.external_run_id,
            "runner_kind": self.runner_kind,
            "runner_revision": self.runner_revision,
            "claw_run_id": self.claw_run_id,
            "claw_task_id": self.claw_task_id,
            "correlation_id": self.correlation_id,
            "repository_ref": self.repository_ref,
            "binding": self.binding.safe_dict(),
            "credential_reference_count": len(self.credential_refs),
            "capability_grant_reference_count": len(self.capability_grant_refs),
            "required_capabilities": list(self.required_capabilities),
            "approval_pause_id": self.approval_pause.pause_id if self.approval_pause else None,
            "idempotency_key": self.idempotency_key,
            "timeout_seconds": self.timeout_seconds,
            "raw_credentials": False,
            "raw_provider_response": False,
            "implicit_write_send": False,
        }


@dataclass(frozen=True, slots=True)
class ExternalCodingAgentRunHandle:
    external_run_id: str
    claw_run_id: str
    runner_kind: str
    runner_revision: str
    status: ExternalCodingAgentStatus
    external_session_id: str | None = None
    provider_opaque_ref: str | None = None
    binding: ExternalCodingAgentBinding | None = None

    def __post_init__(self) -> None:
        for name in ("external_run_id", "claw_run_id", "runner_kind", "runner_revision"):
            object.__setattr__(self, name, _safe_id(name, getattr(self, name)))
        if not isinstance(self.status, ExternalCodingAgentStatus):
            raise ExternalCodingAgentError("invalid_status", "status must be ExternalCodingAgentStatus")
        if self.external_session_id is not None:
            object.__setattr__(self, "external_session_id", _safe_id("external_session_id", self.external_session_id))
        if self.provider_opaque_ref is not None:
            object.__setattr__(self, "provider_opaque_ref", _safe_ref("provider_opaque_ref", self.provider_opaque_ref))
        if self.binding is not None and not isinstance(self.binding, ExternalCodingAgentBinding):
            raise ExternalCodingAgentError("invalid_binding", "binding must be ExternalCodingAgentBinding")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "external-coding-agent-handle.v1",
            "external_run_id": self.external_run_id,
            "claw_run_id": self.claw_run_id,
            "runner_kind": self.runner_kind,
            "runner_revision": self.runner_revision,
            "status": self.status.safe_dict(),
            "external_session_id": self.external_session_id,
            "provider_opaque_ref": self.provider_opaque_ref,
            "binding": self.binding.safe_dict() if self.binding else None,
            "adapter_authority": False,
        }


@dataclass(frozen=True, slots=True)
class ExternalCodingAgentTerminalResult:
    external_run_id: str
    status: ClawRunStatus
    terminal_reason: ExternalCodingAgentTerminalReason
    result_ref: str
    binding: ExternalCodingAgentBinding
    output_digest: str | None = None
    evidence_ref: str | None = None
    provider_opaque_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "external_run_id", _safe_id("external_run_id", self.external_run_id))
        if not isinstance(self.status, ClawRunStatus):
            object.__setattr__(self, "status", ClawRunStatus(self.status))
        if not self.status.terminal:
            raise ExternalCodingAgentError("invalid_terminal_result", "terminal result requires a terminal Claw status")
        if not isinstance(self.terminal_reason, ExternalCodingAgentTerminalReason):
            object.__setattr__(self, "terminal_reason", ExternalCodingAgentTerminalReason(self.terminal_reason))
        if self.status is ClawRunStatus.COMPLETED and self.terminal_reason is not ExternalCodingAgentTerminalReason.COMPLETED:
            raise ExternalCodingAgentError("invalid_terminal_result", "completed result must use completed reason")
        if self.status is ClawRunStatus.CANCELLED and self.terminal_reason is not ExternalCodingAgentTerminalReason.CANCELLED:
            raise ExternalCodingAgentError("invalid_terminal_result", "cancelled result must use cancelled reason")
        object.__setattr__(self, "result_ref", _safe_id("result_ref", self.result_ref))
        if not isinstance(self.binding, ExternalCodingAgentBinding):
            raise ExternalCodingAgentError("invalid_binding", "binding must be ExternalCodingAgentBinding")
        if self.output_digest is not None:
            object.__setattr__(self, "output_digest", _safe_digest("output_digest", self.output_digest))
        if self.evidence_ref is not None:
            object.__setattr__(self, "evidence_ref", _safe_ref("evidence_ref", self.evidence_ref))
        if self.provider_opaque_ref is not None:
            object.__setattr__(self, "provider_opaque_ref", _safe_ref("provider_opaque_ref", self.provider_opaque_ref))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "external-coding-agent-terminal-result.v1",
            "external_run_id": self.external_run_id,
            "status": self.status.value,
            "terminal_reason": self.terminal_reason.value,
            "result_ref": self.result_ref,
            "binding": self.binding.safe_dict(),
            "output_digest": self.output_digest,
            "evidence_ref": self.evidence_ref,
            "provider_opaque_ref": self.provider_opaque_ref,
            "raw_provider_response": False,
            "raw_tool_output": False,
        }


@dataclass(frozen=True, slots=True)
class ExternalCodingAgentEvent:
    event_id: str
    external_run_id: str
    sequence: int
    kind: ExternalCodingAgentEventKind
    status: ExternalCodingAgentStatus
    occurred_at: datetime
    message: str | None = None
    provider_event_ref: str | None = None
    permission: ExternalCodingAgentPermissionHandoff | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _safe_id("event_id", self.event_id))
        object.__setattr__(self, "external_run_id", _safe_id("external_run_id", self.external_run_id))
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
            raise ExternalCodingAgentError("invalid_event_sequence", "event sequence must be a positive integer")
        if not isinstance(self.kind, ExternalCodingAgentEventKind):
            object.__setattr__(self, "kind", ExternalCodingAgentEventKind(self.kind))
        if not isinstance(self.status, ExternalCodingAgentStatus):
            raise ExternalCodingAgentError("invalid_event_status", "event status must be ExternalCodingAgentStatus")
        object.__setattr__(self, "occurred_at", _aware("occurred_at", self.occurred_at))
        if self.message is not None:
            object.__setattr__(self, "message", _safe_text("message", self.message, limit=_MAX_MESSAGE_CHARS))
        if self.provider_event_ref is not None:
            object.__setattr__(self, "provider_event_ref", _safe_ref("provider_event_ref", self.provider_event_ref))
        if self.kind is ExternalCodingAgentEventKind.PERMISSION_REQUESTED and (
            self.status.status is not ClawRunStatus.WAITING_APPROVAL or self.permission is None
        ):
            raise ExternalCodingAgentError("permission_binding_required", "permission event requires a waiting status and handoff")
        if self.kind is ExternalCodingAgentEventKind.PROCESS_LOST and self.status.normalized_label != "lost":
            raise ExternalCodingAgentError("lost_process_not_normalized", "lost process event must carry lost normalization")
        if self.kind is ExternalCodingAgentEventKind.TERMINAL_RESULT and not self.status.is_terminal:
            raise ExternalCodingAgentError("invalid_terminal_event", "terminal result event requires terminal status")
        if self.kind is ExternalCodingAgentEventKind.FAILURE and self.status.status is not ClawRunStatus.FAILED:
            raise ExternalCodingAgentError("invalid_failure_event", "failure event requires failed status")

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(
            "|".join(
                (
                    self.event_id,
                    self.external_run_id,
                    str(self.sequence),
                    self.kind.value,
                    self.status.safe_dict()["status"],
                    self.status.normalized_label,
                    self.occurred_at.isoformat(),
                    self.message or "",
                    self.provider_event_ref or "",
                )
            ).encode("utf-8")
        ).hexdigest()

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "external-coding-agent-event.v1",
            "event_id": self.event_id,
            "external_run_id": self.external_run_id,
            "sequence": self.sequence,
            "kind": self.kind.value,
            "status": self.status.safe_dict(),
            "occurred_at": self.occurred_at.isoformat().replace("+00:00", "Z"),
            "message": self.message,
            "provider_event_ref": self.provider_event_ref,
            "permission": self.permission.safe_dict() if self.permission else None,
            "event_fingerprint": self.fingerprint,
            "raw_provider_response": False,
            "raw_tool_arguments": False,
        }


class ExternalCodingAgentEventStream:
    """Bounded per-run event stream with replay and ordering rules."""

    def __init__(self) -> None:
        self._events: dict[str, list[ExternalCodingAgentEvent]] = {}
        self._by_id: dict[tuple[str, str], ExternalCodingAgentEvent] = {}

    def append(self, event: ExternalCodingAgentEvent) -> None:
        if not isinstance(event, ExternalCodingAgentEvent):
            raise ExternalCodingAgentError("invalid_event", "event must be ExternalCodingAgentEvent")
        key = (event.external_run_id, event.event_id)
        existing = self._by_id.get(key)
        if existing is not None:
            if existing == event:
                return
            raise ExternalCodingAgentError("event_id_reuse_conflict", "event ID replay conflicts with existing event")
        stream = self._events.setdefault(event.external_run_id, [])
        if len(stream) >= _MAX_EVENTS:
            raise ExternalCodingAgentError("event_budget_exceeded", "external event stream budget exceeded")
        if event.sequence != len(stream) + 1:
            raise ExternalCodingAgentError("event_sequence_gap", "external event sequence must be contiguous")
        if stream and event.occurred_at < stream[-1].occurred_at:
            raise ExternalCodingAgentError("event_time_regression", "external event time cannot regress")
        stream.append(event)
        self._by_id[key] = event

    def events(self, external_run_id: str) -> tuple[ExternalCodingAgentEvent, ...]:
        external_run_id = _safe_id("external_run_id", external_run_id)
        return tuple(self._events.get(external_run_id, ()))

    def poll(self, external_run_id: str, *, after_sequence: int = 0) -> tuple[ExternalCodingAgentEvent, ...]:
        if isinstance(after_sequence, bool) or not isinstance(after_sequence, int) or after_sequence < 0:
            raise ExternalCodingAgentError("invalid_poll_cursor", "after_sequence must be a non-negative integer")
        events = self.events(external_run_id)
        return tuple(event for event in events if event.sequence > after_sequence)[:_MAX_POLL_EVENTS]

    def safe_export(self, external_run_id: str) -> dict[str, Any]:
        return {
            "contract_version": "external-coding-agent-event-stream.v1",
            "external_run_id": external_run_id,
            "events": [event.safe_dict() for event in self.events(external_run_id)],
            "history_authority": False,
            "raw_provider_response": False,
        }


class ExternalCodingAgentRunner(Protocol):
    """Provider adapter port; it cannot create Claw authority."""

    def start(self, request: ExternalCodingAgentStartRequest) -> ExternalCodingAgentRunHandle: ...

    def status(self, external_run_id: str) -> ExternalCodingAgentStatus: ...

    def observe(self, external_run_id: str) -> ExternalCodingAgentStatus: ...

    def reconcile_lost_process(self, external_run_id: str, *, reason_ref: str = "process_lost") -> ExternalCodingAgentStatus: ...

    def poll(self, external_run_id: str, *, after_sequence: int = 0) -> tuple[ExternalCodingAgentEvent, ...]: ...

    def stream(self, external_run_id: str, *, after_sequence: int = 0) -> tuple[ExternalCodingAgentEvent, ...]: ...

    def cancel(self, external_run_id: str, *, reason_ref: str = "cancelled") -> ExternalCodingAgentStatus: ...

    def resume_or_message(
        self,
        external_run_id: str,
        *,
        approval: ExternalCodingAgentApprovalBinding | None = None,
        message_ref: str | None = None,
    ) -> ExternalCodingAgentStatus: ...

    def result(self, external_run_id: str) -> ExternalCodingAgentTerminalResult: ...

    def close(self, external_run_id: str) -> None: ...


@dataclass(slots=True)
class _FakeRun:
    request: ExternalCodingAgentStartRequest
    claw_run: ClawRun
    stream: ExternalCodingAgentEventStream
    external_session_id: str
    provider_opaque_ref: str
    terminal_reason: ExternalCodingAgentTerminalReason | None = None
    terminal_result: ExternalCodingAgentTerminalResult | None = None
    permission: ExternalCodingAgentPermissionHandoff | None = None
    closed: bool = False


class DeterministicFakeExternalCodingAgentRunner:
    """Network-free adapter double for contract and conformance tests."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        start_failure: bool = False,
        runtime_failure: bool = False,
        lost_process: bool = False,
        approval_required: bool = False,
    ) -> None:
        self._clock = clock or (lambda: _DEFAULT_CLOCK)
        self._start_failure = start_failure
        self._runtime_failure = runtime_failure
        self._lost_process = lost_process
        self._approval_required = approval_required
        self._lock = RLock()
        self._runs: dict[str, _FakeRun] = {}
        self._correlations: dict[str, str] = {}

    def _now(self) -> datetime:
        return _aware("clock", self._clock())

    def _record(self, external_run_id: str) -> _FakeRun:
        try:
            return self._runs[external_run_id]
        except KeyError as exc:
            raise ExternalCodingAgentError("unknown_external_run", "external run is not known to this adapter") from exc

    def _status(self, record: _FakeRun) -> ExternalCodingAgentStatus:
        return ExternalCodingAgentStatus(
            status=record.claw_run.status,
            terminal_reason=record.terminal_reason,
            sequence=len(record.stream.events(record.request.external_run_id)),
            external_session_id=record.external_session_id,
            provider_opaque_ref=record.provider_opaque_ref,
            binding=record.request.binding,
        )

    def _result(self, record: _FakeRun) -> ExternalCodingAgentTerminalResult:
        if record.terminal_result is None:
            raise ExternalCodingAgentError("result_not_terminal", "terminal result is not available")
        return record.terminal_result

    def _emit(
        self,
        record: _FakeRun,
        kind: ExternalCodingAgentEventKind,
        *,
        permission: ExternalCodingAgentPermissionHandoff | None = None,
        message: str | None = None,
    ) -> ExternalCodingAgentEvent:
        sequence = len(record.stream.events(record.request.external_run_id)) + 1
        event = ExternalCodingAgentEvent(
            event_id=f"{record.request.external_run_id}:event:{sequence}",
            external_run_id=record.request.external_run_id,
            sequence=sequence,
            kind=kind,
            status=self._status(record),
            occurred_at=self._now(),
            message=message,
            provider_event_ref=f"{record.provider_opaque_ref}:{sequence}",
            permission=permission,
        )
        record.stream.append(event)
        return event

    def _transition(
        self,
        record: _FakeRun,
        status: ClawRunStatus,
        reason: ExternalCodingAgentTerminalReason,
        *,
        kind: ExternalCodingAgentEventKind,
        message: str,
    ) -> ExternalCodingAgentStatus:
        if record.claw_run.terminal:
            if record.terminal_result is not None and record.claw_run.status is status:
                return self._status(record)
            raise ExternalCodingAgentError("terminal_run_immutable", "terminal external run cannot transition")
        try:
            record.claw_run.transition(status, summary=message)
        except (RunStateError, ContractError) as exc:
            raise ExternalCodingAgentError("invalid_status_transition", str(exc)) from exc
        record.terminal_reason = reason if status.terminal else None
        self._emit(record, kind, message=message)
        if status.terminal:
            result_status = "completed" if status is ClawRunStatus.COMPLETED else "failed" if status is ClawRunStatus.FAILED else "cancelled"
            result_ref = f"result:{record.request.external_run_id}"
            output_digest = hashlib.sha256(f"{record.request.external_run_id}:{result_status}".encode()).hexdigest() if status is ClawRunStatus.COMPLETED else None
            record.terminal_result = ExternalCodingAgentTerminalResult(
                external_run_id=record.request.external_run_id,
                status=status,
                terminal_reason=reason,
                result_ref=result_ref,
                binding=record.request.binding,
                output_digest=output_digest,
                evidence_ref=f"evidence:{record.request.external_run_id}" if status is ClawRunStatus.COMPLETED else None,
                provider_opaque_ref=record.provider_opaque_ref,
            )
        return self._status(record)

    def start(self, request: ExternalCodingAgentStartRequest) -> ExternalCodingAgentRunHandle:
        if not isinstance(request, ExternalCodingAgentStartRequest):
            raise ExternalCodingAgentError("invalid_request", "request must be ExternalCodingAgentStartRequest")
        if request.external_run_id in self._runs:
            raise ExternalCodingAgentError("duplicate_start", "external run has already been started")
        if request.correlation_id in self._correlations:
            raise ExternalCodingAgentError("duplicate_correlation", "correlation already identifies an external run")
        intent = ClawTaskIntent(
            task_id=request.claw_task_id,
            task=request.task_ref,
            repository_ref=request.repository_ref,
            execution_mode=ExecutionMode.CLOUD,
            requested_revision=request.source_revision,
            source_surface="external_coding_agent",
            trace_id=request.correlation_id,
        )
        claw_run = ClawRun.create(request.claw_run_id, intent)
        digest = hashlib.sha256(request.external_run_id.encode()).hexdigest()[:16]
        record = _FakeRun(
            request=request,
            claw_run=claw_run,
            stream=ExternalCodingAgentEventStream(),
            external_session_id=f"external-session:{digest}",
            provider_opaque_ref=f"provider-ref:{digest}",
        )
        self._runs[request.external_run_id] = record
        self._correlations[request.correlation_id] = request.external_run_id
        if self._start_failure:
            self._transition(
                record,
                ClawRunStatus.FAILED,
                ExternalCodingAgentTerminalReason.START_FAILED,
                kind=ExternalCodingAgentEventKind.FAILURE,
                message="external runner start failed",
            )
        else:
            self._emit(record, ExternalCodingAgentEventKind.STATUS_CHANGED, message="external run queued")
        return ExternalCodingAgentRunHandle(
            external_run_id=request.external_run_id,
            claw_run_id=request.claw_run_id,
            runner_kind=request.runner_kind,
            runner_revision=request.runner_revision,
            status=self._status(record),
            external_session_id=record.external_session_id,
            provider_opaque_ref=record.provider_opaque_ref,
            binding=request.binding,
        )

    def status(self, external_run_id: str) -> ExternalCodingAgentStatus:
        return self._status(self._record(_safe_id("external_run_id", external_run_id)))

    def observe(self, external_run_id: str) -> ExternalCodingAgentStatus:
        record = self._record(_safe_id("external_run_id", external_run_id))
        if record.closed:
            raise ExternalCodingAgentError("runner_closed", "closed external runner cannot observe")
        if record.claw_run.terminal:
            return self._status(record)
        if self._lost_process:
            return self._transition(
                record,
                ClawRunStatus.FAILED,
                ExternalCodingAgentTerminalReason.LOST_PROCESS,
                kind=ExternalCodingAgentEventKind.PROCESS_LOST,
                message="external process was lost",
            )
        if self._runtime_failure:
            return self._transition(
                record,
                ClawRunStatus.FAILED,
                ExternalCodingAgentTerminalReason.RUNTIME_FAILED,
                kind=ExternalCodingAgentEventKind.FAILURE,
                message="external runner runtime failed",
            )
        if self._approval_required and record.claw_run.status in {ClawRunStatus.QUEUED, ClawRunStatus.PREPARING}:
            now = self._now()
            pause = ApprovalPause(
                pause_id=f"pause:{record.request.external_run_id}",
                run_id=record.request.claw_run_id,
                agent_runtime_id="external-runner:fake@1",
                tool_id="tool:external:permission@1",
                invocation_sha256="a" * 64,
                requirement=ApprovalRequirement.USER_CONFIRMATION,
                step_index=1,
                created_at=now,
                expires_at=now + timedelta(minutes=10),
                approval_scope=("external:permission",),
            )
            permission = ExternalCodingAgentPermissionHandoff(
                permission_id=f"permission:{record.request.external_run_id}",
                external_run_id=record.request.external_run_id,
                capability_ref="capability:external:permission@1",
                approval_pause=pause,
            )
            record.permission = permission
            return self._transition_permission(record, permission)
        if record.claw_run.status is ClawRunStatus.QUEUED:
            return self._transition(
                record,
                ClawRunStatus.PREPARING,
                ExternalCodingAgentTerminalReason.UNKNOWN,
                kind=ExternalCodingAgentEventKind.STATUS_CHANGED,
                message="external runner preparing",
            )
        if record.claw_run.status is ClawRunStatus.PREPARING:
            return self._transition(
                record,
                ClawRunStatus.RUNNING,
                ExternalCodingAgentTerminalReason.UNKNOWN,
                kind=ExternalCodingAgentEventKind.STATUS_CHANGED,
                message="external runner running",
            )
        return self._transition(
            record,
            ClawRunStatus.COMPLETED,
            ExternalCodingAgentTerminalReason.COMPLETED,
            kind=ExternalCodingAgentEventKind.TERMINAL_RESULT,
            message="external run completed",
        )

    def reconcile_lost_process(self, external_run_id: str, *, reason_ref: str = "process_lost") -> ExternalCodingAgentStatus:
        record = self._record(_safe_id("external_run_id", external_run_id))
        reason_ref = _safe_ref("reason_ref", reason_ref)
        if record.claw_run.terminal:
            return self._status(record)
        return self._transition(
            record,
            ClawRunStatus.FAILED,
            ExternalCodingAgentTerminalReason.LOST_PROCESS,
            kind=ExternalCodingAgentEventKind.PROCESS_LOST,
            message=reason_ref,
        )

    def _transition_permission(self, record: _FakeRun, permission: ExternalCodingAgentPermissionHandoff) -> ExternalCodingAgentStatus:
        if record.claw_run.status is ClawRunStatus.QUEUED:
            self._transition(
                record,
                ClawRunStatus.PREPARING,
                ExternalCodingAgentTerminalReason.UNKNOWN,
                kind=ExternalCodingAgentEventKind.STATUS_CHANGED,
                message="external runner preparing",
            )
        try:
            record.claw_run.transition(ClawRunStatus.WAITING_APPROVAL, summary="external permission requires canonical approval")
        except (RunStateError, ContractError) as exc:
            raise ExternalCodingAgentError("invalid_status_transition", str(exc)) from exc
        self._emit(record, ExternalCodingAgentEventKind.PERMISSION_REQUESTED, permission=permission, message="external permission requires canonical approval")
        return self._status(record)

    def poll(self, external_run_id: str, *, after_sequence: int = 0) -> tuple[ExternalCodingAgentEvent, ...]:
        return self._record(_safe_id("external_run_id", external_run_id)).stream.poll(external_run_id, after_sequence=after_sequence)

    def stream(self, external_run_id: str, *, after_sequence: int = 0) -> tuple[ExternalCodingAgentEvent, ...]:
        return self.poll(external_run_id, after_sequence=after_sequence)

    def cancel(self, external_run_id: str, *, reason_ref: str = "cancelled") -> ExternalCodingAgentStatus:
        with self._lock:
            record = self._record(_safe_id("external_run_id", external_run_id))
            reason_ref = _safe_ref("reason_ref", reason_ref)
            if record.claw_run.terminal:
                return self._status(record)
            return self._transition(
                record,
                ClawRunStatus.CANCELLED,
                ExternalCodingAgentTerminalReason.CANCELLED,
                kind=ExternalCodingAgentEventKind.TERMINAL_RESULT,
                message=reason_ref,
            )

    def resume_or_message(
        self,
        external_run_id: str,
        *,
        approval: ExternalCodingAgentApprovalBinding | None = None,
        message_ref: str | None = None,
    ) -> ExternalCodingAgentStatus:
        record = self._record(_safe_id("external_run_id", external_run_id))
        if record.claw_run.status is ClawRunStatus.RUNNING and approval is None and message_ref is not None:
            _safe_ref("message_ref", message_ref)
            self._emit(record, ExternalCodingAgentEventKind.STATUS_CHANGED, message="external message accepted")
            return self._status(record)
        if record.claw_run.status is not ClawRunStatus.WAITING_APPROVAL:
            raise ExternalCodingAgentError("resume_not_allowed", "only a waiting external run can be resumed")
        if approval is None or record.permission is None:
            raise ExternalCodingAgentError("unauthorized_permission", "resume requires the matching canonical approval binding")
        if not isinstance(approval, ExternalCodingAgentApprovalBinding):
            raise ExternalCodingAgentError("unauthorized_permission", "resume requires the canonical approval binding")
        approval.assert_matches(record.request, record.permission)
        if message_ref is not None:
            _safe_ref("message_ref", message_ref)
        try:
            record.claw_run.transition(ClawRunStatus.RUNNING, summary="external run resumed after canonical approval")
        except (RunStateError, ContractError) as exc:
            raise ExternalCodingAgentError("invalid_status_transition", str(exc)) from exc
        self._emit(record, ExternalCodingAgentEventKind.PERMISSION_RESOLVED, message="external run resumed after canonical approval")
        return self._status(record)

    def result(self, external_run_id: str) -> ExternalCodingAgentTerminalResult:
        return self._result(self._record(_safe_id("external_run_id", external_run_id)))

    def close(self, external_run_id: str) -> None:
        record = self._record(_safe_id("external_run_id", external_run_id))
        record.closed = True


class ExternalCodingAgentConformanceResult:
    def __init__(self, case_id: str, passed: bool, *, error_code: str | None = None, details: str = "") -> None:
        self.case_id = case_id
        self.passed = passed
        self.error_code = error_code
        self.details = details

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "passed": self.passed,
            "error_code": self.error_code,
            "details": self.details,
        }


@dataclass(frozen=True, slots=True)
class ExternalCodingAgentConformanceReport:
    results: tuple[ExternalCodingAgentConformanceResult, ...]

    @property
    def overall_conforming(self) -> bool:
        return bool(self.results) and all(result.passed for result in self.results)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "external-coding-agent-conformance-report.v1",
            "overall_conforming": self.overall_conforming,
            "cases": [result.to_public_dict() for result in self.results],
            "live_provider_calls": 0,
            "raw_credentials": False,
        }


class ExternalCodingAgentConformanceHarness:
    """Provider-neutral checks over a runner's public adapter port."""

    def run(self, runner: ExternalCodingAgentRunner, request: ExternalCodingAgentStartRequest) -> ExternalCodingAgentConformanceReport:
        results: list[ExternalCodingAgentConformanceResult] = []

        def record(case_id: str, operation: Callable[[], None]) -> None:
            try:
                operation()
            except ExternalCodingAgentError as exc:
                results.append(ExternalCodingAgentConformanceResult(case_id, False, error_code=exc.code, details=exc.safe_message))
            except (KeyError, RuntimeError, TypeError, ValueError) as exc:
                results.append(ExternalCodingAgentConformanceResult(case_id, False, error_code="unexpected_exception", details=type(exc).__name__))
            else:
                results.append(ExternalCodingAgentConformanceResult(case_id, True, details="conformance invariant passed"))

        state: dict[str, Any] = {}

        def start() -> None:
            handle = runner.start(request)
            if not isinstance(handle, ExternalCodingAgentRunHandle):
                raise ExternalCodingAgentConformanceError("invalid_handle", "runner returned an invalid handle")
            if handle.external_run_id != request.external_run_id or handle.claw_run_id != request.claw_run_id:
                raise ExternalCodingAgentConformanceError("identity_mismatch", "runner handle identity does not match request")
            if handle.binding is not None and not handle.binding.matches(request):
                raise ExternalCodingAgentConformanceError("binding_mismatch", "runner handle binding does not match request")
            state["handle"] = handle

        def observe() -> None:
            status = runner.status(request.external_run_id)
            if not isinstance(status, ExternalCodingAgentStatus):
                raise ExternalCodingAgentConformanceError("invalid_status", "runner returned an invalid status")
            status.assert_binding_matches(request)
            observed = runner.observe(request.external_run_id)
            observed.assert_binding_matches(request)
            current = runner.status(request.external_run_id)
            if current.status is not observed.status:
                raise ExternalCodingAgentConformanceError("status_not_stable", "observe and status disagree")
            events = runner.poll(request.external_run_id, after_sequence=0)
            if not events:
                raise ExternalCodingAgentConformanceError("event_missing", "runner did not expose its initial normalized event")
            for index, event in enumerate(events, start=1):
                if event.external_run_id != request.external_run_id:
                    raise ExternalCodingAgentConformanceError("event_identity_mismatch", "event identity does not match run")
                if event.sequence != index:
                    raise ExternalCodingAgentConformanceError("event_sequence_invalid", "event sequence is not contiguous")
                event.status.assert_binding_matches(request)
            if events[-1].status.status is not observed.status:
                raise ExternalCodingAgentConformanceError("event_status_mismatch", "latest event disagrees with observed status")
            state["status"] = observed
            state["events"] = events
            if observed.status is ClawRunStatus.WAITING_APPROVAL:
                permission_events = [event for event in events if event.kind is ExternalCodingAgentEventKind.PERMISSION_REQUESTED]
                if not permission_events or permission_events[-1].permission is None:
                    raise ExternalCodingAgentConformanceError("permission_binding_missing", "waiting status lacks canonical permission handoff")
                permission_events[-1].permission.assert_matches(request)

        def terminal() -> None:
            status = state.get("status")
            if not isinstance(status, ExternalCodingAgentStatus) or not status.is_terminal:
                return
            result = runner.result(request.external_run_id)
            replay = runner.result(request.external_run_id)
            if result != replay:
                raise ExternalCodingAgentConformanceError("terminal_replay_changed", "terminal result replay changed")
            if not result.binding.matches(request):
                raise ExternalCodingAgentConformanceError("terminal_binding_mismatch", "terminal result binding does not match request")
            if result.status is not status.status or result.terminal_reason is not status.terminal_reason:
                raise ExternalCodingAgentConformanceError("terminal_projection_mismatch", "terminal result disagrees with normalized status")

        def close() -> None:
            runner.close(request.external_run_id)
            runner.close(request.external_run_id)

        record("start_identity_and_binding", start)
        if "handle" in state:
            record("observe_status_and_event_projection", observe)
            record("terminal_replay_is_idempotent", terminal)
            record("close_is_idempotent", close)
        return ExternalCodingAgentConformanceReport(tuple(results))


EXTERNAL_CODING_AGENT_RUNNER_LIVE_ADAPTERS = 0
EXTERNAL_CODING_AGENT_RUNNER_SECOND_ORCHESTRATOR = False
EXTERNAL_CODING_AGENT_RUNNER_SECOND_APPROVAL_AUTHORITY = False
EXTERNAL_CODING_AGENT_RUNNER_SECOND_HISTORY_AUTHORITY = False
EXTERNAL_CODING_AGENT_RUNNER_SECOND_SANDBOX_AUTHORITY = False
EXTERNAL_CODING_AGENT_RUNNER_SECOND_CREDENTIAL_AUTHORITY = False

__all__ = [
    "EXTERNAL_CODING_AGENT_RUNNER_LIVE_ADAPTERS",
    "EXTERNAL_CODING_AGENT_RUNNER_SECOND_APPROVAL_AUTHORITY",
    "EXTERNAL_CODING_AGENT_RUNNER_SECOND_CREDENTIAL_AUTHORITY",
    "EXTERNAL_CODING_AGENT_RUNNER_SECOND_HISTORY_AUTHORITY",
    "EXTERNAL_CODING_AGENT_RUNNER_SECOND_ORCHESTRATOR",
    "EXTERNAL_CODING_AGENT_RUNNER_SECOND_SANDBOX_AUTHORITY",
    "DeterministicFakeExternalCodingAgentRunner",
    "ExternalCodingAgentApprovalBinding",
    "ExternalCodingAgentBinding",
    "ExternalCodingAgentConformanceHarness",
    "ExternalCodingAgentConformanceReport",
    "ExternalCodingAgentConformanceResult",
    "ExternalCodingAgentError",
    "ExternalCodingAgentEvent",
    "ExternalCodingAgentEventKind",
    "ExternalCodingAgentEventStream",
    "ExternalCodingAgentPermissionHandoff",
    "ExternalCodingAgentRunHandle",
    "ExternalCodingAgentRunner",
    "ExternalCodingAgentStartRequest",
    "ExternalCodingAgentStatus",
    "ExternalCodingAgentStatusError",
    "ExternalCodingAgentTerminalReason",
    "ExternalCodingAgentTerminalResult",
    "normalize_external_status",
]
