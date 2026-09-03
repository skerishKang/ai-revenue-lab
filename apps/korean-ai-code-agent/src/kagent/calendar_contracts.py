from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .connector_trust import ConnectorWriteIntent, ConnectorWriteReceipt
from .contracts import ContractError
from .security import redact_secrets

MAX_CALENDAR_IDS = 32
MAX_ATTENDEES = 50
MAX_RECURRENCE_RULES = 16
MAX_REMINDERS = 8
MAX_SUMMARY_CHARS = 998
MAX_LOCATION_CHARS = 1024
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _safe_ref(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if not _SAFE_REF_RE.fullmatch(normalized):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    if redact_secrets(normalized) != normalized:
        raise ContractError(f"{field_name} must not contain credential material")
    return normalized


def _optional_ref(value: str | None, field_name: str) -> str | None:
    return None if value is None else _safe_ref(value, field_name)


def _bounded_text(value: str, field_name: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be text")
    normalized = redact_secrets(value.strip())
    if len(normalized) > limit:
        raise ContractError(f"{field_name} exceeds {limit} characters")
    return normalized


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fingerprint(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value.strip().lower()):
        raise ContractError(f"{field_name} must be a lowercase SHA-256 digest")
    return value.strip().lower()


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value


def _email(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be text")
    normalized = value.strip()
    if len(normalized) > 320 or normalized.count("@") != 1:
        raise ContractError(f"{field_name} must be a bounded email address")
    local, domain = normalized.rsplit("@", 1)
    if not local or not domain or "." not in domain:
        raise ContractError(f"{field_name} must be a bounded email address")
    return f"{local}@{domain.lower()}"


def _emails(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if len(values) > MAX_ATTENDEES:
        raise ContractError("calendar attendee count exceeds bound")
    normalized = tuple(_email(value, field_name) for value in values)
    if len(normalized) != len(set(normalized)):
        raise ContractError("calendar attendee addresses must be unique")
    return normalized


def _timezone_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 128:
        raise ContractError("time_zone must be a bounded IANA timezone name")
    normalized = value.strip()
    try:
        ZoneInfo(normalized)
    except ZoneInfoNotFoundError as exc:
        raise ContractError("time_zone must be a valid IANA timezone name") from exc
    return normalized


class CalendarCapability(str, Enum):
    READ = "read"
    SUGGEST_TIME = "suggest_time"
    CREATE_EVENT = "create_event"
    UPDATE_EVENT = "update_event"
    DELETE_EVENT = "delete_event"
    RESPOND_TO_EVENT = "respond_to_event"


class CalendarNotificationLevel(str, Enum):
    NONE = "NONE"
    EXTERNAL_ONLY = "EXTERNAL_ONLY"
    ALL = "ALL"

    @property
    def sends_email(self) -> bool:
        return self is not CalendarNotificationLevel.NONE


class CalendarConferencePolicy(str, Enum):
    NONE = "none"
    CREATE_NEW_GOOGLE_MEET = "create_new_google_meet"


class CalendarRecurrenceScope(str, Enum):
    NON_RECURRING = "non_recurring"
    SERIES = "series"
    INSTANCE = "instance"


class CalendarResponseStatus(str, Enum):
    ACCEPTED = "accepted"
    DECLINED = "declined"
    TENTATIVE = "tentative"


@dataclass(frozen=True, slots=True)
class CalendarScopeProjection:
    binding_ref: str
    workspace_ref: str
    allowed_calendar_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_ref", _safe_ref(self.binding_ref, "binding_ref"))
        object.__setattr__(self, "workspace_ref", _safe_ref(self.workspace_ref, "workspace_ref"))
        if not self.allowed_calendar_ids or len(self.allowed_calendar_ids) > MAX_CALENDAR_IDS:
            raise ContractError("calendar scope requires 1..32 explicit calendar ids")
        ids = tuple(_safe_ref(value, "calendar_id") for value in self.allowed_calendar_ids)
        if len(ids) != len(set(ids)):
            raise ContractError("calendar ids must be unique")
        object.__setattr__(self, "allowed_calendar_ids", ids)

    def authorizes(self, *, binding_ref: str, calendar_id: str) -> bool:
        return (
            _safe_ref(binding_ref, "binding_ref") == self.binding_ref
            and _safe_ref(calendar_id, "calendar_id") in self.allowed_calendar_ids
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-calendar-scope.v1",
            "binding_ref": self.binding_ref,
            "workspace_ref": self.workspace_ref,
            "allowed_calendar_ids": list(self.allowed_calendar_ids),
            "whole_account_calendar_access": False,
        }


@dataclass(frozen=True, slots=True)
class CalendarEventTime:
    all_day: bool
    time_zone: str
    start_date: date | None = None
    end_date: date | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.all_day, bool):
            raise ContractError("all_day must be boolean")
        object.__setattr__(self, "time_zone", _timezone_name(self.time_zone))
        if self.all_day:
            if not isinstance(self.start_date, date) or isinstance(self.start_date, datetime):
                raise ContractError("all-day event requires start_date")
            if not isinstance(self.end_date, date) or isinstance(self.end_date, datetime):
                raise ContractError("all-day event requires exclusive end_date")
            if self.start_at is not None or self.end_at is not None:
                raise ContractError("all-day event cannot carry timed boundaries")
            if self.end_date <= self.start_date:
                raise ContractError("all-day end_date must be after start_date")
        else:
            if self.start_date is not None or self.end_date is not None:
                raise ContractError("timed event cannot carry all-day date boundaries")
            start = _aware(self.start_at, "start_at")
            end = _aware(self.end_at, "end_at")
            if end <= start:
                raise ContractError("timed event end_at must be after start_at")
            zone = ZoneInfo(self.time_zone)
            # Require the supplied instants to be representable in the declared zone.
            start.astimezone(zone)
            end.astimezone(zone)

    def canonical_dict(self) -> dict[str, Any]:
        if self.all_day:
            return {
                "all_day": True,
                "time_zone": self.time_zone,
                "start_date": self.start_date.isoformat(),
                "end_date": self.end_date.isoformat(),
            }
        return {
            "all_day": False,
            "time_zone": self.time_zone,
            "start_at": self.start_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "end_at": self.end_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        }


@dataclass(frozen=True, slots=True)
class CalendarRecurrenceTarget:
    scope: CalendarRecurrenceScope
    recurring_event_id: str | None = None
    original_start_key: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.scope, CalendarRecurrenceScope):
            try:
                object.__setattr__(self, "scope", CalendarRecurrenceScope(self.scope))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid recurrence scope") from exc
        object.__setattr__(
            self,
            "recurring_event_id",
            _optional_ref(self.recurring_event_id, "recurring_event_id"),
        )
        object.__setattr__(
            self,
            "original_start_key",
            _optional_ref(self.original_start_key, "original_start_key"),
        )
        if self.scope is CalendarRecurrenceScope.INSTANCE:
            if self.recurring_event_id is None or self.original_start_key is None:
                raise ContractError("recurring instance requires parent id and original start key")
        elif self.recurring_event_id is not None or self.original_start_key is not None:
            raise ContractError("non-instance recurrence target cannot carry instance identity")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope.value,
            "recurring_event_id": self.recurring_event_id,
            "original_start_key": self.original_start_key,
        }


@dataclass(frozen=True, slots=True)
class CalendarReminder:
    method: str
    minutes: int

    def __post_init__(self) -> None:
        method = _bounded_text(self.method, "reminder method", 32).lower()
        if method not in {"email", "popup"}:
            raise ContractError("unsupported calendar reminder method")
        object.__setattr__(self, "method", method)
        if isinstance(self.minutes, bool) or not isinstance(self.minutes, int) or not 0 <= self.minutes <= 40_320:
            raise ContractError("reminder minutes must be between 0 and 40320")

    def canonical_dict(self) -> dict[str, Any]:
        return {"method": self.method, "minutes": self.minutes}


@dataclass(frozen=True, slots=True)
class CalendarEventProjection:
    calendar_id: str
    event_id: str
    etag: str
    summary: str
    description: str
    location: str
    organizer_email: str
    attendee_emails: tuple[str, ...]
    event_time: CalendarEventTime
    recurrence_rules: tuple[str, ...]
    recurrence_target: CalendarRecurrenceTarget
    status: str
    updated_at: datetime
    sequence: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "calendar_id", _safe_ref(self.calendar_id, "calendar_id"))
        object.__setattr__(self, "event_id", _safe_ref(self.event_id, "event_id"))
        etag = _bounded_text(self.etag, "etag", 512)
        if not etag:
            raise ContractError("event etag is required")
        object.__setattr__(self, "etag", etag)
        object.__setattr__(self, "summary", _bounded_text(self.summary, "summary", MAX_SUMMARY_CHARS))
        object.__setattr__(self, "description", _bounded_text(self.description, "description", 20_000))
        object.__setattr__(self, "location", _bounded_text(self.location, "location", MAX_LOCATION_CHARS))
        object.__setattr__(self, "organizer_email", _email(self.organizer_email, "organizer_email"))
        object.__setattr__(self, "attendee_emails", _emails(self.attendee_emails, "attendee_email"))
        if not isinstance(self.event_time, CalendarEventTime):
            raise ContractError("event_time must be CalendarEventTime")
        rules = tuple(_bounded_text(rule, "recurrence rule", 2048) for rule in self.recurrence_rules)
        if len(rules) > MAX_RECURRENCE_RULES:
            raise ContractError("recurrence rule count exceeds bound")
        object.__setattr__(self, "recurrence_rules", rules)
        if not isinstance(self.recurrence_target, CalendarRecurrenceTarget):
            raise ContractError("recurrence_target must be CalendarRecurrenceTarget")
        object.__setattr__(self, "status", _bounded_text(self.status, "status", 64))
        object.__setattr__(self, "updated_at", _aware(self.updated_at, "updated_at").astimezone(timezone.utc))
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 0:
            raise ContractError("sequence must be a non-negative integer")

    @property
    def etag_sha256(self) -> str:
        return _sha256_text(self.etag)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "calendar_id": self.calendar_id,
            "event_id": self.event_id,
            "etag_sha256": self.etag_sha256,
            "summary": self.summary,
            "description": self.description,
            "location": self.location,
            "organizer_email": self.organizer_email,
            "attendee_emails": list(self.attendee_emails),
            "event_time": self.event_time.canonical_dict(),
            "recurrence_rules": list(self.recurrence_rules),
            "recurrence_target": self.recurrence_target.canonical_dict(),
            "status": self.status,
            "updated_at": self.updated_at.isoformat().replace("+00:00", "Z"),
            "sequence": self.sequence,
            "event_content_trusted": False,
            "raw_etag_exposed_to_model": False,
        }


