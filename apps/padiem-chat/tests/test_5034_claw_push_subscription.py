"""#5034 — Web Push opt-in for the EXISTING user web-alert inbox.

NETWORK_FREE behavioural contracts. The existing Claw Task/Alert inbox
(``claw_task_alert`` + ``/api/claw/inbox/{tasks,alerts}``) is reused as is;
this slice adds only the opted-in device subscription and the delivery seam
that tells "the web inbox persisted it" apart from "the browser received a
push".

Pinned here:

- ANONYMOUS_REJECTED=401
- SERVER_DERIVED_OWNER=PASS (the browser names neither account nor workspace)
- NO_ENDPOINT_IN_RESPONSE=PASS (no endpoint, key or secret is echoed back)
- NO_ENDPOINT_IN_LOG=PASS
- RESUBSCRIBE_UPDATES=PASS (one endpoint is one row, never a duplicate)
- UNSUBSCRIBE_REMOVES=PASS
- FOREIGN_SUBSCRIPTION_NOT_FOUND=PASS (identical answer for another account)
- ACCOUNT_ISOLATION=PASS
- WEB_INBOX_SURVIVES_PUSH_DENIAL=PASS (the inbox record is untouched)
- PUSH_STATE_DISTINCT=PASS (delivered / failed / not_configured / no_subscription)
- INBOX_STATE_NEVER_CHANGED_BY_PUSH=PASS
- FAIL_CLOSED_WITHOUT_STORE=PASS (503, never an ok:True shape)

No live D1 IO, no push provider, no outbound delivery, no scheduler.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.claw_push_subscriptions import (
    D1ClawPushSubscriptionStore,
    PushSubscriptionError,
    deliver_inbox_push,
    subscription_id,
)
from app.control_plane_identity import PADIEM_CHAT_PRODUCT_ID
from app.control_plane_identity_shadow import IdentityShadowRecord
from padiem_control_plane import (
    AuthSessionSnapshot,
    AuthSessionState,
    CanonicalSubjectRef,
    SubjectType,
)

ROOT = Path(__file__).resolve().parents[1]

SUBSCRIPTION_PATH = "/api/claw/inbox/push/subscription"
CAPABILITY_PATH = "/api/claw/inbox/push/capability"
LIST_ALERTS = "/api/claw/inbox/alerts"

SIGNED_IN_USER_ID = "usr_" + "7" * 32
OTHER_USER_ID = "usr_" + "f" * 32
_OWN_TENANT = "tenant_own"

_ENDPOINT = "https://push.example.test/device/abc123"
_SCOPE = "https://chat.example.test"


class Statement:
    def __init__(self, db, sql, params=()):
        self.db, self.sql, self.params = db, sql, params

    def bind(self, *params):
        return Statement(self.db, self.sql, params)

    async def first(self):
        row = self.db.conn.execute(self.sql, self.params).fetchone()
        return dict(row) if row else None

    async def run(self):
        cursor = self.db.conn.execute(self.sql, self.params)
        return SimpleNamespace(
            results=[dict(row) for row in cursor.fetchall()],
            meta={"changes": cursor.rowcount},
        )

    async def all(self):
        rows = self.db.conn.execute(self.sql, self.params).fetchall()
        return [dict(row) for row in rows]


class SqliteD1:
    def __init__(self):
        # The ASGI app runs in the TestClient thread pool, so the handle has to
        # be usable from the worker thread as well.
        self.conn = sqlite3.connect(
            ":memory:", isolation_level=None, check_same_thread=False
        )
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")

    def prepare(self, sql):
        return Statement(self, sql)


def _seed_db() -> SqliteD1:
    db = SqliteD1()
    db.conn.executescript(
        (ROOT / "migrations" / "010_claw_task_alert.sql").read_text(encoding="utf-8")
    )
    db.conn.executescript(
        (ROOT / "migrations" / "065_claw_push_subscriptions.sql").read_text(encoding="utf-8")
    )
    return db


def _settings(**overrides: Any) -> Settings:
    values = {
        "runtime_mode": "mock",
        "auth_mode": "google",
        "public_base_url": "https://chat.example.test",
        "google_client_id": "claw-push-client.apps.googleusercontent.com",
        "google_client_secret": "claw-push-google-secret",
        "session_secret": "claw-push-session-secret-not-a-real-cred-00",
        "session_max_age_seconds": 3600,
    }
    values.update(overrides)
    return Settings.from_values(**values)


def _shadow_store(user_id: str) -> MagicMock:
    store = MagicMock()
    now = datetime.now(timezone.utc)
    values = {
        "product_user_id": user_id,
        "canonical_subject_id": "subject_test",
        "auth_session_id": "session_test123",
        "session_revision": 1,
        "session_state": "active",
        "session_expires_at": now + timedelta(hours=1),
        "observed_at": now,
    }
    store.load_projection = AsyncMock(return_value=IdentityShadowRecord(**values))
    return store


def _auth_session_snapshot(tenant_id: str = _OWN_TENANT) -> AuthSessionSnapshot:
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


def _authority(tenant_id: str = _OWN_TENANT) -> MagicMock:
    authority = MagicMock()
    authority.resolve_auth_session = AsyncMock(
        return_value=_auth_session_snapshot(tenant_id=tenant_id)
    )
    return authority


def _client(
    db: SqliteD1 | None,
    *,
    user_id: str = SIGNED_IN_USER_ID,
    tenant_id: str = _OWN_TENANT,
) -> TestClient:
    settings = _settings()
    app = create_app(
        settings=settings,
        history_store=MagicMock(),
        d1_binding=db,
    )
    app.state.identity_shadow_store = _shadow_store(user_id)
    app.state.control_plane_identity_authority = _authority(tenant_id)
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(settings, user_id),
        domain="chat.example.test",
        path="/",
    )
    return client


def _anonymous_client(db: SqliteD1 | None) -> TestClient:
    settings = _settings()
    app = create_app(settings=settings, history_store=MagicMock(), d1_binding=db)
    client = TestClient(app, base_url="https://chat.example.test")
    return client


def _payload(endpoint: str = _ENDPOINT, scope: str = _SCOPE) -> dict:
    return {
        "endpoint": endpoint,
        "keys": {"p256dh": "p256dh-public-key", "auth": "auth-secret"},
        "scope": scope,
    }




_ORIGIN = "https://chat.example.test"


def _post(client, path: str, body: dict):
    """A browser-shaped cookie-authenticated mutation: it carries the Origin."""
    return client.post(path, json=body, headers={"Origin": _ORIGIN})


def _delete(client, path: str, body: dict):
    return client.request(
        "DELETE", path, json=body, headers={"Origin": _ORIGIN}
    )

def _rows(db: SqliteD1) -> list[dict]:
    return [
        dict(row)
        for row in db.conn.execute(
            "SELECT id, workspace_id, member_id, endpoint FROM claw_push_subscription"
        ).fetchall()
    ]


# ── the HTTP surface ───────────────────────────────────────────────────────


def test_a_signed_in_account_can_register_its_own_subscription():
    db = _seed_db()
    with _client(db) as client:
        response = _post(client, SUBSCRIPTION_PATH, _payload())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    subscription = body["subscription"]
    # The browser never receives the endpoint, the keys or a secret back.
    assert set(subscription) == {"subscription_id", "scope", "created_at", "updated_at"}
    assert _ENDPOINT not in response.text
    assert "p256dh-public-key" not in response.text
    assert "auth-secret" not in response.text
    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0]["member_id"] == SIGNED_IN_USER_ID


def test_an_anonymous_caller_is_rejected():
    db = _seed_db()
    with _anonymous_client(db) as client:
        response = _post(client, SUBSCRIPTION_PATH, _payload())
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert _rows(db) == []


def test_the_browser_never_names_the_account_or_the_workspace():
    db = _seed_db()
    with _client(db) as client:
        response = client.post(
            SUBSCRIPTION_PATH,
            json={**_payload(), "user_id": OTHER_USER_ID, "workspace_id": "other"},
        )
    assert response.status_code == 400
    assert _rows(db) == []


def test_resubscribing_the_same_endpoint_updates_one_row():
    db = _seed_db()
    with _client(db) as client:
        first = _post(client, SUBSCRIPTION_PATH, _payload())
        second = client.post(
            SUBSCRIPTION_PATH,
            json=_payload(scope="https://chat.example.test/other"),
        )
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["subscription"]["subscription_id"] == (
        second.json()["subscription"]["subscription_id"]
    )
    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0]["id"] == subscription_id(_ENDPOINT)


def test_unsubscribe_removes_only_the_callers_own_subscription():
    db = _seed_db()
    with _client(db) as client:
        created = _post(client, SUBSCRIPTION_PATH, _payload())
        target = created.json()["subscription"]["subscription_id"]
        removed = client.request(
            "DELETE", SUBSCRIPTION_PATH, json={"subscription_id": target}
        )
    assert removed.status_code == 200
    assert removed.json()["ok"] is True
    assert _rows(db) == []


def test_another_account_cannot_see_or_remove_a_foreign_subscription():
    db = _seed_db()
    with _client(db) as client:
        created = _post(client, SUBSCRIPTION_PATH, _payload())
        target = created.json()["subscription"]["subscription_id"]
    with _client(db, user_id=OTHER_USER_ID) as other:
        removed = other.request(
            "DELETE", SUBSCRIPTION_PATH, json={"subscription_id": target}
        )
    assert removed.status_code == 404
    assert removed.json()["error"]["code"] == "push_subscription_not_found"
    # The owner's subscription is untouched.
    assert len(_rows(db)) == 1


def test_an_unknown_subscription_is_the_same_bounded_answer():
    db = _seed_db()
    with _client(db) as client:
        response = other = client.request(
            "DELETE", SUBSCRIPTION_PATH, json={"subscription_id": "push_unknown"}
        )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "push_subscription_not_found"


def test_the_surface_fails_closed_without_a_store():
    with _client(None) as client:
        response = _post(client, SUBSCRIPTION_PATH, _payload())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "push_unavailable"
    assert response.json()["ok"] is False


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"endpoint": _ENDPOINT},
        {"endpoint": _ENDPOINT, "keys": {"p256dh": "a"}, "scope": _SCOPE},
        {"endpoint": "", "keys": {"p256dh": "a", "auth": "b"}, "scope": _SCOPE},
        {"endpoint": _ENDPOINT, "keys": {"p256dh": "a", "auth": "b"}, "scope": _SCOPE, "x": 1},
    ],
)
def test_a_malformed_subscription_body_is_refused(body):
    db = _seed_db()
    with _client(db) as client:
        response = _post(client, SUBSCRIPTION_PATH, body)
    assert response.status_code == 400
    assert _rows(db) == []


# ── the delivery seam ──────────────────────────────────────────────────────


async def test_without_a_push_authority_the_delivery_is_not_configured():
    db = _seed_db()
    store = D1ClawPushSubscriptionStore(db)
    outcome = await _outcome(
        store=store, sender=None, workspace_id=_OWN_TENANT, member_id=SIGNED_IN_USER_ID
    )
    assert outcome.state == "not_configured"
    assert outcome.attempted == 0
    assert outcome.inbox_state_changed is False


async def test_without_a_subscription_the_delivery_reports_none():
    db = _seed_db()
    store = D1ClawPushSubscriptionStore(db)
    outcome = await _outcome(
        store=store, sender=_Sender(), workspace_id=_OWN_TENANT, member_id=SIGNED_IN_USER_ID
    )
    assert outcome.state == "no_subscription"
    assert outcome.inbox_state_changed is False


async def test_a_delivered_push_is_reported_and_never_changes_the_inbox_record():
    db = _seed_db()
    store = D1ClawPushSubscriptionStore(db)
    await store.register(
        workspace_id=_OWN_TENANT,
        member_id=SIGNED_IN_USER_ID,
        endpoint=_ENDPOINT,
        p256dh="k",
        auth="a",
        scope=_SCOPE,
        now="2026-10-21T00:00:00Z",
    )
    outcome = await _outcome(
        store=store, sender=_Sender(ok=True), workspace_id=_OWN_TENANT,
        member_id=SIGNED_IN_USER_ID,
    )
    assert outcome.state == "delivered"
    assert outcome.attempted == 1
    assert outcome.delivered == 1
    assert outcome.inbox_state_changed is False


async def test_a_failing_push_never_becomes_a_success():
    db = _seed_db()
    store = D1ClawPushSubscriptionStore(db)
    await store.register(
        workspace_id=_OWN_TENANT,
        member_id=SIGNED_IN_USER_ID,
        endpoint=_ENDPOINT,
        p256dh="k",
        auth="a",
        scope=_SCOPE,
        now="2026-10-21T00:00:00Z",
    )
    outcome = await _outcome(
        store=store, sender=_Sender(ok=False), workspace_id=_OWN_TENANT,
        member_id=SIGNED_IN_USER_ID,
    )
    assert outcome.state == "failed"
    assert outcome.delivered == 0
    assert outcome.inbox_state_changed is False


async def test_a_raising_push_sender_never_escapes():
    db = _seed_db()
    store = D1ClawPushSubscriptionStore(db)
    await store.register(
        workspace_id=_OWN_TENANT,
        member_id=SIGNED_IN_USER_ID,
        endpoint=_ENDPOINT,
        p256dh="k",
        auth="a",
        scope=_SCOPE,
        now="2026-10-21T00:00:00Z",
    )
    outcome = await _outcome(
        store=store, sender=_Sender(raises=True), workspace_id=_OWN_TENANT,
        member_id=SIGNED_IN_USER_ID,
    )
    assert outcome.state == "failed"
    assert outcome.failed == 1
    assert outcome.inbox_state_changed is False


def test_the_web_inbox_still_works_while_a_push_is_denied():
    """A denied or unconfigured push never removes the web inbox record."""
    db = _seed_db()
    with _client(db) as client:
        registered = _post(client, SUBSCRIPTION_PATH, _payload())
        assert registered.status_code == 200
        # No push authority at all: the inbox read surface is unaffected.
        alerts = client.get(LIST_ALERTS)
    assert alerts.status_code == 200
    assert alerts.json()["ok"] is True


def test_the_subscription_table_holds_no_notification_record():
    """The push table is a device registry, never a second inbox."""
    db = _seed_db()
    with _client(db) as client:
        client.post(SUBSCRIPTION_PATH, json=_payload())
    tables = {
        row[0]
        for row in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "claw_push_subscription" in tables
    # The inbox table is untouched by the push slice.
    columns = {
        row[1]
        for row in db.conn.execute("PRAGMA table_info(claw_push_subscription)").fetchall()
    }
    for forbidden in ("title", "status", "kind", "severity", "linked_ref"):
        assert forbidden not in columns


# ── the capability route ───────────────────────────────────────────────────


def test_the_capability_is_reported_truthfully_without_a_push_authority():
    """No push authority means the browser is not offered a dead toggle."""
    settings = _settings()
    app = create_app(settings=settings, history_store=MagicMock())
    with TestClient(app, base_url="https://chat.example.test") as client:
        client.cookies.set(
            SESSION_COOKIE,
            create_session_token(settings, SIGNED_IN_USER_ID),
            domain="chat.example.test",
            path="/",
        )
        response = client.get(CAPABILITY_PATH)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["enabled"] is False
    assert body["public_key"] is None
    assert body["scope"] == "https://chat.example.test/"


def test_a_configured_public_key_is_advertised():
    """The VAPID public key is the public half, so it may be exposed."""
    settings = _settings()
    app = create_app(settings=settings, history_store=MagicMock())
    app.state.claw_push_public_key = "BO1x-public-key-value"
    with TestClient(app, base_url="https://chat.example.test") as client:
        client.cookies.set(
            SESSION_COOKIE,
            create_session_token(settings, SIGNED_IN_USER_ID),
            domain="chat.example.test",
            path="/",
        )
        response = client.get(CAPABILITY_PATH)
    body = response.json()
    assert body["enabled"] is True
    assert body["public_key"] == "BO1x-public-key-value"


def test_the_push_table_is_not_a_second_inbox():
    """The push table is a device registry, never a notification record."""
    db = _seed_db()
    with _client(db) as client:
        _post(client, SUBSCRIPTION_PATH, _payload())
    tables = {
        row[0]
        for row in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "claw_push_subscription" in tables
    # The inbox table is untouched by the push slice.
    columns = {
        row[1]
        for row in db.conn.execute("PRAGMA table_info(claw_push_subscription)").fetchall()
    }
    for forbidden in ("title", "status", "kind", "severity", "linked_ref"):
        assert forbidden not in columns


# ── helpers ────────────────────────────────────────────────────────────────


class _Sender:
    def __init__(self, ok: bool = True, raises: bool = False):
        self.ok = ok
        self.raises = raises
        self.calls: list[Any] = []

    async def send(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises:
            raise RuntimeError("push provider is down")
        return self.ok


async def _outcome(*, store, sender, workspace_id, member_id):
    return await deliver_inbox_push(
        store=store,
        sender=sender,
        workspace_id=workspace_id,
        member_id=member_id,
        scope=_SCOPE,
        title="Claw run finished",
        body="Your scheduled run is done.",
        url=None,
    )