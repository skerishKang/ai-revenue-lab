"""#2834 Phase A Native Padiem Calendar store protocol and in-memory reference store.

Persistence decision for Phase A:
- DOMAIN_CONTRACT = YES
- STORE_PROTOCOL = YES
- REFERENCE_IN_MEMORY_STORE = YES
- DURABLE_STORE = DEFERRED_WITH_REASON

Reason for deferral:
Padiem Chat D1 migrations (008 through 012) require dedicated migration activation
scripts, GitHub Actions migration gate workflows, and explicit deployment authority.
In Phase A, introducing an unverified/unreviewed D1 schema migration would expand scope
and bypass migration governance. Therefore, Phase A defines the canonical store protocol
and provides an in-memory reference implementation enforcing strict workspace isolation,
while deferring durable D1 persistence with explicit recorded reason.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol, runtime_checkable

from .calendar_contracts import (
    AppointmentType,
    CalendarAppointment,
    CalendarContractError,
    CalendarWorkLog,
    MAX_CALENDAR_LIST_LIMIT,
    _safe_identifier,
    parse_aware_datetime,
    parse_date,
)
from .workspace_storage import WorkspaceStorageError, _row_to_dict

DOMAIN_CONTRACT_READY = True
STORE_PROTOCOL_READY = True
REFERENCE_IN_MEMORY_STORE_READY = True
DURABLE_STORE_DEFERRED = True
DURABLE_STORE_DEFERRED_REASON = (
    "unclear_migration_governance_and_pipeline_gate_scope_containment"
)
DURABLE_STORE_READY = True
D1_CALENDAR_STORE_READY = True


@runtime_checkable
class CalendarStore(Protocol):
    """Canonical store protocol for native Padiem Calendar records."""

    async def add_work_log(self, log: CalendarWorkLog) -> CalendarWorkLog:
        """Store a native daily work log entry."""
        ...

    async def get_work_log(
        self, workspace_id: str, log_id: str
    ) -> CalendarWorkLog | None:
        """Fetch a work log strictly scoped to workspace. Returns None if absent or foreign."""
        ...

    async def list_work_logs(
        self,
        workspace_id: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 100,
    ) -> tuple[CalendarWorkLog, ...]:
        """List work logs strictly scoped to workspace, optionally filtered by date range."""
        ...

    async def add_appointment(
        self, appointment: CalendarAppointment
    ) -> CalendarAppointment:
        """Store a native appointment entry."""
        ...

    async def get_appointment(
        self, workspace_id: str, appointment_id: str
    ) -> CalendarAppointment | None:
        """Fetch an appointment strictly scoped to workspace. Returns None if absent or foreign."""
        ...

    async def list_appointments(
        self,
        workspace_id: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 100,
    ) -> tuple[CalendarAppointment, ...]:
        """List appointments strictly scoped to workspace, optionally filtered by date range."""
        ...


class InMemoryCalendarStore:
    """In-memory reference implementation of CalendarStore.

    Guarantees:
    - Strict workspace isolation: workspace A cannot read or mutate workspace B.
    - Non-disclosing lookups: foreign ids resolve to None.
    - Parameter bounds.
    - Deterministic ordering.
    """

    def __init__(self) -> None:
        # Keyed by workspace_id -> dict[id, record]
        self._work_logs: dict[str, dict[str, CalendarWorkLog]] = {}
        self._appointments: dict[str, dict[str, CalendarAppointment]] = {}

    async def add_work_log(self, log: CalendarWorkLog) -> CalendarWorkLog:
        _safe_identifier("workspace_id", log.workspace_id)
        _safe_identifier("log_id", log.log_id)
        ws_logs = self._work_logs.setdefault(log.workspace_id, {})
        ws_logs[log.log_id] = log
        return log

    async def get_work_log(
        self, workspace_id: str, log_id: str
    ) -> CalendarWorkLog | None:
        _safe_identifier("workspace_id", workspace_id)
        _safe_identifier("log_id", log_id)
        ws_logs = self._work_logs.get(workspace_id)
        if ws_logs is None:
            return None
        return ws_logs.get(log_id)

    async def list_work_logs(
        self,
        workspace_id: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 100,
    ) -> tuple[CalendarWorkLog, ...]:
        _safe_identifier("workspace_id", workspace_id)
        bounded_limit = max(1, min(limit, MAX_CALENDAR_LIST_LIMIT))
        ws_logs = self._work_logs.get(workspace_id, {})
        results: list[CalendarWorkLog] = []
        for item in ws_logs.values():
            if start_date is not None and item.date < start_date:
                continue
            if end_date is not None and item.date > end_date:
                continue
            results.append(item)
        # Sort by date ascending, then created_at ascending, then log_id ascending
        results.sort(key=lambda x: (x.date, x.created_at, x.log_id))
        return tuple(results[:bounded_limit])

    async def add_appointment(
        self, appointment: CalendarAppointment
    ) -> CalendarAppointment:
        _safe_identifier("workspace_id", appointment.workspace_id)
        _safe_identifier("appointment_id", appointment.appointment_id)
        ws_apts = self._appointments.setdefault(appointment.workspace_id, {})
        ws_apts[appointment.appointment_id] = appointment
        return appointment

    async def get_appointment(
        self, workspace_id: str, appointment_id: str
    ) -> CalendarAppointment | None:
        _safe_identifier("workspace_id", workspace_id)
        _safe_identifier("appointment_id", appointment_id)
        ws_apts = self._appointments.get(workspace_id)
        if ws_apts is None:
            return None
        return ws_apts.get(appointment_id)

    async def list_appointments(
        self,
        workspace_id: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 100,
    ) -> tuple[CalendarAppointment, ...]:
        _safe_identifier("workspace_id", workspace_id)
        bounded_limit = max(1, min(limit, MAX_CALENDAR_LIST_LIMIT))
        ws_apts = self._appointments.get(workspace_id, {})
        results: list[CalendarAppointment] = []
        for item in ws_apts.values():
            if start_date is not None and item.date < start_date:
                continue
            if end_date is not None and item.date > end_date:
                continue
            results.append(item)
        # Sort by date ascending, then start_at or min, then appointment_id ascending
        results.sort(
            key=lambda x: (
                x.date,
                x.start_at.isoformat() if x.start_at else "",
                x.appointment_id,
            )
        )
        return tuple(results[:bounded_limit])


class D1CalendarStore:
    """Durable, workspace-scoped D1 implementation of CalendarStore for native
    Padiem Calendar work-log entries and appointments (#2834 Phase B-2).

    Guarantees:
    - Strict workspace isolation: workspace A cannot read or mutate workspace B.
    - Non-disclosing lookups: foreign ids resolve to None.
    - Parameter bounds and limits strictly enforced (MAX_CALENDAR_LIST_LIMIT).
    - Deterministic ordering matching InMemoryCalendarStore.
    - Preserves explicit timezones and UTC-normalized timestamps.
    - D1 failures fail closed, raising WorkspaceStorageError.
    """

    def __init__(self, db: Any | None) -> None:
        if db is None:
            raise ValueError("D1 binding (PADIEM_CHAT_DB) is required")
        self.db = db

    def _stmt(self, sql: str, *values: Any) -> Any:
        stmt = self.db.prepare(sql)
        if values:
            stmt = stmt.bind(*values)
        return stmt

    async def _run(self, sql: str, *values: Any) -> Any:
        stmt = self._stmt(sql, *values)
        try:
            return await stmt.run()
        except Exception as exc:
            raise WorkspaceStorageError(f"D1 write failed: {exc}") from exc

    async def _first(self, sql: str, *values: Any) -> dict[str, Any] | None:
        stmt = self._stmt(sql, *values)
        try:
            raw = await stmt.first()
            return _row_to_dict(raw)
        except Exception as exc:
            raise WorkspaceStorageError(f"D1 read failed: {exc}") from exc

    async def _all(self, sql: str, *values: Any) -> list[dict[str, Any]]:
        stmt = self._stmt(sql, *values)
        try:
            raw = await stmt.all()
        except Exception as exc:
            raise WorkspaceStorageError(f"D1 read failed: {exc}") from exc
        rows = raw if isinstance(raw, list) else list(raw)
        results: list[dict[str, Any]] = []
        for r in rows:
            d = _row_to_dict(r)
            if d is not None:
                results.append(d)
        return results

    def _work_log_from_row(self, row: dict[str, Any]) -> CalendarWorkLog:
        try:
            return CalendarWorkLog(
                log_id=str(row["id"]),
                workspace_id=str(row["workspace_id"]),
                owner_id=str(row["owner_id"]),
                date=parse_date(str(row["date"]), "date"),
                title=str(row["title"]),
                content=str(row["content"]) if row.get("content") is not None else None,
                created_at=parse_aware_datetime(row["created_at"], "created_at"),
                updated_at=parse_aware_datetime(row["updated_at"], "updated_at"),
            )
        except Exception as exc:
            raise WorkspaceStorageError(f"invalid calendar work log row: {exc}") from exc

    def _appointment_from_row(self, row: dict[str, Any]) -> CalendarAppointment:
        try:
            rem = row.get("reminder_minutes")
            return CalendarAppointment(
                appointment_id=str(row["id"]),
                workspace_id=str(row["workspace_id"]),
                owner_id=str(row["owner_id"]),
                appointment_type=AppointmentType(str(row["appointment_type"])),
                title=str(row["title"]),
                description=str(row["description"]) if row.get("description") is not None else None,
                date=parse_date(str(row["date"]), "date"),
                start_at=parse_aware_datetime(row["start_at"], "start_at") if row.get("start_at") else None,
                end_at=parse_aware_datetime(row["end_at"], "end_at") if row.get("end_at") else None,
                timezone=str(row["timezone"]) if row.get("timezone") else None,
                reminder_minutes=int(rem) if rem is not None else None,
                created_at=parse_aware_datetime(row["created_at"], "created_at"),
                updated_at=parse_aware_datetime(row["updated_at"], "updated_at"),
            )
        except Exception as exc:
            raise WorkspaceStorageError(f"invalid calendar appointment row: {exc}") from exc

    async def add_work_log(self, log: CalendarWorkLog) -> CalendarWorkLog:
        _safe_identifier("workspace_id", log.workspace_id)
        _safe_identifier("log_id", log.log_id)
        _safe_identifier("owner_id", log.owner_id)
        await self._run(
            "INSERT INTO padiem_calendar_work_log "
            "(id, workspace_id, owner_id, date, title, content, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            log.log_id,
            log.workspace_id,
            log.owner_id,
            log.date.isoformat(),
            log.title,
            log.content,
            log.created_at.isoformat(),
            log.updated_at.isoformat(),
        )
        return log

    async def get_work_log(
        self, workspace_id: str, log_id: str
    ) -> CalendarWorkLog | None:
        _safe_identifier("workspace_id", workspace_id)
        _safe_identifier("log_id", log_id)
        row = await self._first(
            "SELECT id, workspace_id, owner_id, date, title, content, created_at, updated_at "
            "FROM padiem_calendar_work_log "
            "WHERE workspace_id = ? AND id = ?",
            workspace_id,
            log_id,
        )
        if row is None:
            return None
        return self._work_log_from_row(row)

    async def list_work_logs(
        self,
        workspace_id: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 100,
    ) -> tuple[CalendarWorkLog, ...]:
        _safe_identifier("workspace_id", workspace_id)
        bounded_limit = max(1, min(limit, MAX_CALENDAR_LIST_LIMIT))
        clauses = ["workspace_id = ?"]
        params: list[Any] = [workspace_id]
        if start_date is not None:
            clauses.append("date >= ?")
            params.append(start_date.isoformat())
        if end_date is not None:
            clauses.append("date <= ?")
            params.append(end_date.isoformat())
        params.append(bounded_limit)
        sql = (
            f"SELECT id, workspace_id, owner_id, date, title, content, created_at, updated_at "
            f"FROM padiem_calendar_work_log "
            f"WHERE {' AND '.join(clauses)} "
            f"ORDER BY date ASC, created_at ASC, id ASC LIMIT ?"
        )
        rows = await self._all(sql, *params)
        return tuple(self._work_log_from_row(r) for r in rows)

    async def add_appointment(
        self, appointment: CalendarAppointment
    ) -> CalendarAppointment:
        _safe_identifier("workspace_id", appointment.workspace_id)
        _safe_identifier("appointment_id", appointment.appointment_id)
        _safe_identifier("owner_id", appointment.owner_id)
        await self._run(
            "INSERT INTO padiem_calendar_appointment "
            "(id, workspace_id, owner_id, appointment_type, title, description, "
            " date, start_at, end_at, timezone, reminder_minutes, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            appointment.appointment_id,
            appointment.workspace_id,
            appointment.owner_id,
            appointment.appointment_type.value,
            appointment.title,
            appointment.description,
            appointment.date.isoformat(),
            appointment.start_at.isoformat() if appointment.start_at else None,
            appointment.end_at.isoformat() if appointment.end_at else None,
            appointment.timezone,
            appointment.reminder_minutes,
            appointment.created_at.isoformat(),
            appointment.updated_at.isoformat(),
        )
        return appointment

    async def get_appointment(
        self, workspace_id: str, appointment_id: str
    ) -> CalendarAppointment | None:
        _safe_identifier("workspace_id", workspace_id)
        _safe_identifier("appointment_id", appointment_id)
        row = await self._first(
            "SELECT id, workspace_id, owner_id, appointment_type, title, description, "
            "date, start_at, end_at, timezone, reminder_minutes, created_at, updated_at "
            "FROM padiem_calendar_appointment "
            "WHERE workspace_id = ? AND id = ?",
            workspace_id,
            appointment_id,
        )
        if row is None:
            return None
        return self._appointment_from_row(row)

    async def list_appointments(
        self,
        workspace_id: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 100,
    ) -> tuple[CalendarAppointment, ...]:
        _safe_identifier("workspace_id", workspace_id)
        bounded_limit = max(1, min(limit, MAX_CALENDAR_LIST_LIMIT))
        clauses = ["workspace_id = ?"]
        params: list[Any] = [workspace_id]
        if start_date is not None:
            clauses.append("date >= ?")
            params.append(start_date.isoformat())
        if end_date is not None:
            clauses.append("date <= ?")
            params.append(end_date.isoformat())
        params.append(bounded_limit)
        sql = (
            f"SELECT id, workspace_id, owner_id, appointment_type, title, description, "
            f"date, start_at, end_at, timezone, reminder_minutes, created_at, updated_at "
            f"FROM padiem_calendar_appointment "
            f"WHERE {' AND '.join(clauses)} "
            f"ORDER BY date ASC, COALESCE(start_at, '') ASC, id ASC LIMIT ?"
        )
        rows = await self._all(sql, *params)
        return tuple(self._appointment_from_row(r) for r in rows)

