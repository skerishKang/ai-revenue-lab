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
from app.ops_alert_store import D1OpsAlertStore
from app.ops_audit_store import OpsAuditStore
from app import pc_helper_maintenance_host as host
from app import oracle_mesh_read_return_routes as routes
from app.pc_helper_registration import SOURCE_SHA256, registration_command
from app.pc_helper_install import install_command, install_script

NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)
DEVICE = "node//managed-fixture"
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
        oracle_mesh_return_source=SimpleNamespace(configured=True, execution_mode=routes.EXECUTION_MODE_MESH),
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

    async def read(identity, method, **kw):
        if method == "owner_scope":
            return SCOPE
        return {**SCOPE, "device_id": DEVICE, "withdrawn_at": None,
                "consent_id": "consent-fixture"} if flags["consent"] else None

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
    fresh = datetime.now(timezone.utc).isoformat()
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
    try:
        asyncio.run(run())
    finally:
        db.close()


def test_timer_default_off():
    app = SimpleNamespace(router=SimpleNamespace(on_startup=[], on_shutdown=[]))
    host.install_maintenance_timer(app, env={}, db=None, process_lock=None)
    assert app.router.on_startup == app.router.on_shutdown == []


def test_server_owner_context_live_authority_and_reset():
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
    db.execute("CREATE TABLE users(id TEXT,provider_subject TEXT)")
    db.execute("INSERT INTO users VALUES (?,?)", (UID, "shared:" + SUB))
    db.commit()

    class Authority:
        current = session
        uid = UID
        role = TenantMembershipRole.OWNER

        async def resolve_current_auth_session(self, **kw):
            assert kw == {"product_id": "b54-padiem-claw", "product_user_id": UID}
            return self.current

        async def resolve_product_user_for_subject(self, **kw):
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
