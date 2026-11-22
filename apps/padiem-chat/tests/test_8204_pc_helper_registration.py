"""The post-deploy operator action uses the same managed-owner command authority."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from starlette.responses import JSONResponse
from app import pc_helper_registration_routes as routes
from app.d1_sqlite import SqliteD1
from app.mesh_device_drive_store import D1MeshDeviceDriveStore
from app.pc_helper_registration import MAX_AGE, SOURCE_SHA256, parse_receipt, plan_registration, registration_command
from kagent.local_agent_mesh_drive_inventory import DRIVE_REFRESH_SECONDS
from _support.ops_audit_helpers import OTHER, OWNER, database, payload, request
from padiem_ai_core.pc_helper_ready import validate_helper_ready, HelperReadyError

NOW = datetime(2026, 11, 22, 1, 0, tzinfo=timezone.utc)
OLD = "a" * 64
READY = {"task_present": True, "install_dir_present": True, "pipe_open": True,
         "interactive_session": True, "helper_build": OLD[:12], "helper_sha256": OLD,
         "helper_status_present": True, "updater_source_present": True,
         "updater_source_sha256": OLD, "updater_task_present": True}
DEVICES = ["node//current", "node//old", "node//missing", "node//denied", "node//unknown"]


@pytest.mark.parametrize("change,allowed,elapsed,expected", [
    ({"updater_source_sha256": SOURCE_SHA256}, True, 0, ("skipped", "already_current")),
    ({"updater_source_sha256": SOURCE_SHA256, "self_heal_task_present": True}, True, 0, ("skipped", "already_current")),
    ({"updater_source_sha256": SOURCE_SHA256, "self_heal_task_present": False}, True, 0, ("refresh", "watcher_missing")),
    ({"self_heal_task_present": False}, True, 0, ("refresh", "source_changed")),
    ({}, True, 0, ("refresh", "source_changed")),
    ({"helper_status_present": False}, True, 0, ("install", "status_missing")),
    ({"helper_sha256": None, "helper_build": None}, True, 0, ("install", "release_unknown")),
    ({"helper_status_present": None}, True, 0, ("failed", "status_unknown")),
    ({}, False, 0, ("reinstall_required", "system_denied")),
    ({}, True, 181, ("failed", "observation_stale")),
    ({"updater_source_sha256": None}, True, 0, ("failed", "digest_unverified")),
    ({"updater_source_present": False, "updater_source_sha256": None}, True, 0, ("refresh", "source_changed")),
])
def test_plan(change, allowed, elapsed, expected):
    row = {"received_at": (NOW - timedelta(seconds=elapsed)).isoformat(), "state": {**READY, **change}}
    answer = plan_registration(row, system_allowed=allowed, now=NOW)
    assert (answer["action"], answer["reason"]) == expected


def test_bounded_observation_and_receipt():
    assert validate_helper_ready(READY)["updater_source_sha256"] == OLD
    for extra in ({"updater_source_sha256": "private path"}, {"updater_source_present": False},
                  {"helper_status_present": 1}):
        with pytest.raises(HelperReadyError):
            validate_helper_ready({**READY, **extra})
    assert validate_helper_ready({**READY, "self_heal_task_present": True})["self_heal_task_present"] is True
    assert "self_heal_task_present" not in validate_helper_ready(READY)
    with pytest.raises(HelperReadyError):
        validate_helper_ready({**READY, "self_heal_task_present": 1})
    assert parse_receipt("PADIEM_HELPER_REFRESH:updated:registered") == {"action": "updated", "reason": "registered"}
    assert parse_receipt("PADIEM_HELPER_REFRESH:updated:watcher_python_missing")["reason"] == "watcher_python_missing"
    assert parse_receipt("PADIEM_HELPER_REFRESH:failed:watcher_unregistered")["reason"] == "watcher_unregistered"
    assert parse_receipt("PADIEM_HELPER_REFRESH:failed:private_path")["reason"] == "receipt_unverified"
    assert parse_receipt("PADIEM_HELPER_REFRESH:updated:registered\nPADIEM_HELPER_REFRESH:skipped:already_current")["action"] == "failed"


def test_dry_run_no_writes_and_permission_and_one_dispatch(monkeypatch):
    async def run():
        db, feedback = database(full=True)
        try:
            store = D1MeshDeviceDriveStore(SqliteD1(db))
            for device, update in zip(DEVICES[:4], ({"updater_source_sha256": SOURCE_SHA256}, {},
                {"helper_status_present": False}, {})):
                await store.upsert_helper_ready(device_id=device, state={**READY, **update}, received_at=NOW)
            class Pairing:
                async def list_active_device_ids(self): return DEVICES
                async def list_helper_update_preferences(self, *, user_id):
                    assert user_id == OTHER
                    return [{"link_id": str(i), "mesh_node_id": device} for i, device in enumerate(DEVICES)]
            calls = []
            async def canonical(req): return SimpleNamespace(tenant_id="tenant"), None
            async def workspace(req, uid, session): return "workspace"
            async def allowed(req, *, uid, device_id): return uid == OTHER and device_id != DEVICES[3]
            async def target(req, *, session, uid, link):
                return {"node_ref": link["mesh_node_id"]}, None
            async def stage(req, **kwargs): calls.append("stage"); return ("run", "conv")
            async def dispatch(req, **kwargs):
                calls.append(kwargs)
                assert kwargs["command"] == registration_command()
                assert kwargs["user_mode"] is False
                assert kwargs["wire"]["device_id"] == DEVICES[1]
                return JSONResponse({"dispatch": {"dispatch_id": "dsp_fixture", "device_id": DEVICES[1], "user_mode": False}})
            class History:
                done = False
                async def get_oracle_mesh_dispatch_for_owner(self, *, user_id, dispatch_id):
                    assert user_id == OTHER and dispatch_id == "dsp_fixture"
                    return {"state": "done" if self.done else "pending", "exit_code": 0, "run_id": "run"}
                async def get_claw_run(self, uid, run_id): return {"run_id": run_id}
            history = History()
            async def original(*args, **kwargs): return "PADIEM_HELPER_REFRESH:updated:registered"
            monkeypatch.setattr(routes, "_verified_owner_request", canonical)
            monkeypatch.setattr(routes, "_dispatch_workspace_id", workspace)
            monkeypatch.setattr(routes, "_pc_system_mode_allowed", allowed)
            monkeypatch.setattr(routes, "_dispatch_target", target)
            monkeypatch.setattr(routes, "_stage_run", stage)
            monkeypatch.setattr(routes, "dispatch_oracle_mesh_command_intent", dispatch)
            monkeypatch.setattr(routes, "_read_original", original)
            monkeypatch.setattr(routes, "_now", lambda: NOW)
            async def call(user, body):
                req = request(feedback, user=user, body=body, method="POST", path=routes.PATH)
                req.app.state.pc_device_pairing_store = Pairing()
                req.app.state.mesh_device_drive_store = store
                req.app.state.history_store = history
                return await routes.admin_refresh_updaters(req)
            assert (await call(None, {"dry_run": True})).status_code == 401
            assert (await call(OWNER, {"dry_run": False, "source_sha256": SOURCE_SHA256})).status_code == 403
            assert (await call(OTHER, {"dry_run": False, "source_sha256": OLD})).status_code == 409
            assert (await call(OTHER, {"dry_run": True, "command": "anything"})).status_code == 400
            count = lambda: db.execute("SELECT COUNT(*) FROM pc_helper_registration").fetchone()[0]
            dry = payload(await call(OTHER, {"dry_run": True}))
            # #8359 F6: a missing helper plans "install"; the operator button never runs it.
            assert [x["action"] for x in dry["devices"]] == ["skipped", "refresh", "install", "reinstall_required", "failed"]
            assert dry["devices"][2]["reason"] == "status_missing"
            assert dry["source_sha256"] == SOURCE_SHA256 and count() == 0 and not calls
            actual = payload(await call(OTHER, {"dry_run": False, "source_sha256": SOURCE_SHA256}))
            assert actual["devices"][1]["action"] == "queued" and count() == 1 and len(calls) == 2
            again = payload(await call(OTHER, {"dry_run": False, "source_sha256": SOURCE_SHA256}))
            assert again["devices"][1]["action"] == "queued" and count() == 1 and len(calls) == 2
            history.done = True
            done = payload(await call(OTHER, {"dry_run": True}))
            assert done["devices"][1]["action"] == "updated" and len(calls) == 2
        finally:
            db.close()
    asyncio.run(run())


def test_stale_window_outlasts_the_helper_status_round():
    # #8385: the readiness report rides every drive round, so two missed
    # rounds still leave a fresh observation inside the refresh window.
    assert MAX_AGE.total_seconds() > DRIVE_REFRESH_SECONDS * 2


def test_refresh_command_registers_the_fixed_watcher_after_the_updater():
    """#8359 F7: the one refresh command also keeps the SYSTEM self-heal task.

    Both payloads are the repository's own fixed bytes. The watcher is
    registered only when the PC has an interpreter (read the installer's way)
    and is not registered yet; a current updater with a present watcher is
    skipped; no interpreter leaves the updater refreshed and says so.
    """
    from kagent.pc_self_heal_task import TASK_NAME, render_watcher_command
    from app.pc_helper_update import render_helper_updater_command

    command = registration_command()
    updater, watcher = render_helper_updater_command(), render_watcher_command()
    assert command.count(updater) == 1 and command.count(watcher) == 1
    assert command.index(updater) < command.index(watcher)
    assert "-TaskName " + TASK_NAME + " -ErrorAction SilentlyContinue" in command
    assert "$py=$env:PADIEM_PYTHON" in command and "Get-Command python.exe" in command
    assert "if($same -and $task -and ($watcher -or -not $py))" in command
    assert "if(-not($same -and $task)){" + updater in command
    assert "if($py -and -not $watcher){$PythonExecutable=$py;" + watcher in command
    for marker in ("skipped:already_current", "failed:updater_running", "failed:digest_unverified",
                   "failed:watcher_unregistered", "updated:registered", "updated:watcher_python_missing",
                   "failed:registration_failed"):
        assert command.count("PADIEM_HELPER_REFRESH:" + marker) == 1
    # The marker vocabulary and the receipt parser agree.
    for text in ("updated:registered", "updated:watcher_python_missing", "failed:watcher_unregistered"):
        assert parse_receipt("PADIEM_HELPER_REFRESH:" + text)["reason"] == text.split(":")[1]
    assert "http" not in command.replace("FromBase64String", "")
