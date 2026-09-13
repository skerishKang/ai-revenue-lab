"""NETWORK_FREE behavioural HTTP contracts for the #2341 Claw inbox seam.

The merged #2341 test file (`test_b62_2341_task_alert_inbox_ui.py`) is entirely
static source-text assertions — it never issues a request. This file drives the
real `app.claw_inbox_routes` handlers through Starlette's TestClient, so the
security properties that only exist at runtime are actually exercised:

- ANONYMOUS_REJECTED=401
- NON_DISCLOSING_FOREIGN_MISSING=PASS (identical status *and* body)
- MEMBER_SCOPED_TASKS=PASS (same workspace, different member -> not listed)
- BOUNDED_LIMIT=PASS (clamped, and rejected when not a positive integer)
- FAIL_CLOSED_WITHOUT_STORE=PASS (503, never an ok:True shape)
- PAYLOAD_VALIDATION=PASS (415 / 400 for content-type, size, shape, enum)
- NO_STORE_HEADERS=PASS

No live D1 IO, no live model call, no scheduler, no outbound send.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
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

LIST_TASKS = "/api/claw/inbox/tasks"
LIST_ALERTS = "/api/claw/inbox/alerts"

SIGNED_IN_USER_ID = "usr_" + "7" * 32
OTHER_USER_ID = "usr_" + "f" * 32

_OWN_TENANT = "tenant_own"
_FOREIGN_TENANT = "tenant_foreign"

_NO_STORE_EXPECTED = {
    "cache-control": "no-store, max-age=0",
    "pragma": "no-cache",
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
}


# ── harness ────────────────────────────────────────────────────────────────


def _google_settings(**overrides: Any) -> Settings:
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


def _make_identity_shadow_store(**overrides: Any) -> MagicMock:
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


class _InMemoryInboxStore:
    """Mirrors the D1ClawTaskAlertStore surface the inbox routes actually call.

    Includes the `_get_*_locked` helpers, because the status route uses them for
    its non-disclosing 404 decision.
    """

    def __init__(self) -> None:
        self.tasks: dict[str, ClawFollowupTask] = {}
        self.alerts: dict[str, ClawAlert] = {}
        self.status_writes = 0

    async def list_tasks(self, workspace_id, *, limit=256):
        rows = [t for t in self.tasks.values() if t.workspace_id == workspace_id]
        rows.sort(key=lambda t: t.created_at, reverse=True)
        return tuple(rows[: max(1, min(int(limit), 256))])

    async def list_alerts(self, workspace_id, *, member_id=None, limit=256):
        rows = [a for a in self.alerts.values() if a.workspace_id == workspace_id]
        if member_id is not None:
            rows = [a for a in rows if a.is_visible_to(member_id)]
        rows.sort(key=lambda a: a.created_at, reverse=True)
        return tuple(rows[: max(1, min(int(limit), 256))])

    async def _get_task_locked(self, task_id, *, workspace_id):
        task = self.tasks.get(task_id)
        return task if task is not None and task.workspace_id == workspace_id else None

    async def _get_alert_locked(self, alert_id, *, workspace_id):
        alert = self.alerts.get(alert_id)
        return alert if alert is not None and alert.workspace_id == workspace_id else None

    async def set_task_status(self, task_id, status, *, workspace_id, at=None):
        task = await self._get_task_locked(task_id, workspace_id=workspace_id)
        if task is None:
            raise ClawMemoryError("task not found in workspace")
        self.status_writes += 1
        updated = task.with_status(status, at=at or datetime.now(timezone.utc))
        self.tasks[task_id] = updated
        return updated

    async def set_alert_status(self, alert_id, status, *, workspace_id, at=None):
        alert = await self._get_alert_locked(alert_id, workspace_id=workspace_id)
        if alert is None:
            raise ClawMemoryError("alert not found in workspace")
        self.status_writes += 1
        updated = alert.with_status(status, at=at or datetime.now(timezone.utc))
        self.alerts[alert_id] = updated
        return updated


def _seed_task(
    store: _InMemoryInboxStore,
    task_id: str,
    *,
    workspace_id: str = _OWN_TENANT,
    member_id: str = SIGNED_IN_USER_ID,
    status: ClawTaskStatus = ClawTaskStatus.OPEN,
) -> ClawFollowupTask:
    task = ClawFollowupTask(
        task_id=task_id,
        workspace_id=workspace_id,
        member_id=member_id,
        title="Follow up with vendor",
        status=status,
        created_at=datetime.now(timezone.utc),
    )
    store.tasks[task_id] = task
    return task


def _seed_alert(
    store: _InMemoryInboxStore,
    alert_id: str,
    *,
    workspace_id: str = _OWN_TENANT,
    visible_to: tuple[str, ...] = (),
) -> ClawAlert:
    alert = ClawAlert(
        alert_id=alert_id,
        workspace_id=workspace_id,
        kind=ClawAlertKind.FOLLOWUP_DUE,
        severity=ClawAlertSeverity.WARN,
        title="Quote follow-up is due",
        created_at=datetime.now(timezone.utc),
        status=ClawAlertStatus.ACTIVE,
        visible_to_members=tuple(visible_to),
    )
    store.alerts[alert_id] = alert
    return alert


def _client(
    store: Any,
    *,
    user_id: str = SIGNED_IN_USER_ID,
    tenant_id: str = _OWN_TENANT,
) -> TestClient:
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


def _anonymous_client(store: Any) -> TestClient:
    settings = _google_settings()
    app = create_app(settings=settings, history_store=MagicMock(), claw_task_alert_store=store)
    app.state.identity_shadow_store = _make_identity_shadow_store()
    app.state.control_plane_identity_authority = _make_authority()
    return TestClient(app, base_url="https://chat.example.test")


def _assert_no_store_headers(response) -> None:
    for header, expected in _NO_STORE_EXPECTED.items():
        assert response.headers.get(header) == expected, (header, dict(response.headers))


# ── 1. authentication ──────────────────────────────────────────────────────


def test_anonymous_callers_are_rejected_on_both_verbs() -> None:
    store = _InMemoryInboxStore()
    client = _anonymous_client(store)
    listed = client.get(LIST_TASKS)
    patched = client.patch(
        f"{LIST_TASKS}/task-1", json={"status": "done"}
    )
    assert listed.status_code == 401
    assert patched.status_code == 401
    assert listed.json()["error"]["code"] == "unauthorized"
    _assert_no_store_headers(listed)
    _assert_no_store_headers(patched)


def test_anonymous_requests_never_reach_the_store() -> None:
    store = MagicMock()
    store.list_tasks = AsyncMock(side_effect=AssertionError("store must not be touched"))
    store.list_alerts = AsyncMock(side_effect=AssertionError("store must not be touched"))
    client = _anonymous_client(store)
    assert client.get(LIST_TASKS).status_code == 401
    assert client.get(LIST_ALERTS).status_code == 401
    store.list_tasks.assert_not_awaited()
    store.list_alerts.assert_not_awaited()


# ── 2. unknown kind is not disclosed ───────────────────────────────────────


@pytest.mark.parametrize("kind", ["bogus", "task", "TASKS", "Tasks"])
def test_unknown_kind_is_not_disclosed(kind: str) -> None:
    store = _InMemoryInboxStore()
    client = _client(store)
    response = client.get(f"/api/claw/inbox/{kind}")
    assert response.status_code == 404
    _assert_no_store_headers(response)


@pytest.mark.parametrize("suffix", ["", "a/b"])
def test_malformed_inbox_paths_never_reach_the_handler(suffix: str) -> None:
    # The router rejects these before the handler runs, so they cannot disclose
    # store state either way. They carry no no-store headers, which is exactly
    # why the handler-level 404 above is asserted separately.
    store = _InMemoryInboxStore()
    _seed_task(store, "task-1")
    client = _client(store)
    response = client.get(f"/api/claw/inbox/{suffix}")
    assert response.status_code == 404


# ── 3. non-disclosing foreign vs missing ───────────────────────────────────


def test_foreign_and_missing_tasks_share_one_non_disclosing_404() -> None:
    store = _InMemoryInboxStore()
    _seed_task(store, "foreign-task", workspace_id=_FOREIGN_TENANT)
    client = _client(store)

    foreign = client.patch(f"{LIST_TASKS}/foreign-task", json={"status": "done"})
    missing = client.patch(f"{LIST_TASKS}/never-existed", json={"status": "done"})

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert store.status_writes == 0


def test_foreign_and_missing_alerts_share_one_non_disclosing_404() -> None:
    store = _InMemoryInboxStore()
    _seed_alert(store, "foreign-alert", workspace_id=_FOREIGN_TENANT)
    client = _client(store)

    foreign = client.patch(f"{LIST_ALERTS}/foreign-alert", json={"status": "dismissed"})
    missing = client.patch(f"{LIST_ALERTS}/never-existed", json={"status": "dismissed"})

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert store.status_writes == 0


# ── 4. member scoping inside one workspace ─────────────────────────────────


def test_tasks_from_another_member_are_not_listed() -> None:
    store = _InMemoryInboxStore()
    _seed_task(store, "mine", member_id=SIGNED_IN_USER_ID)
    _seed_task(store, "theirs", member_id=OTHER_USER_ID)
    client = _client(store)

    response = client.get(LIST_TASKS)
    assert response.status_code == 200
    ids = [item["task_id"] for item in response.json()["items"]]
    assert ids == ["mine"]


def test_another_members_task_cannot_be_patched() -> None:
    store = _InMemoryInboxStore()
    _seed_task(store, "theirs", member_id=OTHER_USER_ID)
    client = _client(store)

    response = client.patch(f"{LIST_TASKS}/theirs", json={"status": "done"})
    assert response.status_code == 404
    assert store.status_writes == 0


def test_alerts_are_member_scoped_by_visibility() -> None:
    store = _InMemoryInboxStore()
    _seed_alert(store, "for-me", visible_to=(SIGNED_IN_USER_ID,))
    _seed_alert(store, "for-them", visible_to=(OTHER_USER_ID,))
    client = _client(store)

    response = client.get(LIST_ALERTS)
    assert response.status_code == 200
    ids = [item["alert_id"] for item in response.json()["items"]]
    assert ids == ["for-me"]


# ── 5. bounded limit ───────────────────────────────────────────────────────


def test_limit_is_clamped_to_the_declared_maximum() -> None:
    store = _InMemoryInboxStore()
    for index in range(3):
        _seed_task(store, f"task-{index}")
    client = _client(store)

    response = client.get(LIST_TASKS, params={"limit": 9999})
    assert response.status_code == 200
    assert response.json()["limit"] == 50


@pytest.mark.parametrize("limit", ["abc", "0", "-1", "1.5", ""])
def test_non_positive_or_non_integer_limits_are_rejected(limit: str) -> None:
    store = _InMemoryInboxStore()
    client = _client(store)
    response = client.get(LIST_TASKS, params={"limit": limit})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_limit"
    _assert_no_store_headers(response)


# ── 6. fail closed without a store ─────────────────────────────────────────


def test_missing_store_fails_closed_on_read() -> None:
    client = _client(None)
    response = client.get(LIST_TASKS)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "inbox_unavailable"
    assert "items" not in response.json()
    _assert_no_store_headers(response)


def test_missing_store_fails_closed_on_write() -> None:
    client = _client(None)
    response = client.patch(f"{LIST_TASKS}/task-1", json={"status": "done"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "inbox_unavailable"


def test_store_read_failure_never_returns_a_success_shape() -> None:
    store = MagicMock()
    store.list_tasks = AsyncMock(side_effect=RuntimeError("d1 exploded"))
    client = _client(store)
    response = client.get(LIST_TASKS)
    assert response.status_code == 503
    assert response.json()["ok"] is False
    assert response.json()["error"]["code"] == "inbox_read_failed"
    assert "items" not in response.json()


# ── 7. payload validation ──────────────────────────────────────────────────


def test_non_json_content_type_is_rejected() -> None:
    store = _InMemoryInboxStore()
    _seed_task(store, "task-1")
    client = _client(store)
    response = client.patch(
        f"{LIST_TASKS}/task-1",
        content="status=done",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"


def test_malformed_json_is_rejected() -> None:
    store = _InMemoryInboxStore()
    _seed_task(store, "task-1")
    client = _client(store)
    response = client.patch(
        f"{LIST_TASKS}/task-1",
        content="{not json",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_json"


def test_oversized_body_is_rejected() -> None:
    store = _InMemoryInboxStore()
    _seed_task(store, "task-1")
    client = _client(store)
    response = client.patch(
        f"{LIST_TASKS}/task-1",
        content='{"status": "' + ("x" * 5000) + '"}',
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_payload"


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "done", "extra": 1},
        {"status": 123},
        {"state": "done"},
        {},
        [],
        "done",
    ],
)
def test_unexpected_payload_shapes_are_rejected(payload: Any) -> None:
    store = _InMemoryInboxStore()
    _seed_task(store, "task-1")
    client = _client(store)
    response = client.patch(f"{LIST_TASKS}/task-1", json=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_payload"
    assert store.status_writes == 0


def test_undeclared_status_enum_is_rejected() -> None:
    store = _InMemoryInboxStore()
    _seed_task(store, "task-1")
    client = _client(store)
    response = client.patch(f"{LIST_TASKS}/task-1", json={"status": "deleted"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_status"
    assert store.status_writes == 0


# ── 8. the write path stays reversible and bounded ─────────────────────────


def test_status_write_is_reversible_and_uses_only_declared_values() -> None:
    store = _InMemoryInboxStore()
    _seed_task(store, "task-1")
    client = _client(store)

    done = client.patch(f"{LIST_TASKS}/task-1", json={"status": "done"})
    assert done.status_code == 200
    assert done.json()["item"]["status"] == "done"
    _assert_no_store_headers(done)

    reopened = client.patch(f"{LIST_TASKS}/task-1", json={"status": "open"})
    assert reopened.status_code == 200
    assert reopened.json()["item"]["status"] == "open"
    assert store.status_writes == 2


def test_alert_status_write_is_reversible() -> None:
    store = _InMemoryInboxStore()
    _seed_alert(store, "alert-1", visible_to=(SIGNED_IN_USER_ID,))
    client = _client(store)

    dismissed = client.patch(f"{LIST_ALERTS}/alert-1", json={"status": "dismissed"})
    assert dismissed.status_code == 200
    assert dismissed.json()["item"]["status"] == "dismissed"

    restored = client.patch(f"{LIST_ALERTS}/alert-1", json={"status": "active"})
    assert restored.status_code == 200
    assert restored.json()["item"]["status"] == "active"


# ── 9. no background authority is reachable from the seam ──────────────────


def test_inbox_routes_do_not_create_tables_or_dispatch() -> None:
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "app" / "claw_inbox_routes.py"
    ).read_text(encoding="utf-8")
    for forbidden in ("CREATE TABLE", "ALTER TABLE", "scheduler", "connector.write"):
        assert forbidden not in source
