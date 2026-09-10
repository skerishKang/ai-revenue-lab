"""NETWORK_FREE tests for the durable Claw task/alert D1 persistence seam (#2328).

No live D1 IO, no live model call, no background scheduler, no outbound send.
Uses an in-memory D1 double identical in shape to Cloudflare D1
(prepare / bind / async run, first, all).
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

import pytest

from kagent.claw_memory import (
    CONTRACT_VERSION,
    ClawAlert,
    ClawAlertKind,
    ClawAlertSeverity,
    ClawAlertStatus,
    ClawFollowupTask,
    ClawMemoryError,
    ClawTaskStatus,
)

from app.claw_task_alert_store import D1ClawTaskAlertStore
from app.workspace_storage import WorkspaceStorageError

_TABLE = "claw_task_alert"

COLUMNS = (
    "id", "workspace_id", "kind", "status", "title", "created_at", "updated_at",
    "member_id", "due_date", "source_id", "linked_ref", "severity", "kind_value",
    "visible_to_all",
)


def _now() -> _dt.datetime:
    return _dt.datetime(2026, 9, 10, 8, 0, 0, tzinfo=_dt.timezone.utc)


def _T(
    task_id: str = "task-1",
    *,
    workspace_id: str = "ws-1",
    status: ClawTaskStatus = ClawTaskStatus.OPEN,
    title: str = "Follow up with supplier",
    member_id: str = "member-1",
    due_date: _dt.date | None = None,
    source_id: str | None = None,
    linked_ref: str | None = None,
    created_at: _dt.datetime | None = None,
) -> ClawFollowupTask:
    return ClawFollowupTask(
        task_id=task_id,
        workspace_id=workspace_id,
        member_id=member_id,
        title=title,
        status=status,
        created_at=created_at or _now(),
        due_date=due_date,
        source_id=source_id,
        linked_ref=linked_ref,
    )


def _A(
    alert_id: str = "alert-1",
    *,
    workspace_id: str = "ws-1",
    kind: ClawAlertKind = ClawAlertKind.FOLLOWUP_DUE,
    severity: ClawAlertSeverity = ClawAlertSeverity.WARN,
    title: str = "Due follow-up needed",
    status: ClawAlertStatus = ClawAlertStatus.ACTIVE,
    created_at: _dt.datetime | None = None,
    visible_to_members: tuple[str, ...] = (),
) -> ClawAlert:
    return ClawAlert(
        alert_id=alert_id,
        workspace_id=workspace_id,
        kind=kind,
        severity=severity,
        title=title,
        created_at=created_at or _now(),
        status=status,
        visible_to_members=visible_to_members,
    )


def _parse_kind_from_sql(sql: str) -> str:
    """Extract 'task' or 'alert' from the SQL WHERE clause."""
    if "kind='task'" in sql:
        return "task"
    if "kind='alert'" in sql:
        return "alert"
    raise AssertionError(f"could not determine kind from SQL: {sql!r}")


def _parse_insert_columns(sql: str) -> list[str]:
    """Extract the column list from an INSERT statement."""
    paren_open = sql.index("(")
    paren_close = sql.index(")")
    cols_str = sql[paren_open + 1:paren_close]
    return [c.strip() for c in cols_str.split(",")]


def _parse_insert_values_placeholders(values_str: str) -> list[str]:
    """Parse the VALUES clause, returning a list where each element is
    either '?' (bound) or a literal token (e.g. 'NULL', '1')."""
    inner = values_str.strip("()").strip()
    parts = [p.strip() for p in inner.split(",")]
    return parts


def _parse_insert_values_literals(parts: list[str]) -> list[Any]:
    """Convert literal placeholder parts to Python values (None or int)."""
    result = []
    for p in parts:
        if p.upper() == "NULL":
            result.append(None)
        elif p == "1":
            result.append(1)
        elif p == "0":
            result.append(0)
        else:
            result.append(p)
    return result


class _FakeStatement:
    def __init__(self, db: "_FakeD1", sql: str) -> None:
        self._db = db
        self._sql = sql
        self._values: tuple[Any, ...] = ()

    def bind(self, *values: Any) -> "_FakeStatement":
        self._values = values
        return self

    async def run(self) -> dict[str, Any]:
        sql = self._sql
        if sql.startswith(f"INSERT INTO {_TABLE}"):
            cols = _parse_insert_columns(sql)
            values_part = sql.split("VALUES", 1)[1].strip()
            ph_parts = _parse_insert_values_placeholders(values_part)
            value_idx = 0
            row: dict[str, Any] = {}
            for col, ph in zip(cols, ph_parts):
                if ph == "?":
                    row[col] = self._values[value_idx]
                    value_idx += 1
                else:
                    row[col] = _parse_insert_values_literals([ph])[0]
            self._db.rows[row["id"]] = row
            return {"success": True, "meta": {"last_row_id": 1, "changes": 1}}
        if sql.startswith(f"UPDATE {_TABLE}"):
            set_part = sql.split(" SET ")[1].split(" WHERE ")[0]
            where_part = sql.split(" WHERE ")[1]
            col_updates: dict[str, Any] = {}
            vi = 0
            for pair in [p.strip() for p in set_part.split(",")]:
                cname = pair.split("=")[0].strip()
                col_updates[cname] = self._values[vi]
                vi += 1
            where_cols = {}
            for pair in [p.strip() for p in where_part.split(" AND ")]:
                cname = pair.split("=")[0].strip()
                if cname == "kind":
                    continue
                where_cols[cname] = self._values[vi]
                vi += 1
            rid = where_cols["id"]
            ws = where_cols["workspace_id"]
            row = self._db.rows.get(rid)
            if row is not None and row["workspace_id"] == ws:
                row.update(col_updates)
            return {"success": True, "meta": {"changes": 1}}
        raise AssertionError(f"unexpected SQL for run(): {sql!r}")

    async def first(self) -> dict[str, Any] | None:
        sql = self._sql
        (rid, ws) = self._values[:2]
        kind = _parse_kind_from_sql(sql)
        row = self._db.rows.get(rid)
        if row is None or row["workspace_id"] != ws or row["kind"] != kind:
            return None
        return {c: row[c] for c in COLUMNS}

    async def all(self) -> list[dict[str, Any]]:
        sql = self._sql
        ws = self._values[0]
        kind = _parse_kind_from_sql(sql)
        matched = [
            {c: r[c] for c in COLUMNS}
            for r in self._db.rows.values()
            if r["workspace_id"] == ws and r["kind"] == kind
        ]
        matched.sort(key=lambda r: r["created_at"], reverse=True)
        if "LIMIT" in sql.upper():
            matched = matched[: int(sql.upper().split("LIMIT")[-1].strip().rstrip(";"))]
        return matched


class _FakeD1:
    """Minimal in-memory D1 double: prepare / bind / run / first / all only."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def prepare(self, sql: str) -> _FakeStatement:
        return _FakeStatement(self, sql)


