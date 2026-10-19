"""#4139 — end-to-end: the real broker directory feeds the EXISTING ONLINE rule.

This is the multi-device counterpart of
``test_b62_3094_canonical_broker_device_truth_integration.py``. It boots the
real ``packages/padiem-control-plane/local_agent_broker_worker.py`` entrypoint
over SQLite storage, drives the real register → open-session → heartbeat →
revoke write paths, calls the **real** ``device_directory`` RPC, and then feeds
each returned device's facts into the **real** B62 consumer seam
(``CanonicalClawLocalAccessTruthSource``) and the **real** Web-vocabulary
translation (``app.claw_local_projection``).

The point is the single-authority boundary: the broker directory reports only
the never-online canonical vocabulary plus the binding/session/heartbeat facts,
and CONNECTED/usable is produced *only* by the existing
``kagent.local_agent_server_projection`` rule — never by the broker, and never
for a revoked, expired or session-less device.

    ACTUAL_BROKER_ENTRYPOINT_HAS_DIRECTORY_API=YES
    BROKER_DIRECTORY_NEVER_CLAIMS_ONLINE=YES
    EXISTING_ONLINE_RULE_REUSED_PER_DEVICE=YES
    REVOKED_OR_EXPIRED_CANNOT_PROJECT_ONLINE=YES
    SINGLE_WEB_VOCABULARY_TRANSLATION_REUSED=YES
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

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONTROL_PLANE_ROOT = _REPO_ROOT / "packages" / "padiem-control-plane"
_APP_ROOT = _REPO_ROOT / "apps" / "padiem-chat"
for _path in (_CONTROL_PLANE_ROOT, _APP_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

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
    "padiem_b4139_canonical_broker_worker_it",
    _CONTROL_PLANE_ROOT / "local_agent_broker_worker.py",
)
assert _WORKER_SPEC is not None and _WORKER_SPEC.loader is not None
broker_worker = importlib.util.module_from_spec(_WORKER_SPEC)
sys.modules[_WORKER_SPEC.name] = broker_worker
_WORKER_SPEC.loader.exec_module(broker_worker)

import local_agent_broker_durable_runtime as broker_runtime  # noqa: E402
from app.claw_local_access_source import CanonicalClawLocalAccessTruthSource  # noqa: E402
from app.claw_local_projection import translate_device_lifecycle  # noqa: E402
from padiem_control_plane.local_agent_broker_http import DurableLocalAgentSessionRecord  # noqa: E402


OWNER_ID = "usr_4139_dir_owner"
OTHER_OWNER_ID = "usr_4139_dir_other"
WORKSPACE_REF = "ws_4139_dir"
AUTHORITY_REF = "control-plane.local-agent-broker.b4139-it.v1"
PEPPER = "cloudflare-do-b4139-integration-pepper"
CREDENTIAL = b"cloudflare-do-b4139-integration-credential"


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


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _make_real_broker():
    namespace = _Namespace()
    env = _Env(namespace)
    durable_object = broker_worker.LocalAgentBrokerDurableObject(_Context(_Storage()), env)
    namespace.durable_object = durable_object
    return namespace, env, durable_object


def _register(durable_object, *, device_id, binding_ref, issued_at, ttl=None, account_ref=OWNER_ID):
    payload = {
        "binding_ref": binding_ref,
        "device_id": device_id,
        "account_ref": account_ref,
        "workspace_ref": WORKSPACE_REF,
        "credential_b64": base64.b64encode(CREDENTIAL).decode("ascii"),
        "now": _iso(issued_at),
    }
    if ttl is not None:
        payload["credential_ttl_seconds"] = ttl
    registered = asyncio.run(durable_object.register_binding(payload))
    assert registered["ok"] is True, registered


def _open_session(durable_object, *, binding_ref, session_id, issued_at, heartbeat_at=None):
    opened = asyncio.run(
        durable_object.open_session(
            {
                "session_id": session_id,
                "binding_ref": binding_ref,
                "credential_b64": base64.b64encode(CREDENTIAL).decode("ascii"),
                "account_ref": OWNER_ID,
                "workspace_ref": WORKSPACE_REF,
                "now": _iso(issued_at),
                "ttl_seconds": 900,
            }
        )
    )
    assert opened["ok"] is True, opened
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
    if heartbeat_at is not None:
        durable_object.http_state.record_last_seen(session_id, seen_at=heartbeat_at)


def _provision_four_pcs(durable_object, *, now: datetime) -> None:
    """One online, one session-less, one credential-expired, one revoked PC."""

    _register(durable_object, device_id="pc-live", binding_ref="bind.live", issued_at=now - timedelta(minutes=2))
    _open_session(
        durable_object, binding_ref="bind.live", session_id="sess.live",
        issued_at=now - timedelta(minutes=1), heartbeat_at=now - timedelta(seconds=55),
    )
    _register(durable_object, device_id="pc-offline", binding_ref="bind.offline", issued_at=now - timedelta(minutes=2))
    _register(
        durable_object, device_id="pc-expired", binding_ref="bind.expired",
        issued_at=now - timedelta(minutes=2), ttl=300,
    )
    _open_session(
        durable_object, binding_ref="bind.expired", session_id="sess.expired",
        issued_at=now - timedelta(minutes=1), heartbeat_at=now - timedelta(seconds=55),
    )
    _register(durable_object, device_id="pc-revoked", binding_ref="bind.revoked", issued_at=now - timedelta(minutes=2))
    revoked = asyncio.run(
        durable_object.revoke_binding({"binding_ref": "bind.revoked", "now": _iso(now - timedelta(seconds=30))})
    )
    assert revoked["ok"] is True


class _DirectoryDevicePort:
    """Adapts one directory row to the B62 consumer's device_truth port shape."""

    def __init__(self, device: dict) -> None:
        self._device = device

    async def device_truth(self, *, owner_id: str, conversation_id: str, now: datetime):
        return {"ok": True, "available": True, "device_truth": self._device}


