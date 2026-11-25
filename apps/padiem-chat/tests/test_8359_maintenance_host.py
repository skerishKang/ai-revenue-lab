"""Chat-host integration with a real local SQLite journal and fake queue/PC."""
from __future__ import annotations

import asyncio
import json
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
from app.pc_device_pairing_store import D1PcPairingStore
from _support import pc_device_pairing as pairing_support

NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)
DEVICE = "node//managed-fixture"
UID = "usr_owner"
OTHER_UID = "usr_other"
ADMIN = "usr_admin"
#: The real target resolver; the rig below replaces the module attribute.
REAL_TARGET = routes._engine_pc_files_target
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
#: The deployment ownership map as production holds it: one stale file-lane
#: placeholder that names neither this account nor this PC. The maintenance
#: path must work without it and must never read a pair from it.
MAP = [{"account_ref": "account-placeholder", "device_id": "placeholder-device",
        "node_ref": "node//placeholder", "root_ref": "pcroot_placeholder",
        "path_relative": "placeholder.txt", "file_path": "C:/placeholder.txt",
        "command_exec": False}]
#: The link owner's own #8204 setting row, as the owner-scoped list returns it.
PREFERENCE = {"link_id": LINK["link_id"], "mesh_node_id": DEVICE, "label": "PC",
              "auto_helper_update": 1, "helper_update_dismissed_version": None}


class Queue:
    """No PC execution; only existing proxy-shaped methods."""
    def __init__(self):
        self.links = [LINK]
        self.preferences = {UID: [dict(PREFERENCE)]}
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

    async def list_helper_update_preferences(self, *, user_id):
        # Owner-scoped, like the real store: another account's rows never appear.
        return [dict(row) for row in self.preferences.get(user_id, [])]

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
        if not row or row["attempt_id"] != attempt_id:
            return
        if result.get("reason") is not None:
            # A terminal verdict may follow a dispatch; reason is writable once.
            if row["reason"] is None:
                row["reason"] = result["reason"]
            return
        if not row["dispatch_id"] and not row["reason"]:
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
                "exit_code": getattr(self, "exit_code", 0), "termination": getattr(self, "termination", "exited"),
                "dispatch_id": "dispatch-fixture"}


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
    flags = {"session": True, "scope": True, "admin": True, "precontact": False, "stage": "internal",
             "target": DEVICE, "revoked_after_run": False, "owners": {UID}}

    @asynccontextmanager
    async def owner(app, uid):
        assert uid in flags["owners"]
        if not flags["session"] or (flags["revoked_after_run"] and history.runs):
            raise ValueError("maintenance_owner_unresolved")
        yield session

    flags["reads"] = []

    async def read(identity, method, **kw):
        flags["reads"].append(method)
        # 2026-11-24 decision: maintenance asks only for the owner scope. A
        # native connector enrollment consent read would be a regression.
        assert method == "owner_scope", "maintenance must not read enrollment consent"
        return SCOPE if flags["scope"] else None

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
        # #8359 (2026-11-24): the owner authority is the managed mark plus the
        # owner's automatic-update setting; no enrollment consent is read.
        assert flags["reads"] and set(flags["reads"]) == {"owner_scope"}
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

@pytest.mark.parametrize("denial", [
    "switch", "unmanaged", "multi", "offline", "owner", "scope", "auto_off",
    "setting_missing", "foreign_setting", "unmarked", "paused", "admin", "stage",
    "target", "guid", "revoked_after_run"])