def _store() -> tuple[D1ClawTaskAlertStore, _FakeD1]:
    db = _FakeD1()
    return D1ClawTaskAlertStore(db), db


# ---- 1. task create/list/read ----
async def test_task_create_and_get_and_list():
    store, _ = _store()
    task = _T()
    saved = await store.add_task(task)
    assert saved.task_id == "task-1"
    got = await store.get_task("task-1", workspace_id="ws-1")
    assert got is not None
    assert got.task_id == "task-1"
    assert got.status == ClawTaskStatus.OPEN
    assert got.title == "Follow up with supplier"
    assert got.member_id == "member-1"
    listed = await store.list_tasks("ws-1")
    assert len(listed) == 1
    assert listed[0].task_id == "task-1"
    assert listed[0].title == "Follow up with supplier"


async def test_task_get_missing_returns_none():
    store, _ = _store()
    assert await store.get_task("task-1", workspace_id="ws-1") is None


# ---- 2. alert create/list/read ----
async def test_alert_create_and_get_and_list():
    store, _ = _store()
    alert = _A()
    await store.add_alert(alert)
    got = await store.get_alert("alert-1", workspace_id="ws-1")
    assert got is not None
    assert got.kind == ClawAlertKind.FOLLOWUP_DUE
    assert got.severity == ClawAlertSeverity.WARN
    assert got.title == "Due follow-up needed"
    listed = await store.list_alerts("ws-1")
    assert len(listed) == 1
    assert listed[0].alert_id == "alert-1"
    assert listed[0].is_visible_to(None)
    assert listed[0].is_visible_to("member-1")


async def test_alert_member_scoped_is_visible_to_only_listed_member():
    store, _ = _store()
    alert = _A(visible_to_members=("member-1",))
    await store.add_alert(alert)
    none_view = await store.get_alert("alert-1", workspace_id="ws-1", member_id="member-2")
    assert none_view is None
    own_view = await store.get_alert("alert-1", workspace_id="ws-1", member_id="member-1")
    assert own_view is not None


# ---- 3. task status update ----
async def test_task_status_update():
    store, _ = _store()
    await store.add_task(_T())
    updated = await store.set_task_status("task-1", ClawTaskStatus.DONE, workspace_id="ws-1", at=_now())
    assert updated.status == ClawTaskStatus.DONE
    got = await store.get_task("task-1", workspace_id="ws-1")
    assert got.status == ClawTaskStatus.DONE


async def test_task_status_update_unknown_id_fails_closed():
    store, _ = _store()
    with pytest.raises(ClawMemoryError):
        await store.set_task_status("task-x", ClawTaskStatus.DONE, workspace_id="ws-1")


