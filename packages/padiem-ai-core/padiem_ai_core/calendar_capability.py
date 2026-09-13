"""Promoted Google Calendar READ capability contract (#2358, parent #2010).

Canonical Padiem AI Core product-neutral calendar contract alongside Gmail,
Drive, Telegram and Slack. Core owns no HTTP, no Google OAuth token and no
provider client: the host application supplies a trusted
:class:`CalendarReadPort` (the Engine reuses the existing Google OAuth
authority already used by Gmail — no second OAuth stack is introduced here).
Core only shapes bounded, untrusted JSON projections with explicit identity,
server-derived account/calendar scope, timezone semantics, all-day versus
timed event handling, recurrence series/instance identity and a bounded
normalized event projection.

Fail-closed rules for this contract:

* only the four promoted READ tool ids (and their canonical ids) classify as
  READ; every unknown or future Calendar tool id — including events.insert,
  events.update, events.patch, events.delete, events.move, events.import,
  events.watch, calendars.insert and ACL mutations, which are NOT registered
  in Core — classifies as ``WRITE_OR_MATERIAL`` or ``UNKNOWN`` and never
  receives a READ grant;
* the official Google Calendar API (``www.googleapis.com``) is the only
  supported transport; calendar access is limited to the server-derived
  account/calendar allowlist resolved outside Core, and a connected account
  never implies whole-account calendar access;
* recurrence identity is preserved as bounded ids only (event id, series id,
  instance-of-series flag); raw RRULE expansion is never performed in Core;
* the raw Google OAuth token never appears in Core types, projections, grants
  or error messages.

This module is deterministic and network-free. It performs zero provider
calls on its own: every provider read goes through the injected trusted port.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
import inspect
import json
import re
from typing import Any, Awaitable, Mapping, Protocol

from .connector_registry import ConnectorDescriptor
from .contracts import ApprovalPolicy, ToolSideEffect, ToolSpec
from .tool_runtime import MAX_TOOL_OUTPUT_BYTES, ToolHandler, ToolRuntime


class CalendarContractError(ValueError):
    """Safe Calendar projection contract failure."""


CALENDAR_CONNECTOR_ID = "connector:google:calendar@1"

# Core ToolSpec auth-scope tokens.
CALENDAR_READONLY_AUTH_SCOPE = "calendar.readonly"

# Recorded as contract evidence only: no create/update/delete/respond tool is
# registered in Core, so this scope is never requested by this contract.
CALENDAR_WRITE_AUTH_SCOPE = "calendar.write"

# Provider OAuth scope recorded as evidence only. The Engine port reuses the
# existing single Google OAuth authority (same client/refresh-token secrets as
# Gmail) with the readonly calendar scope; Core never handles OAuth strings.
GOOGLE_CALENDAR_READONLY_OAUTH_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"

GOOGLE_CALENDAR_API_HOST = "www.googleapis.com"
GOOGLE_CALENDAR_BASE_URL = "https://www.googleapis.com/calendar/v3"

REQUEST_TIMEOUT_SECONDS = 30

# Core-side output bounds (analogous to the Gmail/Drive/Telegram/Slack promotions).
MAX_PROVIDER_METADATA_BYTES = 128_000
MAX_NAME_CHARS = 512
MAX_CALENDARS = 128
MAX_CALENDAR_EVENT_SUMMARY_CHARS = 2_000
MAX_CALENDAR_PROJECTION_ITEMS = 100

CALENDAR_LIST_CALENDARS_TOOL_ID = "calendar.list_calendars"
CALENDAR_GET_CALENDAR_TOOL_ID = "calendar.get_calendar"
CALENDAR_LIST_EVENTS_TOOL_ID = "calendar.list_events"
CALENDAR_GET_EVENT_TOOL_ID = "calendar.get_event"

CALENDAR_READ_TOOL_IDS = (
    CALENDAR_LIST_CALENDARS_TOOL_ID,
    CALENDAR_GET_CALENDAR_TOOL_ID,
    CALENDAR_LIST_EVENTS_TOOL_ID,
    CALENDAR_GET_EVENT_TOOL_ID,
)

CALENDAR_CANONICAL_TOOL_IDS = (
    "tool:google:calendar.list@1",
    "tool:google:calendar.get@1",
    "tool:google:calendar.event_list@1",
    "tool:google:calendar.event_get@1",
)

# Review-state mirrors, kept fail-closed.
CALENDAR_REGISTERED_APP_REQUIRED = True
CALENDAR_STATIC_READ_TOOL_ALLOWLIST_CONFIGURED = False
CALENDAR_LIVE_TOOLS_LIST_REQUIRED_FOR_READ_CLASSIFICATION = True
CALENDAR_UNKNOWN_MCP_TOOL_FAILS_CLOSED = True
CALENDAR_RAW_OAUTH_TOKEN_IN_CORE = False
CALENDAR_SECOND_GOOGLE_OAUTH_STACK = False
CALENDAR_WRITE_TOOLS_PRESENT = False
CALENDAR_LIVE_PROVIDER_CALLS = 0
CALENDAR_PRODUCTION_WRITE_AUTHORITY_MINTED = False
CALENDAR_AUTONOMOUS_EVENT_CREATION_SUPPORTED = False
CALENDAR_PRODUCTION_ACTIVATION = False


class CalendarReadPort(Protocol):
    """Trusted Google Calendar API HTTP boundary.

    Callers pass only connector binding + actor refs and the exact readonly
    auth-scope requirement. ``path`` is a bare Calendar API v3 path such as
    ``/users/me/calendarList`` or ``/calendars/<calendarId>/events``; the
    implementation injects the OAuth bearer as a transport-only credential
    outside Core state, enforces the server-derived account/calendar scope,
    sanitizes every provider exception, enforces the response byte bound, and
    returns decoded provider JSON. Implementations may be sync or async; Core
    awaits when needed. Core never implements this port.
    """

    def get_json(
        self,
        *,
        binding_ref: str,
        actor_ref: str,
        required_scopes: tuple[str, ...],
        base_url: str,
        path: str,
        query: dict[str, str],
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> dict[str, Any] | Awaitable[dict[str, Any]]:
        ...


def calendar_read_tool_specs() -> tuple[ToolSpec, ...]:
    """READ-only ToolSpecs for the promoted Calendar surface."""

    return (
        ToolSpec(
            id=CALENDAR_LIST_CALENDARS_TOOL_ID,
            title="Google Calendar list calendars",
            description=(
                "List bounded metadata for the server-derived allowed "
                "calendars of the connected Google account only: calendar id, "
                "name and timezone. Whole-account dumps are never returned "
                "and no event content is included."
            ),
            owner="core",
            side_effect=ToolSideEffect.READ,
            approval_policy=ApprovalPolicy.NOT_REQUIRED,
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            auth_scope=(CALENDAR_READONLY_AUTH_SCOPE,),
            timeout_seconds=30.0,
        ),
        ToolSpec(
            id=CALENDAR_GET_CALENDAR_TOOL_ID,
            title="Google Calendar get calendar",
            description=(
                "Read bounded metadata for one server-derived allowed "
                "calendar: id, name and timezone. Calendars outside the "
                "allowlist are never readable."
            ),
            owner="core",
            side_effect=ToolSideEffect.READ,
            approval_policy=ApprovalPolicy.NOT_REQUIRED,
            input_schema={
                "type": "object",
                "properties": {
                    "calendarId": {
                        "type": "string",
                        "description": "Google Calendar id to inspect.",
                    },
                },
                "required": ["calendarId"],
                "additionalProperties": False,
            },
            auth_scope=(CALENDAR_READONLY_AUTH_SCOPE,),
            timeout_seconds=30.0,
        ),
        ToolSpec(
            id=CALENDAR_LIST_EVENTS_TOOL_ID,
            title="Google Calendar list events",
            description=(
                "Read a bounded window of normalized event metadata for one "
                "allowed calendar. The window is explicit RFC 3339 timeMin/"
                "timeMax bounds; all-day and timed events are distinguished, "
                "recurrence series/instance identity is preserved, and "
                "attendee emails, descriptions and links are never returned."
            ),
            owner="core",
            side_effect=ToolSideEffect.READ,
            approval_policy=ApprovalPolicy.NOT_REQUIRED,
            input_schema={
                "type": "object",
                "properties": {
                    "calendarId": {
                        "type": "string",
                        "description": "Google Calendar id to read.",
                    },
                    "timeMin": {
                        "type": "string",
                        "description": "RFC 3339 inclusive lower bound (UTC offset required).",
                    },
                    "timeMax": {
                        "type": "string",
                        "description": "RFC 3339 exclusive upper bound (UTC offset required).",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "description": "Bounded page size (1..100).",
                    },
                },
                "required": ["calendarId", "timeMin", "timeMax"],
                "additionalProperties": False,
            },
            auth_scope=(CALENDAR_READONLY_AUTH_SCOPE,),
            timeout_seconds=30.0,
        ),
        ToolSpec(
            id=CALENDAR_GET_EVENT_TOOL_ID,
            title="Google Calendar get event",
            description=(
                "Read one normalized bounded event projection for one "
                "server-derived allowed calendar. Calendars outside the "
                "allowlist are never readable."
            ),
            owner="core",
            side_effect=ToolSideEffect.READ,
            approval_policy=ApprovalPolicy.NOT_REQUIRED,
            input_schema={
                "type": "object",
                "properties": {
                    "calendarId": {
                        "type": "string",
                        "description": "Google Calendar id containing the event.",
                    },
                    "eventId": {
                        "type": "string",
                        "description": "Google Calendar event id to read.",
                    },
                },
                "required": ["calendarId", "eventId"],
                "additionalProperties": False,
            },
            auth_scope=(CALENDAR_READONLY_AUTH_SCOPE,),
            timeout_seconds=30.0,
        ),
    )


CALENDAR_DESCRIPTOR = ConnectorDescriptor(
    connector_id=CALENDAR_CONNECTOR_ID,
    title="Google Calendar",
    canonical_tool_ids=CALENDAR_CANONICAL_TOOL_IDS,
    requires_authorization=True,
)


# --- bounded validation helpers ---

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
# Calendar ids are emails or structured ids such as
# "en.usa#holiday@group.v.calendar.google.com"; "/" is never allowed so an id
# can never escape its URL path segment.
_CALENDAR_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._%+@\-]{0,511}$")
_EVENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,255}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)
_TIMEZONE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_./+\-]{0,63}$")
_EVENT_STATUSES = ("confirmed", "tentative", "cancelled")


def _safe_ref(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise CalendarContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if not _SAFE_REF_RE.fullmatch(normalized):
        raise CalendarContractError(f"{field_name} must be a bounded safe reference")
    return normalized


def _bounded_text(value: Any, field_name: str, limit: int) -> str:
    if not isinstance(value, str):
        raise CalendarContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if len(normalized) > limit:
        raise CalendarContractError(f"{field_name} exceeds {limit} characters")
    return normalized


def _provider_id(value: Any, field_name: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str):
        raise CalendarContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if not pattern.fullmatch(normalized):
        raise CalendarContractError(f"{field_name} must be a bounded provider identifier")
    return normalized


def _calendar_id_value(value: Any, field_name: str = "calendar_id") -> str:
    return _provider_id(value, field_name, _CALENDAR_ID_RE)


def _event_id_value(value: Any, field_name: str = "event_id") -> str:
    return _provider_id(value, field_name, _EVENT_ID_RE)


def _boolean(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise CalendarContractError(f"{field_name} must be boolean")
    return value


def _timezone_value(value: Any, field_name: str = "time_zone") -> str:
    return _provider_id(value, field_name, _TIMEZONE_RE)


def _rfc3339_value(value: Any, field_name: str) -> str:
    return _provider_id(value, field_name, _RFC3339_RE)


def _parse_rfc3339(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(normalized)


def _require_ordered_window(time_min: str, time_max: str) -> None:
    try:
        lower = _parse_rfc3339(time_min)
        upper = _parse_rfc3339(time_max)
    except ValueError:
        raise CalendarContractError("event window bounds must be valid timestamps") from None
    if lower.tzinfo is None or upper.tzinfo is None:
        raise CalendarContractError("event window bounds must carry a UTC offset")
    if lower.utcoffset() is None or upper.utcoffset() is None:
        raise CalendarContractError("event window bounds must carry a UTC offset")
    if upper <= lower:
        raise CalendarContractError("timeMax must be after timeMin")


class CalendarCapability(str, Enum):
    """Explicit Calendar capability classes (READ + unregistered write set)."""

    READ = "read"
    CREATE_EVENT = "create_event"
    UPDATE_EVENT = "update_event"
    DELETE_EVENT = "delete_event"
    CANCEL_EVENT = "cancel_event"
    RESPOND_TO_EVENT = "respond_to_event"
    ATTENDEE_MUTATION = "attendee_mutation"
    REMINDER_MUTATION = "reminder_mutation"
    CONFERENCE_MUTATION = "conference_mutation"


_WRITE_CAPABILITIES = (
    CalendarCapability.CREATE_EVENT,
    CalendarCapability.UPDATE_EVENT,
    CalendarCapability.DELETE_EVENT,
    CalendarCapability.CANCEL_EVENT,
    CalendarCapability.RESPOND_TO_EVENT,
    CalendarCapability.ATTENDEE_MUTATION,
    CalendarCapability.REMINDER_MUTATION,
    CalendarCapability.CONFERENCE_MUTATION,
)


class CalendarCapabilityClassification(str, Enum):
    """Fail-closed classification result for an unclassified Calendar tool id."""

    READ = "read"
    WRITE_OR_MATERIAL = "write_or_material"
    UNKNOWN = "unknown"


_WRITE_HINT_TOKENS = (
    "create",
    "insert",
    "update",
    "patch",
    "delete",
    "remove",
    "cancel",
    "respond",
    "accept",
    "decline",
    "tentative",
    "attendee",
    "reminder",
    "conference",
    "move",
    "import",
    "watch",
    "clear",
    "send",
    "upload",
    "acl",
    "set",
)


def classify_calendar_tool_id(tool_id: str) -> CalendarCapabilityClassification:
    """Classify a Calendar tool id; everything unregistered fails closed."""

    if not isinstance(tool_id, str) or not tool_id.strip():
        raise CalendarContractError("tool_id must be a non-empty string")
    normalized = tool_id.strip()
    if not _SAFE_ID_RE.fullmatch(normalized):
        raise CalendarContractError("tool_id must be a bounded safe identifier")
    if normalized in CALENDAR_READ_TOOL_IDS or normalized in CALENDAR_CANONICAL_TOOL_IDS:
        return CalendarCapabilityClassification.READ
    lowered = normalized.lower()
    if any(token in lowered for token in _WRITE_HINT_TOKENS):
        return CalendarCapabilityClassification.WRITE_OR_MATERIAL
    return CalendarCapabilityClassification.UNKNOWN


def core_auth_scopes_for_capability(capability: CalendarCapability) -> tuple[str, ...]:
    """Bounded Core auth-scope tokens required by a capability."""

    if not isinstance(capability, CalendarCapability):
        raise CalendarContractError("capability must be CalendarCapability")
    if capability is CalendarCapability.READ:
        return (CALENDAR_READONLY_AUTH_SCOPE,)
    if capability in _WRITE_CAPABILITIES:
        # Recorded as contract evidence only: no write tool is registered in
        # Core, so this scope is never requested by this contract.
        return (CALENDAR_WRITE_AUTH_SCOPE,)
    raise CalendarContractError("unsupported Calendar capability")


def capability_requires_write_approval(capability: CalendarCapability) -> bool:
    """Whether a capability requires durable write-approval semantics.

    READ never requires approval. Every event/calendar mutation requires an
    approval authority that this contract never mints.
    """

    if not isinstance(capability, CalendarCapability):
        raise CalendarContractError("capability must be CalendarCapability")
    return capability in _WRITE_CAPABILITIES


@dataclass(frozen=True, slots=True)
class CalendarScope:
    """Bounded server-derived account/calendar scope.

    ``allowed_calendar_ids`` is a non-empty explicit allowlist (1..128): a
    connected Google account never implies whole-account calendar access.
    ``default_timezone`` is the server-derived IANA timezone used only as
    contract evidence; per-event timezone semantics come from the provider
    projection itself. This value is resolved server-side only; caller or
    model payloads can never mint or widen it.
    """

    binding_ref: str
    account_ref: str
    allowed_calendar_ids: tuple[str, ...]
    default_timezone: str = "UTC"

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_ref", _safe_ref(self.binding_ref, "binding_ref"))
        object.__setattr__(self, "account_ref", _calendar_id_value(self.account_ref, "account_ref"))
        if not self.allowed_calendar_ids or len(self.allowed_calendar_ids) > MAX_CALENDARS:
            raise CalendarContractError("Calendar scope requires 1..128 explicit calendars")
        calendars = tuple(
            _calendar_id_value(value, "calendar_id") for value in self.allowed_calendar_ids
        )
        if len(calendars) != len(set(calendars)):
            raise CalendarContractError("Calendar ids must be unique")
        object.__setattr__(self, "allowed_calendar_ids", calendars)
        object.__setattr__(self, "default_timezone", _timezone_value(self.default_timezone))

    def authorizes(self, *, calendar_id: str) -> bool:
        calendar = _calendar_id_value(calendar_id)
        return calendar in self.allowed_calendar_ids

    def safe_dict(self) -> dict[str, object]:
        return {
            "contract_version": "padiem-calendar-scope.v1",
            "binding_ref": self.binding_ref,
            "account_ref": self.account_ref,
            "allowed_calendar_ids": list(self.allowed_calendar_ids),
            "default_timezone": self.default_timezone,
            "account_connection_implies_all_calendars": False,
            "oauth_token_present": False,
        }


@dataclass(frozen=True, slots=True)
class CalendarCapabilityGrant:
    """One bounded capability grant fact for a connector binding.

    ``granted_capabilities`` carries only explicit capability values resolved
    server-side from grant references; it is never derived from caller JSON.
    The raw OAuth token can never appear here — the grant carries capability
    facts only.
    """

    connector_id: str
    binding_ref: str
    granted_capabilities: tuple[CalendarCapability, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.connector_id, str) or not _SAFE_ID_RE.fullmatch(
            self.connector_id.strip()
        ):
            raise CalendarContractError("connector_id must be a bounded safe identifier")
        if not isinstance(self.binding_ref, str) or not _SAFE_ID_RE.fullmatch(
            self.binding_ref.strip()
        ):
            raise CalendarContractError("binding_ref must be a bounded safe identifier")
        if not isinstance(self.granted_capabilities, tuple) or any(
            not isinstance(item, CalendarCapability) for item in self.granted_capabilities
        ):
            raise CalendarContractError(
                "granted_capabilities must contain CalendarCapability values"
            )
        if len(self.granted_capabilities) != len(set(self.granted_capabilities)):
            raise CalendarContractError("granted_capabilities must be unique")

    def allows(self, capability: CalendarCapability) -> bool:
        if not isinstance(capability, CalendarCapability):
            raise CalendarContractError("capability must be CalendarCapability")
        return capability in self.granted_capabilities

    def write_authority(self) -> bool:
        """Whether this grant carries any Calendar mutation authority."""

        return any(self.allows(capability) for capability in _WRITE_CAPABILITIES)

    def safe_dict(self) -> dict[str, object]:
        return {
            "connector_id": self.connector_id,
            "binding_ref": self.binding_ref,
            "granted_capabilities": sorted(item.value for item in self.granted_capabilities),
            "write_authority": self.write_authority(),
            "oauth_token_present": False,
            "raw_credentials_present": False,
            "mints_approval_authority": False,
        }


@dataclass(frozen=True, slots=True)
class CalendarInfo:
    """Bounded metadata projection for one server-derived allowed calendar."""

    calendar_id: str
    name: str
    time_zone: str = "UTC"

    def __post_init__(self) -> None:
        object.__setattr__(self, "calendar_id", _calendar_id_value(self.calendar_id))
        object.__setattr__(self, "name", _bounded_text(self.name, "name", MAX_NAME_CHARS))
        object.__setattr__(self, "time_zone", _timezone_value(self.time_zone))

    def safe_dict(self) -> dict[str, object]:
        return {
            "calendar_id": self.calendar_id,
            "name": self.name,
            "time_zone": self.time_zone,
            "event_content_present": False,
            "oauth_token_present": False,
        }


@dataclass(frozen=True, slots=True)
class CalendarEventInfo:
    """Bounded normalized projection for one event instance.

    All-day events carry provider dates only; timed events carry an RFC 3339
    timestamp plus its IANA timezone. Recurrence identity is preserved as
    bounded ids (event id, series id, instance flag) without RRULE expansion.
    Attendee emails, descriptions, attachments and links are never projected.
    """

    calendar_id: str
    event_id: str
    series_id: str
    instance_of_series: bool
    status: str
    summary: str
    all_day: bool
    start: str
    end: str
    start_time_zone: str | None = None
    end_time_zone: str | None = None
    attendee_count: int = 0
    organizer_present: bool = False
    conference_present: bool = False
    recurrence_rule_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "calendar_id", _calendar_id_value(self.calendar_id))
        object.__setattr__(self, "event_id", _event_id_value(self.event_id))
        object.__setattr__(self, "series_id", _event_id_value(self.series_id, "series_id"))
        object.__setattr__(self, "instance_of_series", _boolean(self.instance_of_series, "instance_of_series"))
        if self.status not in _EVENT_STATUSES:
            raise CalendarContractError("event status must be a known Calendar status")
        object.__setattr__(self, "summary", _bounded_text(self.summary, "summary", MAX_CALENDAR_EVENT_SUMMARY_CHARS))
        object.__setattr__(self, "all_day", _boolean(self.all_day, "all_day"))
        if self.all_day:
            if self.start_time_zone is not None or self.end_time_zone is not None:
                raise CalendarContractError("all-day events must not carry a time zone")
            object.__setattr__(self, "start", _provider_id(self.start, "start", _DATE_RE))
            object.__setattr__(self, "end", _provider_id(self.end, "end", _DATE_RE))
        else:
            object.__setattr__(self, "start", _rfc3339_value(self.start, "start"))
            object.__setattr__(self, "end", _rfc3339_value(self.end, "end"))
            for field_name in ("start_time_zone", "end_time_zone"):
                value = getattr(self, field_name)
                if value is not None:
                    object.__setattr__(self, field_name, _timezone_value(value, field_name))
        for field_name in ("attendee_count", "recurrence_rule_count"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise CalendarContractError(f"{field_name} must be a non-negative integer")
        object.__setattr__(self, "organizer_present", _boolean(self.organizer_present, "organizer_present"))
        object.__setattr__(self, "conference_present", _boolean(self.conference_present, "conference_present"))

    @property
    def event_kind(self) -> str:
        return "all_day" if self.all_day else "timed"

    def safe_dict(self) -> dict[str, object]:
        return {
            "calendar_id": self.calendar_id,
            "event_id": self.event_id,
            "series_id": self.series_id,
            "instance_of_series": self.instance_of_series,
            "event_kind": self.event_kind,
            "status": self.status,
            "summary": self.summary,
            "start": self.start,
            "end": self.end,
            "start_time_zone": self.start_time_zone,
            "end_time_zone": self.end_time_zone,
            "attendee_count": self.attendee_count,
            "organizer_present": self.organizer_present,
            "conference_present": self.conference_present,
            "recurrence_rule_count": self.recurrence_rule_count,
            "event_content_trusted": False,
            "description_present": False,
            "attendee_emails_present": False,
            "attachment_or_link_present": False,
            "oauth_token_present": False,
        }


def _project_calendar(raw: Any) -> CalendarInfo:
    if not isinstance(raw, Mapping):
        raise CalendarContractError("Calendar entry must be an object")
    return CalendarInfo(
        calendar_id=_calendar_id_value(raw.get("id")),
        name=_bounded_text(raw.get("summary", ""), "name", MAX_NAME_CHARS) or "unnamed",
        time_zone=_timezone_value(raw.get("timeZone") or "UTC"),
    )


def _project_event_time(raw: Any, field_name: str) -> tuple[str, str | None, bool]:
    if not isinstance(raw, Mapping):
        raise CalendarContractError(f"{field_name} must be an object")
    date_value = raw.get("date")
    if date_value is not None:
        if raw.get("dateTime") is not None:
            raise CalendarContractError(f"{field_name} must not mix date and dateTime")
        return _provider_id(date_value, field_name, _DATE_RE), None, True
    date_time = _rfc3339_value(raw.get("dateTime"), field_name)
    time_zone = raw.get("timeZone")
    return date_time, None if time_zone is None else _timezone_value(time_zone, f"{field_name}_time_zone"), False


def _project_event(raw: Any, calendar_id: str) -> CalendarEventInfo:
    if not isinstance(raw, Mapping):
        raise CalendarContractError("Calendar event entry must be an object")
    start, start_tz, start_is_date = _project_event_time(raw.get("start"), "start")
    end, end_tz, end_is_date = _project_event_time(raw.get("end"), "end")
    if start_is_date != end_is_date:
        # all-day requires BOTH sides date-only; timed requires BOTH sides dateTime.
        raise CalendarContractError("event start and end must share one kind")
    all_day = start_is_date
    attendees = raw.get("attendees")
    if attendees is not None and not isinstance(attendees, (list, tuple)):
        raise CalendarContractError("event attendees must be a list")
    recurrence = raw.get("recurrence")
    if recurrence is not None and not isinstance(recurrence, (list, tuple)):
        raise CalendarContractError("event recurrence must be a list")
    status = _bounded_text(raw.get("status", ""), "status", 64).lower()
    if status not in _EVENT_STATUSES:
        raise CalendarContractError("event status must be a known Calendar status")
    event_id = _event_id_value(raw.get("id"), "event_id")
    series_id = raw.get("recurringEventId")
    instance_of_series = series_id is not None
    series = (
        _event_id_value(series_id, "series_id")
        if instance_of_series
        else _event_id_value(raw.get("iCalUID", event_id), "series_id")
    )
    return CalendarEventInfo(
        calendar_id=calendar_id,
        event_id=event_id,
        series_id=series,
        instance_of_series=instance_of_series,
        status=status,
        summary=_bounded_text(raw.get("summary", ""), "summary", MAX_CALENDAR_EVENT_SUMMARY_CHARS),
        all_day=all_day,
        start=start,
        end=end,
        start_time_zone=start_tz,
        end_time_zone=end_tz,
        attendee_count=len(attendees or ()),
        organizer_present=raw.get("organizer") is not None,
        conference_present=raw.get("conferenceData") is not None,
        recurrence_rule_count=len(recurrence or ()),
    )


def _bounded_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    """Bound the final JSON output to Core MAX_TOOL_OUTPUT_BYTES.

    Oversized envelopes are replaced by a visible REVIEW_REQUIRED marker with
    a content digest instead of raising or leaking unbounded provider output.
    """

    encoded = json.dumps(
        envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if len(encoded) <= MAX_TOOL_OUTPUT_BYTES:
        return envelope
    return {
        "provider": "google_calendar",
        "operation": envelope.get("operation"),
        "result_status": "REVIEW_REQUIRED",
        "truncated": True,
        "reason": "bounded Calendar projection exceeded the Core tool output bound",
        "result_sha256": hashlib.sha256(encoded).hexdigest(),
        "event_content_trusted": False,
        "oauth_token_present": False,
    }


async def _port_json(
    port: CalendarReadPort,
    *,
    binding_ref: str,
    actor_ref: str,
    path: str,
    query: dict[str, str],
    max_response_bytes: int,
) -> dict[str, Any]:
    def _call() -> dict[str, Any] | Awaitable[dict[str, Any]]:
        return port.get_json(
            binding_ref=binding_ref,
            actor_ref=actor_ref,
            required_scopes=(CALENDAR_READONLY_AUTH_SCOPE,),
            base_url=GOOGLE_CALENDAR_BASE_URL,
            path=path,
            query=dict(query),
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            max_response_bytes=max_response_bytes,
        )

    try:
        result = _call()
        if inspect.isawaitable(result):
            result = await result
    except Exception:
        # The trusted port boundary is the only place that may surface
        # diagnostics; Core must not propagate its exception message, the
        # cause chain, or the implicit context chain. The raw OAuth token
        # must never reach Core-visible errors.
        sanitized = CalendarContractError("The Calendar provider port failed.")
    else:
        if not isinstance(result, dict):
            raise CalendarContractError("The Calendar provider port returned an invalid body.")
        return result

    raise sanitized


def _provider_shape_ok(body: Mapping[str, Any]) -> None:
    """Fail closed on an errored provider body without echoing provider text."""

    if "error" in body:
        raise CalendarContractError("The Calendar provider returned an error.")


def _bounded_limit(arguments: Mapping[str, Any]) -> int:
    limit = arguments.get("limit", MAX_CALENDAR_PROJECTION_ITEMS)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_CALENDAR_PROJECTION_ITEMS:
        raise CalendarContractError("limit must be an integer between 1 and 100")
    return limit


def build_calendar_read_handlers(
    port: CalendarReadPort,
    *,
    binding_ref: str,
    actor_ref: str,
    allowed_calendar_ids: tuple[str, ...] = (),
) -> dict[str, ToolHandler]:
    """Bind the promoted readonly projections to one trusted port instance.

    binding_ref/actor_ref are forwarded only to the trusted port and never
    appear in the returned output or in CalendarContractError messages.
    ``allowed_calendar_ids`` is a server-derived allowlist re-checked in Core
    as defense in depth; the port remains the scope authority.
    """

    allowed = {_calendar_id_value(item) for item in allowed_calendar_ids}

    def _require_calendar(arguments: Mapping[str, Any]) -> str:
        calendar_id = _calendar_id_value(arguments.get("calendarId"), "calendarId")
        if allowed and calendar_id not in allowed:
            raise CalendarContractError("calendar is not server-derived allowed.")
        return calendar_id

    async def list_calendars(arguments: dict[str, Any]) -> Any:
        if not isinstance(arguments, Mapping) or arguments:
            raise CalendarContractError("calendar.list_calendars accepts no arguments.")
        body = await _port_json(
            port,
            binding_ref=binding_ref,
            actor_ref=actor_ref,
            path="/users/me/calendarList",
            query={"maxResults": str(MAX_CALENDARS)},
            max_response_bytes=MAX_PROVIDER_METADATA_BYTES,
        )
        _provider_shape_ok(body)
        raw_calendars = body.get("items")
        if not isinstance(raw_calendars, (list, tuple)):
            raise CalendarContractError("The Calendar provider returned an invalid calendar list.")
        calendars: list[CalendarInfo] = []
        for raw in raw_calendars[: MAX_CALENDARS + 1]:
            calendar = _project_calendar(raw)
            if allowed and calendar.calendar_id not in allowed:
                continue
            calendars.append(calendar)
        if len(calendars) > MAX_CALENDARS:
            raise CalendarContractError("Calendar list exceeds the bounded calendar count")
        return _bounded_envelope(
            {
                "provider": "google_calendar",
                "operation": CALENDAR_LIST_CALENDARS_TOOL_ID,
                "result_status": "OK",
                "calendars": [calendar.safe_dict() for calendar in calendars],
                "calendar_count": len(calendars),
                "whole_account_dump": False,
                "event_content_trusted": False,
                "oauth_token_present": False,
                "mints_approval_authority": False,
                "write_capability_granted": False,
            }
        )

    async def get_calendar(arguments: dict[str, Any]) -> Any:
        if not isinstance(arguments, Mapping):
            raise CalendarContractError("calendar.get_calendar requires an arguments object.")
        extra = set(arguments) - {"calendarId"}
        if extra:
            raise CalendarContractError("calendar.get_calendar accepts only calendarId.")
        calendar_id = _require_calendar(arguments)
        body = await _port_json(
            port,
            binding_ref=binding_ref,
            actor_ref=actor_ref,
            path=f"/users/me/calendarList/{calendar_id}",
            query={},
            max_response_bytes=MAX_PROVIDER_METADATA_BYTES,
        )
        _provider_shape_ok(body)
        calendar = _project_calendar(body)
        if calendar.calendar_id != calendar_id:
            raise CalendarContractError("Calendar provider returned mismatched calendar identity.")
        return _bounded_envelope(
            {
                "provider": "google_calendar",
                "operation": CALENDAR_GET_CALENDAR_TOOL_ID,
                "result_status": "OK",
                "calendar": calendar.safe_dict(),
                "event_content_trusted": False,
                "oauth_token_present": False,
                "mints_approval_authority": False,
                "write_capability_granted": False,
            }
        )

    async def list_events(arguments: dict[str, Any]) -> Any:
        if not isinstance(arguments, Mapping):
            raise CalendarContractError("calendar.list_events requires an arguments object.")
        extra = set(arguments) - {"calendarId", "timeMin", "timeMax", "limit"}
        if extra:
            raise CalendarContractError(
                "calendar.list_events accepts only calendarId, timeMin, timeMax and limit."
            )
        calendar_id = _require_calendar(arguments)
        time_min = _rfc3339_value(arguments.get("timeMin"), "timeMin")
        time_max = _rfc3339_value(arguments.get("timeMax"), "timeMax")
        _require_ordered_window(time_min, time_max)
        limit = _bounded_limit(arguments)
        body = await _port_json(
            port,
            binding_ref=binding_ref,
            actor_ref=actor_ref,
            path=f"/calendars/{calendar_id}/events",
            query={
                "timeMin": time_min,
                "timeMax": time_max,
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": str(limit),
            },
            max_response_bytes=MAX_PROVIDER_METADATA_BYTES,
        )
        _provider_shape_ok(body)
        raw_events = body.get("items")
        if not isinstance(raw_events, (list, tuple)):
            raise CalendarContractError("The Calendar provider returned an invalid event list.")
        events = [_project_event(raw, calendar_id) for raw in raw_events[:limit]]
        return _bounded_envelope(
            {
                "provider": "google_calendar",
                "operation": CALENDAR_LIST_EVENTS_TOOL_ID,
                "result_status": "OK",
                "calendar_id": calendar_id,
                "time_min": time_min,
                "time_max": time_max,
                "events": [event.safe_dict() for event in events],
                "event_count": len(events),
                "whole_account_dump": False,
                "event_content_trusted": False,
                "oauth_token_present": False,
                "mints_approval_authority": False,
                "write_capability_granted": False,
            }
        )

    async def get_event(arguments: dict[str, Any]) -> Any:
        if not isinstance(arguments, Mapping):
            raise CalendarContractError("calendar.get_event requires an arguments object.")
        extra = set(arguments) - {"calendarId", "eventId"}
        if extra:
            raise CalendarContractError("calendar.get_event accepts only calendarId and eventId.")
        calendar_id = _require_calendar(arguments)
        event_id = _event_id_value(arguments.get("eventId"), "eventId")
        body = await _port_json(
            port,
            binding_ref=binding_ref,
            actor_ref=actor_ref,
            path=f"/calendars/{calendar_id}/events/{event_id}",
            query={},
            max_response_bytes=MAX_PROVIDER_METADATA_BYTES,
        )
        _provider_shape_ok(body)
        event = _project_event(body, calendar_id)
        if event.event_id != event_id:
            raise CalendarContractError("Calendar provider returned mismatched event identity.")
        return _bounded_envelope(
            {
                "provider": "google_calendar",
                "operation": CALENDAR_GET_EVENT_TOOL_ID,
                "result_status": "OK",
                "event": event.safe_dict(),
                "event_content_trusted": False,
                "oauth_token_present": False,
                "mints_approval_authority": False,
                "write_capability_granted": False,
            }
        )

    return {
        CALENDAR_LIST_CALENDARS_TOOL_ID: list_calendars,
        CALENDAR_GET_CALENDAR_TOOL_ID: get_calendar,
        CALENDAR_LIST_EVENTS_TOOL_ID: list_events,
        CALENDAR_GET_EVENT_TOOL_ID: get_event,
    }


def register_calendar_read_tools(
    runtime: ToolRuntime,
    port: CalendarReadPort,
    *,
    binding_ref: str,
    actor_ref: str,
    allowed_calendar_ids: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Register the readonly Calendar tools on a ToolRuntime and return their ids."""

    handlers = build_calendar_read_handlers(
        port,
        binding_ref=binding_ref,
        actor_ref=actor_ref,
        allowed_calendar_ids=allowed_calendar_ids,
    )
    registered: list[str] = []
    for spec in calendar_read_tool_specs():
        runtime.register(spec, handlers[spec.id])
        registered.append(spec.id)
    return tuple(registered)


