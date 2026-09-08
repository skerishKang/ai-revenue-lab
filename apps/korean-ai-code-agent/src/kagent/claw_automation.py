"""B54 Claw Automation, Scheduled Checks, and Notification Delivery Contracts (#2058).

Defines workspace-scoped scheduled checks, automation rules, notification channels,
safe proposal projections, and approval gates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, Sequence

from .contracts import ContractError
from .core import redact_secrets

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CONTROL_RE = re.compile(r"[\x01-\x08-]")


def _safe_id(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    norm = value.strip()
    if not _SAFE_ID_RE.fullmatch(norm):
        raise ContractError(f"{field_name} has invalid identifier shape: {norm!r}")
    return norm


def _bounded_text(value: str, field_name: str, *, limit: int = 1024, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    norm = value.strip()
    if not norm and not allow_empty:
        raise ContractError(f"{field_name} is required")
    if len(norm) > limit:
        raise ContractError(f"{field_name} exceeds {limit} characters")
    if _CONTROL_RE.search(norm):
        raise ContractError(f"{field_name} contains forbidden control characters")
    return norm


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


class ClawScheduleKind(str, Enum):
    CRON = "cron"
    INTERVAL = "interval"
    DAYPART = "daypart"


class ClawDaypart(str, Enum):
    MORNING = "morning"              # 09:00 KST / 00:00 UTC
    MIDDAY = "midday"                # 12:00 KST / 03:00 UTC
    EVENING = "evening"              # 18:00 KST / 09:00 UTC
    CLOSE_OF_BUSINESS = "close_of_business"  # 20:00 KST / 11:00 UTC


class ClawAutomationTarget(str, Enum):
    MEMORY = "memory"
    TASKS = "tasks"
    CONNECTORS = "connectors"
    INBOX = "inbox"


class ClawAutomationOutputType(str, Enum):
    ALERT = "alert"
    DRAFT = "draft"
    REPORT = "report"
    TASK_PROPOSAL = "task_proposal"


class ClawNotificationChannel(str, Enum):
    WEB_ALERT_INBOX = "web_alert_inbox"
    EMAIL = "email"
    TELEGRAM = "telegram"
    DISCORD = "discord"
    KAKAO = "kakao"
    SMS = "sms"

    @property
    def availability_tier(self) -> str:
        if self is ClawNotificationChannel.WEB_ALERT_INBOX:
            return "tier1_active"
        if self is ClawNotificationChannel.EMAIL:
            return "tier2_deferred_or_gated"
        if self in (ClawNotificationChannel.TELEGRAM, ClawNotificationChannel.DISCORD):
            return "tier3_later"
        return "tier4_later_policy_gated"


class ClawScheduledRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ClawScheduleExpression:
    kind: ClawScheduleKind
    expression: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ClawScheduleKind):
            try:
                object.__setattr__(self, "kind", ClawScheduleKind(self.kind))
            except (TypeError, ValueError) as exc:
                raise ContractError(f"invalid schedule kind: {self.kind}") from exc
        expr = _bounded_text(self.expression, "expression", limit=128)
        if self.kind is ClawScheduleKind.DAYPART:
            if expr not in {dp.value for dp in ClawDaypart}:
                allowed = ", ".join(dp.value for dp in ClawDaypart)
                raise ContractError(f"daypart must be one of: {allowed}")
        object.__setattr__(self, "expression", expr)


@dataclass(frozen=True, slots=True)
class ClawNotificationPreference:
    channel: ClawNotificationChannel
    enabled: bool = True
    recipient_ref: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.channel, ClawNotificationChannel):
            try:
                object.__setattr__(self, "channel", ClawNotificationChannel(self.channel))
            except (TypeError, ValueError) as exc:
                raise ContractError(f"invalid notification channel: {self.channel}") from exc
        if self.recipient_ref is not None:
            norm_ref = _bounded_text(self.recipient_ref, "recipient_ref", limit=256)
            if redact_secrets(norm_ref) != norm_ref:
                raise ContractError("recipient_ref must not contain credential material")
            object.__setattr__(self, "recipient_ref", norm_ref)


@dataclass(frozen=True, slots=True)
class ClawApprovalGate:
    approval_required: bool
    reason: str
    suggested_action: str
    approved_by: str | None = None
    approved_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.approval_required, bool):
            raise ContractError("approval_required must be boolean")
        object.__setattr__(self, "reason", _bounded_text(self.reason, "reason", limit=512, allow_empty=True))
        object.__setattr__(self, "suggested_action", _bounded_text(self.suggested_action, "suggested_action", limit=512, allow_empty=True))
        if self.approved_by is not None:
            object.__setattr__(self, "approved_by", _safe_id(self.approved_by, "approved_by"))
        if self.approved_at is not None:
            object.__setattr__(self, "approved_at", _aware_utc(self.approved_at, "approved_at"))


@dataclass(frozen=True, slots=True)
class ClawAutomationRule:
    rule_id: str
    workspace_id: str
    name: str
    schedule: ClawScheduleExpression
    target_source: ClawAutomationTarget
    output_type: ClawAutomationOutputType
    enabled: bool = True
    notification_channels: tuple[ClawNotificationPreference, ...] = field(
        default_factory=lambda: (ClawNotificationPreference(ClawNotificationChannel.WEB_ALERT_INBOX),)
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_id", _safe_id(self.rule_id, "rule_id"))
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "name", _bounded_text(self.name, "name", limit=256))
        if not isinstance(self.schedule, ClawScheduleExpression):
            raise ContractError("schedule must be a ClawScheduleExpression")
        if not isinstance(self.target_source, ClawAutomationTarget):
            try:
                object.__setattr__(self, "target_source", ClawAutomationTarget(self.target_source))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid target_source") from exc
        if not isinstance(self.output_type, ClawAutomationOutputType):
            try:
                object.__setattr__(self, "output_type", ClawAutomationOutputType(self.output_type))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid output_type") from exc
        if not isinstance(self.enabled, bool):
            raise ContractError("enabled must be boolean")
        if not isinstance(self.notification_channels, tuple) or not all(isinstance(c, ClawNotificationPreference) for c in self.notification_channels):
            raise ContractError("notification_channels must be a tuple of ClawNotificationPreference")


@dataclass(frozen=True, slots=True)
class ClawNotificationProposal:
    proposal_id: str
    workspace_id: str
    rule_id: str
    channel: ClawNotificationChannel
    title: str
    summary: str
    approval_gate: ClawApprovalGate
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "proposal_id", _safe_id(self.proposal_id, "proposal_id"))
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "rule_id", _safe_id(self.rule_id, "rule_id"))
        if not isinstance(self.channel, ClawNotificationChannel):
            object.__setattr__(self, "channel", ClawNotificationChannel(self.channel))
        object.__setattr__(self, "title", _bounded_text(self.title, "title", limit=256))
        object.__setattr__(self, "summary", _bounded_text(self.summary, "summary", limit=2048))
        if not isinstance(self.approval_gate, ClawApprovalGate):
            raise ContractError("approval_gate must be a ClawApprovalGate")
        object.__setattr__(self, "created_at", _aware_utc(self.created_at, "created_at"))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "workspace_id": self.workspace_id,
            "rule_id": self.rule_id,
            "channel": self.channel.value,
            "title": redact_secrets(self.title),
            "summary": redact_secrets(self.summary),
            "approval_required": self.approval_gate.approval_required,
            "approval_reason": self.approval_gate.reason,
            "auto_send": False,
            "auto_order": False,
            "auto_memory_confirm": False,
        }


@dataclass(frozen=True, slots=True)
class ClawAutomationOutput:
    output_id: str
    workspace_id: str
    output_type: ClawAutomationOutputType
    title: str
    content: str
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    proposals: tuple[ClawNotificationProposal, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_id", _safe_id(self.output_id, "output_id"))
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        if not isinstance(self.output_type, ClawAutomationOutputType):
            object.__setattr__(self, "output_type", ClawAutomationOutputType(self.output_type))
        object.__setattr__(self, "title", _bounded_text(self.title, "title", limit=256))
        object.__setattr__(self, "content", _bounded_text(self.content, "content", limit=16384))
        if not isinstance(self.evidence_refs, tuple):
            raise ContractError("evidence_refs must be a tuple")
        norm_refs = tuple(_bounded_text(ref, "evidence_ref", limit=512) for ref in self.evidence_refs)
        object.__setattr__(self, "evidence_refs", norm_refs)


@dataclass(frozen=True, slots=True)
class ClawScheduledRun:
    run_id: str
    workspace_id: str
    rule_id: str
    status: ClawScheduledRunStatus
    scheduled_time: datetime
    started_at: datetime
    completed_at: datetime | None = None
    output: ClawAutomationOutput | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _safe_id(self.run_id, "run_id"))
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "rule_id", _safe_id(self.rule_id, "rule_id"))
        if not isinstance(self.status, ClawScheduledRunStatus):
            object.__setattr__(self, "status", ClawScheduledRunStatus(self.status))
        object.__setattr__(self, "scheduled_time", _aware_utc(self.scheduled_time, "scheduled_time"))
        object.__setattr__(self, "started_at", _aware_utc(self.started_at, "started_at"))
        if self.completed_at is not None:
            object.__setattr__(self, "completed_at", _aware_utc(self.completed_at, "completed_at"))
        if self.error_message is not None:
            object.__setattr__(self, "error_message", _bounded_text(self.error_message, "error_message", limit=1024))


class InMemoryClawAutomationStore:
    """In-memory store for Claw automation rules and scheduled runs."""

    def __init__(self) -> None:
        self._rules: dict[str, ClawAutomationRule] = {}
        self._runs: dict[str, ClawScheduledRun] = {}
        self._proposals: dict[str, ClawNotificationProposal] = {}

    def save_rule(self, rule: ClawAutomationRule) -> None:
        self._rules[rule.rule_id] = rule

    def get_rule(self, rule_id: str) -> ClawAutomationRule | None:
        return self._rules.get(rule_id)

    def list_rules(self, workspace_id: str) -> list[ClawAutomationRule]:
        return [r for r in self._rules.values() if r.workspace_id == workspace_id]

    def record_run(self, run: ClawScheduledRun) -> None:
        self._runs[run.run_id] = run
        if run.output and run.output.proposals:
            for p in run.output.proposals:
                self._proposals[p.proposal_id] = p

    def get_run(self, run_id: str) -> ClawScheduledRun | None:
        return self._runs.get(run_id)

    def list_runs(self, workspace_id: str) -> list[ClawScheduledRun]:
        return [r for r in self._runs.values() if r.workspace_id == workspace_id]

    def list_proposals(self, workspace_id: str) -> list[ClawNotificationProposal]:
        return [p for p in self._proposals.values() if p.workspace_id == workspace_id]


class FakeClawScheduler:
    """Deterministic fake scheduler for unit testing and local checks."""

    def __init__(self, store: InMemoryClawAutomationStore) -> None:
        self.store = store

    def evaluate_due_rules(
        self,
        workspace_id: str,
        current_time: datetime,
    ) -> list[ClawAutomationRule]:
        """Finds all enabled rules for workspace eligible to run at current_time."""
        rules = self.store.list_rules(workspace_id)
        due_rules = []
        for rule in rules:
            if not rule.enabled:
                continue
            due_rules.append(rule)
        return due_rules

    def execute_rule_dry_run(
        self,
        rule: ClawAutomationRule,
        scheduled_time: datetime,
    ) -> ClawScheduledRun:
        """Executes a deterministic simulated check creating non-side-effecting outputs."""
        now = datetime.now(timezone.utc)
        run_id = f"sched_run_{rule.rule_id}_{int(scheduled_time.timestamp())}"

        # Generate proposal if follow-up required, gated by approval
        proposal = ClawNotificationProposal(
            proposal_id=f"prop_{rule.rule_id}_001",
            workspace_id=rule.workspace_id,
            rule_id=rule.rule_id,
            channel=ClawNotificationChannel.WEB_ALERT_INBOX,
            title=f"정기 검사 알림: {rule.name}",
            summary="정기 검사 실행 완료 — 외부 전송이나 변경은 사용자 승인이 필요합니다.",
            approval_gate=ClawApprovalGate(
                approval_required=True,
                reason="외부 채널 전송 또는 데이터 변경 방지",
                suggested_action="결과 검토 후 수동 승인",
            ),
        )

        output = ClawAutomationOutput(
            output_id=f"out_{rule.rule_id}_001",
            workspace_id=rule.workspace_id,
            output_type=rule.output_type,
            title=f"자동화 결과: {rule.name}",
            content="결과 보고서 (DRAFT) — 자동 전송 및 확정 없음.",
            evidence_refs=(f"rule://{rule.workspace_id}/{rule.rule_id}",),
            proposals=(proposal,),
        )

        run = ClawScheduledRun(
            run_id=run_id,
            workspace_id=rule.workspace_id,
            rule_id=rule.rule_id,
            status=ClawScheduledRunStatus.COMPLETED,
            scheduled_time=scheduled_time,
            started_at=now,
            completed_at=now,
            output=output,
        )
        self.store.record_run(run)
        return run


__all__ = [
    "ClawScheduleKind",
    "ClawDaypart",
    "ClawAutomationTarget",
    "ClawAutomationOutputType",
    "ClawNotificationChannel",
    "ClawScheduledRunStatus",
    "ClawScheduleExpression",
    "ClawNotificationPreference",
    "ClawApprovalGate",
    "ClawAutomationRule",
    "ClawNotificationProposal",
    "ClawAutomationOutput",
    "ClawScheduledRun",
    "InMemoryClawAutomationStore",
    "FakeClawScheduler",
]