def test_row_creation_denied(rig, denial, caplog):
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
    elif denial == "scope":
        flags["scope"] = False
    elif denial == "auto_off":
        queue.preferences[UID][0]["auto_helper_update"] = 0
    elif denial == "setting_missing":
        queue.preferences = {}
    elif denial == "foreign_setting":
        # Another account linked to the same PC keeps automatic updates on.
        queue.preferences = {UID: [{**PREFERENCE, "auto_helper_update": 0}],
                             OTHER_UID: [{**PREFERENCE, "link_id": "pcl_other"}]}
    elif denial == "unmarked":
        queue.links = [{**LINK, "managed_at": None, "managed_by": None}]
    elif denial == "paused":
        queue.links = [{**LINK, "paused_at": NOW.isoformat()}]
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
        alerts = db.execute("SELECT count(*) FROM ops_alert_outbox").fetchone()[0]
        audits = db.execute("SELECT count(*) FROM ops_audit_log").fetchone()[0]
        if denial in ("owner", "scope", "setting_missing", "paused"):
            # An owner-authority inconsistency is deferred and alerted once.
            assert (alerts, audits) == (1, 1)
        if denial in ("auto_off", "foreign_setting"):
            # The owner's own choice: nothing deferred, alerted or reserved.
            assert (alerts, audits) == (0, 0)
            assert db.execute("SELECT count(*) FROM pc_helper_auto_attempts").fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM pc_helper_maintenance_jobs").fetchone()[0] == 0
    asyncio.run(run())
    lines = [r.getMessage() for r in caplog.records
             if r.getMessage().startswith("pc_maintenance_candidate ")
             and "outcome=not_managed" not in r.getMessage()]
    expected = {
        "scope": ("owner_authority=denied", "outcome=owner_authority_denied"),
        "setting_missing": ("owner_authority=denied", "outcome=owner_authority_denied"),
        "paused": ("owner_authority=denied", "outcome=owner_authority_denied"),
        "auto_off": ("owner_authority=auto_update_off", "outcome=owner_auto_update_off"),
        "foreign_setting": ("owner_authority=auto_update_off", "outcome=owner_auto_update_off"),
        "target": ("owner_authority=target_mismatch", "outcome=target_mismatch"),
        "unmarked": ("owner_authority=not_checked", "outcome=owner_link_denied"),
    }.get(denial)
    if expected:
        assert lines and all(field in line for line in lines for field in expected)
    reasons = {"scope": "scope_missing", "setting_missing": "owner_setting_missing",
               "paused": "owner_managed_missing", "auto_off": "owner_auto_update_off",
               "foreign_setting": "owner_auto_update_off"}
    if denial in reasons:
        # Two rounds, one value-free line (#8658 hourly suppression).
        assert caplog.text.count(
            "pc_maintenance_owner_authority outcome=denied reason=" + reasons[denial]) == 1


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


def _real_pairing(rig, monkeypatch, *, managed=True, auto=True, extra=None):
    """Swap in the real pairing store and the real target resolver.

    The managed mark, the owner's #8204 setting, pause and revoke are written
    by the store's own methods over the migrated schema, so the SQL that
    answers the maintenance path is the production SQL.
    """
    app = rig[0]
    conn = pairing_support.database()
    real = D1PcPairingStore(SqliteD1(conn))

    async def build():
        link = await real.adopt_link(user_id=UID, mesh_node_id=DEVICE, root_paths=[],
                                     now=NOW, drives=["C:"])
        if managed:
            await real.set_managed(link_id=link["link_id"], by_user_id=ADMIN,
                                   managed=True, now=NOW)
        if not auto:
            assert await real.set_helper_update_preference(
                user_id=UID, link_id=link["link_id"], auto=False)
        if extra is not None:
            await extra(real, link)
        return link

    link = asyncio.run(build())
    app.state.pc_device_pairing_store = real
    monkeypatch.setattr(routes, "_engine_pc_files_target", REAL_TARGET)
    return real, link, conn


def _journal(db):
    return {name: db.execute("SELECT count(*) FROM " + name).fetchone()[0]
            for name in ("pc_helper_maintenance_jobs", "pc_helper_auto_attempts",
                         "ops_alert_outbox", "ops_audit_log")}


def test_real_store_managed_link_with_automatic_updates_creates_the_job(rig, monkeypatch, caplog):
    app, queue, history, flags, store, db = rig
    real, link, conn = _real_pairing(rig, monkeypatch)
    try:
        asyncio.run(host.maintenance_round(app, ENV, store))
    finally:
        conn.close()
    assert len(history.rows) == 1
    row = history.rows[0]
    assert row["user_id"] == UID and row["device_id"] == row["node_ref"] == DEVICE
    assert row["command_text"] == registration_command() and row["user_mode"] is False
    assert set(flags["reads"]) == {"owner_scope"}
    job = db.execute("SELECT owner_id,status,action FROM pc_helper_maintenance_jobs").fetchone()
    assert tuple(job) == (UID, "queued", "refresh")
    line = next(r.getMessage() for r in caplog.records
                if r.getMessage().startswith("pc_maintenance_candidate ")
                and "managed=yes" in r.getMessage())
    assert "owner_session=yes" in line and "owner_authority=passed" in line
    assert "outcome=dispatch_attempted" in line
    assert "pc_maintenance_owner_authority" not in caplog.text
    assert link["link_id"] not in caplog.text and UID not in caplog.text