def calendar_capability_snapshot() -> dict[str, object]:
    """Deterministic, network-free snapshot of the promoted Calendar READ contract."""

    return {
        "contract_version": "padiem-calendar-capability.v1",
        "connector_id": CALENDAR_CONNECTOR_ID,
        "capabilities": {
            "read": {
                "core_auth_scopes": list(
                    core_auth_scopes_for_capability(CalendarCapability.READ)
                ),
                "requires_write_approval": capability_requires_write_approval(
                    CalendarCapability.READ
                ),
            },
            "write": {
                "core_auth_scopes": list(
                    core_auth_scopes_for_capability(CalendarCapability.CREATE_EVENT)
                ),
                "requires_write_approval": True,
                "registered": False,
            },
        },
        "read_tool_ids": list(CALENDAR_READ_TOOL_IDS),
        "canonical_tool_ids": list(CALENDAR_CANONICAL_TOOL_IDS),
        "registered_write_tools": [],
        "bounds": {
            "max_calendars": MAX_CALENDARS,
            "max_event_summary_chars": MAX_CALENDAR_EVENT_SUMMARY_CHARS,
            "max_projection_items": MAX_CALENDAR_PROJECTION_ITEMS,
        },
        "registered_app_required": CALENDAR_REGISTERED_APP_REQUIRED,
        "account_connection_implies_all_calendars": False,
        "whole_account_dump_supported": False,
        "create_tools_present": False,
        "update_tools_present": False,
        "delete_tools_present": False,
        "cancel_tools_present": False,
        "invitation_response_tools_present": False,
        "attendee_mutation_tools_present": False,
        "reminder_mutation_tools_present": False,
        "conference_mutation_tools_present": False,
        "write_tools_present": CALENDAR_WRITE_TOOLS_PRESENT,
        "raw_oauth_token_in_core": CALENDAR_RAW_OAUTH_TOKEN_IN_CORE,
        "second_google_oauth_stack": CALENDAR_SECOND_GOOGLE_OAUTH_STACK,
        "autonomous_event_creation_supported": CALENDAR_AUTONOMOUS_EVENT_CREATION_SUPPORTED,
        "production_write_authority_minted": CALENDAR_PRODUCTION_WRITE_AUTHORITY_MINTED,
        "mints_approval_authority": False,
        "live_provider_calls": CALENDAR_LIVE_PROVIDER_CALLS,
        "production_activation": CALENDAR_PRODUCTION_ACTIVATION,
    }