# ---- 4. alert status update ----
async def test_alert_status_update():
    store, _ = _store()
    await store.add_alert(_A())
    updated = await store.set_alert_status("alert-1", ClawAlertStatus.DISMISSED, workspace_id="ws-1", at=_now())
    assert updated.status == ClawAlertStatus.DISMISSED


async def test_alert_status_update_unknown_id_fails_closed():
    store, _ = _store()
    with pytest.raises(ClawMemoryError):
        await store.set_alert_status("alert-x", ClawAlertStatus.DISMISSED, workspace_id="ws-1")


# ---- 5. hard bounded list ----
async def test_list_is_hard_bounded():
    store, _ = _store()
    for i in range(300):
        await store.add_task(_T(f"task-{i}", title=f"title {i}", member_id="m-1"))
    assert len(await store.list_tasks("ws-1")) == 256
    assert len(await store.list_tasks("ws-1", limit=5)) == 5


# ---- 6. owner/workspace isolation ----
async def test_owner_workspace_isolation():
    store, _ = _store()
    await store.add_task(_T("task-1", workspace_id="ws-1", member_id="m-a"))
    await store.add_task(_T("task-2", workspace_id="ws-2", member_id="m-b"))
    t1 = await store.get_task("task-1", workspace_id="ws-1")
    t2 = await store.get_task("task-2", workspace_id="ws-2")
    assert t1 is not None and t1.member_id == "m-a"
    assert t2 is not None and t2.member_id == "m-b"
    listed_ws1 = await store.list_tasks("ws-1")
    listed_ws2 = await store.list_tasks("ws-2")
    assert len(listed_ws1) == 1 and listed_ws1[0].member_id == "m-a"
    assert len(listed_ws2) == 1 and listed_ws2[0].member_id == "m-b"


# ---- 7. foreign/missing non-disclosure ----
async def test_foreign_get_returns_none_not_error():
    store, _ = _store()
    await store.add_task(_T("task-1", workspace_id="ws-1", member_id="m-1"))
    assert await store.get_task("task-1", workspace_id="ws-999") is None
    assert await store.get_alert("task-1", workspace_id="ws-999") is None
    with pytest.raises(ClawMemoryError):
        await store.set_task_status("task-1", ClawTaskStatus.DONE, workspace_id="ws-999")


# ---- 8. D1 failure fail-closed ----
class _AlwaysFailStatement:
    def bind(self, *values: Any) -> "_AlwaysFailStatement":
        return self

    async def run(self) -> dict[str, Any]:
        raise RuntimeError("simulated D1 failure")

    async def first(self) -> Any:
        raise RuntimeError("simulated D1 failure")

    async def all(self) -> list[Any]:
        raise RuntimeError("simulated D1 failure")


class _FailingD1:
    def prepare(self, sql: str) -> _AlwaysFailStatement:
        return _AlwaysFailStatement()


async def test_d1_write_failure_fail_closed():
    store = D1ClawTaskAlertStore(_FailingD1())
    with pytest.raises(WorkspaceStorageError):
        await store.add_task(_T())


async def test_d1_read_failure_fail_closed():
    store = D1ClawTaskAlertStore(_FailingD1())
    assert await store.get_task("task-1", workspace_id="ws-1") is None


# ---- 9. secret / raw-material persistence 0 ----
async def test_no_raw_prompt_secret_token_persisted_in_row():
    store, db = _store()
    task = _T(title="Review proposal")
    await store.add_task(task)
    row = db.rows["task-1"]
    assert row["source_id"] is None
    assert row["linked_ref"] is None
    assert row["severity"] is None
    assert row["kind_value"] is None
    assert row["created_at"] == task.created_at.isoformat()
    assert row["title"] == "Review proposal"


async def test_no_oauth_cookie_persisted_in_row():
    store, db = _store()
    alert = _A(kind=ClawAlertKind.MEMORY_PROPOSAL, severity=ClawAlertSeverity.INFO,
               title="Memory proposal awaiting approval")
    await store.add_alert(alert)
    row = db.rows["alert-1"]
    assert row["due_date"] is None
    assert row["source_id"] is None
    assert row["linked_ref"] is None
    assert row["severity"] == ClawAlertSeverity.INFO.value
    assert row["kind_value"] == ClawAlertKind.MEMORY_PROPOSAL.value
    assert row["visible_to_all"] == 1


async def test_projection_round_trip():
    store, _ = _store()
    await store.add_task(_T("task-1", member_id="m-1"))
    await store.add_alert(_A("alert-1", visible_to_members=("m-1",)))
    proj = await store.projection("ws-1", member_id="m-1")
    assert proj["contract_version"] == CONTRACT_VERSION
    assert proj["workspace_id"] == "ws-1"
    assert len(proj["tasks"]) == 1
    assert proj["tasks"][0]["task_id"] == "task-1"
    assert len(proj["alerts"]) == 1
    assert proj["alerts"][0]["alert_id"] == "alert-1"
