"""B54 Claw Automation, Scheduled Checks, and Notification Delivery Contracts (#2058).

Defines workspace-scoped scheduled checks, automation rules, notification channels,
safe proposal projections, and approval gates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from enum import Enum
import re
from typing import Any, Protocol, Sequence

from .contracts import ContractError
from .core import redact_secrets
from .workspace_visibility import TrustedWorkspaceMembershipProjection

try:  # stdlib IANA tz database; unavailable on tzdata-less Windows without the extra package
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - py<3.9 not supported (requires-python>=3.11)
    ZoneInfo = None  # type: ignore[assignment]

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
    stamp = scheduled.strftime("%Y%m%dT%H%M%SZ")
    return f"claw_occurrence_v1_{workspace}_{rule}_{stamp}"


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
        self._rules[rule.rule_id] = rule

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
        self._runs[run.run_id] = run
        self._occurrences[key] = run.run_id
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
        for rule in self.store.list_rules(workspace_id):
            if not rule.enabled:
                continue
            scheduled = self._candidate(rule, current_time)
            if scheduled is None:
                continue
            key = occurrence_key(rule.workspace_id, rule.rule_id, scheduled)
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
            if not membership.valid_at(scheduled):
                raise ContractError("expired or not-yet-valid workspace membership")
        existing = self.store.get_run_for_occurrence(
            occurrence_key(rule.workspace_id, rule.rule_id, scheduled), rule.workspace_id
        )
        if existing is not None:
            return existing
        stamp = int(scheduled.timestamp())
        run_id = f"sched_run_{rule.workspace_id}_{rule.rule_id}_{stamp}"
        proposal = ClawNotificationProposal(
            proposal_id=f"prop_{rule.workspace_id}_{rule.rule_id}_{stamp}",
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
            output_id=f"out_{rule.workspace_id}_{rule.rule_id}_{stamp}",
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
    "occurrence_key",
    "parse_cron_expression",
    "resolve_timezone",
]
