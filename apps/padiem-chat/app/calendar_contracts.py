"""#2834 Phase A Native Padiem Calendar domain contracts and validation.

Padiem Calendar is the primary canonical calendar product. External calendars
(Google Calendar, Naver Calendar) are optional sync/import integrations only
(#2835_EXTERNAL_CALENDAR is out of scope). Padiem Calendar is fully functional
without any external calendar connection.

Core principles:
- Native work-log record: daily work log entries (CALENDAR_WORK_LOG=YES).
  NOT long-term memory (LONG_TERM_MEMORY=NO, MEMORY_AUTO_PROMOTION=NO).
- Native appointment contract: date-only, all-day, and timed events.
  Explicit timezone is required for timed events (fail closed on missing/naive).
  DATE_ONLY != TIMED_EVENT, ALL_DAY != TIMED_EVENT.
- Canonical calendar item projection: bounded safe projection over native work_log,
  native appointment, existing task, existing alert, existing claw_run.
  Automation projection is deferred pending #2833.
- Authority rules: reuses existing B62 owner/workspace identity pattern.
  Zero raw user ids, provider accounts, credentials, or secrets in projections.
- Date/time correctness: UTC canonical normalization with deterministic user tz projection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
import re
from typing import Any
import uuid
import zoneinfo

CALENDAR_CONTRACT_VERSION = "padiem-calendar.v1"
PADIEM_CALENDAR_CANONICAL_PRODUCT = True
EXTERNAL_CALENDAR_REQUIRED = False
CALENDAR_WORK_LOG = True
LONG_TERM_MEMORY = False
MEMORY_AUTO_PROMOTION = False
SERVER_LOCAL_TIMEZONE_INFERENCE = False
AUTOMATION_PROJECTION = "READ_ONLY_DURABLE_STORE"

MAX_TITLE_CHARS = 200
MAX_CONTENT_CHARS = 4_000
MAX_DESCRIPTION_CHARS = 4_000
MAX_REMINDER_MINUTES = 40_320  # 4 weeks
MAX_CALENDAR_LIST_LIMIT = 256
MAX_CALENDAR_LINK_BACKS = 4

CALENDAR_LINK_BACK_KINDS = frozenset(
    {"claw_session", "task", "artifact", "run"}
)

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_LOG_ID_RE = re.compile(r"^log_[0-9a-f]{16,32}$")
_APT_ID_RE = re.compile(r"^apt_[0-9a-f]{16,32}$")
_DOCUMENT_ID_RE = re.compile(r"^doc_[A-Za-z0-9]{32}$")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_DATE_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class CalendarContractError(ValueError):
    """Domain contract or validation failure for Padiem Calendar."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class CalendarItemType(str, Enum):
    WORK_LOG = "work_log"
    APPOINTMENT = "appointment"
    TASK = "task"
    ALERT = "alert"
    CLAW_RUN = "claw_run"
    AUTOMATION_RUN = "automation_run"


class AppointmentType(str, Enum):
    DATE_ONLY = "date_only"
    ALL_DAY = "all_day"
    TIMED = "timed"


class CalendarSourceType(str, Enum):
    NATIVE_WORK_LOG = "native_work_log"
    NATIVE_APPOINTMENT = "native_appointment"
    TASK = "task"
    ALERT = "alert"
    CLAW_RUN = "claw_run"
    AUTOMATION_RUN = "automation_run"


