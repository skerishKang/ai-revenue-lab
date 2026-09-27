"""#3094 — end-to-end: the ACTUAL canonical broker entrypoint behind the panel.

CENTRAL second-review requirement: the integration proof must instantiate or
call the **actual canonical broker Worker/service entrypoint** — not a
test-only object whose sole purpose is to provide ``device_truth``.

This test therefore boots the real
``packages/padiem-control-plane/local_agent_broker_worker.py`` module (with the
same ``workers`` runtime stub harness the control-plane suite uses), builds the
real ``LocalAgentBrokerDurableObject`` over SQLite storage, drives the real
register → open-session → heartbeat write paths, binds the real ``Default``
gateway to that live object through the Durable Object namespace stub, and then
composes the B62 app exactly like ``worker.py`` does:

    real LocalAgentBrokerDurableObject (SQLite state)
        -> real Default gateway (device_truth RPC)
        -> LOCAL_AGENT_BROKER_AUTHORITY_SERVICE binding
        -> worker.py composition lines
        -> CanonicalClawLocalAccessTruthSource (ONLINE via #3080 rule)
        -> GET /api/claw/local-access (authenticated)

    ACTUAL_BROKER_ENTRYPOINT_HAS_PROJECTION_API=YES
    B62_COMPOSES_THAT_API=YES
    SERVER_ONLINE_TO_WEB_CONNECTED=YES
    INVALID_SESSION_OR_HEARTBEAT_CANNOT_PROJECT_ONLINE=YES
    OWNER_SCOPE_SERVER_DERIVED=YES
    HANDOFF_OPAQUE=YES
    SECOND_DEVICE_LIFECYCLE_AUTHORITY=0
    PRODUCTION_MUTATION=0
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sqlite3
import sys
import types
from unittest.mock import MagicMock

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.claw_local_access_composition import build_claw_local_access_source_with_diagnostic
from app.claw_local_access_routes import CLAW_LOCAL_ACCESS_PATH
from app.config import Settings
from app.main import create_app
from padiem_control_plane.local_agent_broker_http import DurableLocalAgentSessionRecord

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONTROL_PLANE_ROOT = _REPO_ROOT / "packages" / "padiem-control-plane"
if str(_CONTROL_PLANE_ROOT) not in sys.path:
    sys.path.insert(0, str(_CONTROL_PLANE_ROOT))

# The control-plane worker module imports the ``workers`` runtime module, which
# only exists inside a Cloudflare Workers Python runtime. The same stub harness
# the control-plane suite uses keeps this a plain-Python test.
if "workers" not in sys.modules:
    class _FakeResponse:
        def __init__(self, body="", *, status=200, headers=None):
            self.body = body
            self.status = status
            self.headers = headers or {}

    class _FakeWorkerEntrypoint:
        def __init__(self, env=None):
            self.env = env

    class _FakeDurableObject:
        def __init__(self, ctx, env):
            self.ctx = ctx
            self.env = env

    _workers = types.ModuleType("workers")
    _workers.Response = _FakeResponse
    _workers.WorkerEntrypoint = _FakeWorkerEntrypoint
    _workers.DurableObject = _FakeDurableObject
    sys.modules["workers"] = _workers

_WORKER_SPEC = importlib.util.spec_from_file_location(
    "padiem_b3094_canonical_broker_worker_it",
    _CONTROL_PLANE_ROOT / "local_agent_broker_worker.py",
)
assert _WORKER_SPEC is not None and _WORKER_SPEC.loader is not None
broker_worker = importlib.util.module_from_spec(_WORKER_SPEC)
sys.modules[_WORKER_SPEC.name] = broker_worker
_WORKER_SPEC.loader.exec_module(broker_worker)


BASE_URL = "https://chat.example.test"
# The B62 session identity is the device's account_ref on this seam: the
# composed pairing path registers the device under the signed-in owner's
# server identity, and the projection passes it through unchanged.
OWNER_ID = "usr_3094_e2e_owner"
OTHER_OWNER_ID = "usr_3094_e2e_other"
WORKSPACE_REF = "ws_3094_e2e"
AUTHORITY_REF = "control-plane.local-agent-broker.b3094-it.v1"
PEPPER = "cloudflare-do-b3094-integration-pepper"
CREDENTIAL = b"cloudflare-do-b3094-integration-credential"
BINDING_REF = "bind.3094.it.1"
DEVICE_ID = "device.3094.it.1"
SESSION_ID = "sess.3094.it.1"
BROKER_AUTHORITY_BINDING_NAME = "LOCAL_AGENT_BROKER_AUTHORITY_SERVICE"
CONVERSATION_ID = "conv_3094_e2e_01"


class _Cursor:
    def __init__(self, rows: list[dict], rows_written: int) -> None:
        self._rows = rows
        self.rowsWritten = rows_written

    def toArray(self):
        return list(self._rows)

    def one(self):
        if len(self._rows) != 1:
            raise RuntimeError("expected exactly one row")
        return self._rows[0]


class _Sql:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def exec(self, query: str, *bindings):
        cursor = self.connection.execute(query, bindings)
        rows: list[dict] = []
        if cursor.description is not None:
            names = [item[0] for item in cursor.description]
            rows = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
        rows_written = cursor.rowcount if cursor.rowcount >= 0 else 0
        return _Cursor(rows, rows_written)


class _Storage:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:", isolation_level=None)
        self.sql = _Sql(self.connection)

    def transactionSync(self, callback):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            value = callback()
            self.connection.execute("COMMIT")
            return value
        except Exception:
            self.connection.execute("ROLLBACK")
            raise


class _Context:
    def __init__(self, storage: _Storage) -> None:
        self.storage = storage


class _Namespace:
    """The DO namespace stub, bound to the REAL durable object instance."""

    def __init__(self) -> None:
        self.durable_object = None

    def idFromName(self, name: str):
        return f"do::{name}"

    def get(self, object_id: str):
        return self.durable_object


class _Env:
    def __init__(self, namespace: _Namespace) -> None:
        self.LOCAL_AGENT_BROKER_AUTHORITY_REF = AUTHORITY_REF
        self.LOCAL_AGENT_BROKER_PEPPER = PEPPER
        self.LOCAL_AGENT_BROKER_STATE = namespace


def _make_real_broker() -> object:
    """The real DO + real Default gateway, bound together like the runtime."""

    namespace = _Namespace()
    env = _Env(namespace)
    durable_object = broker_worker.LocalAgentBrokerDurableObject(_Context(_Storage()), env)
    namespace.durable_object = durable_object
    return durable_object


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _provision_live_device(durable_object, *, now: datetime) -> None:
    """Drive the real register → open-session → heartbeat write paths."""

    registered = asyncio.run(
        durable_object.register_binding(
            {
                "binding_ref": BINDING_REF,
                "device_id": DEVICE_ID,
                "account_ref": OWNER_ID,
                "workspace_ref": WORKSPACE_REF,
                "credential_b64": base64.b64encode(CREDENTIAL).decode("ascii"),
                "now": _iso(now - timedelta(minutes=2)),
            }
        )
    )
    assert registered["ok"] is True
    opened = asyncio.run(
        durable_object.open_session(
            {
                "session_id": SESSION_ID,
                "binding_ref": BINDING_REF,
                "credential_b64": base64.b64encode(CREDENTIAL).decode("ascii"),
                "account_ref": OWNER_ID,
                "workspace_ref": WORKSPACE_REF,
                "now": _iso(now - timedelta(minutes=1)),
                "ttl_seconds": 900,
            }
        )
    )
    assert opened["ok"] is True
    session = opened["session"]
    durable_object.http_state.save_session(
        DurableLocalAgentSessionRecord(
            session_id=session["session_id"],
            binding_ref=session["binding_ref"],
            device_id=session["device_id"],
            account_ref=session["account_ref"],
            workspace_ref=session["workspace_ref"],
            credential_generation=session["credential_generation"],
            issued_at=datetime.fromisoformat(session["issued_at"]),
            expires_at=datetime.fromisoformat(session["expires_at"]),
        )
    )
    durable_object.http_state.record_last_seen(
        SESSION_ID, seen_at=now - timedelta(seconds=55)
    )


def _b62_app_with_real_broker(*, namespace: _Namespace):
    """create_app() exactly like worker.py, composed against the real
    Default gateway bound to the real durable object."""

    default_gateway = broker_worker.Default(_Env(namespace))
    settings = Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url=BASE_URL,
        session_secret="claw-3094-broker-integration-session-secret-not-real",
        session_max_age_seconds=3600,
    )
    app = create_app(settings, history_store=MagicMock())
    # --- verbatim worker.py composition root lines ---
    source, diagnostic = build_claw_local_access_source_with_diagnostic(
        {BROKER_AUTHORITY_BINDING_NAME: default_gateway}
    )
    if source is not None:
        app.state.claw_local_access_source = source
    # --- end verbatim lines ---
    assert diagnostic is None, "the real canonical broker must compose"
    return app, settings


async def _authorized_get(
    app, settings, *, user_id: str, params: dict[str, str] | None = None
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        client.cookies.set(SESSION_COOKIE, create_session_token(settings, user_id))
        return await client.get(CLAW_LOCAL_ACCESS_PATH, params=params)


def test_actual_canonical_broker_entrypoint_serves_the_b62_panel_end_to_end() -> None:
    now = datetime.now(timezone.utc)
    namespace = _Namespace()
    env = _Env(namespace)
    durable_object = broker_worker.LocalAgentBrokerDurableObject(_Context(_Storage()), env)
    namespace.durable_object = durable_object

    _provision_live_device(durable_object, now=now)
    app, settings = _b62_app_with_real_broker(namespace=namespace)

    response = asyncio.run(
        _authorized_get(app, settings, user_id=OWNER_ID, params={"conversationId": CONVERSATION_ID})
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["available"] is True
    device = body["projection"]["device"]
    # SERVER_ONLINE_TO_WEB_CONNECTED, decided by the #3080 rule inside B62 from
    # the real broker's facts: a redeemed binding + canonical session + a
    # server-owned heartbeat inside the session window.
    assert device["canonicalState"] == "online"
    assert device["state"] == "CONNECTED"
    assert device["usable"] is True
    assert body["projection"]["handoff"]["kind"] == "deep_link"
    # ACTUAL_BROKER_ENTRYPOINT_HAS_PROJECTION_API + B62_COMPOSES_THAT_API are
    # proven by construction: Default.device_truth is the real control-plane
    # entrypoint method, reached through the namespace stub.


def test_real_broker_refuses_a_foreign_owner_fail_closed() -> None:
    now = datetime.now(timezone.utc)
    namespace = _Namespace()
    env = _Env(namespace)
    durable_object = broker_worker.LocalAgentBrokerDurableObject(_Context(_Storage()), env)
    namespace.durable_object = durable_object
    _provision_live_device(durable_object, now=now)
    app, settings = _b62_app_with_real_broker(namespace=namespace)

    response = asyncio.run(
        _authorized_get(app, settings, user_id=OTHER_OWNER_ID, params={"conversationId": CONVERSATION_ID})
    )
    body = response.json()
    assert body["available"] is False
    assert body["projection"]["device"] is None
    assert OWNER_ID not in str(body)


def test_real_broker_revocation_cannot_project_online() -> None:
    now = datetime.now(timezone.utc)
    namespace = _Namespace()
    env = _Env(namespace)
    durable_object = broker_worker.LocalAgentBrokerDurableObject(_Context(_Storage()), env)
    namespace.durable_object = durable_object
    _provision_live_device(durable_object, now=now)
    revoked = asyncio.run(
        durable_object.revoke_binding({"binding_ref": BINDING_REF, "now": _iso(now)})
    )
    assert revoked["ok"] is True
    app, settings = _b62_app_with_real_broker(namespace=namespace)

    response = asyncio.run(
        _authorized_get(app, settings, user_id=OWNER_ID, params={"conversationId": CONVERSATION_ID})
    )
    device = response.json()["projection"]["device"]
    assert device["canonicalState"] == "revoked"
    assert device["state"] == "REVOKED"
    assert device["usable"] is False


def test_real_broker_without_a_live_session_cannot_project_online() -> None:
    # A binding with no session/heartbeat at all: the #3080 rule must refuse
    # ONLINE, so the panel shows OFFLINE, never a connected claim.
    now = datetime.now(timezone.utc)
    namespace = _Namespace()
    env = _Env(namespace)
    durable_object = broker_worker.LocalAgentBrokerDurableObject(_Context(_Storage()), env)
    namespace.durable_object = durable_object
    durable_object.__b3094_namespace__ = namespace
    registered = asyncio.run(
        durable_object.register_binding(
            {
                "binding_ref": BINDING_REF,
                "device_id": DEVICE_ID,
                "account_ref": OWNER_ID,
                "workspace_ref": WORKSPACE_REF,
                "credential_b64": base64.b64encode(CREDENTIAL).decode("ascii"),
                "now": _iso(now - timedelta(minutes=2)),
            }
        )
    )
    assert registered["ok"] is True
    app, settings = _b62_app_with_real_broker(namespace=namespace)

    response = asyncio.run(
        _authorized_get(app, settings, user_id=OWNER_ID, params={"conversationId": CONVERSATION_ID})
    )
    device = response.json()["projection"]["device"]
    assert device["canonicalState"] == "paired_offline"
    assert device["state"] == "OFFLINE"
    assert device["usable"] is False


def test_real_broker_credential_expiry_with_current_session_cannot_project_online(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#3094 CENTRAL third-review regression, on the real DO path.

    The overlap the review flagged: the broker's trusted clock has passed the
    binding's credential expiry (so the real device_truth RPC reports
    ``credential_expired``) while the canonical session and server-owned
    heartbeat are still current from the B62 consumer's perspective. The
    hard-coded ``PAIRED_OFFLINE`` reconstruction would have let the #3080 rule
    promote this exact shape to ONLINE / CONNECTED; the invariant refuses the
    ONLINE projection for any non-``paired_offline`` broker state.
    """

    import local_agent_broker_durable_runtime as broker_runtime

    now = datetime.now(timezone.utc)
    namespace = _Namespace()
    env = _Env(namespace)
    durable_object = broker_worker.LocalAgentBrokerDurableObject(_Context(_Storage()), env)
    namespace.durable_object = durable_object

    # Minimum credential TTL (300s) so the credential expires while the
    # session the broker just opened is still current: binding issued at
    # now-2min expires at now+3min; the session opened at now-1min is capped
    # at the credential expiry (now+3min) and the heartbeat is fresh.
    registered = asyncio.run(
        durable_object.register_binding(
            {
                "binding_ref": BINDING_REF,
                "device_id": DEVICE_ID,
                "account_ref": OWNER_ID,
                "workspace_ref": WORKSPACE_REF,
                "credential_b64": base64.b64encode(CREDENTIAL).decode("ascii"),
                "now": _iso(now - timedelta(minutes=2)),
                "credential_ttl_seconds": 300,
            }
        )
    )
    assert registered["ok"] is True
    opened = asyncio.run(
        durable_object.open_session(
            {
                "session_id": SESSION_ID,
                "binding_ref": BINDING_REF,
                "credential_b64": base64.b64encode(CREDENTIAL).decode("ascii"),
                "account_ref": OWNER_ID,
                "workspace_ref": WORKSPACE_REF,
                "now": _iso(now - timedelta(minutes=1)),
                "ttl_seconds": 900,
            }
        )
    )
    assert opened["ok"] is True
    session = opened["session"]
    assert datetime.fromisoformat(session["expires_at"]) > now, (
        "the fixture must keep the session current from the B62 perspective"
    )
    durable_object.http_state.save_session(
        DurableLocalAgentSessionRecord(
            session_id=session["session_id"],
            binding_ref=session["binding_ref"],
            device_id=session["device_id"],
            account_ref=session["account_ref"],
            workspace_ref=session["workspace_ref"],
            credential_generation=session["credential_generation"],
            issued_at=datetime.fromisoformat(session["issued_at"]),
            expires_at=datetime.fromisoformat(session["expires_at"]),
        )
    )
    durable_object.http_state.record_last_seen(
        SESSION_ID, seen_at=now - timedelta(seconds=55)
    )

    # Advance ONLY the broker's trusted clock past the credential expiry. The
    # B62 consumer keeps its real clock, so the session/heartbeat facts in the
    # envelope remain current — the exact overlap CENTRAL flagged.
    frozen_broker_now = now + timedelta(minutes=4)
    real_datetime = broker_runtime.datetime

    class _FrozenBrokerDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return frozen_broker_now if tz is None else frozen_broker_now.astimezone(tz)

    monkeypatch.setattr(broker_runtime, "datetime", _FrozenBrokerDatetime, raising=True)

    # The real Default gateway still answers through the actual entrypoint.
    default_gateway = broker_worker.Default(env)
    raw = asyncio.run(default_gateway.device_truth({"account_ref": OWNER_ID}))
    assert raw["ok"] is True and raw["available"] is True
    assert raw["device_truth"]["canonical_state"] == "credential_expired"
    assert raw["device_truth"]["session"]["session_id"] == SESSION_ID

    # Compose B62 exactly like worker.py and drive the authenticated route.
    settings = Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url=BASE_URL,
        session_secret="claw-3094-broker-integration-session-secret-not-real",
        session_max_age_seconds=3600,
    )
    app = create_app(settings, history_store=MagicMock())
    source, diagnostic = build_claw_local_access_source_with_diagnostic(
        {BROKER_AUTHORITY_BINDING_NAME: default_gateway}
    )
    assert diagnostic is None
    app.state.claw_local_access_source = source

    response = asyncio.run(
        _authorized_get(app, settings, user_id=OWNER_ID, params={"conversationId": CONVERSATION_ID})
    )
    body = response.json()
    assert body["available"] is True
    device = body["projection"]["device"]
    # BROKER_STATE=credential_expired -> the existing fail-closed mapping.
    assert device["canonicalState"] == "credential_expired"
    assert device["state"] == "ACTION_REQUIRED"
    assert device["usable"] is False
    assert device["expired"] is True
    # SERVER_ONLINE_TO_WEB_CONNECTED=NO for this state; HANDOFF_OPENABLE=NO.
    assert device["state"] != "CONNECTED"
    assert "value" not in body["projection"]["handoff"]