@dataclass(frozen=True, slots=True)
class CalendarMutationMaterial:
    binding_ref: str
    workspace_ref: str
    operation: CalendarCapability
    calendar_id: str
    summary: str
    description_sha256: str
    location: str
    attendee_emails: tuple[str, ...]
    event_time: CalendarEventTime
    recurrence_target: CalendarRecurrenceTarget
    recurrence_rules: tuple[str, ...] = ()
    reminders: tuple[CalendarReminder, ...] = ()
    conference_policy: CalendarConferencePolicy = CalendarConferencePolicy.NONE
    notification_level: CalendarNotificationLevel = CalendarNotificationLevel.NONE
    event_id: str | None = None
    expected_etag_sha256: str | None = None
    response_status: CalendarResponseStatus | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_ref", _safe_ref(self.binding_ref, "binding_ref"))
        object.__setattr__(self, "workspace_ref", _safe_ref(self.workspace_ref, "workspace_ref"))
        if not isinstance(self.operation, CalendarCapability):
            try:
                object.__setattr__(self, "operation", CalendarCapability(self.operation))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Calendar operation") from exc
        if self.operation not in {
            CalendarCapability.CREATE_EVENT,
            CalendarCapability.UPDATE_EVENT,
            CalendarCapability.DELETE_EVENT,
            CalendarCapability.RESPOND_TO_EVENT,
        }:
            raise ContractError("mutation material requires a Calendar write capability")
        object.__setattr__(self, "calendar_id", _safe_ref(self.calendar_id, "calendar_id"))
        object.__setattr__(self, "summary", _bounded_text(self.summary, "summary", MAX_SUMMARY_CHARS))
        object.__setattr__(self, "description_sha256", _fingerprint(self.description_sha256, "description_sha256"))
        object.__setattr__(self, "location", _bounded_text(self.location, "location", MAX_LOCATION_CHARS))
        object.__setattr__(self, "attendee_emails", _emails(self.attendee_emails, "attendee_email"))
        if not isinstance(self.event_time, CalendarEventTime):
            raise ContractError("event_time must be CalendarEventTime")
        if not isinstance(self.recurrence_target, CalendarRecurrenceTarget):
            raise ContractError("recurrence_target must be CalendarRecurrenceTarget")
        rules = tuple(_bounded_text(rule, "recurrence rule", 2048) for rule in self.recurrence_rules)
        if len(rules) > MAX_RECURRENCE_RULES:
            raise ContractError("recurrence rule count exceeds bound")
        object.__setattr__(self, "recurrence_rules", rules)
        if len(self.reminders) > MAX_REMINDERS or any(not isinstance(item, CalendarReminder) for item in self.reminders):
            raise ContractError("calendar reminders exceed bounded contract")
        if not isinstance(self.conference_policy, CalendarConferencePolicy):
            object.__setattr__(self, "conference_policy", CalendarConferencePolicy(self.conference_policy))
        if not isinstance(self.notification_level, CalendarNotificationLevel):
            object.__setattr__(self, "notification_level", CalendarNotificationLevel(self.notification_level))
        object.__setattr__(self, "event_id", _optional_ref(self.event_id, "event_id"))
        if self.expected_etag_sha256 is not None:
            object.__setattr__(
                self,
                "expected_etag_sha256",
                _fingerprint(self.expected_etag_sha256, "expected_etag_sha256"),
            )
        if self.response_status is not None and not isinstance(self.response_status, CalendarResponseStatus):
            object.__setattr__(self, "response_status", CalendarResponseStatus(self.response_status))

        if self.operation is CalendarCapability.CREATE_EVENT:
            if self.event_id is not None or self.expected_etag_sha256 is not None:
                raise ContractError("create_event cannot carry existing event/etag identity")
            if self.recurrence_target.scope is CalendarRecurrenceScope.INSTANCE:
                raise ContractError("create_event cannot target an existing recurrence instance")
            if self.response_status is not None:
                raise ContractError("create_event cannot carry response status")
        else:
            if self.event_id is None or self.expected_etag_sha256 is None:
                raise ContractError("existing-event mutation requires event id and expected etag hash")
            if self.operation is CalendarCapability.RESPOND_TO_EVENT:
                if self.response_status is None:
                    raise ContractError("respond_to_event requires response status")
            elif self.response_status is not None:
                raise ContractError("response status is only valid for respond_to_event")

    @property
    def attendee_notification_side_effect(self) -> bool:
        return bool(self.attendee_emails) and self.notification_level.sends_email

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "binding_ref": self.binding_ref,
            "workspace_ref": self.workspace_ref,
            "operation": self.operation.value,
            "calendar_id": self.calendar_id,
            "event_id": self.event_id,
            "expected_etag_sha256": self.expected_etag_sha256,
            "summary": self.summary,
            "description_sha256": self.description_sha256,
            "location": self.location,
            "attendee_emails": sorted(self.attendee_emails),
            "event_time": self.event_time.canonical_dict(),
            "recurrence_target": self.recurrence_target.canonical_dict(),
            "recurrence_rules": sorted(self.recurrence_rules),
            "reminders": sorted(
                (item.canonical_dict() for item in self.reminders),
                key=lambda item: (item["method"], item["minutes"]),
            ),
            "conference_policy": self.conference_policy.value,
            "notification_level": self.notification_level.value,
            "attendee_notification_side_effect": self.attendee_notification_side_effect,
            "response_status": self.response_status.value if self.response_status else None,
        }

    @property
    def material_fingerprint(self) -> str:
        encoded = json.dumps(
            self.canonical_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def target_ref(self) -> str:
        if self.event_id is None:
            return f"calendar:{self.calendar_id}:new"
        return f"calendar:{self.calendar_id}:event:{self.event_id}"

    @property
    def version_ref(self) -> str:
        if self.expected_etag_sha256 is None:
            return f"calendar-create:{self.material_fingerprint}"
        return f"calendar-etag:{self.expected_etag_sha256}"


@dataclass(frozen=True, slots=True)
class CalendarMutationApproval:
    approval_ref: str
    evidence_ref: str
    material_fingerprint: str
    approved_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "approval_ref", _safe_ref(self.approval_ref, "approval_ref"))
        object.__setattr__(self, "evidence_ref", _safe_ref(self.evidence_ref, "evidence_ref"))
        object.__setattr__(
            self, "material_fingerprint", _fingerprint(self.material_fingerprint, "material_fingerprint")
        )
        object.__setattr__(self, "approved_at", _aware(self.approved_at, "approved_at").astimezone(timezone.utc))