def _canonical_for(device: dict, *, now: datetime):
    source = CanonicalClawLocalAccessTruthSource(port=_DirectoryDevicePort(device))
    projection = asyncio.run(
        source.project_local_access(owner_id=OWNER_ID, conversation_id="conv.4139", now=now)
    )
    assert projection is not None
    return projection["canonical_state"]


def test_real_broker_directory_lists_pcs_and_defers_online_to_the_existing_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    namespace, env, durable_object = _make_real_broker()
    _provision_four_pcs(durable_object, now=now)

    # Advance ONLY the broker's trusted clock past the 300s credential TTL, so
    # pc-expired's credential is expired while the consumer still sees a current
    # session/heartbeat — the exact overlap the single-authority rule must refuse.
    pinned = now + timedelta(minutes=4)
    real_datetime = broker_runtime.datetime

    class _PinnedBrokerDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return pinned if tz is None else pinned.astimezone(tz)

    monkeypatch.setattr(broker_runtime, "datetime", _PinnedBrokerDatetime, raising=True)

    # The real Default gateway answers the directory through the actual entrypoint.
    default_gateway = broker_worker.Default(env)
    directory = asyncio.run(default_gateway.device_directory({"account_ref": OWNER_ID}))
    assert directory["ok"] is True and directory["available"] is True
    assert directory["owner_scoped"] is True
    assert [d["binding"]["device_id"] for d in directory["devices"]] == [
        "pc-expired", "pc-live", "pc-offline", "pc-revoked",
    ]
    # The broker itself never claims ONLINE for any device.
    assert "online" not in str(directory)
    broker_states = {d["binding"]["device_id"]: d["canonical_state"] for d in directory["devices"]}
    assert broker_states == {
        "pc-expired": "credential_expired",
        "pc-offline": "paired_offline",
        "pc-live": "paired_offline",
        "pc-revoked": "revoked",
    }

    # Feed each directory row through the EXISTING consumer seam + ONLINE rule.
    canonical = {d["binding"]["device_id"]: _canonical_for(d, now=pinned) for d in directory["devices"]}
    assert canonical["pc-live"].value == "online"
    assert canonical["pc-offline"].value == "paired_offline"
    assert canonical["pc-expired"].value == "credential_expired"
    assert canonical["pc-revoked"].value == "revoked"

    # The EXISTING single Web-vocabulary translation maps them; only the device
    # the server projection promoted to ONLINE is usable/CONNECTED.
    web = {device_id: translate_device_lifecycle(state) for device_id, state in canonical.items()}
    assert web["pc-live"]["state"] == "CONNECTED" and web["pc-live"]["usable"] is True
    assert web["pc-offline"]["state"] == "OFFLINE" and web["pc-offline"]["usable"] is False
    assert web["pc-expired"]["state"] == "ACTION_REQUIRED" and web["pc-expired"]["usable"] is False
    assert web["pc-expired"]["expired"] is True
    assert web["pc-revoked"]["state"] == "REVOKED" and web["pc-revoked"]["usable"] is False

    usable = [device_id for device_id, item in web.items() if item["usable"]]
    assert usable == ["pc-live"]


def test_real_broker_directory_is_owner_scoped_end_to_end() -> None:
    now = datetime.now(timezone.utc)
    _namespace, env, durable_object = _make_real_broker()
    _provision_four_pcs(durable_object, now=now)

    default_gateway = broker_worker.Default(env)
    foreign = asyncio.run(default_gateway.device_directory({"account_ref": OTHER_OWNER_ID}))
    assert foreign == {"ok": True, "available": False, "reason": "no_device_binding"}
    assert OWNER_ID not in str(foreign)