__all__ = [
    "CALENDAR_CANONICAL_TOOL_IDS",
    "CALENDAR_CONNECTOR_ID",
    "CALENDAR_DESCRIPTOR",
    "CALENDAR_GET_CALENDAR_TOOL_ID",
    "CALENDAR_GET_EVENT_TOOL_ID",
    "CALENDAR_LIVE_PROVIDER_CALLS",
    "CALENDAR_LIVE_TOOLS_LIST_REQUIRED_FOR_READ_CLASSIFICATION",
    "CALENDAR_LIST_CALENDARS_TOOL_ID",
    "CALENDAR_LIST_EVENTS_TOOL_ID",
    "CALENDAR_PRODUCTION_WRITE_AUTHORITY_MINTED",
    "CALENDAR_RAW_OAUTH_TOKEN_IN_CORE",
    "CALENDAR_READONLY_AUTH_SCOPE",
    "CALENDAR_READ_TOOL_IDS",
    "CALENDAR_REGISTERED_APP_REQUIRED",
    "CALENDAR_SECOND_GOOGLE_OAUTH_STACK",
    "CALENDAR_STATIC_READ_TOOL_ALLOWLIST_CONFIGURED",
    "CALENDAR_UNKNOWN_MCP_TOOL_FAILS_CLOSED",
    "CALENDAR_WRITE_AUTH_SCOPE",
    "CALENDAR_WRITE_TOOLS_PRESENT",
    "GOOGLE_CALENDAR_API_HOST",
    "GOOGLE_CALENDAR_BASE_URL",
    "GOOGLE_CALENDAR_READONLY_OAUTH_SCOPE",
    "MAX_CALENDARS",
    "MAX_CALENDAR_EVENT_SUMMARY_CHARS",
    "MAX_CALENDAR_PROJECTION_ITEMS",
    "MAX_PROVIDER_METADATA_BYTES",
    "CalendarCapability",
    "CalendarCapabilityClassification",
    "CalendarCapabilityGrant",
    "CalendarContractError",
    "CalendarEventInfo",
    "CalendarInfo",
    "CalendarReadPort",
    "CalendarScope",
    "build_calendar_read_handlers",
    "calendar_capability_snapshot",
    "calendar_read_tool_specs",
    "capability_requires_write_approval",
    "classify_calendar_tool_id",
    "core_auth_scopes_for_capability",
    "register_calendar_read_tools",
]
