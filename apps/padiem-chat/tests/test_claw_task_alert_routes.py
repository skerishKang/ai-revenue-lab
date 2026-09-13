"""NETWORK_FREE route contracts for the #2341 Claw task/alert inbox read seam.

No live D1 IO, no live model call, no background scheduler, no outbound send.
The store authority is faked in memory; the routes are the unit under test.

Proves:
- OWNER_WORKSPACE_SCOPE=PASS (server-derived scope, caller cannot override)
- BOUNDED_LIST=PASS
- NON_DISCLOSING_FOREIGN_MISSING=PASS
- SAFE_STATUS_UPDATE=PASS (only the declared enum values, fully reversible)
- FAIL_CLOSED_WITHOUT_STORE=PASS
- SENSITIVE_FIELD_PROJECTION=0
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.control_plane_identity import PADIEM_CHAT_PRODUCT_ID
from app.control_plane_identity_shadow import IdentityShadowRecord
from kagent.claw_memory import (
    ClawAlert,
    ClawAlertKind,
    ClawAlertSeverity,
    ClawAlertStatus,
    ClawFollowupTask,
    ClawMemoryError,
    ClawTaskStatus,
)
from padiem_control_plane import (
    AuthSessionSnapshot,
    AuthSessionState,
    CanonicalSubjectRef,
    SubjectType,
)

TASKS_PATH = "/api/claw/tasks"
ALERTS_PATH = "/api/claw/alerts"

SIGNED_IN_USER_ID = "usr_" + "7" * 32
OTHER_USER_ID = "usr_" + "f" * 32

_OWN_TENANT = "tenant_own"
_FOREIGN_TENANT = "tenant_foreign"


def _google_settings(**overrides) -> Settings:
    values = {
        "runtime_mode": "mock",
        "auth_mode": "google",
        "public_base_url": "https://chat.example.test",
        "google_client_id": "claw-inbox-client.apps.googleusercontent.com",
        "google_client_secret": "claw-inbox-google-secret",
        "session_secret": "claw-inbox-session-secret-not-a-real-cred-000",
        "session_max_age_seconds": 3600,
    }
    values.update(overrides)
    return Settings.from_values(**values)


def _make_identity_shadow_store(**overrides) -> MagicMock:
    store = MagicMock()
    now = datetime.now(timezone.utc)
    values = {
        "product_user_id": SIGNED_IN_USER_ID,
        "canonical_subject_id": "subject_test",
        "auth_session_id": "session_test123",
        "session_revision": 1,
        "session_state": "active",
        "session_expires_at": now + timedelta(hours=1),
        "observed_at": now,
    }
    values.update(overrides)
    store.load_projection = AsyncMock(return_value=IdentityShadowRecord(**values))
    return store


def _make_auth_session_snapshot(tenant_id: str = _OWN_TENANT) -> AuthSessionSnapshot:
    now = datetime.now(timezone.utc)
    return AuthSessionSnapshot(
        session_id="session_test123",
        product_id=PADIEM_CHAT_PRODUCT_ID,
        subject=CanonicalSubjectRef(SubjectType.USER, "subject_test"),
        issued_at=now - timedelta(hours=1),
        expires_at=now + timedelta(hours=1),
        state=AuthSessionState.ACTIVE,
        revision=1,
        tenant_id=tenant_id,
    )


def _make_authority(tenant_id: str = _OWN_TENANT) -> MagicMock:
    authority = MagicMock()
    authority.resolve_auth_session = AsyncMock(
        return_value=_make_auth_session_snapshot(tenant_id=tenant_id)
    )
    return authority


class _InMemoryTaskAlertStore:
    """Route-level fake mirroring D1ClawTaskAlertStore's contract surface."""

    def __init__(self) -> None:
        self.tasks: dict[str, ClawFollowupTask] = {}
        self.alerts: dict[str, ClawAlert] = {}
        self.status_writes = 0

    async def list_tasks(self, workspace_id, *, limit=256):
        rows = [t for t in self.tasks.values() if t.workspace_id == workspace_id]
        rows.sort(key=lambda t: t.created_at, reverse=True)
        return tuple(rows[: max(1, min(int(limit), 256))])

    async def get_task(self, task_id, *, workspace_id):
        task = self.tasks.get(task_id)
        return task if task is not None and task.workspace_id == workspace_id else None

    async def set_task_status(self, task_id, status, *, workspace_id, at=None):
        task = self.tasks.get(task_id)
        if task is None or task.workspace_id != workspace_id:
            raise ClawMemoryError("task not found in workspace")
        self.status_writes += 1
        updated = task.with_status(status, at=at or datetime.now(timezone.utc))
        self.tasks[task_id] = updated
        return updated

    async def list_alerts(self, workspace_id, *, member_id=None, limit=256):
        rows = [a for a in self.alerts.values() if a.workspace_id == workspace_id]
        if member_id is not None:
            rows = [a for a in rows if a.is_visible_to(member_id)]
        rows.sort(key=lambda a: a.created_at, reverse=True)
        return tuple(rows[: max(1, min(int(limit), 256))])

    async def get_alert(self, alert_id, *, workspace_id, member_id=None):
        alert = self.alerts.get(alert_id)
        if alert is None or alert.workspace_id != workspace_id:
            return None
        if member_id is not None and not alert.is_visible_to(member_id):
            return None
        return alert

    async def set_alert_status(self, alert_id, status, *, workspace_id, at=None):
        alert = self.alerts.get(alert_id)
        if alert is None or alert.workspace_id != workspace_id:
            raise ClawMemoryError("alert not found in workspace")
        self.status_writes += 1
        updated = alert.with_status(status, at=at or datetime.now(timezone.utc))
        self.alerts[alert_id] = updated
        return updated


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _seed_task(store, task_id, *, workspace_id, status=ClawTaskStatus.OPEN, title="Follow up with vendor"):
    task = ClawFollowupTask(
        task_id=task_id,
        workspace_id=workspace_id,
        member_id=SIGNED_IN_USER_ID,
        title=title,
        status=status,
        created_at=_now(),
    )
    store.tasks[task_id] = task
    return task


