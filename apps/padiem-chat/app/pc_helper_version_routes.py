"""#8192: public release manifest and administrator-only observed PC versions."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from starlette.responses import JSONResponse
from starlette.routing import Route

from .central_model_control_routes import _central_admin
from .pc_device_pairing_routes import _body, _now, user_helper_config
from .auth_routes import current_user_id
from .pc_helper_rollout import DEVICE_HEADER, change_plan, device_offer, load_plan, summarize

HELPER_VERSION_PATH = "/api/pc/helper-version"
ADMIN_PC_VERSIONS_PATH = "/api/admin/ops-pc-versions"
ADMIN_PC_ROLLOUT_PATH = ADMIN_PC_VERSIONS_PATH + "/rollout"
# First supported Windows helper release; the release builder uses CONNECT_VERSION.
MIN_SUPPORTED_VERSION = "0.3.0-rc1"
_RELEASE_VERSION = re.compile(r"[0-9][0-9A-Za-z._-]{0,63}")
_NO_STORE = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


def helper_manifest(state):
    pair = user_helper_config(getattr(state, "pc_pairing_user_helper_url", None),
                              getattr(state, "pc_pairing_user_helper_sha256", None))
    if pair is None:
        return None
    url, sha = pair
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    # The release script publishes an immutable versioned object. Never expose
    # an account-specific, signed or otherwise query-bearing installation URL.
    parts = parsed.path.split("/")
    if (parsed.query or parsed.fragment or len(parts) < 3
            or parts[-1] != "padiem-user-helper.exe"
            or _RELEASE_VERSION.fullmatch(parts[-2]) is None
            or any(part in (".", "..") for part in parts)):
        return None
    return {"version": parts[-2], "sha256": sha, "download_url": url,
            "min_supported_version": MIN_SUPPORTED_VERSION}


async def pc_helper_version(request):
    manifest = helper_manifest(request.app.state)
    if manifest is None:
        return JSONResponse({"error": "helper_release_unavailable"}, status_code=503,
                            headers=_NO_STORE)
    try:
        manifest = await device_offer(request.app.state, manifest,
                                      device_id=request.headers.get(DEVICE_HEADER), install_id=True)
    except Exception:
        return JSONResponse({"error": "helper_release_unavailable"}, status_code=503, headers=_NO_STORE)
    # Device-specific and immediately revocable. No shared cached offer.
    return JSONResponse(manifest, headers=_NO_STORE)


async def admin_change_rollout(request):
    denied = await _central_admin(request)
    if denied is not None:
        return denied
    body = await _body(request)
    if (not isinstance(body, dict) or set(body) != {"action", "percent", "revision", "target_sha256"}
            or body["action"] not in ("initialize", "next", "pause", "percentage")
            or type(body["percent"]) is not int or not 1 <= body["percent"] <= 99
            or type(body["revision"]) is not int or body["revision"] < 0):
        return JSONResponse({"error": "rollout_invalid"}, status_code=400, headers=_NO_STORE)
    state = request.app.state
    try:
        plan = await load_plan(state, helper_manifest(state))
        if (plan["revision"] != body["revision"] or plan["target"]["sha256"] != body["target_sha256"]):
            return JSONResponse({"error": "rollout_changed"}, status_code=409, headers=_NO_STORE)
        try:
            changed = change_plan(plan, body["action"], body["percent"])
        except ValueError:
            return JSONResponse({"error": "rollout_invalid_transition"}, status_code=409, headers=_NO_STORE)
        saved = await state.pc_device_pairing_store.save_helper_rollout(
            plan=changed, revision=plan["revision"], now=_now())
        if not saved:
            return JSONResponse({"error": "rollout_changed"}, status_code=409, headers=_NO_STORE)
        audit = getattr(state, "ops_audit_store", None)
        if audit is not None:
            await audit.append(actor_user_id=current_user_id(request), action="helper_rollout_change",
                               target_type="helper_release", target_id=plan["target"]["version"],
                               detail={"stage": changed["stage"], "percent": changed["percent"]})
        return JSONResponse({"ok": True}, headers=_NO_STORE)
    except Exception:
        return JSONResponse({"error": "rollout_unavailable"}, status_code=503, headers=_NO_STORE)


async def admin_ops_pc_versions(request):
    denied = await _central_admin(request)
    if denied is not None:
        return denied
    state = request.app.state
    pairing = getattr(state, "pc_device_pairing_store", None)
    store = getattr(state, "mesh_device_drive_store", None)
    manifest = helper_manifest(state)
    try:
        devices = await pairing.list_active_device_ids()
        rows, observations = [], {}
        for device in devices:
            row = await store.load_helper_ready(device_id=device, include_versions=True)
            row = row or {}
            observations[device] = row
            observation = row.get("state") or {}
            build = observation.get("helper_build")
            sha = row.get("helper_sha256")
            # Old reports have only the short build fingerprint. Never infer
            # a release version from an unmatched or truncated digest.
            version = manifest["version"] if manifest and sha == manifest["sha256"] else row.get("helper_version")
            rows.append({"device_id": device, "helper_version": version,
                         "helper_build": build, "mesh_agent_version": row.get("mesh_agent_version"),
                         "update_result": observation.get("update_result"),
                         "last_healthy_at": row.get("last_healthy_at"),
                         "received_at": row.get("received_at"),
                         **({"update_registration_error": observation["update_registration_error"]}
                            if observation.get("update_registration_error") else {})})
        rollout = None
        if manifest and callable(getattr(pairing, "load_helper_rollout", None)):
            plan = await load_plan(state, manifest)
            managed = set(await pairing.list_managed_device_ids())
            outcomes = await store.load_rollout_outcomes(sha256=manifest["sha256"])
            rollout = {**plan, "groups": summarize(plan, devices, managed, observations, outcomes)}
    except Exception:
        return JSONResponse({"error": "pc_versions_unavailable"}, status_code=503,
                            headers=_NO_STORE)
    return JSONResponse({"ok": True, "devices": rows, "rollout": rollout}, headers=_NO_STORE)


def register_pc_helper_version_routes(routes: list) -> None:
    from .pc_helper_update_routes import register_helper_update_routes

    register_helper_update_routes(routes)
    routes.extend([
        Route(HELPER_VERSION_PATH, pc_helper_version, methods=["GET"]),
        Route(ADMIN_PC_VERSIONS_PATH, admin_ops_pc_versions, methods=["GET"]),
        Route(ADMIN_PC_ROLLOUT_PATH, admin_change_rollout, methods=["POST"]),
    ])
