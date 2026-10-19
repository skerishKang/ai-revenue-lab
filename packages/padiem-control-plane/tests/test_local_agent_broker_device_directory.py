"""#4139 — the canonical broker's read-only owner-scoped multi-device directory.

Unit coverage for the ``device_directory`` runtime method added beside #3094's
``device_truth``: owner/workspace scoping, the bounded never-online fact
vocabulary, re-pairing collapse, the 24-device bound, duplicate-identity
fail-closed, stable ordering, read-only behaviour and secret-free envelopes.
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import re
import sqlite3
import sys
import types

import pytest

from padiem_control_plane.local_agent_broker import BrokerBindingState, BrokerDeviceBinding
from padiem_control_plane.local_agent_broker_http import DurableLocalAgentSessionRecord
from padiem_control_plane.local_agent_broker_state import (
    LocalAgentBrokerStateSnapshot,
    VersionedLocalAgentBrokerState,
)


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
sys.modules.setdefault("workers", _workers)

_WORKER_PATH = Path(__file__).parents[1] / "local_agent_broker_worker.py"
_WORKER_SPEC = importlib.util.spec_from_file_location("padiem_local_agent_broker_device_directory_test", _WORKER_PATH)
assert _WORKER_SPEC is not None and _WORKER_SPEC.loader is not None
worker = importlib.util.module_from_spec(_WORKER_SPEC)
sys.modules[_WORKER_SPEC.name] = worker
_WORKER_SPEC.loader.exec_module(worker)

runtime_module = importlib.import_module("local_agent_broker_durable_runtime")


BASE = datetime(2026, 9, 4, 2, 0, tzinfo=timezone.utc)
AUTHORITY_REF = "control-plane.local-agent-broker.device-directory-test.v1"
PEPPER = "cloudflare-do-device-directory-test-pepper"
CREDENTIAL = b"cloudflare-do-device-directory-credential"
ACCOUNT_REF = "acct.directory.1"
OTHER_ACCOUNT_REF = "acct.directory.other"
WORKSPACE_REF = "ws.directory.1"
OTHER_WORKSPACE_REF = "ws.directory.other"
MAX_DEVICES = runtime_module.MAX_DEVICE_DIRECTORY_DEVICES


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
    def __init__(self, connection: sqlite3.Connection | None = None) -> None:
        self.connection = connection or sqlite3.connect(":memory:", isolation_level=None)
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


class _Env:
    def __init__(self) -> None:
        self.LOCAL_AGENT_BROKER_AUTHORITY_REF = AUTHORITY_REF
        self.LOCAL_AGENT_BROKER_PEPPER = PEPPER


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _rpc_fixture(*, connection: sqlite3.Connection | None = None):
    storage = _Storage(connection)
    env = _Env()
    durable_object = worker.LocalAgentBrokerDurableObject(_Context(storage), env)
    return storage, env, durable_object


def _pin_now(monkeypatch: pytest.MonkeyPatch, instant: datetime) -> None:
    """Freeze the runtime's trusted clock so canonical states are deterministic.

    The wall clock (2026-10-11+) has already crossed the 30-day credential TTL
    of the fixed BASE fixture, so any assertion about ``paired_offline`` must be
    made at a pinned instant inside the credential window.
    """

    real_datetime = runtime_module.datetime

    class _PinnedDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return instant if tz is None else instant.astimezone(tz)

    monkeypatch.setattr(runtime_module, "datetime", _PinnedDatetime, raising=True)


def _register(
    durable_object,
    *,
    device_id: str,
    binding_ref: str,
    account_ref: str = ACCOUNT_REF,
    workspace_ref: str = WORKSPACE_REF,
    issued_at: datetime | None = None,
    credential_ttl_seconds: int | None = None,
) -> dict:
    payload = {
        "binding_ref": binding_ref,
        "device_id": device_id,
        "account_ref": account_ref,
        "workspace_ref": workspace_ref,
        "credential_b64": base64.b64encode(CREDENTIAL).decode("ascii"),
        "now": _iso(issued_at or BASE),
    }
    if credential_ttl_seconds is not None:
        payload["credential_ttl_seconds"] = credential_ttl_seconds
    registered = asyncio.run(durable_object.register_binding(payload))
    assert registered["ok"] is True, registered
    return registered["binding"]


def _open_session(
    durable_object,
    *,
    binding_ref: str,
    session_id: str,
    account_ref: str = ACCOUNT_REF,
    workspace_ref: str = WORKSPACE_REF,
    issued_at: datetime | None = None,
    save_record: bool = True,
    heartbeat_at: datetime | None = None,
) -> dict:
    opened = asyncio.run(
        durable_object.open_session(
            {
                "session_id": session_id,
                "binding_ref": binding_ref,
                "credential_b64": base64.b64encode(CREDENTIAL).decode("ascii"),
                "account_ref": account_ref,
                "workspace_ref": workspace_ref,
                "now": _iso(issued_at or (BASE + timedelta(minutes=1))),
                "ttl_seconds": 900,
            }
        )
    )
    assert opened["ok"] is True, opened
    session = opened["session"]
    if save_record:
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
    return session


def _provision_device(
    durable_object,
    *,
    device_id: str,
    binding_ref: str,
    account_ref: str = ACCOUNT_REF,
    workspace_ref: str = WORKSPACE_REF,
    with_session: bool = True,
    heartbeat_at: datetime | None = None,
    save_record: bool = True,
    issued_at: datetime | None = None,
) -> None:
    _register(
        durable_object,
        device_id=device_id,
        binding_ref=binding_ref,
        account_ref=account_ref,
        workspace_ref=workspace_ref,
        issued_at=issued_at,
    )
    if with_session:
        _open_session(
            durable_object,
            binding_ref=binding_ref,
            session_id=f"sess.{device_id}",
            account_ref=account_ref,
            workspace_ref=workspace_ref,
            save_record=save_record,
            heartbeat_at=heartbeat_at,
        )


def _directory(durable_object, payload: dict) -> dict:
    return asyncio.run(durable_object.device_directory(payload))


def _device_ids(result: dict) -> list[str]:
    return [item["binding"]["device_id"] for item in result["devices"]]


# --- 1. three PCs under one account ----------------------------------------


def test_directory_lists_three_pcs_under_one_account(monkeypatch: pytest.MonkeyPatch) -> None:
    _storage, _env, durable_object = _rpc_fixture()
    _pin_now(monkeypatch, BASE + timedelta(minutes=2))
    # Registered in reverse device-id order to prove the listing order is the
    # directory's own stable order, not registration order.
    _provision_device(durable_object, device_id="pc-c", binding_ref="bind.c")
    _provision_device(durable_object, device_id="pc-a", binding_ref="bind.a")
    _provision_device(durable_object, device_id="pc-b", binding_ref="bind.b")

    result = _directory(durable_object, {"account_ref": ACCOUNT_REF})
    assert result["ok"] is True
    assert result["available"] is True
    assert result["owner_scoped"] is True
    assert result["device_count"] == 3
    assert result["max_devices"] == MAX_DEVICES
    assert _device_ids(result) == ["pc-a", "pc-b", "pc-c"]
    for device in result["devices"]:
        assert device["canonical_state"] == "paired_offline"
        assert device["binding"]["account_ref"] == ACCOUNT_REF
        assert device["session"] is not None
        # No device carries an ONLINE claim: ONLINE is decided downstream.
        assert "online" not in device
        assert "online" not in device["canonical_state"]


def test_directory_lists_a_single_connected_pc(monkeypatch: pytest.MonkeyPatch) -> None:
    _storage, _env, durable_object = _rpc_fixture()
    _pin_now(monkeypatch, BASE + timedelta(minutes=2))
    _provision_device(durable_object, device_id="only-pc", binding_ref="bind.only")

    result = _directory(durable_object, {"account_ref": ACCOUNT_REF})
    assert result["device_count"] == 1
    assert _device_ids(result) == ["only-pc"]


# --- 2/3. offline vs revoked devices are distinguished ----------------------


def test_directory_distinguishes_offline_and_revoked_devices(monkeypatch: pytest.MonkeyPatch) -> None:
    _storage, _env, durable_object = _rpc_fixture()
    _pin_now(monkeypatch, BASE + timedelta(minutes=2))
    _provision_device(
        durable_object, device_id="pc-live", binding_ref="bind.live",
        heartbeat_at=BASE + timedelta(minutes=1, seconds=5),
    )
    _provision_device(durable_object, device_id="pc-quiet", binding_ref="bind.quiet", heartbeat_at=None)
    _provision_device(durable_object, device_id="pc-revoked", binding_ref="bind.revoked")
    revoked = asyncio.run(
        durable_object.revoke_binding({"binding_ref": "bind.revoked", "now": _iso(BASE + timedelta(minutes=2))})
    )
    assert revoked["ok"] is True

    result = _directory(durable_object, {"account_ref": ACCOUNT_REF})
    states = {item["binding"]["device_id"]: item["canonical_state"] for item in result["devices"]}
    assert states == {
        "pc-live": "paired_offline",
        "pc-quiet": "paired_offline",
        "pc-revoked": "revoked",
    }
    by_id = {item["binding"]["device_id"]: item for item in result["devices"]}
    assert by_id["pc-live"]["heartbeat_last_seen_at"] is not None
    assert by_id["pc-quiet"]["heartbeat_last_seen_at"] is None
    # A revoked device loses its session in the same revoke, so no stale
    # heartbeat can make it look reachable.
    assert by_id["pc-revoked"]["session"] is None
    assert by_id["pc-revoked"]["heartbeat_last_seen_at"] is None


# --- 4/5. owner and workspace isolation ------------------------------------


def test_directory_never_exposes_another_accounts_devices(monkeypatch: pytest.MonkeyPatch) -> None:
    _storage, _env, durable_object = _rpc_fixture()
    _pin_now(monkeypatch, BASE + timedelta(minutes=2))
    _provision_device(durable_object, device_id="mine-pc", binding_ref="bind.mine")
    _provision_device(
        durable_object, device_id="victim-pc", binding_ref="bind.victim",
        account_ref=OTHER_ACCOUNT_REF,
    )

    mine = _directory(durable_object, {"account_ref": ACCOUNT_REF})
    assert _device_ids(mine) == ["mine-pc"]

    # The foreign owner is a real owner with a real device, but sees only theirs.
    other = _directory(durable_object, {"account_ref": OTHER_ACCOUNT_REF})
    assert _device_ids(other) == ["victim-pc"]
    assert OTHER_ACCOUNT_REF not in str(mine)


def test_directory_isolates_workspaces_within_one_account(monkeypatch: pytest.MonkeyPatch) -> None:
    _storage, _env, durable_object = _rpc_fixture()
    _pin_now(monkeypatch, BASE + timedelta(minutes=2))
    _provision_device(durable_object, device_id="ws1-pc", binding_ref="bind.ws1")
    _provision_device(
        durable_object, device_id="ws2-pc", binding_ref="bind.ws2",
        workspace_ref=OTHER_WORKSPACE_REF,
    )

    scoped = _directory(durable_object, {"account_ref": ACCOUNT_REF, "workspace_ref": WORKSPACE_REF})
    assert _device_ids(scoped) == ["ws1-pc"]

    other = _directory(durable_object, {"account_ref": ACCOUNT_REF, "workspace_ref": OTHER_WORKSPACE_REF})
    assert _device_ids(other) == ["ws2-pc"]

    # Account-wide sees both, still one row per device.
    whole = _directory(durable_object, {"account_ref": ACCOUNT_REF})
    assert _device_ids(whole) == ["ws1-pc", "ws2-pc"]


# --- 6. credential expiry and revocation -----------------------------------


def test_directory_reports_credential_expiry_and_revocation(monkeypatch: pytest.MonkeyPatch) -> None:
    _storage, _env, durable_object = _rpc_fixture()
    _register(
        durable_object, device_id="pc-expiring", binding_ref="bind.expiring",
        credential_ttl_seconds=300,
    )
    _open_session(durable_object, binding_ref="bind.expiring", session_id="sess.expiring")
    _register(durable_object, device_id="pc-revoked", binding_ref="bind.revoked2")
    revoked = asyncio.run(
        durable_object.revoke_binding({"binding_ref": "bind.revoked2", "now": _iso(BASE + timedelta(minutes=1))})
    )
    assert revoked["ok"] is True

    # Past the 300s credential TTL: the credential-expired device must be
    # reported expired even though its session record still exists.
    _pin_now(monkeypatch, BASE + timedelta(minutes=10))
    result = _directory(durable_object, {"account_ref": ACCOUNT_REF})
    states = {item["binding"]["device_id"]: item["canonical_state"] for item in result["devices"]}
    assert states["pc-expiring"] == "credential_expired"
    assert states["pc-revoked"] == "revoked"


# --- 7. missing and stale heartbeat ----------------------------------------


def test_directory_reports_missing_and_stale_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    _storage, _env, durable_object = _rpc_fixture()
    _pin_now(monkeypatch, BASE + timedelta(minutes=2))
    # A: session but the heartbeat row was never written.
    _provision_device(durable_object, device_id="pc-norow", binding_ref="bind.norow", save_record=False)
    # B: heartbeat row written, but never touched by the device.
    _provision_device(durable_object, device_id="pc-noseen", binding_ref="bind.noseen", heartbeat_at=None)
    # C: a heartbeat that is already stale relative to the pinned now.
    _provision_device(
        durable_object, device_id="pc-stale", binding_ref="bind.stale",
        heartbeat_at=BASE + timedelta(minutes=1, seconds=1),
    )

    result = _directory(durable_object, {"account_ref": ACCOUNT_REF})
    by_id = {item["binding"]["device_id"]: item for item in result["devices"]}
    assert by_id["pc-norow"]["heartbeat_last_seen_at"] is None
    assert by_id["pc-noseen"]["heartbeat_last_seen_at"] is None
    # A stale heartbeat is reported as the fact it is — never as ONLINE.
    assert by_id["pc-stale"]["heartbeat_last_seen_at"] is not None
    assert by_id["pc-stale"]["canonical_state"] == "paired_offline"
    # No device in the whole envelope carries an ONLINE claim.
    assert "online" not in str(result)


# --- 8. re-pairing collapses to the current binding -------------------------


def test_directory_reports_only_the_current_binding_after_repairing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _storage, _env, durable_object = _rpc_fixture()
    _pin_now(monkeypatch, BASE + timedelta(minutes=5))
    # First pairing, then revoke and re-pair the SAME device id under a new
    # binding_ref — exactly what a user reconnecting a machine produces.
    _register(durable_object, device_id="pc-repair", binding_ref="bind.old")
    revoked = asyncio.run(
        durable_object.revoke_binding({"binding_ref": "bind.old", "now": _iso(BASE + timedelta(minutes=1))})
    )
    assert revoked["ok"] is True
    _register(
        durable_object, device_id="pc-repair", binding_ref="bind.new",
        issued_at=BASE + timedelta(minutes=2),
    )
    _open_session(
        durable_object, binding_ref="bind.new", session_id="sess.repair",
        issued_at=BASE + timedelta(minutes=3),
    )

    result = _directory(durable_object, {"account_ref": ACCOUNT_REF})
    # One device id, and it is the current (active) binding, not the revoked one.
    assert _device_ids(result) == ["pc-repair"]
    assert result["devices"][0]["binding"]["binding_ref"] == "bind.new"
    assert result["devices"][0]["canonical_state"] == "paired_offline"


# --- 9. duplicate device identity and the 24-device bound -------------------


def _binding(*, device_id: str, binding_ref: str, state: BrokerBindingState) -> BrokerDeviceBinding:
    return BrokerDeviceBinding(
        binding_ref=binding_ref,
        device_id=device_id,
        account_ref=ACCOUNT_REF,
        workspace_ref=WORKSPACE_REF,
        credential_generation=1,
        credential_digest="a" * 64,
        issued_at=BASE,
        credential_expires_at=BASE + timedelta(days=30),
        state=state,
    )


def test_select_current_bindings_rejects_duplicate_active_device_identity() -> None:
    forged = [
        _binding(device_id="pc-dup", binding_ref="bind.dup.1", state=BrokerBindingState.ACTIVE),
        _binding(device_id="pc-dup", binding_ref="bind.dup.2", state=BrokerBindingState.ACTIVE),
    ]
    with pytest.raises(Exception) as excinfo:
        runtime_module.select_current_bindings_by_device(forged)
    assert getattr(excinfo.value, "code", "") == "device_directory_duplicate_device_identity"

    # A revoked historical binding beside the current active one is NOT a
    # duplicate: it collapses to the active binding.
    legitimate = [
        _binding(device_id="pc-ok", binding_ref="bind.ok.old", state=BrokerBindingState.REVOKED),
        _binding(device_id="pc-ok", binding_ref="bind.ok.new", state=BrokerBindingState.ACTIVE),
    ]
    selected = runtime_module.select_current_bindings_by_device(legitimate)
    assert selected["pc-ok"].binding_ref == "bind.ok.new"


def test_directory_rejects_a_forged_duplicate_identity_whole(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _storage, _env, durable_object = _rpc_fixture()
    _pin_now(monkeypatch, BASE + timedelta(minutes=2))
    _provision_device(durable_object, device_id="pc-keep", binding_ref="bind.keep")

    # Force the exact tamper shape the runtime must refuse even if the state
    # validator were ever bypassed: two ACTIVE bindings for one device id.
    snapshot = LocalAgentBrokerStateSnapshot(authority_ref=AUTHORITY_REF)
    object.__setattr__(
        snapshot,
        "bindings",
        (
            _binding(device_id="pc-keep", binding_ref="bind.keep", state=BrokerBindingState.ACTIVE),
            _binding(device_id="pc-twin", binding_ref="bind.twin.1", state=BrokerBindingState.ACTIVE),
            _binding(device_id="pc-twin", binding_ref="bind.twin.2", state=BrokerBindingState.ACTIVE),
        ),
    )

    class _StubPort:
        def load(self, *, authority_ref: str) -> VersionedLocalAgentBrokerState:
            return VersionedLocalAgentBrokerState(version=1, snapshot=snapshot)

    durable_object._runtime.state_port = _StubPort()
    result = _directory(durable_object, {"account_ref": ACCOUNT_REF})
    assert result["ok"] is False
    assert result["error"]["code"] == "device_directory_duplicate_device_identity"


def test_directory_allows_exactly_the_bound_and_rejects_one_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _storage, _env, durable_object = _rpc_fixture()
    _pin_now(monkeypatch, BASE + timedelta(minutes=2))
    for index in range(MAX_DEVICES):
        _provision_device(
            durable_object,
            device_id=f"pc-{index:02d}",
            binding_ref=f"bind.{index:02d}",
            with_session=False,
        )

    at_bound = _directory(durable_object, {"account_ref": ACCOUNT_REF})
    assert at_bound["ok"] is True
    assert at_bound["device_count"] == MAX_DEVICES
    assert at_bound["devices"][0]["binding"]["device_id"] == "pc-00"
    assert at_bound["devices"][-1]["binding"]["device_id"] == f"pc-{MAX_DEVICES - 1:02d}"

    _provision_device(
        durable_object,
        device_id="pc-overflow",
        binding_ref="bind.overflow",
        with_session=False,
    )
    over = _directory(durable_object, {"account_ref": ACCOUNT_REF})
    assert over["ok"] is False
    assert over["error"]["code"] == "device_directory_too_large"
    # Refused whole: no partial list is ever returned.
    assert "devices" not in over


# --- 10. the single-PC device_truth API is unchanged ------------------------


def test_single_device_truth_api_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    _storage, _env, durable_object = _rpc_fixture()
    _pin_now(monkeypatch, BASE + timedelta(minutes=2))
    _provision_device(
        durable_object, device_id="pc-solo", binding_ref="bind.solo",
        heartbeat_at=BASE + timedelta(minutes=1, seconds=5),
    )
    # A second device exists, yet device_truth still reports exactly one — the
    # owner's newest binding — proving the directory did not alter it.
    _provision_device(
        durable_object, device_id="pc-other", binding_ref="bind.other2",
        issued_at=BASE + timedelta(minutes=1),
    )

    truth = asyncio.run(durable_object.device_truth({"account_ref": ACCOUNT_REF}))
    assert truth["ok"] is True and truth["available"] is True
    facts = truth["device_truth"]
    assert facts["binding"]["device_id"] == "pc-other"  # newest binding wins
    assert facts["canonical_state"] == "paired_offline"
    assert set(facts) == {"canonical_state", "binding", "session", "heartbeat_last_seen_at"}


def test_directory_rejects_malformed_requests_with_a_bounded_error() -> None:
    _storage, _env, durable_object = _rpc_fixture()
    for payload in ({}, {"account_ref": ""}, {"account_ref": "bad ref with spaces!"}, {"nope": 1},
                    {"account_ref": ACCOUNT_REF, "device_id": "pc-a"}):
        result = _directory(durable_object, payload)
        assert result["ok"] is False
        assert result["error"] == {
            "code": "invalid_device_directory_request",
            "message": "device directory request was rejected",
        }


# --- 11. read-only ----------------------------------------------------------


def test_directory_is_read_only_and_needs_no_transaction() -> None:
    storage = _Storage()
    durable_object = worker.LocalAgentBrokerDurableObject(_Context(storage), _Env())
    _provision_device(durable_object, device_id="pc-a", binding_ref="bind.a")
    _provision_device(durable_object, device_id="pc-b", binding_ref="bind.b")
    before = durable_object._runtime.state_port.load(authority_ref=AUTHORITY_REF)

    storage.transactionSync = None  # type: ignore[method-assign]
    result = _directory(durable_object, {"account_ref": ACCOUNT_REF})
    assert result["available"] is True and result["device_count"] == 2
    after = durable_object._runtime.state_port.load(authority_ref=AUTHORITY_REF)
    assert after.version == before.version
    assert after.snapshot.bindings == before.snapshot.bindings
    assert after.snapshot.sessions == before.snapshot.sessions
    assert after.snapshot.commands == before.snapshot.commands


# --- 12. no secret leakage --------------------------------------------------


def test_directory_never_leaks_credentials_or_raw_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    _storage, _env, durable_object = _rpc_fixture()
    _pin_now(monkeypatch, BASE + timedelta(minutes=2))
    _provision_device(
        durable_object, device_id="pc-a", binding_ref="bind.a",
        heartbeat_at=BASE + timedelta(minutes=1, seconds=5),
    )

    result = _directory(durable_object, {"account_ref": ACCOUNT_REF})
    flat = str(result)
    assert not re.search(r"[0-9a-f]{64}", flat)
    assert base64.b64encode(CREDENTIAL).decode("ascii") not in flat
    for device in result["devices"]:
        assert device["binding"]["credential_digest_exposed"] is False
        assert device["binding"]["raw_device_credential"] is False
        if device["session"] is not None:
            assert device["session"]["raw_session_secret"] is False


# --- entrypoint exposure ----------------------------------------------------


def test_worker_entrypoints_expose_the_directory_rpc_without_a_public_route() -> None:
    assert callable(getattr(worker.LocalAgentBrokerDurableObject, "device_directory"))
    assert callable(getattr(worker.Default, "device_directory"))
    assert worker.PUBLIC_ENDPOINT_ADDED is False
    assert worker.NARROW_DEVICE_DIRECTORY_PROJECTION is True
    assert worker.DEVICE_DIRECTORY_VOCABULARY_HAS_ONLINE is False
    assert worker.DEVICE_DIRECTORY_SECOND_ONLINE_AUTHORITY is False
    assert worker.DEVICE_DIRECTORY_SECOND_DEVICE_AUTHORITY is False
    assert worker.DEVICE_DIRECTORY_MUTATION is False
    assert runtime_module.DEVICE_DIRECTORY_VOCABULARY_HAS_ONLINE is False
    assert runtime_module.DEVICE_DIRECTORY_MAX_DEVICES == MAX_DEVICES
    assert runtime_module.DEVICE_DIRECTORY_TRUNCATES is False
    assert runtime_module.DEVICE_DIRECTORY_READ_ONLY is True