def _seed_alert(store, alert_id, *, workspace_id, status=ClawAlertStatus.ACTIVE, visible_to=()):
    alert = ClawAlert(
        alert_id=alert_id,
        workspace_id=workspace_id,
        kind=ClawAlertKind.FOLLOWUP_DUE,
        severity=ClawAlertSeverity.WARN,
        title="Quote follow-up is due",
        created_at=_now(),
        status=status,
        visible_to_members=tuple(visible_to),
    )
    store.alerts[alert_id] = alert
    return alert


def _client(store, *, user_id: str = SIGNED_IN_USER_ID, tenant_id: str = _OWN_TENANT) -> TestClient:
    settings = _google_settings()
    app = create_app(settings=settings, history_store=MagicMock(), claw_task_alert_store=store)
    app.state.identity_shadow_store = _make_identity_shadow_store(product_user_id=user_id)
    app.state.control_plane_identity_authority = _make_authority(tenant_id)
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(settings, user_id),
        domain="chat.example.test",
        path="/",
    )
    return client


def _anonymous_client(store) -> TestClient:
    settings = _google_settings()
    app = create_app(settings=settings, history_store=MagicMock(), claw_task_alert_store=store)
    app.state.identity_shadow_store = _make_identity_shadow_store()
    app.state.control_plane_identity_authority = _make_authority()
    return TestClient(app, base_url="https://chat.example.test")


# ── registration ───────────────────────────────────────────────────────────


def test_routes_are_registered() -> None:
    app = create_app(Settings.from_values(runtime_mode="mock", live_enabled="false", auth_mode="off"))
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/claw/tasks" in paths
    assert "/api/claw/tasks/{task_id}" in paths
    assert "/api/claw/tasks/{task_id}/status" in paths
    assert "/api/claw/alerts" in paths
    assert "/api/claw/alerts/{alert_id}" in paths
    assert "/api/claw/alerts/{alert_id}/status" in paths


def test_store_state_defaults_to_none_without_d1_binding() -> None:
    # No new database authority: without the existing D1 binding the seam is
    # absent rather than invented.
    app = create_app(Settings.from_values(runtime_mode="mock", live_enabled="false", auth_mode="off"))
    assert getattr(app.state, "claw_task_alert_store", "missing") is None


# ── authentication ─────────────────────────────────────────────────────────


def test_anonymous_callers_are_rejected() -> None:
    store = _InMemoryTaskAlertStore()
    client = _anonymous_client(store)
    assert client.get(TASKS_PATH).status_code == 401
    assert client.get(ALERTS_PATH).status_code == 401
    assert client.get(f"{TASKS_PATH}/task-1").status_code == 401
    assert client.get(f"{ALERTS_PATH}/alert-1").status_code == 401
    assert client.post(f"{TASKS_PATH}/task-1/status", json={"status": "done"}).status_code == 401
    assert client.post(f"{ALERTS_PATH}/alert-1/status", json={"status": "dismissed"}).status_code == 401


# ── owner / workspace scope ────────────────────────────────────────────────


def test_list_is_workspace_scoped() -> None:
    store = _InMemoryTaskAlertStore()
    _seed_task(store, "task-own", workspace_id=_OWN_TENANT)
    _seed_task(store, "task-foreign", workspace_id=_FOREIGN_TENANT)
    _seed_alert(store, "alert-own", workspace_id=_OWN_TENANT)
    _seed_alert(store, "alert-foreign", workspace_id=_FOREIGN_TENANT)

    client = _client(store)
    tasks = client.get(TASKS_PATH).json()["tasks"]
    alerts = client.get(ALERTS_PATH).json()["alerts"]
    assert [t["task_id"] for t in tasks] == ["task-own"]
    assert [a["alert_id"] for a in alerts] == ["alert-own"]


