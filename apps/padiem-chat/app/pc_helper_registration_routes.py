"""Administrator-triggered, release-pinned updater maintenance; no free command input."""
from __future__ import annotations

import json
import uuid

from starlette.responses import JSONResponse
from .auth_routes import current_user_id
from .central_model_control_routes import _central_admin
from .claw_connector_enrollment_routes import _verified_owner_request
from .mcp_gateway_execution import _pc_system_mode_allowed
from .mcp_gateway_shell import _read_original
from .pc_device_pairing_routes import _body, _now
from .pc_file_exchange_routes import _dispatch_target, _stage_run
from .pc_helper_registration import (SOURCE_SHA256, command_finished, parse_receipt, plan_registration,
                                     registration_command)
from .oracle_mesh_read_return_routes import _dispatch_workspace_id, dispatch_oracle_mesh_command_intent

PATH = "/api/admin/ops-pc-versions/refresh-updaters"


def _response(body, status=200):
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})


async def _receipt_view(request, receipt):
    if receipt.get("reason"):
        return {"action": "failed", "reason": receipt["reason"]}
    if not receipt.get("dispatch_id"):
        return {"action": "failed", "reason": "dispatch_unconfirmed"}
    history = request.app.state.history_store
    owner, job = receipt["actor_user_id"], receipt["dispatch_id"]
    try:
        dispatch = await history.get_oracle_mesh_dispatch_for_owner(user_id=owner, dispatch_id=job)
        if not isinstance(dispatch, dict):
            raise ValueError("missing dispatch")
        if dispatch.get("state") in {"pending", "received"}:
            return {"action": "queued", "reason": "awaiting_receipt"}
        if not command_finished(dispatch):
            return {"action": "failed", "reason": "dispatch_failed"}
        run = await history.get_claw_run(owner, dispatch["run_id"])
        text = await _read_original(request, uid=owner, dispatch=dispatch, run_row=run)
        return parse_receipt(text)
    except Exception:
        return {"action": "failed", "reason": "receipt_unverified"}


async def registration_view(request, *, device, row, now, allowed=None):
    """Only the bounded outcome is projected; no run text or actor identifiers."""
    if allowed is None:
        allowed = await _pc_system_mode_allowed(request, uid=current_user_id(request), device_id=device)
    plan = plan_registration(row, system_allowed=allowed, now=now)
    if plan["action"] in ("reinstall_required", "install"):
        # No refresh receipt can exist for a PC that has nothing to refresh; an
        # install (#8359 F6) is reported as the plan and never executed here.
        return plan
    store = request.app.state.mesh_device_drive_store
    receipt = await store.load_updater_registration(device_id=device, sha256=SOURCE_SHA256)
    return await _receipt_view(request, receipt) if receipt else plan


async def _execute(request, *, owner, device, link, plan, now):
    state = request.app.state
    session, uid, workspace = owner
    store = state.mesh_device_drive_store
    if link is None or not await _pc_system_mode_allowed(request, uid=uid, device_id=device):
        return {"action": "reinstall_required", "reason": "system_denied"}
    target, denial = await _dispatch_target(request, session=session, uid=uid, link=link)
    if denial is not None:
        return {"action": "reinstall_required", "reason": "system_denied"}
    # A release/device UNIQUE key prevents multiple dispatches, including when
    # a browser retries the POST. An ambiguous dispatch is never retried blindly.
    attempt = uuid.uuid4().hex
    args = {"device_id": device, "sha256": SOURCE_SHA256, "attempt_id": attempt}
    if not await store.reserve_updater_registration(**args, actor=uid, now=now):
        return await registration_view(request, device=device, row=None, now=now, allowed=True)
    try:
        run = await _stage_run(request, uid=uid, workspace_id=workspace, note="PC updater registration")
        if isinstance(run, JSONResponse):
            raise ValueError("run refused")
        if not await _pc_system_mode_allowed(request, uid=uid, device_id=device):
            await store.record_updater_registration(**args, reason="system_denied")
            return {"action": "reinstall_required", "reason": "system_denied"}
        result = await dispatch_oracle_mesh_command_intent(
            request, command=registration_command(),
            wire={"run_id": run[0], "device_id": device, "confirmed": True},
            trusted_owner=owner, files_target=target, user_mode=False, ttl_seconds=300,
        )
        if result.status_code != 200:
            await store.record_updater_registration(**args, reason="dispatch_refused")
            return {"action": "failed", "reason": "dispatch_refused"}
        dispatch = json.loads(result.body)["dispatch"]
        job = dispatch["dispatch_id"]
        if (not isinstance(job, str) or dispatch.get("device_id") != device
                or dispatch.get("user_mode") is not False):
            raise ValueError("dispatch mismatch")
        await store.record_updater_registration(**args, dispatch_id=job)
        return {"action": "queued", "reason": "awaiting_receipt"}
    except Exception:
        await store.record_updater_registration(**args, reason="dispatch_unconfirmed")
        return {"action": "failed", "reason": "dispatch_unconfirmed"}


async def admin_refresh_updaters(request):
    denial = await _central_admin(request)
    if denial is not None:
        return denial
    body = await _body(request)
    if (not isinstance(body, dict) or type(body.get("dry_run")) is not bool
            or set(body) != ({"dry_run"} if body.get("dry_run") else {"dry_run", "source_sha256"})):
        return _response({"error": "invalid_refresh"}, 400)
    dry = body["dry_run"]
    if not dry and body["source_sha256"] != SOURCE_SHA256:
        return _response({"error": "release_changed"}, 409)
    uid = current_user_id(request)
    # Preview projects exactly the same read-only facts as the admin versions
    # GET. The canonical owner/CSRF dependency is needed for creating a run,
    # not for an already-authorized administrator to inspect the plan.
    session = workspace = None
    if not dry:
        session, denial = await _verified_owner_request(request)
        if denial is not None:
            return denial
        workspace = await _dispatch_workspace_id(request, uid, session)
        if not workspace:
            return _response({"error": "canonical_session_required"}, 401)
    pairing, store = request.app.state.pc_device_pairing_store, request.app.state.mesh_device_drive_store
    now = _now()
    try:
        devices = await pairing.list_active_device_ids()
        links = {link["mesh_node_id"]: link for link in await pairing.list_helper_update_preferences(user_id=uid)}
        rows = []
        for device in devices:
            allowed = device in links and await _pc_system_mode_allowed(request, uid=uid, device_id=device)
            row = await store.load_helper_ready(device_id=device, include_versions=True)
            plan = await registration_view(request, device=device, row=row, now=now, allowed=allowed)
            if not dry and plan["action"] == "refresh":
                plan = await _execute(request, owner=(session, uid, workspace), device=device,
                                      link=links.get(device), plan=plan, now=now)
            rows.append({"device_id": device, **plan})
        return _response({"ok": True, "dry_run": dry, "source_sha256": SOURCE_SHA256, "devices": rows})
    except Exception:
        return _response({"error": "refresh_unavailable"}, 503)
