"""Bounded approval pause/resume contract for Padiem AI Core.

This module bridges ToolRuntime's existing fail-closed approval errors into an
Agent-level pause state. It deliberately does not mint ToolAuthorizationContext
values, grant scopes, approve tools, or execute continuations. A trusted caller
must authenticate an external decision and then re-enter the existing
ToolRuntime with an updated trusted authorization context.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import hashlib
import json
import re

from .contracts import RunStatus
from .tool_runtime import ToolInvocation, ToolRuntimeError


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_APPROVAL_WINDOW = timedelta(hours=24)


class AgentApprovalError(ValueError):
    """Raised when approval lifecycle state violates the bounded contract."""


class ApprovalRequirement(str, Enum):
    USER_CONFIRMATION = "user_confirmation"
    EXTERNAL_AUTHORIZATION = "external_authorization"


class ApprovalOutcome(str, Enum):
    APPROVED = "approved"
    DENIED = "denied"


class ContinuationStatus(str, Enum):
    WAITING_APPROVAL = "waiting_approval"
    RESUMABLE = "resumable"
    DENIED = "denied"
    EXPIRED = "expired"


def _identifier(name: str, value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise AgentApprovalError(f"{name} must be a bounded safe identifier")
    return value


def _aware(name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise AgentApprovalError(f"{name} must be timezone-aware")
    return value


def tool_invocation_digest(invocation: ToolInvocation) -> str:
    """Bind a pause to the exact immutable tool invocation without storing args."""
    if not isinstance(invocation, ToolInvocation):
        raise AgentApprovalError("invocation must be ToolInvocation")
    payload = {
        "tool_id": invocation.tool_id,
        "arguments": invocation.arguments_copy(),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ApprovalPause:
    pause_id: str
    run_id: str
    agent_runtime_id: str
    tool_id: str
    invocation_sha256: str
    requirement: ApprovalRequirement
    step_index: int
    created_at: datetime
    expires_at: datetime
    trace_id: str | None = None
    plan_id: str | None = None
    approval_scope: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "pause_id", _identifier("pause_id", self.pause_id))
        object.__setattr__(self, "run_id", _identifier("run_id", self.run_id))
        object.__setattr__(
            self,
            "agent_runtime_id",
            _identifier("agent_runtime_id", self.agent_runtime_id),
        )
        object.__setattr__(self, "tool_id", _identifier("tool_id", self.tool_id))
        if not isinstance(self.invocation_sha256, str) or not _SHA256_RE.fullmatch(
            self.invocation_sha256
        ):
            raise AgentApprovalError("invocation_sha256 must be a lowercase SHA-256 hex digest")
        if not isinstance(self.requirement, ApprovalRequirement):
            raise AgentApprovalError("requirement must be ApprovalRequirement")
        if isinstance(self.step_index, bool) or not isinstance(self.step_index, int):
            raise AgentApprovalError("step_index must be an integer")
        if not 1 <= self.step_index <= 64:
            raise AgentApprovalError("step_index must be between 1 and 64")
        created_at = _aware("created_at", self.created_at)
        expires_at = _aware("expires_at", self.expires_at)
        if expires_at <= created_at:
            raise AgentApprovalError("expires_at must be after created_at")
        if expires_at - created_at > MAX_APPROVAL_WINDOW:
            raise AgentApprovalError("approval window exceeds 24 hours")
        if self.trace_id is not None:
            object.__setattr__(self, "trace_id", _identifier("trace_id", self.trace_id))
        if self.plan_id is not None:
            object.__setattr__(self, "plan_id", _identifier("plan_id", self.plan_id))
        if not isinstance(self.approval_scope, tuple) or any(
            not isinstance(s, str) or not s for s in self.approval_scope
        ):
            raise AgentApprovalError("approval_scope must be a tuple of non-empty strings")

    @property
    def continuation_id(self) -> str:
        return self.pause_id

    @property
    def agent_id(self) -> str:
        return self.agent_runtime_id

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "status": "paused",
            "continuation_id": self.pause_id,
            "run_id": self.run_id,
            "trace_id": self.trace_id,
            "step_index": self.step_index,
            "agent_id": self.agent_runtime_id,
            "tool_id": self.tool_id,
            "requirement": self.requirement.value,
            "approval_scope": list(self.approval_scope),
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class VerifiedApprovalDecision:
    """Decision evidence already authenticated by a trusted product/control plane.

    The type name is a contract boundary, not a cryptographic verifier. Callers
    remain responsible for authenticating the actor/session/evidence before
    constructing this value.
    """

    decision_id: str
    pause_id: str
    outcome: ApprovalOutcome
    authority_ref: str
    evidence_ref: str
    decided_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision_id", _identifier("decision_id", self.decision_id))
        object.__setattr__(self, "pause_id", _identifier("pause_id", self.pause_id))
        if not isinstance(self.outcome, ApprovalOutcome):
            raise AgentApprovalError("outcome must be ApprovalOutcome")
        object.__setattr__(self, "authority_ref", _identifier("authority_ref", self.authority_ref))
        object.__setattr__(self, "evidence_ref", _identifier("evidence_ref", self.evidence_ref))
        _aware("decided_at", self.decided_at)


@dataclass(frozen=True, slots=True)
class AgentContinuationState:
    pause: ApprovalPause
    status: ContinuationStatus
    decision_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.pause, ApprovalPause):
            raise AgentApprovalError("pause must be ApprovalPause")
        if not isinstance(self.status, ContinuationStatus):
            raise AgentApprovalError("status must be ContinuationStatus")
        if self.status is ContinuationStatus.WAITING_APPROVAL:
            if self.decision_id is not None:
                raise AgentApprovalError("waiting state cannot contain decision_id")
        else:
            if self.decision_id is None:
                raise AgentApprovalError("resolved continuation requires decision_id")
            object.__setattr__(
                self,
                "decision_id",
                _identifier("decision_id", self.decision_id),
            )


def approval_pause_from_tool_error(
    error: ToolRuntimeError,
    *,
    pause_id: str,
    run_id: str,
    agent_runtime_id: str,
    invocation: ToolInvocation,
    step_index: int,
    created_at: datetime,
    expires_at: datetime,
    trace_id: str | None = None,
    plan_id: str | None = None,
    approval_scope: tuple[str, ...] = (),
) -> ApprovalPause | None:
    """Translate only explicit ToolRuntime approval blocks into Agent pauses.

    Other policy blocks remain terminal/handled by their existing owner. This
    prevents an Agent from converting arbitrary authorization failures into a
    resumable approval request.
    """
    if not isinstance(error, ToolRuntimeError):
        raise AgentApprovalError("error must be ToolRuntimeError")
    if not isinstance(invocation, ToolInvocation):
        raise AgentApprovalError("invocation must be ToolInvocation")

    requirement_by_code = {
        "tool_user_confirmation_required": ApprovalRequirement.USER_CONFIRMATION,
        "tool_external_authorization_required": ApprovalRequirement.EXTERNAL_AUTHORIZATION,
    }
    requirement = requirement_by_code.get(error.code)
    if requirement is None:
        return None
    if error.event is None or error.event.status is not RunStatus.POLICY_BLOCKED:
        raise AgentApprovalError("approval ToolRuntimeError must carry POLICY_BLOCKED event")
    if error.event.tool_id != invocation.tool_id:
        raise AgentApprovalError("approval error tool_id does not match invocation")

    return ApprovalPause(
        pause_id=pause_id,
        run_id=run_id,
        agent_runtime_id=agent_runtime_id,
        tool_id=invocation.tool_id,
        invocation_sha256=tool_invocation_digest(invocation),
        requirement=requirement,
        step_index=step_index,
        created_at=created_at,
        expires_at=expires_at,
        trace_id=trace_id,
        plan_id=plan_id,
        approval_scope=approval_scope,
    )


def resolve_approval_pause(
    pause: ApprovalPause,
    decision: VerifiedApprovalDecision,
    *,
    now: datetime,
    consumed_decision_ids: frozenset[str] = frozenset(),
) -> AgentContinuationState:
    """Resolve lifecycle state without creating any Tool authorization grant."""
    if not isinstance(pause, ApprovalPause):
        raise AgentApprovalError("pause must be ApprovalPause")
    if not isinstance(decision, VerifiedApprovalDecision):
        raise AgentApprovalError("decision must be VerifiedApprovalDecision")
    current = _aware("now", now)
    if decision.pause_id != pause.pause_id:
        raise AgentApprovalError("decision does not belong to this pause")
    if decision.decision_id in consumed_decision_ids:
        raise AgentApprovalError("decision_id has already been consumed")
    if decision.decided_at < pause.created_at:
        raise AgentApprovalError("decision predates approval pause")
    if decision.decided_at > current:
        raise AgentApprovalError("decision cannot be from the future")
    if current > pause.expires_at or decision.decided_at > pause.expires_at:
        return AgentContinuationState(
            pause=pause,
            status=ContinuationStatus.EXPIRED,
            decision_id=decision.decision_id,
        )
    if decision.outcome is ApprovalOutcome.DENIED:
        return AgentContinuationState(
            pause=pause,
            status=ContinuationStatus.DENIED,
            decision_id=decision.decision_id,
        )
    return AgentContinuationState(
        pause=pause,
        status=ContinuationStatus.RESUMABLE,
        decision_id=decision.decision_id,
    )


def assert_same_invocation(
    pause: ApprovalPause,
    invocation: ToolInvocation,
) -> None:
    """Fail closed if a resumed invocation differs from the approved one."""
    if not isinstance(pause, ApprovalPause):
        raise AgentApprovalError("pause must be ApprovalPause")
    if not isinstance(invocation, ToolInvocation):
        raise AgentApprovalError("invocation must be ToolInvocation")
    if invocation.tool_id != pause.tool_id:
        raise AgentApprovalError("resumed tool_id does not match paused invocation")
    if tool_invocation_digest(invocation) != pause.invocation_sha256:
        raise AgentApprovalError("resumed invocation does not match paused invocation")
