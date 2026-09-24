"""B54 Claw Automation, Scheduled Checks, and Notification Delivery Contracts (#2058).

Defines workspace-scoped scheduled checks, automation rules, notification channels,
safe proposal projections, and approval gates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from enum import Enum
import hashlib
import inspect
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Protocol, Sequence

from .contracts import ContractError, ExecutionMode, exact_commit_revision
from .contracts import ClawTaskIntent
from .runs import ClawRun, ClawRunStatus
from .contracts import _CONTROL_RE as _CANONICAL_CONTROL_RE
from .core import redact_secrets
from .workspace_visibility import TrustedWorkspaceMembershipProjection

try:  # stdlib IANA tz database; unavailable on tzdata-less Windows without the extra package
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - py<3.9 not supported (requires-python>=3.11)
    ZoneInfo = None  # type: ignore[assignment]

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CANONICAL_TENANT_ID_RE = re.compile(r"^tenant_[0-9a-f]{32}$")
_CANONICAL_SUBJECT_ID_RE = re.compile(r"^sub_[0-9a-f]{32}$")
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


_SAFE_TZ_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/+-]{0,63}$")

_INTERVAL_MIN_SECONDS = 60
_INTERVAL_MAX_SECONDS = 30 * 24 * 60 * 60
# Compatibility lock (#2833): the only word-token interval spellings accepted
# by pre-existing contracts/tests stay valid, mapped to exact durations.
_INTERVAL_ALIASES = {"daily": 24 * 60 * 60, "hourly": 60 * 60, "minutely": 60}
_INTERVAL_DURATION_RE = re.compile(r"^(\d+)([smhd])$")

_DAYPART_AT: dict[str, time] = {
    "morning": time(9, 0),
    "midday": time(12, 0),
    "evening": time(18, 0),
    "close_of_business": time(20, 0),
}

_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}

_CRON_FIELD_RANGES: tuple[tuple[int, int], ...] = (
    (0, 59),  # minute
    (0, 23),  # hour
    (1, 31),  # day of month
    (1, 12),  # month
    (0, 6),   # day of week (7 normalizes to 0)
)


def _validate_timezone(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    norm = value.strip()
    if not _SAFE_TZ_RE.fullmatch(norm):
        raise ContractError(f"{field_name} has invalid timezone identifier shape: {norm!r}")
    return norm


def resolve_timezone(name: str) -> timezone:
    """Fail closed for unknown/unavailable IANA zones; ``UTC`` is always available."""
    norm = _validate_timezone(name, "timezone")
    if norm.upper() == "UTC":
        return timezone.utc
    if ZoneInfo is None:
        raise ContractError(f"timezone {norm!r} unavailable: zoneinfo is not importable")
    try:
        return ZoneInfo(norm)
    except Exception as exc:  # ZoneInfoNotFoundError key-independent
        raise ContractError(f"timezone {norm!r} is not resolvable") from exc


def _parse_interval_seconds(expression: str) -> int:
    expr = expression.strip().lower()
    if expr in _INTERVAL_ALIASES:
        return _INTERVAL_ALIASES[expr]
    match = _INTERVAL_DURATION_RE.fullmatch(expr)
    if not match:
        raise ContractError(f"interval must be a positive bounded duration such as 15m/6h/2d, got {expression!r}")
    amount = int(match.group(1))
    if amount <= 0:
        raise ContractError("interval duration must be greater than zero")
    seconds = amount * _UNIT_SECONDS[match.group(2)]
    if not (_INTERVAL_MIN_SECONDS <= seconds <= _INTERVAL_MAX_SECONDS):
        raise ContractError(f"interval must be between {_INTERVAL_MIN_SECONDS}s and {_INTERVAL_MAX_SECONDS}s")
    return seconds


def _parse_cron_field(raw: str, lo: int, hi: int, position: int) -> frozenset[int]:
    if raw == "*":
        return frozenset(range(lo, hi + 1))
    values: set[int] = set()
    for part in raw.split(","):
        if not part:
            raise ContractError(f"empty cron list item in field {position}")
        step = 1
        body = part
        if "/" in part:
            body, _, step_raw = part.partition("/")
            if not step_raw.isdigit() or int(step_raw) < 1:
                raise ContractError(f"invalid cron step {part!r} in field {position}")
            step = int(step_raw)
        if body == "*":
            start, end = lo, hi
        elif "-" in body and not body.startswith("-"):
            start_raw, _, end_raw = body.partition("-")
            if not start_raw.isdigit() or not end_raw.isdigit():
                raise ContractError(f"invalid cron range {part!r} in field {position}")
            start, end = int(start_raw), int(end_raw)
        elif body.isdigit():
            if "/" in part:
                raise ContractError(f"invalid cron bounded step {part!r} in field {position}")
            start = end = int(body)
        else:
            raise ContractError(f"unsupported cron syntax {part!r} in field {position}")
        if position == 4:
            if start == 7:
                start = 0
            if end == 7:
                end = 0
        if start > hi or end > hi or start < lo or end < lo or start > end:
            raise ContractError(f"cron field {position} out of range in {part!r}")
        for value in range(start, end + 1, step):
            values.add(0 if position == 4 and value == 7 else value)
    if not values:
        raise ContractError(f"cron field {position} matched nothing")
    return frozenset(values)


def parse_cron_expression(expression: str) -> dict[str, Any]:
    """Bounded 5-field cron subset (Vixie semantics). Anything else fails closed."""
    fields = expression.split()
    if len(fields) != 5:
        raise ContractError(f"cron expression must have exactly 5 fields, got {len(fields)}: {expression!r}")
    parsed = [
        _parse_cron_field(raw, lo, hi, position)
        for position, (raw, (lo, hi)) in enumerate(zip(fields, _CRON_FIELD_RANGES, strict=True))
    ]
    return {
        "minute": parsed[0],
        "hour": parsed[1],
        "dom": parsed[2],
        "month": parsed[3],
        "dow": parsed[4],
        # Vixie OR rule only applies when both day fields are restricted.
        "dom_restricted": fields[2] != "*",
        "dow_restricted": fields[4] != "*",
    }


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
    timezone: str = "UTC"

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ClawScheduleKind):
            try:
                object.__setattr__(self, "kind", ClawScheduleKind(self.kind))
            except (TypeError, ValueError) as exc:
                raise ContractError(f"invalid schedule kind: {self.kind}") from exc
        expr = _bounded_text(self.expression, "expression", limit=128)
        if redact_secrets(expr) != expr:
            raise ContractError("schedule expression must not carry credential material")
        tz_name = _validate_timezone(self.timezone, "timezone")
        if self.kind is ClawScheduleKind.DAYPART:
            if expr not in {dp.value for dp in ClawDaypart}:
                allowed = ", ".join(dp.value for dp in ClawDaypart)
                raise ContractError(f"daypart must be one of: {allowed}")
        elif self.kind is ClawScheduleKind.CRON:
            parse_cron_expression(expr)
        else:
            _parse_interval_seconds(expr)
        object.__setattr__(self, "expression", expr)
        object.__setattr__(self, "timezone", tz_name)


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


# #2833 S2F1: version tag for the canonical scheduled execution-intent material.
EXECUTION_INTENT_VERSION = "claw-automation-execution-intent.v1"


@dataclass(frozen=True, slots=True)
class ClawAutomationExecutionIntent:
    """Immutable execution material a scheduled rule owns (#2833 S2F1).

    A scheduled rule could not reach canonical execution because the real input
    object requires a non-empty ``task`` and a ``repository_ref``, and neither can
    be derived from any rule field: ``name`` is a display label used in titles, and
    ``target_source`` / ``output_type`` are closed enums. Reading them as an
    instruction would be inference, so this contract carries the three values
    explicitly instead.

    This is data only. It dispatches nothing, calls nothing, grants no authority,
    and resolves no owner: a later slice decides how it is consumed.
    """

    task: str
    repository_ref: str
    exact_revision: str

    def __post_init__(self) -> None:
        task = _bounded_text(self.task, "task", limit=12_000)
        if redact_secrets(task) != task:
            raise ContractError("task must not contain credential material")
        repository = _bounded_text(self.repository_ref, "repository_ref", limit=1_024)
        # The rule-name precedent: credential material is refused at construction,
        # so persisting and projecting the repository ref needs no second mask.
        if redact_secrets(repository) != repository:
            raise ContractError("repository_ref must not contain credential material")
        # This module's own _CONTROL_RE starts at \x01, so NUL slips past it, while
        # the canonical input object that will consume this material refuses NUL.
        # Refusing the canonical set here keeps a rule from storing text that could
        # never be handed to execution — reuse of that predicate, not a new one.
        for name, value in (("task", task), ("repository_ref", repository)):
            if _CANONICAL_CONTROL_RE.search(value):
                raise ContractError(f"{name} contains forbidden control characters")
        # Reuse the contract layer's single exact-commit predicate. No second
        # revision regex may exist for this boundary.
        revision = exact_commit_revision(self.exact_revision, "exact_revision")
        object.__setattr__(self, "task", task)
        object.__setattr__(self, "repository_ref", repository)
        object.__setattr__(self, "exact_revision", revision)

    @property
    def task_sha256(self) -> str:
        return hashlib.sha256(self.task.encode("utf-8")).hexdigest()

    @property
    def material_document(self) -> dict[str, str]:
        """The exact byte sequence the digest is computed over."""

        return {
            "version": EXECUTION_INTENT_VERSION,
            "task": self.task,
            "repository_ref": self.repository_ref,
            "exact_revision": self.exact_revision,
        }

    @property
    def intent_sha256(self) -> str:
        canonical = json.dumps(self.material_document, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def safe_dict(self) -> dict[str, Any]:
        """Projection for logs and receipts: identity without the task body."""

        return {
            "version": EXECUTION_INTENT_VERSION,
            "repository_ref": self.repository_ref,
            "exact_revision": self.exact_revision,
            "task_sha256": self.task_sha256,
            "intent_sha256": self.intent_sha256,
            "raw_task_in_projection": False,
        }


def _execution_intent_document(intent: ClawAutomationExecutionIntent | None) -> dict[str, str] | None:
    """Persistence form of the intent. Absence is stored as absence, not as ``null``."""

    if intent is None:
        return None
    return {
        "version": EXECUTION_INTENT_VERSION,
        "task": intent.task,
        "repository_ref": intent.repository_ref,
        "exact_revision": intent.exact_revision,
    }


def _execution_intent_from_document(document: Any) -> ClawAutomationExecutionIntent | None:
    """Legacy rule payloads carry no such key; absence reads None, not an error."""

    if document is None:
        return None
    if not isinstance(document, dict):
        raise ContractError("stored automation rule is corrupt")
    return ClawAutomationExecutionIntent(
        task=document["task"],
        repository_ref=document["repository_ref"],
        exact_revision=document["exact_revision"],
    )


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
    # #2833 B2A: optional opaque delivery-owner provenance. Deliberately NOT
    # assumed to be a B62 usr_* product id, a canonical subject, or a membership
    # principal_ref. It is bounded opaque text the trusted product composition
    # may attach at rule creation; B54/KAgent never interprets its meaning, and
    # it grants no authority of any kind. Absent on legacy rules (None).
    owner_ref: str | None = None
    # #2833 S2F1: execution_intent remains the final dataclass field and
    # keeps its pre-existing positional slot. The new authority provenance is
    # declared before it but keyword-only, so it cannot rebind legacy positional
    # construction and does not disturb the pinned field-order contract.
    canonical_subject_id: str | None = field(default=None, kw_only=True)
    execution_intent: ClawAutomationExecutionIntent | None = None



    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_id", _safe_id(self.rule_id, "rule_id"))
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        name = _bounded_text(self.name, "name", limit=256)
        if redact_secrets(name) != name:
            raise ContractError("name must not contain credential material")
        object.__setattr__(self, "name", name)
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
        if self.owner_ref is not None:
            # Same bounded-opaque-ref shape as _safe_id, but never echoes the
            # rejected value into the error text (no owner provenance leak).
            owner = self.owner_ref
            if not isinstance(owner, str):
                raise ContractError("owner_ref must be a bounded opaque reference")
            norm = owner.strip()
            if not norm or not _SAFE_ID_RE.fullmatch(norm):
                raise ContractError("owner_ref must be a bounded opaque reference")
            object.__setattr__(self, "owner_ref", norm)
        if self.execution_intent is not None and not isinstance(
            self.execution_intent, ClawAutomationExecutionIntent
        ):
            raise ContractError("execution_intent must be a ClawAutomationExecutionIntent")
        if self.canonical_subject_id is not None:
            if (
                not isinstance(self.canonical_subject_id, str)
                or not _CANONICAL_SUBJECT_ID_RE.fullmatch(self.canonical_subject_id)
            ):
                raise ContractError("canonical_subject_id must be a canonical subject identifier")
            object.__setattr__(self, "canonical_subject_id", self.canonical_subject_id)



class ClawAutomationRuleAuthority(str, Enum):
    CANONICAL_BACKGROUND_ELIGIBLE = "CANONICAL_BACKGROUND_ELIGIBLE"
    LEGACY_MISSING_SUBJECT = "LEGACY_MISSING_SUBJECT"
    LEGACY_NONCANONICAL_WORKSPACE = "LEGACY_NONCANONICAL_WORKSPACE"


def classify_rule_background_authority(rule: ClawAutomationRule) -> ClawAutomationRuleAuthority:
    if not _CANONICAL_TENANT_ID_RE.fullmatch(rule.workspace_id):
        return ClawAutomationRuleAuthority.LEGACY_NONCANONICAL_WORKSPACE
    if rule.canonical_subject_id is None:
        return ClawAutomationRuleAuthority.LEGACY_MISSING_SUBJECT
    return ClawAutomationRuleAuthority.CANONICAL_BACKGROUND_ELIGIBLE


def select_automation_rule_membership(
    rule: ClawAutomationRule,
    memberships: tuple[TrustedWorkspaceMembershipProjection, ...],
) -> TrustedWorkspaceMembershipProjection | None:
    if rule.canonical_subject_id is not None:
        for membership in memberships:
            if (
                membership.workspace_id == rule.workspace_id
                and membership.principal_ref == rule.canonical_subject_id
            ):
                return membership
        return None
    if any(
        re.fullmatch(r"sub_[0-9a-f]{32}", membership.principal_ref)
        for membership in memberships
    ):
        return None
    return memberships[0] if memberships else None


CANONICAL_BACKGROUND_ELIGIBLE = ClawAutomationRuleAuthority.CANONICAL_BACKGROUND_ELIGIBLE
LEGACY_MISSING_SUBJECT = ClawAutomationRuleAuthority.LEGACY_MISSING_SUBJECT
LEGACY_NONCANONICAL_WORKSPACE = ClawAutomationRuleAuthority.LEGACY_NONCANONICAL_WORKSPACE


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


def _cron_matches(local: datetime, parsed: dict[str, Any]) -> bool:
    if local.minute not in parsed["minute"] or local.hour not in parsed["hour"]:
        return False
    if local.month not in parsed["month"]:
        return False
    dom_matches = local.day in parsed["dom"]
    # Cron numbers Sunday as 0 (or 7), while datetime numbers Monday as 0.
    dow_matches = ((local.weekday() + 1) % 7) in parsed["dow"]
    if parsed["dom_restricted"] and parsed["dow_restricted"]:
        return dom_matches or dow_matches
    return dom_matches and dow_matches


def occurrence_key(workspace_id: str, rule_id: str, scheduled_time: datetime) -> str:
    """Canonical logical occurrence identity, including every isolation axis."""
    workspace = _safe_id(workspace_id, "workspace_id")
    rule = _safe_id(rule_id, "rule_id")
    scheduled = _aware_utc(scheduled_time, "scheduled_time")
    stamp = scheduled.isoformat(timespec="microseconds").replace("+00:00", "Z")
    payload = json.dumps(
        {
            "v": 1,
            "workspace_id": workspace,
            "rule_id": rule,
            "scheduled_at": stamp,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"claw_occurrence_v1_{digest}"


def _derived_occurrence_id(prefix: str, workspace_id: str, rule_id: str, scheduled_time: datetime) -> str:
    """Create a bounded ID without dropping any logical-occurrence identity."""
    digest = hashlib.sha256(
        occurrence_key(workspace_id, rule_id, scheduled_time).encode("utf-8")
    ).hexdigest()
    return f"{prefix}_{digest}"


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str, field_name: str) -> datetime:
    """Fail closed for malformed stored timestamps."""
    if not isinstance(value, str) or not value:
        raise ContractError(f"stored {field_name} is not a valid ISO datetime")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"stored {field_name} is not a valid ISO datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractError(f"stored {field_name} must be timezone-aware")
    return parsed.astimezone(timezone.utc)

# ---------------------------------------------------------------------------
# #2833 S2F2: same-run-id lifecycle bridge between a scheduled occurrence and
# the canonical ClawRun state machine.
#
# ClawRun is the canonical lifecycle state machine. The scheduled row is a
# projection of it, never a second state machine. This section introduces no
# second run id, no second dedup authority, and no durable canonical-run
# persistence claim (the in-memory run store is not an authority).
# ---------------------------------------------------------------------------

_TERMINAL_PROJECTION_STATUSES = frozenset(
    {
        ClawScheduledRunStatus.COMPLETED,
        ClawScheduledRunStatus.FAILED,
        ClawScheduledRunStatus.CANCELLED,
    }
)
_CANONICAL_TO_PROJECTION_STATUS: dict[ClawRunStatus, ClawScheduledRunStatus] = {
    ClawRunStatus.QUEUED: ClawScheduledRunStatus.PENDING,
    ClawRunStatus.PREPARING: ClawScheduledRunStatus.RUNNING,
    ClawRunStatus.RUNNING: ClawScheduledRunStatus.RUNNING,
    ClawRunStatus.WAITING_APPROVAL: ClawScheduledRunStatus.RUNNING,
    ClawRunStatus.COMPLETED: ClawScheduledRunStatus.COMPLETED,
    ClawRunStatus.FAILED: ClawScheduledRunStatus.FAILED,
    ClawRunStatus.CANCELLED: ClawScheduledRunStatus.CANCELLED,
}
_MAX_ERROR_MESSAGE = 1_024


def project_canonical_status(status: ClawRunStatus) -> ClawScheduledRunStatus:
    """Project one canonical ClawRun status onto the scheduled vocabulary.

    Non-terminal canonical states project to RUNNING, except QUEUED which projects
    to PENDING: the occurrence is claimed but execution has not started. No new
    scheduled status is invented for PREPARING or WAITING_APPROVAL.
    """

    if not isinstance(status, ClawRunStatus):
        try:
            status = ClawRunStatus(status)
        except (TypeError, ValueError) as exc:
            raise ContractError(f"invalid canonical run status: {status}") from exc
    return _CANONICAL_TO_PROJECTION_STATUS[status]


def canonical_task_intent_for_occurrence(
    rule: ClawAutomationRule, scheduled_time: datetime
) -> ClawTaskIntent:
    """Build the canonical task intent for one scheduled occurrence.

    Execution material comes only from the rule's S2F1 execution intent: ``name``,
    ``target_source`` and ``output_type`` are display labels and closed enums and are
    never reinterpreted as an instruction. ``task_id`` is derived deterministically
    from the occurrence identity and is not a dedup authority. Legacy rules without
    an execution intent fail closed.
    """

    if rule.execution_intent is None:
        raise ContractError("canonical scheduling requires an execution intent")
    scheduled = _aware_utc(scheduled_time, "scheduled_time")
    return ClawTaskIntent(
        task_id=_derived_occurrence_id("task", rule.workspace_id, rule.rule_id, scheduled),
        task=rule.execution_intent.task,
        repository_ref=rule.execution_intent.repository_ref,
        execution_mode=ExecutionMode.CLOUD,
        requested_revision=rule.execution_intent.exact_revision,
        source_surface="automation",
    )


def canonical_claw_run_for_occurrence(
    rule: ClawAutomationRule, scheduled_time: datetime
) -> tuple[ClawRun, ClawTaskIntent]:
    """Create the canonical run for one occurrence, reusing the same run id.

    ``SAME_RUN_ID_REUSED``: the canonical run id IS the occurrence-derived
    ``sched_run_<digest>`` the scheduled projection already uses, so one logical
    occurrence owns exactly one id. This builds the lifecycle container only: it
    dispatches nothing, calls no P01 helper, resolves no owner, and writes
    nothing to History/Task/Alert stores.
    """

    scheduled = _aware_utc(scheduled_time, "scheduled_time")
    run_id = _derived_occurrence_id("sched_run", rule.workspace_id, rule.rule_id, scheduled)
    intent = canonical_task_intent_for_occurrence(rule, scheduled)
    return ClawRun.create(run_id, intent), intent


def _projection_update_material(
    *,
    run_id: str,
    workspace_id: str,
    rule_id: str,
    scheduled_time: datetime,
    status: ClawScheduledRunStatus,
    completed_at: datetime | None,
    error_message: str | None,
) -> tuple[str, str, str, datetime, ClawScheduledRunStatus, datetime | None, str | None]:
    """Validate one bounded projection update before either store touches data.

    ``completed_at`` is only legal for a terminal projection status and an
    ``error_message`` only for a failed one; both fail closed otherwise. Text is
    bounded to 1_024 characters and run through the existing redaction helper, so
    no credential material can reach the projection.
    """

    bounded_run_id = _safe_id(run_id, "run_id")
    bounded_workspace = _safe_id(workspace_id, "workspace_id")
    bounded_rule = _safe_id(rule_id, "rule_id")
    scheduled = _aware_utc(scheduled_time, "scheduled_time")
    if not isinstance(status, ClawScheduledRunStatus):
        try:
            status = ClawScheduledRunStatus(status)
        except (TypeError, ValueError) as exc:
            raise ContractError(f"invalid projection status: {status}") from exc
    if status in _TERMINAL_PROJECTION_STATUSES:
        if completed_at is None:
            raise ContractError("completed_at is required for a terminal projection status")
        completed = _aware_utc(completed_at, "completed_at")
    else:
        if completed_at is not None:
            raise ContractError("completed_at is only allowed for a terminal projection status")
        completed = None
    bounded_error: str | None = None
    if error_message is not None:
        if status is not ClawScheduledRunStatus.FAILED:
            raise ContractError("error_message is only allowed for a failed projection")
        redacted = redact_secrets(
            _bounded_text(error_message, "error_message", limit=_MAX_ERROR_MESSAGE)
        )
        bounded_error = _bounded_text(redacted, "error_message", limit=_MAX_ERROR_MESSAGE)
    return (
        bounded_run_id,
        bounded_workspace,
        bounded_rule,
        scheduled,
        status,
        completed,
        bounded_error,
    )



def _projection_output_for_update(
    *,
    workspace_id: str,
    rule_id: str,
    status: ClawScheduledRunStatus,
    output: ClawAutomationOutput | None,
    existing_status: ClawScheduledRunStatus,
    existing_output: ClawAutomationOutput | None,
) -> ClawAutomationOutput | None:
    """Validate an optional output attachment for an existing projection row.

    S2F4A is deliberately existing-row only: ``record_run`` remains the sole
    occurrence-claim authority. Legacy status-only updates pass ``output=None``
    and preserve the stored output byte-for-byte. A real output may be attached
    only to a COMPLETED projection, must belong to the same workspace, may never
    resurrect FAILED/CANCELLED rows, and becomes immutable once present. Repeating
    the exact same output is an idempotent retry.
    """

    if output is None:
        return existing_output
    if not isinstance(output, ClawAutomationOutput):
        raise ContractError("projection output must be a ClawAutomationOutput")
    if status is not ClawScheduledRunStatus.COMPLETED:
        raise ContractError("projection output may only be attached to COMPLETED")
    if output.workspace_id != workspace_id:
        raise ContractError("projection output workspace does not match the scheduled run")
    if not isinstance(output.proposals, tuple) or not all(
        isinstance(proposal, ClawNotificationProposal) for proposal in output.proposals
    ):
        raise ContractError("projection output proposals must be trusted notification proposals")
    if any(
        proposal.workspace_id != workspace_id or proposal.rule_id != rule_id
        for proposal in output.proposals
    ):
        raise ContractError("projection output proposal scope does not match the scheduled run")
    if existing_status in {
        ClawScheduledRunStatus.FAILED,
        ClawScheduledRunStatus.CANCELLED,
    }:
        raise ContractError("terminal failed/cancelled projection cannot attach output")
    if existing_output is not None and existing_output != output:
        raise ContractError("projection output is immutable once attached")
    return output


def _execution_claim_material(
    *,
    run_id: str,
    workspace_id: str,
    rule_id: str,
    scheduled_time: datetime,
) -> tuple[str, str, str, datetime]:
    """Validate one bounded execution claim before either store touches data.

    A claim carries no payload of its own: it only names the existing
    scheduled-run row whose ``PENDING`` status is about to become ``RUNNING``.
    Sharing this material builder keeps the in-memory and durable stores from
    drifting on what a well-formed claim target is.
    """

    return (
        _safe_id(run_id, "run_id"),
        _safe_id(workspace_id, "workspace_id"),
        _safe_id(rule_id, "rule_id"),
        _aware_utc(scheduled_time, "scheduled_time"),
    )

class ClawAutomationStore(Protocol):
    def save_rule(self, rule: ClawAutomationRule) -> None: ...
    def get_rule(self, rule_id: str, workspace_id: str) -> ClawAutomationRule | None: ...
    def list_rules(self, workspace_id: str) -> list[ClawAutomationRule]: ...
    def update_rule(self, rule: ClawAutomationRule) -> None: ...
    def set_rule_enabled(self, workspace_id: str, rule_id: str, enabled: bool) -> ClawAutomationRule: ...
    def record_run(self, run: ClawScheduledRun) -> ClawScheduledRun: ...
    def get_run(self, run_id: str, workspace_id: str) -> ClawScheduledRun | None: ...
    def get_run_for_occurrence(self, key: str, workspace_id: str) -> ClawScheduledRun | None: ...
    def list_runs(self, workspace_id: str) -> list[ClawScheduledRun]: ...
    def claim_execution(
        self,
        *,
        run_id: str,
        workspace_id: str,
        rule_id: str,
        scheduled_time: datetime,
    ) -> ClawScheduledRun | None: ...

    def update_run_projection(
        self,
        *,
        run_id: str,
        workspace_id: str,
        rule_id: str,
        scheduled_time: datetime,
        status: ClawScheduledRunStatus,
        completed_at: datetime | None = None,
        error_message: str | None = None,
        output: ClawAutomationOutput | None = None,
    ) -> ClawScheduledRun: ...
    def list_proposals(self, workspace_id: str) -> list[ClawNotificationProposal]: ...


class InMemoryClawAutomationStore:
    """Reference store contract; production durability is deliberately deferred."""

    def __init__(self) -> None:
        self._rules: dict[str, ClawAutomationRule] = {}
        self._runs: dict[str, ClawScheduledRun] = {}
        self._proposals: dict[str, ClawNotificationProposal] = {}
        self._occurrences: dict[str, str] = {}

    def save_rule(self, rule: ClawAutomationRule) -> None:
        previous = self._rules.get(rule.rule_id)
        if previous is not None and previous.workspace_id != rule.workspace_id:
            raise ContractError("rule_id is already owned by another workspace")
        # #2833 B2A: owner provenance is immutable after rule creation. A
        # generic save/update may never transfer, drop, or mint an owner_ref;
        # it must echo the previously persisted value exactly.
        if previous is not None and previous.owner_ref != rule.owner_ref:
            raise ContractError("rule owner provenance is immutable")
        if previous is not None and previous.canonical_subject_id != rule.canonical_subject_id:
            raise ContractError("rule canonical subject provenance is immutable")
        # #2833 S2F1: execution material is immutable after creation as well. A

        # legacy rule must not be promoted to an execution-capable one through a
        # generic save/update, and an existing intent must not be swapped or
        # dropped — that would silently change what a scheduled occurrence runs.
        if previous is not None and previous.execution_intent != rule.execution_intent:
            raise ContractError("rule execution intent is immutable")
        self._rules[rule.rule_id] = rule

    def get_rule(self, rule_id: str, workspace_id: str) -> ClawAutomationRule | None:
        rule = self._rules.get(rule_id)
        return rule if rule is not None and rule.workspace_id == workspace_id else None

    def list_rules(self, workspace_id: str) -> list[ClawAutomationRule]:
        return [rule for rule in self._rules.values() if rule.workspace_id == workspace_id]

    def update_rule(self, rule: ClawAutomationRule) -> None:
        current = self._rules.get(rule.rule_id)
        if current is None or current.workspace_id != rule.workspace_id:
            raise ContractError("rule does not belong to workspace")
        # Route through save_rule so the owner-provenance immutability guard
        # also covers the generic update path.
        self.save_rule(rule)

    def set_rule_enabled(self, workspace_id: str, rule_id: str, enabled: bool) -> ClawAutomationRule:
        if not isinstance(enabled, bool):
            raise ContractError("enabled must be boolean")
        rule = self.get_rule(rule_id, workspace_id)
        if rule is None:
            raise ContractError("rule does not belong to workspace")
        updated = ClawAutomationRule(
            rule_id=rule.rule_id, workspace_id=rule.workspace_id, name=rule.name,
            schedule=rule.schedule, target_source=rule.target_source,
            output_type=rule.output_type, enabled=enabled,
            notification_channels=rule.notification_channels,
            owner_ref=rule.owner_ref,
            execution_intent=rule.execution_intent,
            canonical_subject_id=rule.canonical_subject_id,
        )

        self._rules[rule_id] = updated
        return updated

    def record_run(self, run: ClawScheduledRun) -> ClawScheduledRun:
        existing_run = self._runs.get(run.run_id)
        if existing_run is not None and existing_run.workspace_id != run.workspace_id:
            raise ContractError("run_id is already owned by another workspace")
        key = occurrence_key(run.workspace_id, run.rule_id, run.scheduled_time)
        existing_id = self._occurrences.get(key)
        if existing_id is not None:
            return self._runs[existing_id]
        # A run_id may only ever identify ONE logical occurrence. If this id
        # is already stored, the two occurrences would alias the same run,
        # so fail closed before claiming.
        if run.run_id in self._runs:
            raise ContractError(
                "run_id is already stored for a different logical occurrence"
            )
        # Claim the occurrence first so the canonical run is the claim holder,
        # mirroring the durable adapter's at-most-one-run guarantee.
        self._occurrences[key] = run.run_id
        self._runs[run.run_id] = run
        if run.output and run.output.proposals:
            for proposal in run.output.proposals:
                self._proposals[proposal.proposal_id] = proposal
        return run

    def get_run(self, run_id: str, workspace_id: str) -> ClawScheduledRun | None:
        run = self._runs.get(run_id)
        return run if run is not None and run.workspace_id == workspace_id else None

    def get_run_for_occurrence(self, key: str, workspace_id: str) -> ClawScheduledRun | None:
        run_id = self._occurrences.get(key)
        return self.get_run(run_id, workspace_id) if run_id is not None else None

    def list_runs(self, workspace_id: str) -> list[ClawScheduledRun]:
        return [run for run in self._runs.values() if run.workspace_id == workspace_id]

    def list_proposals(self, workspace_id: str) -> list[ClawNotificationProposal]:
        return [proposal for proposal in self._proposals.values() if proposal.workspace_id == workspace_id]

    def claim_execution(
        self,
        *,
        run_id: str,
        workspace_id: str,
        rule_id: str,
        scheduled_time: datetime,
    ) -> ClawScheduledRun | None:
        """Claim ONE existing ``PENDING`` row for execution. Never inserts.

        The observable contract is the durable one: exactly one caller turns a
        ``PENDING`` row into ``RUNNING``, and every other state -- ``RUNNING``,
        ``COMPLETED``, ``FAILED``, ``CANCELLED`` -- returns ``None`` instead of
        dispatching again. This store preserves those semantics for tests; the
        single-statement atomic guarantee belongs to SQLite.
        """

        (
            bounded_run_id,
            bounded_workspace,
            bounded_rule,
            scheduled,
        ) = _execution_claim_material(
            run_id=run_id,
            workspace_id=workspace_id,
            rule_id=rule_id,
            scheduled_time=scheduled_time,
        )
        existing = self._runs.get(bounded_run_id)
        if existing is None or existing.workspace_id != bounded_workspace:
            raise ContractError("execution claim requires an existing scheduled run")
        if existing.rule_id != bounded_rule or existing.scheduled_time != scheduled:
            raise ContractError(
                "execution claim cannot change the scheduled occurrence identity"
            )
        key = occurrence_key(bounded_workspace, bounded_rule, scheduled)
        if self._occurrences.get(key) != bounded_run_id:
            raise ContractError(
                "execution claim must match the existing occurrence claim"
            )
        if existing.status is not ClawScheduledRunStatus.PENDING:
            return None
        claimed = ClawScheduledRun(
            run_id=existing.run_id,
            workspace_id=existing.workspace_id,
            rule_id=existing.rule_id,
            status=ClawScheduledRunStatus.RUNNING,
            scheduled_time=existing.scheduled_time,
            started_at=existing.started_at,
            completed_at=None,
            output=None,
            error_message=None,
        )
        self._runs[bounded_run_id] = claimed
        return claimed

    def update_run_projection(
        self,
        *,
        run_id: str,
        workspace_id: str,
        rule_id: str,
        scheduled_time: datetime,
        status: ClawScheduledRunStatus,
        completed_at: datetime | None = None,
        error_message: str | None = None,
        output: ClawAutomationOutput | None = None,
    ) -> ClawScheduledRun:
        """Update an existing projection row. Fail-closed: never claims or inserts."""

        (
            bounded_run_id,
            bounded_workspace,
            bounded_rule,
            scheduled,
            projected,
            completed,
            bounded_error,
        ) = _projection_update_material(
            run_id=run_id,
            workspace_id=workspace_id,
            rule_id=rule_id,
            scheduled_time=scheduled_time,
            status=status,
            completed_at=completed_at,
            error_message=error_message,
        )
        existing = self._runs.get(bounded_run_id)
        if existing is None or existing.workspace_id != bounded_workspace:
            raise ContractError("projection update requires an existing scheduled run")
        if existing.rule_id != bounded_rule or existing.scheduled_time != scheduled:
            raise ContractError("projection update cannot change the scheduled occurrence identity")
        key = occurrence_key(bounded_workspace, bounded_rule, scheduled)
        if self._occurrences.get(key) != bounded_run_id:
            raise ContractError("projection update must match the existing occurrence claim")
        persisted_output = _projection_output_for_update(
            workspace_id=bounded_workspace,
            rule_id=bounded_rule,
            status=projected,
            output=output,
            existing_status=existing.status,
            existing_output=existing.output,
        )
        updated = ClawScheduledRun(
            run_id=existing.run_id,
            workspace_id=existing.workspace_id,
            rule_id=existing.rule_id,
            status=projected,
            scheduled_time=existing.scheduled_time,
            started_at=existing.started_at,
            completed_at=completed,
            output=persisted_output,
            error_message=bounded_error,
        )
        self._runs[bounded_run_id] = updated
        if output is not None and existing.output is None and output.proposals:
            for proposal in output.proposals:
                self._proposals[proposal.proposal_id] = proposal
        return updated



async def _store_call(value: Any) -> Any:
    """Resolve ONE store result whether it answers synchronously or awaitably.

    The durable SQLite reference and in-memory stores answer synchronously,
    while the D1-backed Worker store can only answer through awaited
    statements. Resolving both here keeps ONE store contract for the sync and
    async persistence applications of the tick algorithm (#2995). It never
    wraps a coroutine in ``asyncio.run`` and never blocks the event loop.
    """

    if inspect.isawaitable(value):
        return await value
    return value


class FakeClawScheduler:
    """Deterministic reference scheduler with no provider or dispatch side effects."""

    def __init__(self, store: ClawAutomationStore) -> None:
        self.store = store

    @staticmethod
    def _candidate(rule: ClawAutomationRule, current_time: datetime) -> datetime | None:
        current_utc = _aware_utc(current_time, "current_time")
        local = current_utc.astimezone(resolve_timezone(rule.schedule.timezone))
        kind = rule.schedule.kind
        if kind is ClawScheduleKind.CRON:
            if _cron_matches(local, parse_cron_expression(rule.schedule.expression)):
                return current_utc.replace(second=0, microsecond=0)
            return None
        if kind is ClawScheduleKind.DAYPART:
            slot = _DAYPART_AT[rule.schedule.expression]
            if local.hour == slot.hour and local.minute == slot.minute:
                return current_utc.replace(second=0, microsecond=0)
            return None
        seconds = _parse_interval_seconds(rule.schedule.expression)
        timestamp = int(current_utc.timestamp())
        if timestamp % seconds != 0:
            return None
        return datetime.fromtimestamp(timestamp, timezone.utc)

    @staticmethod
    def snapshot_due_candidates(
        rules: Sequence[ClawAutomationRule],
        current_time: datetime,
    ) -> list[tuple[ClawAutomationRule, datetime, str]]:
        """Pure, deterministic due-candidate selection over an in-memory snapshot.

        This is the ONE schedule-math step shared by every persistence shape
        (#2995): the synchronous ``due_occurrences`` / ``tick`` path and the
        awaited ``ClawAutomationTickRuntime.atick`` application both derive
        their candidates exclusively from here, so no second scheduler
        algorithm can drift beside it. It reads no store, claims nothing and
        mints no run id: ``occurrence_key`` remains the pre-existing dedup
        identity, and persistence stays with the caller's store shape.
        """

        current_utc = _aware_utc(current_time, "current_time")
        candidates: list[tuple[ClawAutomationRule, datetime, str]] = []
        for rule in rules:
            if not rule.enabled:
                continue
            scheduled = FakeClawScheduler._candidate(rule, current_utc)
            if scheduled is None:
                continue
            candidates.append(
                (
                    rule,
                    scheduled,
                    occurrence_key(rule.workspace_id, rule.rule_id, scheduled),
                )
            )
        return candidates

    def due_occurrences(
        self,
        workspace_id: str,
        current_time: datetime,
        membership: TrustedWorkspaceMembershipProjection | None = None,
    ) -> list[tuple[ClawAutomationRule, datetime]]:
        """Return due rules and their canonical occurrence at an explicit instant."""
        current_utc = _aware_utc(current_time, "current_time")
        if membership is not None:
            if membership.workspace_id != workspace_id:
                raise ContractError("membership workspace does not match scheduler workspace")
            if not membership.valid_at(current_utc):
                return []
        due: list[tuple[ClawAutomationRule, datetime]] = []
        for rule, scheduled, key in self.snapshot_due_candidates(
            self.store.list_rules(workspace_id), current_utc
        ):
            if self.store.get_run_for_occurrence(key, workspace_id) is None:
                due.append((rule, scheduled))
        return due

    def evaluate_due_rules(
        self,
        workspace_id: str,
        current_time: datetime,
        membership: TrustedWorkspaceMembershipProjection | None = None,
    ) -> list[ClawAutomationRule]:
        return [rule for rule, _ in self.due_occurrences(workspace_id, current_time, membership)]

    def compute_next_occurrence(self, rule: ClawAutomationRule, after: datetime) -> datetime:
        """Compute a stable next occurrence; unsupported/unavailable schedules fail closed."""
        cursor = _aware_utc(after, "after")
        if rule.schedule.kind is ClawScheduleKind.INTERVAL:
            seconds = _parse_interval_seconds(rule.schedule.expression)
            return datetime.fromtimestamp((int(cursor.timestamp()) // seconds + 1) * seconds, timezone.utc)
        if rule.schedule.kind is ClawScheduleKind.DAYPART:
            tz = resolve_timezone(rule.schedule.timezone)
            slot = _DAYPART_AT[rule.schedule.expression]
            local = cursor.astimezone(tz)
            for offset in range(0, 367):
                day = local.date() + timedelta(days=offset)
                candidate = datetime.combine(day, slot, tzinfo=tz).astimezone(timezone.utc)
                if candidate > cursor:
                    return candidate
            raise ContractError("no daypart occurrence found in bounded search")
        parsed = parse_cron_expression(rule.schedule.expression)
        tz = resolve_timezone(rule.schedule.timezone)
        probe = cursor.replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(366 * 24 * 60 + 1):
            if _cron_matches(probe.astimezone(tz), parsed):
                return probe
            probe += timedelta(minutes=1)
        raise ContractError("cron search exceeded bounded horizon")

    def execute_rule_dry_run(
        self,
        rule: ClawAutomationRule,
        scheduled_time: datetime,
        membership: TrustedWorkspaceMembershipProjection | None = None,
    ) -> ClawScheduledRun:
        if not rule.enabled:
            raise ContractError("disabled automation rule cannot execute")
        scheduled = _aware_utc(scheduled_time, "scheduled_time")
        if membership is not None:
            if membership.workspace_id != rule.workspace_id:
                raise ContractError("membership workspace does not match rule workspace")
            if rule.canonical_subject_id is not None and membership.principal_ref != rule.canonical_subject_id:
                raise ContractError("membership subject does not match rule subject")
            if rule.canonical_subject_id is None and re.fullmatch(
                r"sub_[0-9a-f]{32}", membership.principal_ref
            ):
                raise ContractError("legacy rule cannot use a canonical subject membership")
            if not membership.valid_at(scheduled):
                raise ContractError("expired or not-yet-valid workspace membership")
        existing = self.store.get_run_for_occurrence(
            occurrence_key(rule.workspace_id, rule.rule_id, scheduled), rule.workspace_id
        )
        if existing is not None:
            return existing
        run_id = _derived_occurrence_id("sched_run", rule.workspace_id, rule.rule_id, scheduled)
        proposal = ClawNotificationProposal(
            proposal_id=_derived_occurrence_id("prop", rule.workspace_id, rule.rule_id, scheduled),
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
            created_at=scheduled,
        )
        output = ClawAutomationOutput(
            output_id=_derived_occurrence_id("out", rule.workspace_id, rule.rule_id, scheduled),
            workspace_id=rule.workspace_id,
            output_type=rule.output_type,
            title=f"자동화 결과: {rule.name}",
            content="결과 보고서 (DRAFT) — 자동 전송 및 확정 없음.",
            evidence_refs=(f"rule://{rule.workspace_id}/{rule.rule_id}",),
            proposals=(proposal,),
        )
        run = ClawScheduledRun(
            run_id=run_id, workspace_id=rule.workspace_id, rule_id=rule.rule_id,
            status=ClawScheduledRunStatus.COMPLETED, scheduled_time=scheduled,
            started_at=scheduled, completed_at=scheduled, output=output,
        )
        return self.store.record_run(run)


@dataclass(frozen=True, slots=True)
class ClawAutomationTickReceipt:
    """Bounded, non-secret evidence for exactly one processed tick.

    This is deliberately NOT a user-facing execution report: it carries no
    output body, no proposal text, no provider response, no recipient and no
    credential material. It answers only "what did this tick observe and claim".
    """

    workspace_id: str
    observed_at: datetime
    due_count: int
    created_run_ids: tuple[str, ...]
    deduplicated_count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "observed_at", _aware_utc(self.observed_at, "observed_at"))
        for field_name in ("due_count", "deduplicated_count"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ContractError(f"{field_name} must be a non-negative integer")
        if not isinstance(self.created_run_ids, tuple):
            raise ContractError("created_run_ids must be a tuple")
        norm_ids = tuple(_safe_id(run_id, "created_run_id") for run_id in self.created_run_ids)
        object.__setattr__(self, "created_run_ids", norm_ids)
        if len(norm_ids) != len(set(norm_ids)):
            raise ContractError("created_run_ids must not contain duplicates")
        if self.due_count < len(norm_ids):
            raise ContractError("due_count cannot be smaller than the created run count")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "observed_at": _iso(self.observed_at),
            "due_count": self.due_count,
            "created_run_ids": list(self.created_run_ids),
            "deduplicated_count": self.deduplicated_count,
        }


class ClawAutomationTickRuntime:
    """Provider-neutral durable tick kernel for one explicit workspace.

    One tick is one trusted scheduler trigger for exactly one workspace::

        trigger -> explicit workspace -> authoritative membership projection
                -> current UTC instant -> durable rules -> due occurrences
                -> occurrence dedup -> PENDING occurrence claim
                -> durable persistence -> bounded tick receipt

    Deliberate boundaries:

    * No cloud cron registration, no Celery/APScheduler, no new provider.
    * Membership is mandatory. There is no "background" mode that omits it.
    * Occurrence identity is the pre-existing ``occurrence_key``; this class
      introduces no second dedup authority and no second lock table.
    * A tick CLAIMS an occurrence; it never completes one. The claimed row is
      ``PENDING`` with ``output=None`` and ``completed_at=None``, so no
      synthetic DRAFT/report body and no proposal can be mistaken for an
      execution outcome. Completion belongs to the later canonical execution
      path (the existing execution bridge), which consumes this claimed row.
    * ``self.scheduler`` is reused for due-occurrence/schedule math ONLY.
      ``FakeClawScheduler.execute_rule_dry_run`` stays available to callers
      that explicitly ask for reference/fake materialization, but it is NOT
      this runtime's completion authority.
    * No external send and no terminal output of any kind.
    """

    def __init__(self, store: ClawAutomationStore) -> None:
        for required in ("list_rules", "get_run_for_occurrence", "record_run"):
            if not callable(getattr(store, required, None)):
                raise ContractError(f"tick runtime store must provide {required}()")
        self.store = store
        self.scheduler = FakeClawScheduler(store)

    def tick(
        self,
        *,
        workspace_id: str,
        current_time: datetime,
        membership: TrustedWorkspaceMembershipProjection | None = None,
        memberships: tuple[TrustedWorkspaceMembershipProjection, ...] = (),
    ) -> ClawAutomationTickReceipt:
        """Process one trusted trigger for one workspace and return a receipt."""

        workspace = _safe_id(workspace_id, "workspace_id")
        observed_at = _aware_utc(current_time, "current_time")
        trusted_memberships = self._require_memberships(
            workspace, observed_at, membership, memberships
        )
        if not any(item.valid_at(observed_at) for item in trusted_memberships):
            return ClawAutomationTickReceipt(
                workspace_id=workspace,
                observed_at=observed_at,
                due_count=0,
                created_run_ids=(),
                deduplicated_count=0,
            )
        due = self._authorized_due(
            workspace=workspace,
            current_time=observed_at,
            memberships=trusted_memberships,
        )
        created: list[str] = []
        deduplicated = 0
        for rule, scheduled, rule_membership in due:
            key = occurrence_key(rule.workspace_id, rule.rule_id, scheduled)
            already = self.store.get_run_for_occurrence(key, workspace)
            run = self._claim_pending_occurrence(rule, scheduled, rule_membership)
            if run.run_id in created:
                continue
            if already is not None:
                deduplicated += 1
                continue
            created.append(run.run_id)

        return ClawAutomationTickReceipt(
            workspace_id=workspace,
            observed_at=observed_at,
            due_count=len(due),
            created_run_ids=tuple(sorted(created)),
            deduplicated_count=deduplicated,
        )

    async def atick(
        self,
        *,
        workspace_id: str,
        current_time: datetime,
        membership: TrustedWorkspaceMembershipProjection | None = None,
        memberships: tuple[TrustedWorkspaceMembershipProjection, ...] = (),
    ) -> ClawAutomationTickReceipt:
        """Async persistence application of the SAME tick algorithm (#2995).

        The schedule math (``FakeClawScheduler.snapshot_due_candidates``), the
        dedup identity (``occurrence_key``), the PENDING claim construction
        (``_build_pending_claim``) and the receipt contract are the exact
        objects ``tick()`` uses -- only the persistence application awaits, so
        a D1-shaped async store is served with no synchronous wrapper and no
        blocked event loop. Differential contract tests pin that ``tick()`` and
        ``atick()`` produce identical receipts and rows for identical store
        state: one scheduling/dedup/run-id authority, two persistence shapes.
        """

        workspace = _safe_id(workspace_id, "workspace_id")
        observed_at = _aware_utc(current_time, "current_time")
        trusted_memberships = self._require_memberships(
            workspace, observed_at, membership, memberships
        )
        if not any(item.valid_at(observed_at) for item in trusted_memberships):
            return ClawAutomationTickReceipt(
                workspace_id=workspace,
                observed_at=observed_at,
                due_count=0,
                created_run_ids=(),
                deduplicated_count=0,
            )
        rules = await _store_call(self.store.list_rules(workspace))
        due: list[tuple[ClawAutomationRule, datetime, str, TrustedWorkspaceMembershipProjection]] = []
        for rule, scheduled, key in FakeClawScheduler.snapshot_due_candidates(
            rules, observed_at
        ):
            rule_membership = self._membership_for_rule(rule, trusted_memberships)
            if (
                rule_membership is None
                or not rule_membership.valid_at(observed_at)
                or not rule_membership.valid_at(scheduled)
            ):
                continue
            if await _store_call(self.store.get_run_for_occurrence(key, workspace)) is None:
                due.append((rule, scheduled, key, rule_membership))
        created: list[str] = []
        deduplicated = 0
        for rule, scheduled, key, rule_membership in due:
            already = await _store_call(
                self.store.get_run_for_occurrence(key, workspace)
            )
            run = await _store_call(
                self.store.record_run(
                    self._build_pending_claim(rule, scheduled, rule_membership)
                )
            )
            if run.run_id in created:
                continue
            if already is not None:
                deduplicated += 1
                continue
            created.append(run.run_id)

        return ClawAutomationTickReceipt(
            workspace_id=workspace,
            observed_at=observed_at,
            due_count=len(due),
            created_run_ids=tuple(sorted(created)),
            deduplicated_count=deduplicated,
        )

    @staticmethod
    def _require_memberships(
        workspace_id: str,
        observed_at: datetime,
        membership: TrustedWorkspaceMembershipProjection | None,
        memberships: tuple[TrustedWorkspaceMembershipProjection, ...],
    ) -> tuple[TrustedWorkspaceMembershipProjection, ...]:
        values = (membership, *memberships) if membership is not None else tuple(memberships)
        if not values or not all(
            isinstance(item, TrustedWorkspaceMembershipProjection) for item in values
        ):
            raise ContractError("tick runtime requires a TrustedWorkspaceMembershipProjection")
        unique: list[TrustedWorkspaceMembershipProjection] = []
        for item in values:
            if item.workspace_id != workspace_id:
                raise ContractError("membership workspace does not match scheduler workspace")
            if item not in unique:
                unique.append(item)
        return tuple(unique)

    @staticmethod
    def _membership_for_rule(
        rule: ClawAutomationRule,
        memberships: tuple[TrustedWorkspaceMembershipProjection, ...],
    ) -> TrustedWorkspaceMembershipProjection | None:
        return select_automation_rule_membership(rule, memberships)

    def _authorized_due(
        self,
        *,
        workspace: str,
        current_time: datetime,
        memberships: tuple[TrustedWorkspaceMembershipProjection, ...],
    ) -> list[tuple[ClawAutomationRule, datetime, TrustedWorkspaceMembershipProjection]]:
        authorized: list[tuple[ClawAutomationRule, datetime, TrustedWorkspaceMembershipProjection]] = []
        for rule, scheduled, key in FakeClawScheduler.snapshot_due_candidates(
            self.store.list_rules(workspace), current_time
        ):
            membership = self._membership_for_rule(rule, memberships)
            if membership is None or not membership.valid_at(current_time):
                continue
            if not membership.valid_at(scheduled):
                continue
            if self.store.get_run_for_occurrence(key, workspace) is not None:
                continue
            authorized.append((rule, scheduled, membership))
        return authorized

    def _build_pending_claim(
        self,
        rule: ClawAutomationRule,
        scheduled: datetime,
        membership: TrustedWorkspaceMembershipProjection,
    ) -> ClawScheduledRun:
        """Pure pre-I/O construction of the canonical PENDING claim row (#2995).

        The guards and row shape are exactly what ``_claim_pending_occurrence``
        has always written; factoring them out lets the async persistence
        application (``atick``) record the identical claim through an awaited
        store without a second claim or run-id authority. No store write
        happens here.
        """

        if not rule.enabled:
            raise ContractError("disabled automation rule cannot execute")
        if membership.workspace_id != rule.workspace_id:
            raise ContractError("membership workspace does not match rule workspace")
        if rule.canonical_subject_id is not None and membership.principal_ref != rule.canonical_subject_id:
            raise ContractError("membership subject does not match rule subject")
        if rule.canonical_subject_id is None and re.fullmatch(
            r"sub_[0-9a-f]{32}", membership.principal_ref
        ):
            raise ContractError("legacy rule cannot use a canonical subject membership")
        if not membership.valid_at(scheduled):
            raise ContractError("expired or not-yet-valid workspace membership")
        return ClawScheduledRun(
            run_id=_derived_occurrence_id(
                "sched_run", rule.workspace_id, rule.rule_id, scheduled
            ),
            workspace_id=rule.workspace_id,
            rule_id=rule.rule_id,
            status=ClawScheduledRunStatus.PENDING,
            scheduled_time=scheduled,
            started_at=scheduled,
            completed_at=None,
            output=None,
        )

    def _claim_pending_occurrence(
        self,
        rule: ClawAutomationRule,
        scheduled: datetime,
        membership: TrustedWorkspaceMembershipProjection,
    ) -> ClawScheduledRun:
        """Claim ONE logical occurrence as a ``PENDING`` scheduled run.

        This is the durable tick path's only materialization step, and it is
        deliberately not a completion step:

        * ``status`` is ``PENDING`` -- the occurrence is claimed, execution has
          not started, and this kernel has no authority to start it.
        * ``output`` stays ``None`` -- no DRAFT body, no report, no proposal is
          fabricated here, so no caller can read a synthetic result as a real
          one. The pre-existing completion authority (the canonical execution
          path) is the only writer of terminal output.
        * ``completed_at`` stays ``None`` -- the row is not terminal.
        * ``run_id`` remains the pre-existing occurrence-derived
          ``sched_run_<digest>``; ``record_run`` remains the only claim
          authority, so a replay adopts the canonical row instead of creating a
          second one.

        ``started_at`` is the CLAIM instant (the occurrence instant). The
        pre-existing schema makes the column mandatory, and for a ``PENDING``
        row it records when the occurrence was claimed -- never that execution
        began.

        Pre-I/O guards mirror the refusals the reference scheduler used to make
        on this path (disabled rule, foreign membership, membership that does
        not cover the occurrence instant). They fail closed before any store
        write, and they add no new authority.
        """

        claimed = self._build_pending_claim(rule, scheduled, membership)
        return self.store.record_run(claimed)

    @staticmethod
    def _require_membership(
        membership: TrustedWorkspaceMembershipProjection,
        workspace_id: str,
        observed_at: datetime,
    ) -> None:
        """Fail closed unless a well-formed projection covers this workspace.

        A missing projection is never a reason to fall back to tenant scope.
        A malformed or foreign projection is a hard contract violation and
        raises; mere temporal inactivity is handled by the caller as a
        zero-run tick, never as an implicit tenant-scoped fallback.
        """

        if not isinstance(membership, TrustedWorkspaceMembershipProjection):
            raise ContractError(
                "tick runtime requires a TrustedWorkspaceMembershipProjection; "
                "anonymous or background execution is not permitted"
            )
        if membership.workspace_id != workspace_id:
            raise ContractError("membership projection does not cover this workspace")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "provider_neutral_tick_runtime": True,
            "durable_tick_runtime": True,
            "real_cloud_cron_registration": False,
            "production_scheduler_activation": False,
            "requires_explicit_workspace": True,
            "requires_membership_projection": True,
            "membership_may_be_omitted": False,
            "per_rule_subject_isolation": True,
            "provider_calls": False,
            "external_send": False,
        }

class SqliteClawAutomationStore:
    """Durable automation store following the canonical SQLite pattern.

    Mirrors the canonical ``SqliteSealedGoogleOAuthStore`` authority:
    SQLite stdlib, JSON serialization, workspace-scoped rows,
    ``ON CONFLICT`` upsert, ``PRAGMA foreign_keys = ON``,
    ``BEGIN IMMEDIATE`` transaction safety, and fail-closed on invalid data.
    """

    def __init__(self, database_path: str | Path) -> None:
        if isinstance(database_path, Path):
            database_path = str(database_path)
        if not isinstance(database_path, str) or not database_path.strip():
            raise ContractError("database_path must be non-empty")
        self._database_path = database_path.strip()
        if self._database_path != ":memory:":
            Path(self._database_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self._database_path, isolation_level=None, check_same_thread=False)
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS claw_rules ("
            "rule_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, name TEXT NOT NULL, "
            "schedule_kind TEXT NOT NULL, schedule_expression TEXT NOT NULL, schedule_timezone TEXT NOT NULL, "
            "target_source TEXT NOT NULL, output_type TEXT NOT NULL, "
            "enabled INTEGER NOT NULL DEFAULT 1, "
            "notification_channels TEXT NOT NULL DEFAULT '[]', "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
            "canonical_subject_id TEXT)"
        )
        columns = {
            str(row[1]) for row in self._db.execute("PRAGMA table_info(claw_rules)")
        }
        if "canonical_subject_id" not in columns:
            self._db.execute("ALTER TABLE claw_rules ADD COLUMN canonical_subject_id TEXT")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS claw_runs ("
            "run_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, rule_id TEXT NOT NULL, "
            "status TEXT NOT NULL, scheduled_time TEXT NOT NULL, started_at TEXT NOT NULL, "
            "completed_at TEXT, output TEXT, error_message TEXT)"
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS claw_occurrences ("
            "occurrence_key TEXT PRIMARY KEY, run_id TEXT NOT NULL, workspace_id TEXT NOT NULL)"
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS claw_proposals ("
            "proposal_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, rule_id TEXT NOT NULL, "
            "channel TEXT NOT NULL, title TEXT NOT NULL, summary TEXT NOT NULL, "
            "approval_required INTEGER NOT NULL DEFAULT 1, approval_reason TEXT NOT NULL DEFAULT '', "
            "suggested_action TEXT NOT NULL DEFAULT '', approved_by TEXT, approved_at TEXT, "
            "created_at TEXT NOT NULL)"
        )

    # --- rule persistence ---

    def save_rule(self, rule: ClawAutomationRule) -> None:
        # owner_ref remains opaque payload provenance; canonical subject provenance
        # is stored in its own nullable rule column.
        payload = self._serialize_rule(rule)
        try:
            self._db.execute(
                "INSERT INTO claw_rules(rule_id, workspace_id, name, schedule_kind, schedule_expression, schedule_timezone, target_source, output_type, enabled, notification_channels, created_at, updated_at, canonical_subject_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rule.rule_id, rule.workspace_id, rule.name,
                    rule.schedule.kind.value, rule.schedule.expression, rule.schedule.timezone,
                    rule.target_source.value, rule.output_type.value,
                    1 if rule.enabled else 0, payload,
                    _iso(datetime.now(timezone.utc)), _iso(datetime.now(timezone.utc)),
                    rule.canonical_subject_id,
                ),
            )
        except sqlite3.IntegrityError:
            existing = self._get_rule_row(rule.rule_id)
            if existing is None or existing[1] != rule.workspace_id:
                raise ContractError("rule_id is already owned by another workspace")
            # Owner provenance is immutable after rule creation: a generic
            # update may never transfer, drop, or mint an owner_ref. Fail
            # closed before any row write when the value would change.
            try:
                existing_payload = json.loads(existing[9])
            except Exception as exc:
                raise ContractError("stored automation rule is corrupt") from exc
            if existing_payload.get("owner_ref") != rule.owner_ref:
                raise ContractError("rule owner provenance is immutable")
            if existing[12] != rule.canonical_subject_id:
                raise ContractError("rule canonical subject provenance is immutable")
            # Execution material is immutable here too, checked before any write so

            # a generic update can never promote a legacy rule or swap its task.
            if existing_payload.get("execution_intent") != _execution_intent_document(
                rule.execution_intent
            ):
                raise ContractError("rule execution intent is immutable")
            self._db.execute(
                "UPDATE claw_rules SET name=?, schedule_kind=?, schedule_expression=?, schedule_timezone=?, target_source=?, output_type=?, enabled=?, notification_channels=?, updated_at=? WHERE rule_id=?",
                (
                    rule.name, rule.schedule.kind.value, rule.schedule.expression, rule.schedule.timezone,
                    rule.target_source.value, rule.output_type.value,
                    1 if rule.enabled else 0, payload,
                    _iso(datetime.now(timezone.utc)), rule.rule_id,
                ),
            )

    def get_rule(self, rule_id: str, workspace_id: str) -> ClawAutomationRule | None:
        row = self._get_rule_row(rule_id)
        if row is None or row[1] != workspace_id:
            return None
        return self._rule_from_row(row)

    def list_rules(self, workspace_id: str) -> list[ClawAutomationRule]:
        rows = self._db.execute(
            "SELECT rule_id, workspace_id, name, schedule_kind, schedule_expression, schedule_timezone, target_source, output_type, enabled, notification_channels, created_at, updated_at, canonical_subject_id FROM claw_rules WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchall()
        return [self._rule_from_row(row) for row in rows]

    def update_rule(self, rule: ClawAutomationRule) -> None:
        current = self._get_rule_row(rule.rule_id)
        if current is None or current[1] != rule.workspace_id:
            raise ContractError("rule does not belong to workspace")
        self.save_rule(rule)

    def set_rule_enabled(self, workspace_id: str, rule_id: str, enabled: bool) -> ClawAutomationRule:
        if not isinstance(enabled, bool):
            raise ContractError("enabled must be boolean")
        rule = self.get_rule(rule_id, workspace_id)
        if rule is None:
            raise ContractError("rule does not belong to workspace")
        updated = ClawAutomationRule(
            rule_id=rule.rule_id, workspace_id=rule.workspace_id, name=rule.name,
            schedule=rule.schedule, target_source=rule.target_source,
            output_type=rule.output_type, enabled=enabled,
            notification_channels=rule.notification_channels,
            owner_ref=rule.owner_ref,
            execution_intent=rule.execution_intent,
            canonical_subject_id=rule.canonical_subject_id,
        )

        self.save_rule(updated)
        return updated

    # --- run persistence ---

    def record_run(self, run: ClawScheduledRun) -> ClawScheduledRun:
        existing_run = self._get_run_row(run.run_id)
        if existing_run is not None and existing_run[1] != run.workspace_id:
            raise ContractError("run_id is already owned by another workspace")
        key = occurrence_key(run.workspace_id, run.rule_id, run.scheduled_time)
        existing_id = self._get_occurrence_run_id(key, run.workspace_id)
        if existing_id is not None:
            # Fast path: the occurrence is already claimed. Adopt the
            # canonical run; never write, and never delete anything.
            canonical = self.get_run(existing_id, run.workspace_id)
            if canonical is None:
                raise ContractError("occurrence claim points at a missing run")
            return canonical
        self._db.execute("BEGIN IMMEDIATE")
        try:
            # Claim the occurrence FIRST. The occurrence primary key is the
            # only dedup authority, so whichever writer wins the claim owns
            # the canonical run for this logical occurrence.
            claim = self._db.execute(
                "INSERT OR IGNORE INTO claw_occurrences(occurrence_key, run_id, workspace_id) VALUES (?, ?, ?)",
                (key, run.run_id, run.workspace_id),
            )
            if claim.rowcount == 0:
                # We lost the claim. Under claim-first ordering this writer
                # never inserted a run row, so the loser path must perform
                # NO DELETE. Deleting by run_id is unsafe: the runtime
                # derives run_id from the occurrence identity, so both
                # contenders name the SAME row and a delete would destroy
                # the winner's canonical run.
                winner_id = self._get_occurrence_run_id(key, run.workspace_id)
                if winner_id is None:
                    raise ContractError("occurrence claim vanished during concurrent write")
                canonical = self.get_run(winner_id, run.workspace_id)
                if canonical is None:
                    raise ContractError("occurrence claim points at a missing run")
                self._db.execute("COMMIT")
                return canonical
            # We won the claim, so this run is the canonical one. A plain
            # INSERT (not OR IGNORE) fails closed if the same run_id is
            # already stored for a DIFFERENT logical occurrence, preventing
            # the occurrence from aliasing an unrelated run. The driver
            # error is translated so only a domain error escapes.
            try:
                self._db.execute(
                    "INSERT INTO claw_runs(run_id, workspace_id, rule_id, status, scheduled_time, started_at, completed_at, output, error_message) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run.run_id, run.workspace_id, run.rule_id, run.status.value,
                        _iso(run.scheduled_time), _iso(run.started_at),
                        _iso(run.completed_at) if run.completed_at else None,
                        self._serialize_output(run.output), run.error_message,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ContractError(
                    "run_id is already stored for a different logical occurrence"
                ) from exc
            if run.output and run.output.proposals:
                for proposal in run.output.proposals:
                    self._db.execute(
                        "INSERT OR IGNORE INTO claw_proposals(proposal_id, workspace_id, rule_id, channel, title, summary, approval_required, approval_reason, suggested_action, approved_by, approved_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            proposal.proposal_id, proposal.workspace_id, proposal.rule_id,
                            proposal.channel.value, proposal.title, proposal.summary,
                            1 if proposal.approval_gate.approval_required else 0,
                            proposal.approval_gate.reason, proposal.approval_gate.suggested_action,
                            proposal.approval_gate.approved_by,
                            _iso(proposal.approval_gate.approved_at) if proposal.approval_gate.approved_at else None,
                            _iso(proposal.created_at),
                        ),
                    )
            self._db.execute("COMMIT")
        except Exception:
            # Exactly one ROLLBACK on the error path. The loser path above
            # COMMITs before returning, so it never reaches here with a
            # closed transaction.
            self._db.execute("ROLLBACK")
            raise
        return run

    def get_run(self, run_id: str, workspace_id: str) -> ClawScheduledRun | None:
        row = self._get_run_row(run_id)
        if row is None or row[1] != workspace_id:
            return None
        return self._run_from_row(row)

    def get_run_for_occurrence(self, key: str, workspace_id: str) -> ClawScheduledRun | None:
        run_id = self._get_occurrence_run_id(key, workspace_id)
        return self.get_run(run_id, workspace_id) if run_id is not None else None

    def list_runs(self, workspace_id: str) -> list[ClawScheduledRun]:
        rows = self._db.execute(
            "SELECT run_id, workspace_id, rule_id, status, scheduled_time, started_at, completed_at, output, error_message FROM claw_runs WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchall()
        return [self._run_from_row(row) for row in rows]

    def list_proposals(self, workspace_id: str) -> list[ClawNotificationProposal]:
        rows = self._db.execute(
            "SELECT proposal_id, workspace_id, rule_id, channel, title, summary, approval_required, approval_reason, suggested_action, approved_by, approved_at, created_at FROM claw_proposals WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchall()
        return [self._proposal_from_row(row) for row in rows]

    def claim_execution(
        self,
        *,
        run_id: str,
        workspace_id: str,
        rule_id: str,
        scheduled_time: datetime,
    ) -> ClawScheduledRun | None:
        """Atomically claim ONE existing ``PENDING`` row for execution.

        The claim reuses the EXISTING scheduled-run row and its status column.
        There is no lock table, no claim token, no lease row, no second dedup
        key and no second run id: ``PENDING -> RUNNING`` is one bounded
        conditional update on the row the durable tick already claimed.

        ``RUNNING``, ``COMPLETED``, ``FAILED`` and ``CANCELLED`` all resolve to
        ``None`` -- not claimed -- so a second claimant can never dispatch the
        same occurrence twice, and a stuck ``RUNNING`` row is preferred over a
        duplicated external side effect.
        """

        (
            bounded_run_id,
            bounded_workspace,
            bounded_rule,
            scheduled,
        ) = _execution_claim_material(
            run_id=run_id,
            workspace_id=workspace_id,
            rule_id=rule_id,
            scheduled_time=scheduled_time,
        )
        row = self._get_run_row(bounded_run_id)
        if row is None or row[1] != bounded_workspace:
            raise ContractError("execution claim requires an existing scheduled run")
        stored = self._run_from_row(row)
        if stored.rule_id != bounded_rule or stored.scheduled_time != scheduled:
            raise ContractError(
                "execution claim cannot change the scheduled occurrence identity"
            )
        key = occurrence_key(bounded_workspace, bounded_rule, scheduled)
        if self._get_occurrence_run_id(key, bounded_workspace) != bounded_run_id:
            raise ContractError(
                "execution claim must match the existing occurrence claim"
            )
        if stored.status is not ClawScheduledRunStatus.PENDING:
            # RUNNING / COMPLETED / FAILED / CANCELLED: never dispatched again.
            return None
        self._db.execute("BEGIN IMMEDIATE")
        try:
            update_cursor = self._db.execute(
                "UPDATE claw_runs SET status=? "
                "WHERE run_id=? AND status=? AND completed_at IS NULL",
                (
                    ClawScheduledRunStatus.RUNNING.value,
                    bounded_run_id,
                    ClawScheduledRunStatus.PENDING.value,
                ),
            )
            claimed_now = update_cursor.rowcount == 1
            # Exactly one COMMIT either way: the loser's conditional update
            # matched no row, so committing persists nothing and no DELETE is
            # ever issued on the loser path.
            self._db.execute("COMMIT")
        except Exception:
            self._db.execute("ROLLBACK")
            raise
        if not claimed_now:
            return None
        claimed_row = self._get_run_row(bounded_run_id)
        if claimed_row is None:
            raise ContractError("execution claim lost its scheduled run row")
        return self._run_from_row(claimed_row)

    def update_run_projection(
        self,
        *,
        run_id: str,
        workspace_id: str,
        rule_id: str,
        scheduled_time: datetime,
        status: ClawScheduledRunStatus,
        completed_at: datetime | None = None,
        error_message: str | None = None,
        output: ClawAutomationOutput | None = None,
    ) -> ClawScheduledRun:
        """Update an existing projection row in place. Fail-closed: never inserts.

        The row must already exist, its immutable occurrence identity must match,
        and the existing occurrence claim must point at this same run id. A second
        run row or a fresh claim is impossible through this path.
        """

        (
            bounded_run_id,
            bounded_workspace,
            bounded_rule,
            scheduled,
            projected,
            completed,
            bounded_error,
        ) = _projection_update_material(
            run_id=run_id,
            workspace_id=workspace_id,
            rule_id=rule_id,
            scheduled_time=scheduled_time,
            status=status,
            completed_at=completed_at,
            error_message=error_message,
        )
        row = self._get_run_row(bounded_run_id)
        if row is None or row[1] != bounded_workspace:
            raise ContractError("projection update requires an existing scheduled run")
        stored = self._run_from_row(row)
        if stored.rule_id != bounded_rule or stored.scheduled_time != scheduled:
            raise ContractError("projection update cannot change the scheduled occurrence identity")
        key = occurrence_key(bounded_workspace, bounded_rule, scheduled)
        if self._get_occurrence_run_id(key, bounded_workspace) != bounded_run_id:
            raise ContractError("projection update must match the existing occurrence claim")
        persisted_output = _projection_output_for_update(
            workspace_id=bounded_workspace,
            rule_id=bounded_rule,
            status=projected,
            output=output,
            existing_status=stored.status,
            existing_output=stored.output,
        )
        serialized_output = self._serialize_output(persisted_output)
        self._db.execute("BEGIN IMMEDIATE")
        try:
            update_cursor = self._db.execute(
                "UPDATE claw_runs SET status=?, completed_at=?, output=?, error_message=? "
                "WHERE run_id=? AND status=? AND (output IS NULL OR output=?)",
                (
                    projected.value,
                    _iso(completed) if completed is not None else None,
                    serialized_output,
                    bounded_error,
                    bounded_run_id,
                    stored.status.value,
                    serialized_output,
                ),
            )
            if update_cursor.rowcount != 1:
                raise ContractError("projection output changed concurrently")
            if output is not None and stored.output is None and output.proposals:
                for proposal in output.proposals:
                    self._db.execute(
                        "INSERT OR IGNORE INTO claw_proposals(proposal_id, workspace_id, rule_id, channel, title, summary, approval_required, approval_reason, suggested_action, approved_by, approved_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            proposal.proposal_id, proposal.workspace_id, proposal.rule_id,
                            proposal.channel.value, proposal.title, proposal.summary,
                            1 if proposal.approval_gate.approval_required else 0,
                            proposal.approval_gate.reason, proposal.approval_gate.suggested_action,
                            proposal.approval_gate.approved_by,
                            _iso(proposal.approval_gate.approved_at) if proposal.approval_gate.approved_at else None,
                            _iso(proposal.created_at),
                        ),
                    )
            self._db.execute("COMMIT")
        except Exception:
            self._db.execute("ROLLBACK")
            raise
        updated = self.get_run(bounded_run_id, bounded_workspace)
        if updated is None:
            raise ContractError("projection update lost its scheduled run")
        return updated


    # --- internal helpers ---

    def _get_rule_row(self, rule_id: str) -> tuple | None:
        row = self._db.execute(
            "SELECT rule_id, workspace_id, name, schedule_kind, schedule_expression, schedule_timezone, target_source, output_type, enabled, notification_channels, created_at, updated_at, canonical_subject_id FROM claw_rules WHERE rule_id = ?",
            (rule_id,),
        ).fetchone()
        return row

    def _get_run_row(self, run_id: str) -> tuple | None:
        row = self._db.execute(
            "SELECT run_id, workspace_id, rule_id, status, scheduled_time, started_at, completed_at, output, error_message FROM claw_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return row

    def _get_occurrence_run_id(self, occurrence_key: str, workspace_id: str) -> str | None:
        row = self._db.execute(
            "SELECT run_id FROM claw_occurrences WHERE occurrence_key = ? AND workspace_id = ?",
            (occurrence_key, workspace_id),
        ).fetchone()
        return row[0] if row else None

    @staticmethod
    def _serialize_rule(rule: ClawAutomationRule) -> bytes:
        """Encode one rule into the single canonical stored-rule payload.

        #2833 B2A: owner_ref rides inside the existing notification_channels
        JSON payload as an additive field — no new table, no new column. Legacy
        payloads without it simply persist the key's absence.

        #2833 S2F1: the execution intent is additive inside the same document —
        no new table, column or migration. Absent for legacy and intent-free
        rules.

        This is the ONE rule encoder. The durable reference store and any
        provider adapter must share it, so the two can never drift on what a
        stored rule means: a second encoder would be a second rule authority.
        """

        payload_document: dict[str, Any] = {
                "rule_id": rule.rule_id,
                "workspace_id": rule.workspace_id,
                "name": rule.name,
                "schedule": {"kind": rule.schedule.kind.value, "expression": rule.schedule.expression, "timezone": rule.schedule.timezone},
                "target_source": rule.target_source.value,
                "output_type": rule.output_type.value,
                "enabled": rule.enabled,
                "notification_channels": [
                    {"channel": c.channel.value, "enabled": c.enabled, "recipient_ref": c.recipient_ref}
                    for c in rule.notification_channels
                ],
        }
        if rule.owner_ref is not None:
            payload_document["owner_ref"] = rule.owner_ref
        intent_document = _execution_intent_document(rule.execution_intent)
        if intent_document is not None:
            payload_document["execution_intent"] = intent_document
        return json.dumps(
            payload_document,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def _rule_from_row(row: tuple) -> ClawAutomationRule:
        try:
            payload = json.loads(row[9])
            return ClawAutomationRule(
                rule_id=row[0], workspace_id=row[1], name=row[2],
                schedule=ClawScheduleExpression(
                    kind=ClawScheduleKind(payload["schedule"]["kind"]),
                    expression=payload["schedule"]["expression"],
                    timezone=payload["schedule"]["timezone"],
                ),
                target_source=ClawAutomationTarget(payload["target_source"]),
                output_type=ClawAutomationOutputType(payload["output_type"]),
                enabled=bool(row[8]),
                notification_channels=tuple(
                    ClawNotificationPreference(
                        channel=c["channel"], enabled=c["enabled"], recipient_ref=c.get("recipient_ref"),
                    )
                    for c in payload["notification_channels"]
                ),
                # Legacy payloads carry no owner_ref key; absence reads None.
                owner_ref=payload.get("owner_ref"),
                # Same for S2F1 execution material: no key means no intent, and a
                # legacy rule stays exactly as legacy as it was.
                execution_intent=_execution_intent_from_document(payload.get("execution_intent")),
                canonical_subject_id=row[12] if len(row) > 12 else None,

            )
        except Exception as exc:
            raise ContractError("stored automation rule is corrupt") from exc

    @staticmethod
    def _run_from_row(row: tuple) -> ClawScheduledRun:
        output = SqliteClawAutomationStore._deserialize_output(row[7]) if row[7] else None
        try:
            return ClawScheduledRun(
                run_id=row[0], workspace_id=row[1], rule_id=row[2],
                status=ClawScheduledRunStatus(row[3]),
                scheduled_time=_parse_iso(row[4], "scheduled_time"),
                started_at=_parse_iso(row[5], "started_at"),
                completed_at=_parse_iso(row[6], "completed_at") if row[6] else None,
                output=output, error_message=row[8],
            )
        except ContractError:
            raise
        except Exception as exc:
            raise ContractError("stored scheduled run is corrupt") from exc

    @staticmethod
    def _proposal_from_row(row: tuple) -> ClawNotificationProposal:
        try:
            return ClawNotificationProposal(
                proposal_id=row[0], workspace_id=row[1], rule_id=row[2],
                channel=ClawNotificationChannel(row[3]),
                title=row[4], summary=row[5],
                approval_gate=ClawApprovalGate(
                    approval_required=bool(row[6]), reason=row[7], suggested_action=row[8],
                    approved_by=row[9],
                    approved_at=_parse_iso(row[10], "approved_at") if row[10] else None,
                ),
                created_at=_parse_iso(row[11], "created_at"),
            )
        except ContractError:
            raise
        except Exception as exc:
            raise ContractError("stored notification proposal is corrupt") from exc

    @staticmethod
    def _serialize_output(output: ClawAutomationOutput | None) -> str | None:
        if output is None:
            return None
        return json.dumps(
            {
                "output_id": output.output_id,
                "workspace_id": output.workspace_id,
                "output_type": output.output_type.value,
                "title": output.title,
                "content": output.content,
                "evidence_refs": list(output.evidence_refs),
                "proposals": [
                    {
                        "proposal_id": p.proposal_id,
                        "workspace_id": p.workspace_id,
                        "rule_id": p.rule_id,
                        "channel": p.channel.value,
                        "title": p.title,
                        "summary": p.summary,
                        "approval_gate": {
                            "approval_required": p.approval_gate.approval_required,
                            "reason": p.approval_gate.reason,
                            "suggested_action": p.approval_gate.suggested_action,
                            "approved_by": p.approval_gate.approved_by,
                            "approved_at": _iso(p.approval_gate.approved_at) if p.approval_gate.approved_at else None,
                        },
                        "created_at": _iso(p.created_at),
                    }
                    for p in output.proposals
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _deserialize_output(raw: str) -> ClawAutomationOutput | None:
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            raise ContractError("stored output record is corrupt")
        try:
            proposals = tuple(
                ClawNotificationProposal(
                    proposal_id=p["proposal_id"], workspace_id=p["workspace_id"], rule_id=p["rule_id"],
                    channel=p["channel"], title=p["title"], summary=p["summary"],
                    approval_gate=ClawApprovalGate(
                        approval_required=p["approval_gate"]["approval_required"],
                        reason=p["approval_gate"]["reason"],
                        suggested_action=p["approval_gate"]["suggested_action"],
                        approved_by=p["approval_gate"].get("approved_by"),
                        approved_at=_parse_iso(p["approval_gate"]["approved_at"], "approved_at") if p["approval_gate"].get("approved_at") else None,
                    ),
                    created_at=_parse_iso(p["created_at"], "created_at"),
                )
                for p in payload.get("proposals", [])
            )
            return ClawAutomationOutput(
                output_id=payload["output_id"], workspace_id=payload["workspace_id"],
                output_type=payload["output_type"], title=payload["title"], content=payload["content"],
                evidence_refs=tuple(payload.get("evidence_refs", [])),
                proposals=proposals,
            )
        except ContractError:
            raise
        except Exception as exc:
            raise ContractError("stored output record is corrupt") from exc


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
    "ClawAutomationStore",
    "InMemoryClawAutomationStore",
    "FakeClawScheduler",
    "SqliteClawAutomationStore",
    "ClawAutomationTickReceipt",
    "ClawAutomationTickRuntime",
    "occurrence_key",
    "parse_cron_expression",
    "resolve_timezone",
]

# --- #2833 durable provider-neutral tick runtime boundaries ---
# The kernel exists and is durable, but nothing schedules it in the cloud and
# no production trigger is wired yet. These flags are deliberately explicit
# so no consumer can mistake the kernel for an activated scheduler.
DURABLE_TICK_RUNTIME = True
BACKGROUND_RUNTIME_KERNEL = True
# --- #2833 S2F5A ---
# The durable tick claims a PENDING occurrence and never fabricates a terminal
# result. These flags are constants, not claims: no code path in this module
# can raise the second one or enable the third.
DURABLE_TICK_CLAIMS_PENDING_OCCURRENCE = True
DURABLE_TICK_SYNTHETIC_COMPLETION = False
DURABLE_TICK_REFERENCE_SCHEDULER_IS_COMPLETION_AUTHORITY = False
REAL_BACKGROUND_TRIGGER = False
REAL_CLOUD_CRON_REGISTRATION = False
PRODUCTION_SCHEDULER_ACTIVATION = False
TICK_RUNTIME_REQUIRES_MEMBERSHIP = True
TICK_RUNTIME_MEMBERSHIP_OPTIONAL = False
TICK_RUNTIME_PERFORMS_PROVIDER_CALLS = False
TICK_RUNTIME_REGISTERS_CLOUD_CRON = False
# #2995: the awaited persistence twin (``atick``) exists in source; it reuses
# the same schedule math / occurrence_key / claim and activates nothing.
TICK_RUNTIME_ASYNC_PERSISTENCE_SEAM = True
EXTERNAL_SEND_ENABLED = False
AUTO_SEND_ENABLED = False
AUTO_ORDER_ENABLED = False
AUTO_MEMORY_CONFIRM_ENABLED = False
ONE_OCCURRENCE_MAX_CANONICAL_RUNS = 1
# --- #2833 S2F5B ---
# The execution claim reuses the existing scheduled-run row and status column.
# These flags are constants, not claims: no code path in this module can add a
# second lock table, mint a claim token, introduce a second dedup authority,
# dispatch a RUNNING or terminal row again, or activate a Production scheduler.
EXECUTION_CLAIM_AUTHORITY_REUSED = True
EXECUTION_CLAIM_NEW_LOCK_TABLE = False
EXECUTION_CLAIM_NEW_CLAIM_TOKEN = False
EXECUTION_CLAIM_SECOND_DEDUP_AUTHORITY = False
EXECUTION_CLAIM_SECOND_RUN_ID = False
EXECUTION_CLAIM_REDISPATCHES_RUNNING = False
EXECUTION_CLAIM_REDISPATCHES_TERMINAL = False
EXECUTION_CLAIM_PERFORMS_PROVIDER_CALLS = False
EXECUTION_CLAIM_ACTIVATES_PRODUCTION_SCHEDULER = False
