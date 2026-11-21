"""#8192: public release manifest and administrator-only observed PC versions."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from starlette.responses import JSONResponse
from starlette.routing import Route

from .central_model_control_routes import _central_admin
from .pc_device_pairing_routes import user_helper_config

HELPER_VERSION_PATH = "/api/pc/helper-version"
ADMIN_PC_VERSIONS_PATH = "/api/admin/ops-pc-versions"
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
    return JSONResponse(manifest, headers={**_NO_STORE, "Cache-Control": "public, max-age=60"})


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
        rows = []
        for device in devices:
            row = await store.load_helper_ready(device_id=device, include_versions=True)
            row = row or {}
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
    except Exception:
        return JSONResponse({"error": "pc_versions_unavailable"}, status_code=503,
                            headers=_NO_STORE)
    return JSONResponse({"ok": True, "devices": rows}, headers=_NO_STORE)


def register_pc_helper_version_routes(routes: list) -> None:
    routes.extend([
        Route(HELPER_VERSION_PATH, pc_helper_version, methods=["GET"]),
        Route(ADMIN_PC_VERSIONS_PATH, admin_ops_pc_versions, methods=["GET"]),
    ])
