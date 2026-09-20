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
from typing import Protocol

from .calendar_contracts import (
    CalendarAppointment,
    CalendarContractError,
    CalendarWorkLog,
    MAX_CALENDAR_LIST_LIMIT,
    _safe_identifier,
)

DOMAIN_CONTRACT_READY = True
STORE_PROTOCOL_READY = True
REFERENCE_IN_MEMORY_STORE_READY = True
DURABLE_STORE_DEFERRED = True
DURABLE_STORE_DEFERRED_REASON = (
    "unclear_migration_governance_and_pipeline_gate_scope_containment"
)


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