def test_foreign_tenant_cannot_read_own_records() -> None:
    store = _InMemoryTaskAlertStore()
    _seed_task(store, "task-own", workspace_id=_OWN_TENANT)
    _seed_alert(store, "alert-own", workspace_id=_OWN_TENANT)

    foreign = _client(store, user_id=OTHER_USER_ID, tenant_id=_FOREIGN_TENANT)
    assert foreign.get(TASKS_PATH).json()["tasks"] == []
    assert foreign.get(ALERTS_PATH).json()["alerts"] == []
    assert foreign.get(f"{TASKS_PATH}/task-own").status_code == 404
    assert foreign.get(f"{ALERTS_PATH}/alert-own").status_code == 404


def test_caller_supplied_workspace_is_ignored_on_write() -> None:
    store = _InMemoryTaskAlertStore()
    _seed_task(store, "task-own", workspace_id=_OWN_TENANT)
    client = _client(store)
    resp = client.post(
        f"{TASKS_PATH}/task-own/status",
        json={"status": "done", "workspace_id": _FOREIGN_TENANT, "owner": OTHER_USER_ID},
    )
    # The server-derived workspace wins; the attacker-supplied scope is inert.
    assert resp.status_code == 200
    assert resp.json()["task"]["status"] == "done"
    assert store.tasks["task-own"].workspace_id == _OWN_TENANT


# ── bounded list ───────────────────────────────────────────────────────────


def test_list_is_bounded_by_limit_query() -> None:
    store = _InMemoryTaskAlertStore()
    for index in range(5):
        _seed_task(store, f"task-{index}", workspace_id=_OWN_TENANT)
    client = _client(store)
    assert len(client.get(f"{TASKS_PATH}?limit=2").json()["tasks"]) == 2
    assert len(client.get(TASKS_PATH).json()["tasks"]) == 5


def test_limit_is_capped_and_validated() -> None:
    store = _InMemoryTaskAlertStore()
    client = _client(store)
    assert client.get(f"{TASKS_PATH}?limit=0").status_code == 400
    assert client.get(f"{TASKS_PATH}?limit=-3").status_code == 400
    assert client.get(f"{TASKS_PATH}?limit=abc").status_code == 400
    # Over-large limits are clamped, never rejected and never unbounded.
    assert client.get(f"{TASKS_PATH}?limit=99999").status_code == 200


# ── non-disclosure ─────────────────────────────────────────────────────────


def test_missing_and_foreign_are_observationally_identical() -> None:
    store = _InMemoryTaskAlertStore()
    _seed_task(store, "task-foreign", workspace_id=_FOREIGN_TENANT)
    _seed_alert(store, "alert-foreign", workspace_id=_FOREIGN_TENANT)
    client = _client(store)

    foreign_task = client.get(f"{TASKS_PATH}/task-foreign")
    missing_task = client.get(f"{TASKS_PATH}/task-does-not-exist")
    assert foreign_task.status_code == missing_task.status_code == 404
    assert foreign_task.json() == missing_task.json()

    foreign_alert = client.get(f"{ALERTS_PATH}/alert-foreign")
    missing_alert = client.get(f"{ALERTS_PATH}/alert-does-not-exist")
    assert foreign_alert.status_code == missing_alert.status_code == 404
    assert foreign_alert.json() == missing_alert.json()


def test_sensitive_internal_fields_are_never_projected() -> None:
    store = _InMemoryTaskAlertStore()
    _seed_task(store, "task-own", workspace_id=_OWN_TENANT)
    _seed_alert(store, "alert-own", workspace_id=_OWN_TENANT)
    client = _client(store)

    raw_tasks = client.get(TASKS_PATH).text
    raw_alerts = client.get(ALERTS_PATH).text
    for leaked in ("workspace_id", "member_id", "source_id", "visible_to_members", "linked_refs"):
        assert leaked not in raw_tasks, leaked
        assert leaked not in raw_alerts, leaked

    task = client.get(f"{TASKS_PATH}/task-own").json()["task"]
    alert = client.get(f"{ALERTS_PATH}/alert-own").json()["alert"]
    assert set(task) == {"task_id", "title", "status", "due_date", "created_at"}
    assert set(alert) == {"alert_id", "kind", "severity", "title", "status", "created_at"}


def test_alert_member_scoping_is_enforced() -> None:
    store = _InMemoryTaskAlertStore()
    # Visible only to a different member of the same workspace.
    _seed_alert(store, "alert-other-member", workspace_id=_OWN_TENANT, visible_to=("member-other",))
    client = _client(store)
    assert client.get(ALERTS_PATH).json()["alerts"] == []
    assert client.get(f"{ALERTS_PATH}/alert-other-member").status_code == 404