def _safe_identifier(name: str, value: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise CalendarContractError(
            "invalid_identifier", f"{name} must be a bounded safe identifier"
        )
    return value


def _clean_bounded_text(
    value: Any,
    field_name: str,
    *,
    max_len: int,
    required: bool = True,
    allow_newlines: bool = True,
) -> str | None:
    if value is None:
        if required:
            raise CalendarContractError(f"{field_name}_required", f"{field_name} is required")
        return None
    if not isinstance(value, str):
        raise CalendarContractError(f"invalid_{field_name}", f"{field_name} must be text")
    if not allow_newlines and "\n" in value:
        raise CalendarContractError(
            f"invalid_{field_name}", f"{field_name} must not contain newlines"
        )
    if _CONTROL_CHARS_RE.search(value):
        raise CalendarContractError(
            f"invalid_{field_name}", f"{field_name} contains forbidden control characters"
        )
    cleaned = value.strip()
    if required and not cleaned:
        raise CalendarContractError(f"{field_name}_required", f"{field_name} cannot be empty")
    if len(cleaned) > max_len:
        raise CalendarContractError(
            f"{field_name}_too_long", f"{field_name} exceeds maximum length of {max_len}"
        )
    return cleaned if cleaned else None


def validate_timezone(tz_name: str | None) -> zoneinfo.ZoneInfo:
    """Validate explicit IANA or UTC timezone name.

    Server-local timezone inference is strictly prohibited.
    """
    if tz_name is None:
        raise CalendarContractError(
            "timezone_required",
            "Explicit timezone is required. Server-local timezone inference is prohibited.",
        )
    if not isinstance(tz_name, str) or not tz_name.strip():
        raise CalendarContractError("invalid_timezone", "Timezone identifier must be non-empty text")
    tz_clean = tz_name.strip()
    try:
        return zoneinfo.ZoneInfo(tz_clean)
    except Exception as exc:
        raise CalendarContractError(
            "invalid_timezone", f"Timezone '{tz_clean}' is not recognized in timezone database"
        ) from exc


def parse_date(value: Any, field_name: str = "date") -> date:
    """Parse a date value strictly as a calendar date."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        raise CalendarContractError(
            f"invalid_{field_name}",
            f"{field_name} must be a plain calendar date (YYYY-MM-DD), not datetime",
        )
    if isinstance(value, str):
        cleaned = value.strip()
        if not _DATE_ISO_RE.fullmatch(cleaned):
            raise CalendarContractError(
                f"invalid_{field_name}", f"{field_name} must match format YYYY-MM-DD"
            )
        try:
            return date.fromisoformat(cleaned)
        except ValueError as exc:
            raise CalendarContractError(
                f"invalid_{field_name}", f"{field_name} is not a valid calendar date"
            ) from exc
    raise CalendarContractError(
        f"invalid_{field_name}", f"{field_name} must be a date or YYYY-MM-DD string"
    )


def parse_aware_datetime(value: Any, field_name: str) -> datetime:
    """Parse a timezone-aware datetime strictly. Naive datetimes fail closed."""
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise CalendarContractError(
                "naive_datetime_rejected",
                f"{field_name} must be timezone-aware with an explicit offset or timezone",
            )
        return value
    if isinstance(value, str):
        cleaned = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(cleaned)
        except ValueError as exc:
            raise CalendarContractError(
                f"invalid_{field_name}", f"{field_name} must be a valid ISO-8601 datetime"
            ) from exc
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise CalendarContractError(
                "naive_datetime_rejected",
                f"{field_name} must include an explicit timezone offset (e.g. +09:00 or Z)",
            )
        return dt
    raise CalendarContractError(
        f"invalid_{field_name}", f"{field_name} must be a datetime or ISO-8601 string"
    )


def _new_log_id() -> str:
    return "log_" + uuid.uuid4().hex[:16]


def _new_appointment_id() -> str:
    return "apt_" + uuid.uuid4().hex[:16]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


@dataclass(frozen=True, slots=True)
class CalendarWorkLog:
    """Native daily work log entry.

    Contract guarantees:
    - CALENDAR_WORK_LOG = True
    - LONG_TERM_MEMORY = False
    - MEMORY_AUTO_PROMOTION = False
    This record has no memory promotion capability or promotion state.
    """

    log_id: str
    workspace_id: str
    owner_id: str
    date: date
    title: str
    content: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(
        cls,
        *,
        workspace_id: str,
        owner_id: str,
        date_val: Any,
        title: str,
        content: str | None = None,
        log_id: str | None = None,
        now: datetime | None = None,
    ) -> CalendarWorkLog:
        _safe_identifier("workspace_id", workspace_id)
        _safe_identifier("owner_id", owner_id)
        parsed_date = parse_date(date_val, "date")
        clean_title = _clean_bounded_text(
            title, "title", max_len=MAX_TITLE_CHARS, required=True, allow_newlines=False
        )
        assert clean_title is not None
        clean_content = _clean_bounded_text(
            content, "content", max_len=MAX_CONTENT_CHARS, required=False, allow_newlines=True
        )
        lid = log_id or _new_log_id()
        _safe_identifier("log_id", lid)
        ts = now or _utcnow()
        if ts.tzinfo is None or ts.utcoffset() is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return cls(
            log_id=lid,
            workspace_id=workspace_id,
            owner_id=owner_id,
            date=parsed_date,
            title=clean_title,
            content=clean_content,
            created_at=ts,
            updated_at=ts,
        )


@dataclass(frozen=True, slots=True)
class CalendarAppointment:
    """Native appointment contract supporting date-only, all-day, and timed events.

    Invariants:
    - DATE_ONLY != TIMED_EVENT
    - ALL_DAY != TIMED_EVENT
    - DATE_ONLY != ALL_DAY
    - TIMED requires explicit timezone and tz-aware datetimes.
    - Naive datetimes fail closed.
    """

    appointment_id: str
    workspace_id: str
    owner_id: str
    appointment_type: AppointmentType
    title: str
    description: str | None
    date: date
    start_at: datetime | None  # UTC-normalized tz-aware datetime for timed events
    end_at: datetime | None    # UTC-normalized tz-aware datetime for timed events
    timezone: str | None       # explicit IANA tz string for timed events
    reminder_minutes: int | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(
        cls,
        *,
        workspace_id: str,
        owner_id: str,
        appointment_type: AppointmentType | str,
        title: str,
        description: str | None = None,
        date_val: Any | None = None,
        start_at: Any | None = None,
        end_at: Any | None = None,
        tz_name: str | None = None,
        reminder_minutes: int | None = None,
        appointment_id: str | None = None,
        now: datetime | None = None,
    ) -> CalendarAppointment:
        _safe_identifier("workspace_id", workspace_id)
        _safe_identifier("owner_id", owner_id)
        clean_title = _clean_bounded_text(
            title, "title", max_len=MAX_TITLE_CHARS, required=True, allow_newlines=False
        )
        assert clean_title is not None
        clean_desc = _clean_bounded_text(
            description, "description", max_len=MAX_DESCRIPTION_CHARS, required=False, allow_newlines=True
        )

        if isinstance(appointment_type, str):
            try:
                appointment_type = AppointmentType(appointment_type.strip().lower())
            except ValueError as exc:
                raise CalendarContractError(
                    "invalid_appointment_type",
                    f"appointment_type must be one of: {', '.join(t.value for t in AppointmentType)}",
                ) from exc

        if reminder_minutes is not None:
            if not isinstance(reminder_minutes, int) or reminder_minutes < 0:
                raise CalendarContractError(
                    "invalid_reminder_minutes", "reminder_minutes must be a non-negative integer"
                )
            if reminder_minutes > MAX_REMINDER_MINUTES:
                raise CalendarContractError(
                    "invalid_reminder_minutes",
                    f"reminder_minutes exceeds maximum bound of {MAX_REMINDER_MINUTES}",
                )

        parsed_date: date
        norm_start_at: datetime | None = None
        norm_end_at: datetime | None = None
        explicit_tz: str | None = None

        if appointment_type == AppointmentType.DATE_ONLY:
            if date_val is None:
                raise CalendarContractError("date_required", "date is required for date-only appointment")
            parsed_date = parse_date(date_val, "date")
            if start_at is not None or end_at is not None:
                raise CalendarContractError(
                    "date_only_cannot_have_time",
                    "date-only appointment must not specify start_at or end_at",
                )
            # Timezone is not used for date-only appointments
            explicit_tz = None

        elif appointment_type == AppointmentType.ALL_DAY:
            if date_val is None:
                raise CalendarContractError("date_required", "date is required for all-day event")
            parsed_date = parse_date(date_val, "date")
            if start_at is not None or end_at is not None:
                raise CalendarContractError(
                    "all_day_cannot_have_time",
                    "all-day appointment must not specify start_at or end_at",
                )
            explicit_tz = None

        elif appointment_type == AppointmentType.TIMED:
            # TIMED requires explicit timezone. No server-local fallback!
            tz_info = validate_timezone(tz_name)
            explicit_tz = tz_name.strip() if tz_name else str(tz_info)
            if start_at is None:
                raise CalendarContractError(
                    "start_at_required", "start_at is required for timed appointment"
                )
            aware_start = parse_aware_datetime(start_at, "start_at")
            norm_start_at = aware_start.astimezone(timezone.utc)

            if end_at is not None:
                aware_end = parse_aware_datetime(end_at, "end_at")
                norm_end_at = aware_end.astimezone(timezone.utc)
                if norm_end_at < norm_start_at:
                    raise CalendarContractError(
                        "invalid_time_range", "end_at cannot be earlier than start_at"
                    )
            else:
                norm_end_at = None

            # Date in user timezone
            start_in_user_tz = aware_start.astimezone(tz_info)
            derived_date = start_in_user_tz.date()
            if date_val is not None:
                parsed_date = parse_date(date_val, "date")
                if parsed_date != derived_date:
                    raise CalendarContractError(
                        "date_mismatch",
                        f"date '{parsed_date}' does not match start_at date '{derived_date}' in timezone {explicit_tz}",
                    )
            else:
                parsed_date = derived_date

        else:
            raise CalendarContractError("invalid_appointment_type", "Unknown appointment type")

        apt_id = appointment_id or _new_appointment_id()
        _safe_identifier("appointment_id", apt_id)
        ts = now or _utcnow()
        if ts.tzinfo is None or ts.utcoffset() is None:
            ts = ts.replace(tzinfo=timezone.utc)

        return cls(
            appointment_id=apt_id,
            workspace_id=workspace_id,
            owner_id=owner_id,
            appointment_type=appointment_type,
            title=clean_title,
            description=clean_desc,
            date=parsed_date,
            start_at=norm_start_at,
            end_at=norm_end_at,
            timezone=explicit_tz,
            reminder_minutes=reminder_minutes,
            created_at=ts,
            updated_at=ts,
        )


@dataclass(frozen=True, slots=True)
class CalendarItemProjection:
    """Canonical bounded public projection for any Padiem Calendar item.

    Privacy invariants:
    - NO raw user id / owner_id
    - NO provider account id
    - NO credential or token reference
    - NO internal database row or primary key leakage
    """

    calendar_item_id: str
    workspace_id: str
    item_type: str
    title: str
    summary: str | None
    date: str
    start_at: str | None
    end_at: str | None
    timezone: str | None
    all_day: bool
    source_type: str
    source_ref: str
    created_at: str
    updated_at: str
    artifact: dict[str, str] | None = None

    def safe_dict(self) -> dict[str, Any]:
        return {
            "calendar_item_id": self.calendar_item_id,
            "workspace_id": self.workspace_id,
            "item_type": self.item_type,
            "title": self.title,
            "summary": self.summary,
            "date": self.date,
            "start_at": self.start_at,
            "end_at": self.end_at,
            "timezone": self.timezone,
            "all_day": self.all_day,
            "source_type": self.source_type,
            "source_ref": self.source_ref,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "artifact": self.artifact,
        }


@dataclass(frozen=True, slots=True)
class CalendarLinkBack:
    kind: str
    target_id: str

    def __post_init__(self) -> None:
        if self.kind not in CALENDAR_LINK_BACK_KINDS:
            raise CalendarContractError(
                "invalid_link_back_kind", "Calendar link-back kind is not allowed"
            )
        if self.kind == "claw_session":
            try:
                from .history import validate_conversation_id

                conversation_id = validate_conversation_id(self.target_id)
            except (ImportError, ValueError) as exc:
                raise CalendarContractError(
                    "invalid_link_back_target", "Calendar link-back target is invalid"
                ) from exc
            if conversation_id is None or conversation_id != self.target_id:
                raise CalendarContractError(
                    "invalid_link_back_target", "Calendar link-back target is invalid"
                )
        elif self.kind == "artifact":
            if not isinstance(self.target_id, str) or not _DOCUMENT_ID_RE.fullmatch(
                self.target_id
            ):
                raise CalendarContractError(
                    "invalid_link_back_target", "Calendar link-back target is invalid"
                )
        else:
            _safe_identifier("link_back_target", self.target_id)

    def safe_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "target_id": self.target_id}


@dataclass(frozen=True, slots=True)
class CalendarItemDetail:
    item: CalendarItemProjection
    link_backs: tuple[CalendarLinkBack, ...] = ()

    def __post_init__(self) -> None:
        if len(self.link_backs) > MAX_CALENDAR_LINK_BACKS:
            raise CalendarContractError(
                "too_many_link_backs", "Calendar detail has too many link-backs"
            )
        identities = [(link.kind, link.target_id) for link in self.link_backs]
        if len(identities) != len(set(identities)):
            raise CalendarContractError(
                "duplicate_link_back", "Calendar detail contains a duplicate link-back"
            )

    def safe_dict(self) -> dict[str, Any]:
        item = self.item.safe_dict()
        item.pop("workspace_id", None)
        item.pop("source_ref", None)
        item.pop("artifact", None)
        return {
            "contract_version": CALENDAR_CONTRACT_VERSION,
            "item": item,
            "link_backs": [link.safe_dict() for link in self.link_backs],
        }