class CalendarMutationPreflightDecision(str, Enum):
    ALLOW = "allow"
    OUT_OF_SCOPE = "out_of_scope"
    WRONG_CONNECTOR_OR_TOOL = "wrong_connector_or_tool"
    TARGET_MISMATCH = "target_mismatch"
    APPROVAL_MISMATCH = "approval_mismatch"
    MATERIAL_CHANGED = "material_changed"
    VERSION_BINDING_MISMATCH = "version_binding_mismatch"
    STALE_ETAG = "stale_etag"


def calendar_mutation_preflight(
    *,
    scope: CalendarScopeProjection,
    material: CalendarMutationMaterial,
    approval: CalendarMutationApproval,
    intent: ConnectorWriteIntent,
    current_event: CalendarEventProjection | None = None,
) -> CalendarMutationPreflightDecision:
    if not all(
        [
            isinstance(scope, CalendarScopeProjection),
            isinstance(material, CalendarMutationMaterial),
            isinstance(approval, CalendarMutationApproval),
            isinstance(intent, ConnectorWriteIntent),
        ]
    ):
        raise ContractError("invalid calendar mutation preflight contract")
    if not scope.authorizes(binding_ref=material.binding_ref, calendar_id=material.calendar_id):
        return CalendarMutationPreflightDecision.OUT_OF_SCOPE
    if intent.connector_id != "google-calendar" or intent.tool_name != material.operation.value:
        return CalendarMutationPreflightDecision.WRONG_CONNECTOR_OR_TOOL
    if intent.binding_ref != material.binding_ref or intent.target_ref != material.target_ref:
        return CalendarMutationPreflightDecision.TARGET_MISMATCH
    if intent.approval_ref != approval.approval_ref or intent.evidence_ref != approval.evidence_ref:
        return CalendarMutationPreflightDecision.APPROVAL_MISMATCH
    if material.material_fingerprint != approval.material_fingerprint:
        return CalendarMutationPreflightDecision.MATERIAL_CHANGED
    if intent.payload_fingerprint != material.material_fingerprint:
        return CalendarMutationPreflightDecision.MATERIAL_CHANGED
    if intent.expected_version_ref != material.version_ref:
        return CalendarMutationPreflightDecision.VERSION_BINDING_MISMATCH

    if material.operation is not CalendarCapability.CREATE_EVENT:
        if not isinstance(current_event, CalendarEventProjection):
            return CalendarMutationPreflightDecision.STALE_ETAG
        if current_event.calendar_id != material.calendar_id or current_event.event_id != material.event_id:
            return CalendarMutationPreflightDecision.TARGET_MISMATCH
        if current_event.etag_sha256 != material.expected_etag_sha256:
            return CalendarMutationPreflightDecision.STALE_ETAG
    return CalendarMutationPreflightDecision.ALLOW


