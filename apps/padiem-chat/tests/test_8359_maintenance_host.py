"""Chat-host integration with a real local SQLite journal and fake queue/PC."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from app.d1_sqlite import SqliteD1
from app.lifespan_hooks import LifespanHooks
from app.ops_alert_store import D1OpsAlertStore
from app.ops_audit_store import OpsAuditStore
from app import pc_helper_maintenance_host as host
from app import oracle_mesh_read_return_routes as routes
from app.pc_helper_registration import SOURCE_SHA256, registration_command
from app.pc_helper_install import install_command, install_script
from canonical_connector_enrollment_durable import (
    IdentityDurableConnectorEnrollmentRecords,
)
from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.padiem_connector_enrollment import ConnectorEnrollmentConsent

NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)
DEVICE = "node//managed-fixture"
#: The connector's own enrollment device id. It is a different string from
#: the Mesh node a managed link names, and it is what a consent grant stores.
CONNECTOR = "connector-device-fixture"
UID = "usr_owner"
SUB = "sub_" + "a" * 32
TENANT = "tenant_" + "b" * 32
RELEASE = {"version": "0.3.0-rc2", "sha256": "a" * 64,
           "download_url": "https://downloads.padiem.net/pc-helper/0.3.0-rc2/padiem-user-helper.exe",
           "min_supported_version": "0.3.0-rc1"}
LINK = {"mesh_node_id": DEVICE, "state": "active", "paused_at": None,
        "managed_at": NOW.isoformat(), "managed_by": "usr_admin", "user_id": UID,
        "link_id": "pcl_fixture"}
ENV = {"PADIEM_PC_HELPER_AUTO_UPDATE_ENABLED": "1"}
SCOPE = {"owner_subject_id": SUB, "account_ref": "account-fixture", "workspace_ref": "workspace-fixture"}
#: The deployment ownership map's one server-owned row for this PC: the
#: connector device id and the Mesh node it addresses, side by side.
MAP = [{"account_ref": SCOPE["account_ref"], "device_id": CONNECTOR, "node_ref": DEVICE,
        "root_ref": "pcroot_fixture", "path_relative": "fixture.txt",
        "file_path": "C:/fixture.txt", "command_exec": True}]


class Cursor:
    def __init__(self, rows):
        self._rows = rows

    def toArray(self):
        return self._rows


class Sql:
    def __init__(self, db):
        self._db = db

    def exec(self, statement, *args):
        cursor = self._db.execute(statement, args)
        if cursor.description is not None:
            fields = [col[0] for col in cursor.description]
            return Cursor([dict(zip(fields, row, strict=True)) for row in cursor.fetchall()])
        return Cursor([])


class DurableStorage:
    """The same SQLite storage shape the canonical Identity DO exposes."""

    def __init__(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.sql = Sql(self.db)

    def transactionSync(self, callback):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            result = callback()
            self.db.execute("COMMIT")
            return result
        except Exception:
            self.db.execute("ROLLBACK")
            raise


class Queue:
    """No PC execution; only existing proxy-shaped methods."""
    def __init__(self):
        self.links = [LINK]
        self.registration = {}
        self.state = {"helper_status_present": True, "helper_sha256": "b" * 64,
                      "helper_version": "0.3.0-rc1", "updater_source_present": True,
                      "updater_source_sha256": "c" * 64, "updater_task_present": True,
                      "self_heal_task_present": True}
        self.now = NOW
        self.online = True
        self.resolved = DEVICE

    async def list_managed_device_ids(self):
        return [DEVICE]

    async def list_active_device_ids(self):
        return [DEVICE, "node//general-fixture"]

    async def resolve_helper_rollout_device(self, **kw):
        return {"device_id": self.resolved, "managed": True}

    async def managed_owner_for_device(self, **kw):
        return self.links

    async def load(self, **kw):
        return {"device_id": DEVICE, "connected": self.online, "received_at": self.now.isoformat()}

    async def load_helper_ready(self, **kw):
        return {"device_id": DEVICE, "received_at": self.now.isoformat(), "state": self.state}

    async def reserve_updater_registration(self, *, device_id, sha256, actor, attempt_id, now):
        key = (device_id, sha256)
        self.registration.setdefault(key, {"actor_user_id": actor, "attempt_id": attempt_id,
                                           "dispatch_id": None, "reason": None})
        return self.registration[key]["attempt_id"] == attempt_id

    async def load_updater_registration(self, *, device_id, sha256):
        return self.registration.get((device_id, sha256))

    async def record_updater_registration(self, *, device_id, sha256, attempt_id, **result):
        row = self.registration.get((device_id, sha256))
        if row and row["attempt_id"] == attempt_id and not row["dispatch_id"] and not row["reason"]:
            row.update(result)


class History:
    def __init__(self):
        self.runs = {}
        self.rows = []
        self.failed = False
        self.done = False
        self.before_create = None

    async def ensure_claw_automation_conversation(self, **kw):
        return "chat_" + "a" * 32

    async def record_chat_pc_drive_run(self, **kw):
        self.runs[kw["run_id"]] = kw

    async def get_claw_run(self, uid, run):
        return self.runs.get(run)

    async def get_local_task_correlation(self, *args):
        return None

    async def create_oracle_mesh_dispatch(self, **kw):
        self.rows.append(kw)
        if self.failed:
            raise RuntimeError("lost response")
        return {"dispatch_id": "dispatch-fixture", "state": "pending", "expires_at": kw["expires_at"]}

    async def get_oracle_mesh_dispatch_for_owner(self, **kw):
        return {"run_id": self.rows[-1]["run_id"], "state": "done" if self.done else "pending",
                "exit_code": 0, "dispatch_id": "dispatch-fixture"}


@pytest.fixture
def rig(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    migrations = Path(__file__).resolve().parents[1] / "migrations"
    for num in (128, 130, 131, 132, 137, 139):
        conn.executescript(next(migrations.glob(str(num) + "_*.sql")).read_text())
    db = SqliteD1(conn)
    queue, history = Queue(), History()
    state = SimpleNamespace(
        pc_device_pairing_store=queue, mesh_device_presence_store=queue, mesh_device_drive_store=queue,
        history_store=history, ops_audit_store=OpsAuditStore(db), ops_alert_store=D1OpsAlertStore(db),
        control_plane_identity_authority=SimpleNamespace(resolve_connector_owner_scope=lambda: None),
        oracle_mesh_return_source=routes.OracleMeshReturnSource(
            MAP, "s" * 32, routes.EXECUTION_MODE_MESH),
        pc_pairing_user_helper_url=RELEASE["download_url"], pc_pairing_user_helper_sha256=RELEASE["sha256"])
    app = SimpleNamespace(state=state)
    session = SimpleNamespace(session_id="session-fixture", tenant_id=TENANT,
                              subject=SimpleNamespace(subject_id=SUB))
    flags = {"session": True, "consent": True, "admin": True, "precontact": False, "stage": "internal",
             "target": DEVICE, "revoked_after_run": False}

    @asynccontextmanager
    async def owner(app, uid):
        assert uid == UID
        if not flags["session"] or (flags["revoked_after_run"] and history.runs):
            raise ValueError("maintenance_owner_unresolved")
        yield session

    flags["consent_refs"] = []

    async def read(identity, method, **kw):
        if method == "owner_scope":
            return SCOPE
        # The consent server keys records by the connector's own enrollment
        # device id, not by the Mesh node. A composed node/ value is refused
        # by its reference grammar; a wrong bare value finds no record.
        flags["consent_refs"].append(kw.get("device_id"))
        if not flags["consent"]:
            return None
        if kw.get("device_id") != CONNECTOR:
            raise ValueError("connector_enrollment_invalid_reference")
        return {**SCOPE, "device_id": CONNECTOR, "withdrawn_at": None,
                "consent_id": "consent-fixture"}

    async def route_read(*args, **kwargs):
        if flags["precontact"]:
            raise RuntimeError("authority unavailable before row creation")
        return await read(*args, **kwargs)

    async def target(*args, **kw):
        return {"authorized": True, **SCOPE,
                "target": {"node_ref": flags["target"], "device_id": flags["target"],
                           "link_id": LINK["link_id"]}}, None

    async def admin(**kw):
        return flags["admin"]

    async def rollout(state, candidate):
        return {"initialized": True, "stage": flags["stage"], "percent": 10,
                "stable": {**candidate, "version": "0.3.0-rc1"}, "target": candidate}

    monkeypatch.setattr(host, "maintenance_owner_context", owner)
    monkeypatch.setattr(host, "mode_connector_read", read)
    monkeypatch.setattr(routes, "mode_connector_read", route_read)
    monkeypatch.setattr(routes, "_engine_pc_files_target", target)
    monkeypatch.setattr(host, "platform_authority_for", lambda req: SimpleNamespace(is_global_model_admin=admin))
    monkeypatch.setattr(host, "load_plan", rollout)
    monkeypatch.setattr(host, "_now", lambda: queue.now)
    monkeypatch.setattr(host, "helper_manifest", lambda state: RELEASE)
    monkeypatch.setattr("app.pc_helper_version_routes.helper_manifest", lambda state: RELEASE)
    store = host.HostMaintenanceStore(db)
    yield app, queue, history, flags, store, conn
    conn.close()


def test_actual_dispatch_path_and_next_observation(rig, monkeypatch):
    app, queue, history, flags, store, db = rig

    async def original(*args, **kw):
        return "PADIEM_HELPER_REFRESH:updated:registered"

    monkeypatch.setattr("app.mcp_gateway_shell._read_original", original)

    async def run():
        await host.maintenance_round(app, ENV, store)
        await host.maintenance_round(app, ENV, store)
        assert len(history.rows) == 1
        row = history.rows[0]
        assert row["user_id"] == UID and row["device_id"] == row["node_ref"] == DEVICE
        # ##8359: the consent lookup carries the map's connector device id
        # unchanged - not the Mesh node and not a reshaped piece of it.
        assert flags["consent_refs"] and set(flags["consent_refs"]) == {CONNECTOR}
        assert row["user_mode"] is False and row["kind"] == "command"
        assert row["command_text"] == registration_command()
        assert history.runs[row["run_id"]]["action"] == "pc_maintenance"
        history.done = True
        queue.now += timedelta(seconds=60)
        await host.maintenance_round(app, ENV, store)
        assert db.execute("SELECT status FROM pc_helper_maintenance_jobs").fetchone()[0] == "queued"
        queue.now += timedelta(seconds=60)
        queue.state["updater_source_sha256"] = SOURCE_SHA256
        await host.maintenance_round(app, ENV, store)
        await host.maintenance_round(app, ENV, store)
        assert db.execute("SELECT outcome FROM pc_helper_maintenance_jobs").fetchone()[0] == "verified"
        assert db.execute("SELECT count(*) FROM ops_alert_outbox").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM ops_audit_log WHERE action='helper_auto_verified'").fetchone()[0] == 1
    asyncio.run(run())


def test_consent_lookup_carries_the_map_pin_unchanged(rig):
    """The accumulated wire calls carry the ownership map's pinned connector
    device id; the Mesh node and any reshaping of it never reach the consent
    server (server-side refusal is pinned in the control-plane durable tests)."""
    app, queue, history, flags, store, db = rig
    async def run():
        await host.maintenance_round(app, ENV, store)
    asyncio.run(run())
    assert flags["consent_refs"] and set(flags["consent_refs"]) == {CONNECTOR}
    assert CONNECTOR not in (DEVICE, DEVICE.rsplit("/", 1)[1])


def test_no_map_row_naming_the_pc_means_no_consent_lookup(rig):
    """Without the server-owned pair there is no reference to look up, so the
    candidate stops before the consent call and stages no run."""
    app, queue, history, flags, store, db = rig
    app.state.oracle_mesh_return_source = routes.OracleMeshReturnSource(
        [{**MAP[0], "node_ref": "node//another-pc"}], "s" * 32,
        routes.EXECUTION_MODE_MESH)
    async def run():
        await host.maintenance_round(app, ENV, store)
    asyncio.run(run())
    assert flags["consent_refs"] == []
    assert history.rows == []
    assert db.execute("SELECT count(*) FROM pc_helper_maintenance_jobs").fetchone()[0] == 0


def test_consent_device_grammar_still_refuses_the_mesh_forms(rig):
    """The consent server's own reference check is not widened: neither the
    composed node/ form nor a shortened node id is accepted as a device key."""
    source = rig[0].state.oracle_mesh_return_source
    assert source.consent_device_for_node(
        account_ref=SCOPE["account_ref"], node_ref=DEVICE) == CONNECTOR
    assert source.consent_device_for_node(
        account_ref=SCOPE["account_ref"], node_ref="node//unknown") is None
    assert source.consent_device_for_node(
        account_ref="account-other", node_ref=DEVICE) is None


@pytest.mark.parametrize(("denial", "expected"), [
    ("missing_digest", ("observation=fresh", "helper_digest=missing", "updater_digest=missing",
                        "maintenance_candidate=digest_unverified", "outcome=candidate_denied")),
    ("stage", ("rollout=paused", "maintenance_candidate=stage_closed")),
    ("offline", ("online=no", "outcome=offline")),
    ("owner", ("owner_session=no", "outcome=owner_unresolved")),
    ("owner_link", ("owner_link=missing_or_invalid", "outcome=owner_link_denied")),
    ("error", ("outcome=error_check_manager_admin",)),
])
def test_candidate_diagnostics_are_bounded_and_cover_general_pc(rig, caplog, monkeypatch, denial, expected):
    app, queue, history, flags, store, db = rig
    if denial == "missing_digest":
        queue.state.pop("updater_source_sha256")
        queue.state.pop("helper_sha256")
    elif denial == "stage":
        flags["stage"] = "paused"
    elif denial == "offline":
        queue.online = False
    elif denial == "owner":
        flags["session"] = False
    elif denial == "owner_link":
        queue.links = []
    else:
        async def broken(**kw):
            raise RuntimeError("private-fixture " + DEVICE + UID)
        monkeypatch.setattr(host, "platform_authority_for",
                            lambda req: SimpleNamespace(is_global_model_admin=broken))
    asyncio.run(host.maintenance_round(app, ENV, store))
    lines = [r.getMessage() for r in caplog.records
             if r.getMessage().startswith("pc_maintenance_candidate ")]
    assert len(lines) == 2
    general, managed = lines
    assert "managed=no" in general and "outcome=not_managed" in general
    assert all(field in managed for field in expected)
    for line in lines:
        assert all(value not in line for value in (DEVICE, UID, "node//general-fixture",
                                                    "private-fixture", "usr_admin", "pcl_fixture"))
    assert not history.rows


def test_file_only_observation_can_select_refresh_but_not_verify_it(rig, monkeypatch, caplog):
    app, queue, history, flags, store, db = rig
    for key in ("updater_source_present", "updater_source_sha256", "updater_task_present",
                "self_heal_task_present"):
        queue.state.pop(key)

    async def original(*args, **kw):
        return "PADIEM_HELPER_REFRESH:updated:registered"

    monkeypatch.setattr("app.mcp_gateway_shell._read_original", original)

    async def run():
        await host.maintenance_round(app, ENV, store)
        assert len(history.rows) == 1
        assert history.rows[0]["command_text"] == registration_command()
        assert history.rows[0]["user_mode"] is False
        assert any("maintenance_candidate=refresh" in r.getMessage()
                   and "updater_digest=missing" in r.getMessage() for r in caplog.records)
        history.done = True
        queue.now += timedelta(seconds=60)
        await host.maintenance_round(app, ENV, store)
        queue.now += timedelta(seconds=60)
        await host.maintenance_round(app, ENV, store)
        assert db.execute("SELECT status FROM pc_helper_maintenance_jobs").fetchone()[0] == "queued"
        queue.state.update(updater_source_present=True, updater_source_sha256=SOURCE_SHA256,
                           updater_task_present=True, self_heal_task_present=True)
        queue.now += timedelta(seconds=60)
        await host.maintenance_round(app, ENV, store)
        assert db.execute("SELECT outcome FROM pc_helper_maintenance_jobs").fetchone()[0] == "verified"
        assert len(history.rows) == 1

    asyncio.run(run())

@pytest.mark.parametrize("denial", ["switch", "unmanaged", "multi", "offline", "owner", "consent",
                                    "admin", "stage", "target", "guid", "revoked_after_run"])
def test_row_creation_denied(rig, denial):
    app, queue, history, flags, store, db = rig
    env = ENV
    if denial == "switch":
        env = {}
    elif denial == "unmanaged":
        queue.links = []
    elif denial == "multi":
        queue.links = [LINK, LINK]
    elif denial == "offline":
        queue.online = False
    elif denial == "owner":
        flags["session"] = False
    elif denial == "consent":
        flags["consent"] = False
    elif denial == "admin":
        flags["admin"] = False
    elif denial == "stage":
        flags["stage"] = "paused"
    elif denial == "target":
        flags["target"] = "node//other"
    elif denial == "guid":
        queue.resolved = "0123456789abcdef0123456789abcdef"
    else:
        flags["revoked_after_run"] = True

    async def run():
        await host.maintenance_round(app, env, store)
        await host.maintenance_round(app, env, store)
        assert not history.rows
        if denial != "revoked_after_run":
            assert not history.runs
        if denial in ("owner", "consent"):
            assert db.execute("SELECT count(*) FROM ops_alert_outbox").fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM ops_audit_log").fetchone()[0] == 1
    asyncio.run(run())


@pytest.mark.parametrize("precontact", [True, False])
def test_retry_only_known_no_row_and_failure_notice(rig, precontact):
    app, queue, history, flags, store, db = rig
    flags["precontact"] = precontact
    history.failed = not precontact

    async def run():
        for _ in range(6):
            await host.maintenance_round(app, ENV, store)
        assert len(history.runs) == (3 if precontact else 1)
        assert len(history.rows) == (0 if precontact else 1)
        assert db.execute("SELECT stopped FROM pc_helper_auto_attempts").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM ops_alert_outbox").fetchone()[0] == (3 if precontact else 1)
        assert db.execute("SELECT count(*) FROM ops_audit_log WHERE action IN "
                          "('helper_auto_precontact_refused','helper_auto_dispatch_unconfirmed')").fetchone()[0] == (3 if precontact else 1)
    asyncio.run(run())


def test_install_switch_and_exact_manifest(rig):
    app, queue, history, flags, store, db = rig
    queue.state = {"helper_status_present": False}

    async def run():
        await host.maintenance_round(app, ENV, store)
        assert not history.rows
        await host.maintenance_round(app, {**ENV, "PADIEM_PC_HELPER_AUTO_INSTALL_ENABLED": "1"}, store)
        assert len(history.rows) == 1 and history.rows[0]["command_text"] == install_command(RELEASE)
        assert history.rows[0]["user_mode"] is False
        assert registration_command() in install_script(RELEASE)
    asyncio.run(run())


def test_one_active_source_per_device(rig):
    _, _, _, _, store, _ = rig

    async def run():
        first = await store.reserve(device_id=DEVICE, source_sha256="a" * 64, now=NOW.isoformat())
        assert first
        assert not await store.reserve(device_id=DEVICE, source_sha256="b" * 64, now=NOW.isoformat())
        assert await store.settle(first, now=NOW.isoformat(), verified=True)
        assert await store.reserve(device_id=DEVICE, source_sha256="b" * 64, now=NOW.isoformat())
    asyncio.run(run())


def test_guid_resolution_requires_unique_fresh_queue_observation():
    import hashlib
    import json
    from app.pc_device_pairing_store import D1PcPairingStore
    from kagent.local_agent_mesh_helper_ready import _file_state
    from padiem_ai_core.pc_helper_ready import validate_helper_ready

    guid = "0123456789abcdef0123456789abcdef"
    state, _ = _file_state(json.dumps({"status": "installed", "sha256": "a" * 64,
                                      "version": "0.3.0-rc2", "device_id": guid}).encode())
    assert state["helper_install_ref_sha256"] == hashlib.sha256(guid.encode()).hexdigest()
    assert guid not in json.dumps(state)
    assert validate_helper_ready(state) == state
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("CREATE TABLE pc_device_links (link_id TEXT,user_id TEXT,mesh_node_id TEXT,"
                     "state TEXT,paused_at TEXT,managed_at TEXT,managed_by TEXT);"
                     "CREATE TABLE mesh_device_helper_ready (device_id TEXT,state_json TEXT,received_at TEXT);")
    pairing = D1PcPairingStore(SqliteD1(db))
    # Millisecond precision like queue receipts, one second in the past so a
    # same-millisecond stamp never falls outside the truncated upper bound.
    fresh = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(timespec="milliseconds")
    db.execute("INSERT INTO pc_device_links VALUES (?,?,?,'active',NULL,?,?)",
               (LINK["link_id"], UID, DEVICE, fresh, LINK["managed_by"]))

    async def run():
        assert await pairing.resolve_helper_rollout_device(device_id=guid, install_id=True) is None
        links = await pairing.managed_owner_for_device(device_id=DEVICE)
        assert len(links) == 1 and links[0]["managed_by"] == LINK["managed_by"]
        db.execute("INSERT INTO mesh_device_helper_ready VALUES (?,?,?)", (DEVICE, json.dumps(state), fresh))
        db.commit()
        assert await pairing.resolve_helper_rollout_device(device_id=guid, install_id=True) == {
            "device_id": DEVICE, "managed": True}
        db.execute("INSERT INTO pc_device_links VALUES (?,?,?,'active',NULL,?,?)",
                   ("pcl_other", UID, "node//other", fresh, "usr_admin"))
        db.execute("INSERT INTO mesh_device_helper_ready VALUES (?,?,?)",
                   ("node//other", json.dumps(state), fresh))
        db.commit()
        assert await pairing.resolve_helper_rollout_device(device_id=guid, install_id=True) is None
        db.execute("UPDATE mesh_device_helper_ready SET received_at='2020-01-01T00:00:00Z'")
        db.commit()
        assert await pairing.resolve_helper_rollout_device(device_id=guid, install_id=True) is None
        db.execute("DELETE FROM mesh_device_helper_ready WHERE device_id != ?", (DEVICE,))
        future = (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat(timespec="milliseconds")
        db.execute("UPDATE mesh_device_helper_ready SET received_at=?", (future,))
        db.commit()
        assert await pairing.resolve_helper_rollout_device(device_id=guid, install_id=True) is None
    try:
        asyncio.run(run())
    finally:
        db.close()


def test_timer_default_off():
    hooks = LifespanHooks()
    app = SimpleNamespace(router=SimpleNamespace(lifespan_context=hooks))
    host.install_maintenance_timer(app, env={}, db=None, process_lock=None)
    assert hooks.on_startup == hooks.on_shutdown == []


def test_server_owner_context_live_authority_and_reset(caplog):
    from dataclasses import replace
    from app.connector_account_subject import maintenance_owner_context, subject_for_connector_read
    from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
    from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType
    from padiem_control_plane.tenants import TenantMembership, TenantMembershipRole

    now = datetime.now(timezone.utc)
    session = AuthSessionSnapshot(
        session_id="session_test", product_id="b54-padiem-claw",
        subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=SUB),
        issued_at=now-timedelta(minutes=1), expires_at=now+timedelta(minutes=10), tenant_id=TENANT)
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE users(id TEXT,auth_provider TEXT,provider_subject TEXT)")
    db.execute("INSERT INTO users VALUES (?,?,?)", (UID, "shared", "shared:" + SUB))
    db.commit()

    class Authority:
        current = session
        uid = UID
        role = TenantMembershipRole.OWNER

        async def resolve_current_auth_session(self, **kw):
            assert kw == {"product_id": "b54-padiem-claw", "product_user_id": UID}
            return self.current

        async def resolve_product_user_for_subject_uncached(self, **kw):
            assert kw == {"product_id": "b62", "canonical_subject_id": SUB}
            return self.uid

        async def resolve_active_tenant_membership(self, **kw):
            return TenantMembership(tenant_id=TENANT, canonical_subject_id=SUB, role=self.role)

    authority = Authority()
    wrapper = SimpleNamespace(maintenance_uncached_authority=lambda: authority)
    app = SimpleNamespace(state=SimpleNamespace(control_plane_identity_authority=wrapper,
                                               account_data_db=SqliteD1(db)))

    async def run():
        async with maintenance_owner_context(app, UID) as verified:
            assert verified is session
            assert subject_for_connector_read(session.session_id, "owner_scope").subject_id == SUB
        assert subject_for_connector_read(session.session_id, "owner_scope") is None
        authority.uid = "usr_other"
        with pytest.raises(ValueError, match="maintenance_owner_unresolved"):
            async with maintenance_owner_context(app, UID):
                pytest.fail("foreign owner")
        authority.uid = UID
        authority.role = None
        with pytest.raises(ValueError, match="maintenance_owner_unresolved"):
            async with maintenance_owner_context(app, UID):
                pytest.fail("inactive membership")
        authority.role = TenantMembershipRole.OWNER
        authority.current = replace(session, state=AuthSessionState.REVOKED)
        with pytest.raises(ValueError, match="maintenance_owner_unresolved"):
            async with maintenance_owner_context(app, UID):
                pytest.fail("revoked session")
    try:
        asyncio.run(run())
    finally:
        db.close()
    text = caplog.text
    for stage in ("b62_reverse_link", "membership", "session_expiry"):
        assert f"outcome=denied stage={stage}" in text
    assert UID not in text and SUB not in text and TENANT not in text


@pytest.mark.parametrize(("failure", "expected"), [
    (None, None), ("b54", "b54_session"), ("reverse", "b62_reverse_link"),
    ("membership", "membership"), ("provider", "provider_subject"),
    ("b62_missing", "b62_session"), ("b62_other_subject", "b62_session"),
    ("b62_other_tenant", "b62_session"), ("b62_revoked", "session_expiry"),
])
def test_legacy_google_owner_requires_exact_live_b54_and_b62(failure, expected, caplog):
    from dataclasses import replace
    from app.connector_account_subject import maintenance_owner_context, subject_for_connector_read
    from app.history import _user_id
    from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
    from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType
    from padiem_control_plane.tenants import TenantMembership, TenantMembershipRole

    provider = "legacy-google-fixture-private"
    uid = _user_id(provider)
    now = datetime.now(timezone.utc)
    b54 = AuthSessionSnapshot(
        session_id="session_b54", product_id="b54-padiem-claw",
        subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=SUB),
        issued_at=now-timedelta(minutes=1), expires_at=now+timedelta(minutes=10), tenant_id=TENANT)
    b62 = replace(b54, product_id="b62", session_id="session_b62",
                  expires_at=now+timedelta(minutes=5))
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE users(id TEXT,auth_provider TEXT,provider_subject TEXT)")
    db.execute("INSERT INTO users VALUES (?,?,?)",
               (uid, "google", "wrong-legacy-subject" if failure == "provider" else provider))

    class Authority:
        async def resolve_current_auth_session(self, **kw):
            assert kw["product_user_id"] == uid
            if kw["product_id"] == "b54-padiem-claw":
                if failure == "b54":
                    raise RuntimeError("private-fixture")
                return b54
            assert kw["product_id"] == "b62"
            if failure == "b62_missing":
                raise RuntimeError("private-fixture")
            if failure == "b62_other_subject":
                return replace(b62, subject=CanonicalSubjectRef(
                    subject_type=SubjectType.USER, subject_id="sub_" + "c"*32))
            if failure == "b62_other_tenant":
                return replace(b62, tenant_id="tenant_" + "d"*32)
            if failure == "b62_revoked":
                return replace(b62, state=AuthSessionState.REVOKED)
            return b62

        async def resolve_product_user_for_subject_uncached(self, **kw):
            assert kw == {"product_id": "b62", "canonical_subject_id": SUB}
            return "usr_other" if failure == "reverse" else uid

        async def resolve_product_user_for_subject(self, **kw):
            pytest.fail("maintenance must not read the process cache")

        async def resolve_active_tenant_membership(self, **kw):
            return TenantMembership(tenant_id=TENANT, canonical_subject_id=SUB,
                                    role=None if failure == "membership" else TenantMembershipRole.OWNER)

    authority = Authority()
    app = SimpleNamespace(state=SimpleNamespace(control_plane_identity_authority=authority,
                                               account_data_db=SqliteD1(db)))

    async def run():
        if expected:
            with pytest.raises(ValueError, match="maintenance_owner_unresolved"):
                async with maintenance_owner_context(app, uid):
                    pytest.fail("unverified owner")
            assert f"outcome=denied stage={expected}" in caplog.text
        else:
            async with maintenance_owner_context(app, uid) as verified:
                assert verified is b54
                proof = subject_for_connector_read(b54.session_id, "owner_scope")
                assert proof.subject_id == SUB
                assert proof.expires_at == b62.expires_at.timestamp()
        assert subject_for_connector_read(b54.session_id, "owner_scope") is None
        for private in (uid, provider, SUB, TENANT, "private-fixture"):
            assert private not in caplog.text

    try:
        asyncio.run(run())
    finally:
        db.close()


def test_maintenance_reverse_lookup_reads_live_authority_not_process_cache(monkeypatch):
    from app import control_plane_identity_worker as identity

    def cache_forbidden(*args):
        pytest.fail("maintenance cannot use the reverse-link cache")

    monkeypatch.setattr(identity, "_product_user_cache_get", cache_forbidden)
    monkeypatch.setattr(identity, "_product_user_cache_put", cache_forbidden)
    calls = []

    async def reverse(payload):
        calls.append(payload)
        return {"ok": True, "product_user_id": UID if len(calls) == 1 else "usr_other"}

    authority = identity.CloudflareControlPlaneIdentityAuthority(
        SimpleNamespace(resolve_product_user_for_subject=reverse))

    async def run():
        for expected in (UID, "usr_other"):
            assert await authority.resolve_product_user_for_subject_uncached(
                product_id="b62", canonical_subject_id=SUB) == expected
    asyncio.run(run())
    assert len(calls) == 2


def test_granted_consent_is_found_by_the_maintenance_lookup(rig, monkeypatch):
    """Round trip through the real durable store: the human grant stores the
    connector device id, and maintenance reads that exact record through the
    managed link's server-owned map pair. No Mesh string is reshaped."""
    app, queue, history, flags, store, db = rig
    storage = DurableStorage()
    records = IdentityDurableConnectorEnrollmentRecords(
        storage=storage,
        session_reader=SimpleNamespace(resolve_auth_session=lambda **kw: None),
    )
    records.install_schema()
    records.persist_preverified_consent(
        consent=ConnectorEnrollmentConsent(
            consent_id="consent." + "a" * 32, owner_subject_id=SUB,
            account_ref=SCOPE["account_ref"], workspace_ref=SCOPE["workspace_ref"],
            device_id=CONNECTOR, granted_at=NOW,
        ),
        now=NOW,
    )
    stored = records.current_for_device(owner_subject_id=SUB, device_id=CONNECTOR, now=NOW)
    assert stored is not None and stored.device_id == CONNECTOR
    # The consent server's own grammar is unchanged: the composed Mesh value
    # is refused as a reference, and a valid-but-different value finds nothing.
    with pytest.raises(ControlPlaneContractError) as refusal:
        records.current_for_device(owner_subject_id=SUB, device_id=DEVICE, now=NOW)
    assert refusal.value.code == "connector_enrollment_invalid_reference"
    assert records.current_for_device(
        owner_subject_id=SUB, device_id=DEVICE.rsplit("/", 1)[1], now=NOW) is None

    class DurableRefusal(Exception):
        def __init__(self, code):
            super().__init__(code)
            self.code = code

    async def durable_read(identity, method, **kw):
        if method == "owner_scope":
            return SCOPE
        flags["consent_refs"].append(kw.get("device_id"))
        try:
            current = records.current_for_device(
                owner_subject_id=SUB, device_id=kw.get("device_id"), now=NOW)
        except ControlPlaneContractError as exc:
            raise DurableRefusal(exc.code) from None
        if (current is None or current.account_ref != SCOPE["account_ref"]
                or current.workspace_ref != SCOPE["workspace_ref"]):
            raise DurableRefusal("enrollment_consent_required")
        return {"owner_subject_id": current.owner_subject_id,
                "device_id": current.device_id, "withdrawn_at": None,
                "consent_id": current.consent_id, "account_ref": current.account_ref,
                "workspace_ref": current.workspace_ref}

    monkeypatch.setattr(host, "mode_connector_read", durable_read)
    asyncio.run(host.maintenance_round(app, ENV, store))
    assert set(flags["consent_refs"]) == {CONNECTOR}
    assert len(history.rows) == 1
    assert history.rows[0]["node_ref"] == DEVICE
