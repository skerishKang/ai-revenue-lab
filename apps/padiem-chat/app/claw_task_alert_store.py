"""Durable D1 persistence adapter for the B54 Claw task/alert contracts.

Thin B62 product-persistence seam that *consumes* (does not reimplement) the
``kagent.claw_memory.ClawMemoryStore`` contract from ``apps/korean-ai-code-agent``
(B54). It implements task + alert CRUD scoped to ``workspace_id`` /
``member_id``, fail-closed on missing foreign records, bounded list windows,
and never persists raw inbound bodies, prompts, secrets, or OAuth tokens.

This adapter does NOT:
- create tables at runtime (``RUNTIME_CREATE_TABLE=NO``)
- schedule or dispatch automation/cron (``BACKGROUND_SCHEDULER=NO``)
- send outbound notifications (``EXTERNAL_SEND=NO``)
- reimplement P01/Core workflow/approval semantics
  (``P01_CORE_WORKFLOW_AUTHORITY_PRESERVED=YES``)
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from kagent.claw_memory import (
    CONTRACT_VERSION,
    ClawAlert,
    ClawAlertKind,
    ClawAlertSeverity,
    ClawAlertStatus,
    ClawFollowupTask,
    ClawMemoryStore,
    ClawMemoryError,
    ClawTaskStatus,
)

from .workspace_storage import (
    WorkspaceStorageAccessError,
    WorkspaceStorageError,
    _parse_time,
    _row_to_dict,
    _safe_identifier,
    _utcnow,
)

_TASK_ALERT_TABLE = "claw_task_alert"
_MAX_INBOX_LIST = 256


def _parse_date(value: Any) -> "date | None":
    """Parse a persisted due date.

    ``add_task`` writes ``due_date.isoformat()``, i.e. a *plain* date string
    (``"2026-09-30"``), not a timestamp. ``_parse_time`` requires a tz-aware
    datetime, so it must only be the fallback for rows written as timestamps.
    """
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    parsed = _parse_time(value)
    return parsed.date()


def _bool_int(value: Any) -> int:
    try:
        return 1 if value else 0
    except Exception:
        raise WorkspaceStorageError("invalid boolean value")


class D1ClawTaskAlertStore(ClawMemoryStore):
    """Durable, workspace-scoped D1 implementation of ClawMemoryStore for
    follow-up tasks and web alert-inbox records only.

    No other ClawMemoryStore memory kinds are persisted here (parties/items/prices
    remain B54 in-memory only). D1 failures fail closed.
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
            return _row_to_dict(await stmt.first())
        except Exception as exc:
            raise WorkspaceStorageError(f"D1 read failed: {exc}") from exc

    async def _all(self, sql: str, *values: Any) -> list[dict[str, Any]]:
        stmt = self._stmt(sql, *values)
        try:
            raw = await stmt.all()
        except Exception as exc:
            raise WorkspaceStorageError(f"D1 read failed: {exc}") from exc
        rows = raw if isinstance(raw, list) else list(raw)
        return [_row_to_dict(r) for r in rows]

    def _task_row_to_record(self, row: dict[str, Any]) -> ClawFollowupTask:
        try:
            member = row.get("member_id")
            return ClawFollowupTask(
                task_id=str(row["id"]),
                workspace_id=str(row["workspace_id"]),
                member_id=str(member) if member else "",
                title=str(row["title"]),
                status=ClawTaskStatus(row["status"]),
                created_at=_parse_time(row["created_at"]),
                due_date=_parse_date(row.get("due_date")),
                source_id=str(row["source_id"]) if row.get("source_id") else None,
                linked_ref=str(row["linked_ref"]) if row.get("linked_ref") else None,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkspaceStorageError("claw task row is invalid") from exc

    def _alert_row_to_record(self, row: dict[str, Any]) -> ClawAlert:
        try:
            visible_to_all = bool(int(row["visible_to_all"]))
            member_id = str(row["member_id"]) if row.get("member_id") else ""
            visible_to_members: tuple[str, ...] = (
                () if visible_to_all else ((member_id,) if member_id else ())
            )
            return ClawAlert(
                alert_id=str(row["id"]),
                workspace_id=str(row["workspace_id"]),
                kind=ClawAlertKind(row["kind_value"]),
                severity=ClawAlertSeverity(str(row["severity"])),
                title=str(row["title"]),
                created_at=_parse_time(row["created_at"]),
                status=ClawAlertStatus(row["status"]),
                visible_to_members=visible_to_members,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkspaceStorageError("claw alert row is invalid") from exc

    async def add_task(self, task: ClawFollowupTask) -> ClawFollowupTask:
        _safe_identifier("workspace_id", task.workspace_id)
        _safe_identifier("member_id", task.member_id)
        now = _utcnow()
        await self._run(
            f"INSERT INTO {_TASK_ALERT_TABLE} "
            "(id, workspace_id, kind, status, title, created_at, updated_at, "
            " member_id, due_date, source_id, linked_ref, severity, kind_value, visible_to_all) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 1)",
            task.task_id,
            task.workspace_id,
            "task",
            task.status.value,
            task.title,
            task.created_at.isoformat(),
            now.isoformat(),
            task.member_id,
            task.due_date.isoformat() if task.due_date else None,
            task.source_id,
            task.linked_ref,
        )
        return task

    async def set_task_status(
        self, task_id: str, status: ClawTaskStatus, *, workspace_id: str, at: datetime | None = None
    ) -> ClawFollowupTask:
        _safe_identifier("workspace_id", workspace_id)
        _safe_identifier("task_id", task_id)
        if not isinstance(status, ClawTaskStatus):
            try:
                status = ClawTaskStatus(status)
            except (TypeError, ValueError) as exc:
                raise ClawMemoryError(f"invalid task status: {status}") from exc
        now = at or _utcnow()
        current = await self._get_task_locked(task_id, workspace_id=workspace_id)
        if current is None:
            raise ClawMemoryError("task not found in workspace")
        await self._run(
            f"UPDATE {_TASK_ALERT_TABLE} SET status=?, updated_at=? "
            f"WHERE id=? AND workspace_id=? AND kind='task'",
            status.value,
            now.isoformat(),
            task_id,
            workspace_id,
        )
        return current.with_status(status, at=now)

    async def add_alert(self, alert: ClawAlert) -> ClawAlert:
        _safe_identifier("workspace_id", alert.workspace_id)
        now = _utcnow()
        visible_to_all = alert.visible_to_all
        member_id = "" if visible_to_all else (alert.visible_to_members[0] if alert.visible_to_members else "")
        await self._run(
            f"INSERT INTO {_TASK_ALERT_TABLE} "
            "(id, workspace_id, kind, status, title, created_at, updated_at, "
            " member_id, due_date, source_id, linked_ref, severity, kind_value, visible_to_all) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?)",
            alert.alert_id,
            alert.workspace_id,
            "alert",
            alert.status.value,
            alert.title,
            alert.created_at.isoformat(),
            now.isoformat(),
            member_id,
            alert.severity.value,
            alert.kind.value,
            1 if visible_to_all else 0,
        )
        return alert

    async def set_alert_status(
        self, alert_id: str, status: ClawAlertStatus, *, workspace_id: str, at: datetime | None = None
    ) -> ClawAlert:
        _safe_identifier("workspace_id", workspace_id)
        _safe_identifier("alert_id", alert_id)
        if not isinstance(status, ClawAlertStatus):
            try:
                status = ClawAlertStatus(status)
            except (TypeError, ValueError) as exc:
                raise ClawMemoryError(f"invalid alert status: {status}") from exc
        now = at or _utcnow()
        current = await self._get_alert_locked(alert_id, workspace_id=workspace_id)
        if current is None:
            raise ClawMemoryError("alert not found in workspace")
        await self._run(
            f"UPDATE {_TASK_ALERT_TABLE} SET status=?, updated_at=? "
            f"WHERE id=? AND workspace_id=? AND kind='alert'",
            status.value,
            now.isoformat(),
            alert_id,
            workspace_id,
        )
        return current.with_status(status, at=now)

    async def _get_task_locked(self, task_id: str, *, workspace_id: str) -> ClawFollowupTask | None:
        _safe_identifier("workspace_id", workspace_id)
        _safe_identifier("task_id", task_id)
        row = await self._first(
            f"SELECT id, workspace_id, status, title, created_at, member_id, due_date, source_id, "
            f"linked_ref, severity, kind_value, visible_to_all FROM {_TASK_ALERT_TABLE} "
            f"WHERE id=? AND workspace_id=? AND kind='task'",
            task_id,
            workspace_id,
        )
        return self._task_row_to_record(row) if row else None

    async def _get_alert_locked(self, alert_id: str, *, workspace_id: str) -> ClawAlert | None:
        _safe_identifier("workspace_id", workspace_id)
        _safe_identifier("alert_id", alert_id)
        row = await self._first(
            f"SELECT id, workspace_id, status, title, created_at, member_id, due_date, source_id, "
            f"linked_ref, severity, kind_value, visible_to_all FROM {_TASK_ALERT_TABLE} "
            f"WHERE id=? AND workspace_id=? AND kind='alert'",
            alert_id,
            workspace_id,
        )
        if row is None:
            return None
        return self._alert_row_to_record(row)

    async def get_task(self, task_id: str, *, workspace_id: str) -> ClawFollowupTask | None:
        """Bounded, non-disclosing task lookup. Returns None (never raises with
        cross-workspace details) when the task is absent or owned elsewhere."""
        _safe_identifier("workspace_id", workspace_id)
        _safe_identifier("task_id", task_id)
        try:
            return await self._get_task_locked(task_id, workspace_id=workspace_id)
        except WorkspaceStorageError:
            return None

    async def get_alert(self, alert_id: str, *, workspace_id: str, member_id: str | None = None) -> ClawAlert | None:
        """Bounded, non-disclosing alert lookup. Member-scoped when a member is
        supplied; foreign/invisible alerts resolve to None."""
        _safe_identifier("workspace_id", workspace_id)
        _safe_identifier("alert_id", alert_id)
        try:
            record = await self._get_alert_locked(alert_id, workspace_id=workspace_id)
        except WorkspaceStorageError:
            return None
        if record is None:
            return None
        if member_id is not None and not record.is_visible_to(member_id):
            return None
        return record

    async def list_tasks(
        self, workspace_id: str, *, limit: int = _MAX_INBOX_LIST
    ) -> tuple[ClawFollowupTask, ...]:
        _safe_identifier("workspace_id", workspace_id)
        bounded = max(1, min(limit, _MAX_INBOX_LIST))
        rows = await self._all(
            f"SELECT id, workspace_id, status, title, created_at, member_id, due_date, source_id, "
            f"linked_ref, severity, kind_value, visible_to_all FROM {_TASK_ALERT_TABLE} "
            f"WHERE workspace_id=? AND kind='task' "
            f"ORDER BY created_at DESC LIMIT {int(bounded)}",
            workspace_id,
        )
        return tuple(self._task_row_to_record(r) for r in rows)

    async def list_alerts(
        self,
        workspace_id: str,
        *,
        member_id: str | None = None,
        limit: int = _MAX_INBOX_LIST,
    ) -> tuple[ClawAlert, ...]:
        _safe_identifier("workspace_id", workspace_id)
        bounded = max(1, min(limit, _MAX_INBOX_LIST))
        rows = await self._all(
            f"SELECT id, workspace_id, status, title, created_at, member_id, due_date, source_id, "
            f"linked_ref, severity, kind_value, visible_to_all FROM {_TASK_ALERT_TABLE} "
            f"WHERE workspace_id=? AND kind='alert' "
            f"ORDER BY created_at DESC LIMIT {int(bounded)}",
            workspace_id,
        )
        records = [self._alert_row_to_record(r) for r in rows]
        if member_id is not None:
            records = [r for r in records if r.is_visible_to(member_id)]
        return tuple(records[:bounded])

    async def projection(self, workspace_id: str, *, member_id: str | None = None) -> dict[str, Any]:
        _safe_identifier("workspace_id", workspace_id)
        tasks = await self.list_tasks(workspace_id)
        alerts = await self.list_alerts(workspace_id, member_id=member_id)
        return {
            "contract_version": CONTRACT_VERSION,
            "workspace_id": workspace_id,
            "tasks": [task.safe_dict() for task in tasks],
            "alerts": [alert.safe_dict() for alert in alerts],
        }

    async def submit_candidate(self, candidate: Any, *, proposal_id: str) -> Any:
        raise NotImplementedError

    async def decide_proposal(
        self, proposal_id: str, state: Any, *, workspace_id: str, decided_by: str,
        decided_at: datetime, edited_payload: dict[str, Any] | None = None
    ) -> Any:
        raise NotImplementedError

    async def apply_proposal(self, proposal_id: str, *, workspace_id: str, memory_id: str, applied_at: datetime) -> Any:
        raise NotImplementedError

    async def list_parties(self, workspace_id: str) -> tuple[Any, ...]:
        _safe_identifier("workspace_id", workspace_id)
        return ()

    async def list_items(self, workspace_id: str) -> tuple[Any, ...]:
        _safe_identifier("workspace_id", workspace_id)
        return ()

    async def list_prices(self, workspace_id: str) -> tuple[Any, ...]:
        _safe_identifier("workspace_id", workspace_id)
        return ()