# ── safe, reversible status updates ────────────────────────────────────────


def test_task_status_transitions_use_only_declared_enum_values() -> None:
    store = _InMemoryTaskAlertStore()
    _seed_task(store, "task-own", workspace_id=_OWN_TENANT)
    client = _client(store)

    for value in ("done", "cancelled", "open"):
        resp = client.post(f"{TASKS_PATH}/task-own/status", json={"status": value})
        assert resp.status_code == 200, value
        assert resp.json()["task"]["status"] == value

    for bad in ("archived", "DONE", "", "running", "in_progress"):
        resp = client.post(f"{TASKS_PATH}/task-own/status", json={"status": bad})
        assert resp.status_code == 400, bad
        assert resp.json()["error"]["code"] == "invalid_status"


def test_alert_status_transitions_use_only_declared_enum_values() -> None:
    store = _InMemoryTaskAlertStore()
    _seed_alert(store, "alert-own", workspace_id=_OWN_TENANT)
    client = _client(store)

    for value in ("dismissed", "active"):
        resp = client.post(f"{ALERTS_PATH}/alert-own/status", json={"status": value})
        assert resp.status_code == 200, value
        assert resp.json()["alert"]["status"] == value

    for bad in ("resolved", "closed", "ACTIVE"):
        resp = client.post(f"{ALERTS_PATH}/alert-own/status", json={"status": bad})
        assert resp.status_code == 400, bad
        assert resp.json()["error"]["code"] == "invalid_status"


def test_status_update_on_foreign_record_is_non_disclosing_404() -> None:
    store = _InMemoryTaskAlertStore()
    _seed_task(store, "task-foreign", workspace_id=_FOREIGN_TENANT)
    client = _client(store)
    resp = client.post(f"{TASKS_PATH}/task-foreign/status", json={"status": "done"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "claw_task_not_found"
    assert store.status_writes == 0


def test_status_update_rejects_non_json_body() -> None:
    store = _InMemoryTaskAlertStore()
    _seed_task(store, "task-own", workspace_id=_OWN_TENANT)
    client = _client(store)
    resp = client.post(
        f"{TASKS_PATH}/task-own/status",
        content="status=done",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 415


# ── fail closed ────────────────────────────────────────────────────────────


def test_routes_fail_closed_without_a_store() -> None:
    settings = _google_settings()
    app = create_app(settings=settings, history_store=MagicMock(), claw_task_alert_store=None)
    app.state.identity_shadow_store = _make_identity_shadow_store()
    app.state.control_plane_identity_authority = _make_authority()
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(settings, SIGNED_IN_USER_ID),
        domain="chat.example.test",
        path="/",
    )
    for path in (TASKS_PATH, ALERTS_PATH):
        resp = client.get(path)
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "claw_task_alert_unavailable"


def test_read_failure_returns_503_not_a_success_shape() -> None:
    store = _InMemoryTaskAlertStore()

    async def boom(*_args, **_kwargs):
        raise RuntimeError("d1 exploded")

    store.list_tasks = boom  # type: ignore[assignment]
    client = _client(store)
    resp = client.get(TASKS_PATH)
    assert resp.status_code == 503
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "claw_task_alert_read_failed"
    assert "tasks" not in body


def test_no_store_calls_on_read_only_listing() -> None:
    store = _InMemoryTaskAlertStore()
    _seed_task(store, "task-own", workspace_id=_OWN_TENANT)
    client = _client(store)
    client.get(TASKS_PATH)
    client.get(ALERTS_PATH)
    assert store.status_writes == 0


if __name__ == "__main__":
    test_routes_are_registered()
    test_store_state_defaults_to_none_without_d1_binding()
    test_anonymous_callers_are_rejected()
    test_list_is_workspace_scoped()
    test_foreign_tenant_cannot_read_own_records()
    test_caller_supplied_workspace_is_ignored_on_write()
    test_list_is_bounded_by_limit_query()
    test_limit_is_capped_and_validated()
    test_missing_and_foreign_are_observationally_identical()
    test_sensitive_internal_fields_are_never_projected()
    test_alert_member_scoping_is_enforced()
    test_task_status_transitions_use_only_declared_enum_values()
    test_alert_status_transitions_use_only_declared_enum_values()
    test_status_update_on_foreign_record_is_non_disclosing_404()
    test_status_update_rejects_non_json_body()
    test_routes_fail_closed_without_a_store()
    test_read_failure_returns_503_not_a_success_shape()
    test_no_store_calls_on_read_only_listing()
    print("B62_CLAW_TASK_ALERT_ROUTES_TESTS=PASS")
