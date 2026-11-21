"""Version-only PC helper update policy, shared by owner views and admission."""
from __future__ import annotations

import re
from datetime import datetime

from .pc_command_ready import HELPER_READY_MAX_AGE_SECONDS, _received

_RELEASE = re.compile(r"([0-9]{1,5})\.([0-9]{1,5})\.([0-9]{1,5})(?:-rc([0-9]{1,5}))?")


def version_parts(value):
    """Same version ordering as the Windows updater; unknown is not old."""
    matched = _RELEASE.fullmatch(value) if isinstance(value, str) else None
    if matched is None:
        return None
    major, minor, patch, rc = matched.groups()
    return int(major), int(minor), int(patch), int(rc) if rc else 100000


def update_view(row, manifest, *, device_id: str, now: datetime):
    """Only current, device-bound version evidence may limit commands."""
    unknown = {"helper_version": None, "latest_version": None,
               "update_available": False, "update_required": False}
    if not isinstance(row, dict) or row.get("device_id") != device_id or not manifest:
        return unknown
    received = _received(row.get("received_at"))
    if received is None or not 0 <= (now - received).total_seconds() <= HELPER_READY_MAX_AGE_SECONDS:
        return unknown
    version = (manifest["version"] if row.get("helper_sha256") == manifest["sha256"]
               else row.get("helper_version"))
    current = version_parts(version)
    latest = version_parts(manifest.get("version"))
    minimum = version_parts(manifest.get("min_supported_version"))
    if current is None or latest is None or minimum is None:
        return unknown
    return {"helper_version": version, "latest_version": manifest["version"],
            "update_available": current < latest, "update_required": current < minimum}


async def load_update_view(state, *, device_id: str, now: datetime):
    from .pc_helper_version_routes import helper_manifest

    store = getattr(state, "mesh_device_drive_store", None)
    manifest = helper_manifest(state)
    try:
        row = await store.load_helper_ready(device_id=device_id, include_versions=True)
    except Exception:
        row = None
    return update_view(row, manifest, device_id=device_id, now=now)