def test_real_store_automatic_updates_off_runs_nothing_and_owner_notice_takes_over(
        rig, monkeypatch, caplog):
    """자동 꺼짐: 자동 실행하지 않고, #8204의 주인 알림(같은 링크 설정이 켜는 표시)에 맡긴다."""
    from app import pc_helper_update_routes as updates

    app, queue, history, flags, store, db = rig
    real, link, conn = _real_pairing(rig, monkeypatch, auto=False)

    async def available(_state, *, device_id, now):
        assert device_id == DEVICE
        return {"helper_version": "0.3.0-rc1", "latest_version": RELEASE["version"],
                "update_available": True, "update_required": False}

    monkeypatch.setattr(updates, "current_user_id", lambda request: request.user)
    monkeypatch.setattr(updates, "_now", lambda: queue.now)
    monkeypatch.setattr(updates, "load_update_view", available)

    async def run():
        await host.maintenance_round(app, ENV, store)
        await host.maintenance_round(app, ENV, store)
        assert history.rows == [] and history.runs == {}
        assert set(_journal(db).values()) == {0}
        shown = await updates.list_updates(SimpleNamespace(app=app, user=UID))
        device = json.loads(shown.body)["devices"][0]
        assert device["link_id"] == link["link_id"]
        assert device["auto_update"] is False and device["notice"] is True
        # 주인이 다시 켜면 다음 회차에 자동 유지보수가 그대로 이어진다.
        assert await real.set_helper_update_preference(
            user_id=UID, link_id=link["link_id"], auto=True)
        queue.now += timedelta(seconds=60)
        await host.maintenance_round(app, ENV, store)
        assert len(history.rows) == 1 and history.rows[0]["user_id"] == UID
    try:
        asyncio.run(run())
    finally:
        conn.close()
    assert caplog.text.count(
        "pc_maintenance_owner_authority outcome=denied reason=owner_auto_update_off") == 1
    assert "owner_authority=auto_update_off outcome=owner_auto_update_off" in caplog.text


@pytest.mark.parametrize("state", ["unmanaged", "unmarked_later", "paused", "revoked"])
def test_real_store_unmanaged_paused_or_revoked_link_is_refused(rig, monkeypatch, caplog, state):
    app, queue, history, flags, store, db = rig

    async def change(real, link):
        if state == "unmarked_later":
            await real.set_managed(link_id=link["link_id"], by_user_id=ADMIN,
                                   managed=False, now=NOW)
        elif state == "paused":
            await real.pause_link(user_id=UID, link_id=link["link_id"], now=NOW)
        elif state == "revoked":
            assert await real.revoke_link(user_id=UID, link_id=link["link_id"], now=NOW)

    real, link, conn = _real_pairing(rig, monkeypatch, managed=state != "unmanaged", extra=change)
    try:
        asyncio.run(host.maintenance_round(app, ENV, store))
    finally:
        conn.close()
    assert history.rows == [] and history.runs == {}
    assert set(_journal(db).values()) == {0}
    assert "owner_authority=passed" not in caplog.text
    assert "outcome=dispatch_attempted" not in caplog.text