@dataclass(frozen=True, slots=True)
class CalendarMutationReceipt:
    connector_receipt: ConnectorWriteReceipt
    operation: CalendarCapability
    calendar_id: str
    event_id: str
    result_etag_sha256: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.connector_receipt, ConnectorWriteReceipt):
            raise ContractError("connector_receipt must be ConnectorWriteReceipt")
        if self.connector_receipt.connector_id != "google-calendar":
            raise ContractError("Calendar receipt requires google-calendar connector receipt")
        if not isinstance(self.operation, CalendarCapability) or self.operation not in {
            CalendarCapability.CREATE_EVENT,
            CalendarCapability.UPDATE_EVENT,
            CalendarCapability.DELETE_EVENT,
            CalendarCapability.RESPOND_TO_EVENT,
        }:
            raise ContractError("invalid Calendar receipt operation")
        object.__setattr__(self, "calendar_id", _safe_ref(self.calendar_id, "calendar_id"))
        object.__setattr__(self, "event_id", _safe_ref(self.event_id, "event_id"))
        if self.result_etag_sha256 is not None:
            object.__setattr__(
                self,
                "result_etag_sha256",
                _fingerprint(self.result_etag_sha256, "result_etag_sha256"),
            )
        if self.operation is CalendarCapability.DELETE_EVENT:
            if self.result_etag_sha256 is not None:
                raise ContractError("delete receipt must not invent a returned event etag")
        elif self.result_etag_sha256 is None:
            raise ContractError("non-delete Calendar receipt requires returned event etag evidence")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "connector_receipt": self.connector_receipt.safe_dict(),
            "operation": self.operation.value,
            "calendar_id": self.calendar_id,
            "event_id": self.event_id,
            "result_etag_sha256": self.result_etag_sha256,
            "trusted_provider_receipt": True,
            "model_text_counts_as_mutation_success": False,
        }


CALENDAR_MCP_DEVELOPER_PREVIEW = True
CALENDAR_REST_IF_MATCH_SUPPORTED = True
CALENDAR_MCP_ETAG_IF_MATCH_ATOMICITY_VERIFIED = False
CALENDAR_EVENT_CONTENT_TRUSTED = False
CALENDAR_MUTATION_REQUIRES_P01_APPROVAL = True
CALENDAR_HIDDEN_NOTIFICATION_DEFAULT_ALLOWED = False
REAL_GOOGLE_CALENDAR_OAUTH_CONFIGURED = False
REAL_GOOGLE_CALENDAR_MUTATION_CONFIGURED = False