def test_real_store_other_account_on_the_same_pc_never_lends_its_permission(
        rig, monkeypatch, caplog):
    """같은 PC에 다른 계정 링크(관리 표시 없음, 자동 켜짐)가 있어도 그 설정을 빌리지 않는다."""
    app, queue, history, flags, store, db = rig

    async def second_account(real, link):
        other = await real.adopt_link(user_id=OTHER_UID, mesh_node_id=DEVICE, root_paths=[],
                                      now=NOW, drives=["C:"])
        rows = await real.list_helper_update_preferences(user_id=OTHER_UID)
        assert [row["auto_helper_update"] for row in rows] == [1]
        assert other["link_id"] != link["link_id"]

    real, link, conn = _real_pairing(rig, monkeypatch, auto=False, extra=second_account)
    try:
        asyncio.run(host.maintenance_round(app, ENV, store))
        assert history.rows == [] and history.runs == {}
        assert set(_journal(db).values()) == {0}
        assert "outcome=owner_auto_update_off" in caplog.text
        # 관리 표시가 다른 계정의 링크에만 있으면 그 계정의 세션·범위·설정으로만 판정한다.
        async def move_mark():
            await real.set_managed(link_id=link["link_id"], by_user_id=ADMIN,
                                   managed=False, now=NOW)
            other = (await real.list_helper_update_preferences(user_id=OTHER_UID))[0]
            await real.set_managed(link_id=other["link_id"], by_user_id=ADMIN,
                                   managed=True, now=NOW)
            return other
        other = asyncio.run(move_mark())
        flags["owners"] = {OTHER_UID}
        queue.now += timedelta(seconds=60)
        asyncio.run(host.maintenance_round(app, ENV, store))
        assert len(history.rows) == 1
        assert history.rows[0]["user_id"] == OTHER_UID
        job = db.execute("SELECT owner_id FROM pc_helper_maintenance_jobs").fetchone()
        assert job[0] == OTHER_UID and other["link_id"] != link["link_id"]
    finally:
        conn.close()


def _run_to_receipt(app, queue, history, store, *, exit_code, termination):
    async def run():
        await host.maintenance_round(app, ENV, store)
        assert len(history.rows) == 1
        history.done, history.exit_code, history.termination = True, exit_code, termination
        queue.now += timedelta(seconds=60)
        await host.maintenance_round(app, ENV, store)
        queue.now += timedelta(seconds=60)
        queue.state["updater_source_sha256"] = SOURCE_SHA256
        await host.maintenance_round(app, ENV, store)
        await host.maintenance_round(app, ENV, store)
    asyncio.run(run())


def test_system_command_without_exit_code_is_judged_by_receipt_and_observation(rig, monkeypatch):
    """#8359 (2026-11-24): the SYSTEM lane often ends ``no_exit_code`` even when
    the script finished; the fixed marker and the later observation decide."""
    app, queue, history, _flags, store, db = rig

    async def original(*args, **kw):
        return "PADIEM_HELPER_REFRESH:updated:registered\r\n"

    monkeypatch.setattr("app.mcp_gateway_shell._read_original", original)
    _run_to_receipt(app, queue, history, store, exit_code=None, termination="no_exit_code")
    assert db.execute("SELECT outcome FROM pc_helper_maintenance_jobs").fetchone()[0] == "verified"


@pytest.mark.parametrize(("exit_code", "termination"), [(None, "timed_out"), (None, "no_reply"), (1, "exited")])
def test_command_that_did_not_finish_stays_dispatch_failed(rig, monkeypatch, exit_code, termination):
    app, queue, history, _flags, store, db = rig

    async def original(*args, **kw):
        return "PADIEM_HELPER_REFRESH:updated:registered"

    monkeypatch.setattr("app.mcp_gateway_shell._read_original", original)
    _run_to_receipt(app, queue, history, store, exit_code=exit_code, termination=termination)
    assert db.execute("SELECT outcome FROM pc_helper_maintenance_jobs").fetchone()[0] == "dispatch_failed"


def test_failed_refresh_logs_its_bounded_cause(rig, monkeypatch, caplog):
    app, queue, history, _flags, store, db = rig

    async def original(*args, **kw):
        return ("PADIEM_HELPER_REFRESH:failed:registration_failed\r\n"
                "PADIEM_HELPER_REFRESH_DETAIL:unexpected_helper_task_12_getitem\r\n")

    monkeypatch.setattr("app.mcp_gateway_shell._read_original", original)
    caplog.set_level("WARNING")
    _run_to_receipt(app, queue, history, store, exit_code=None, termination="no_exit_code")
    assert db.execute("SELECT outcome FROM pc_helper_maintenance_jobs").fetchone()[0] == "registration_failed"
    assert "reason=registration_failed detail=unexpected_helper_task_12_getitem" in caplog.text
