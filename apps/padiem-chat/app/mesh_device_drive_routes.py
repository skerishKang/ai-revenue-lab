"""Authenticated Mesh executor -> production queue drive snapshot receipt.

The PC reports through its already authenticated Mesh Agent channel. Only the
COM2 executor holds the existing queue channel secret; no shared deployment
secret is installed on a customer's PC. The executor derives device_id from
the authenticated Mesh node, and this door resolves its current active pairing.
"""
from __future__ import annotations

from datetime import datetime, timezone

from starlette.requests import Request
from starlette.responses import JSONResponse

from padiem_ai_core.pc_device_identity import is_pc_device_id
from padiem_ai_core.pc_drive_inventory import DriveInventoryError, validate_drive_inventory

from .oracle_mesh_read_return_routes import (
    _channel_proof, _channel_source, _error, _read_body, _response,
)

MESH_DEVICE_DRIVES_PATH = "/api/claw/connector/mesh-reads/drives"
MESH_DEVICE_DRIVE_TARGETS_PATH = MESH_DEVICE_DRIVES_PATH + "/targets"
_REPORT_KEYS = frozenset({"device_id", "drives"})


async def mesh_device_drive_report(request: Request) -> JSONResponse:
    source = _channel_source(request)
    if source is None:
        return _error(503, "oracle_mesh_unconfigured")
    if not _channel_proof(request, source):
        return _error(403, "oracle_mesh_channel_rejected")
    wire = await _read_body(request, _REPORT_KEYS)
    if wire is None or not is_pc_device_id(wire.get("device_id")):
        return _error(400, "mesh_drives_invalid_body")
    try:
        drives = validate_drive_inventory(wire["drives"])
    except DriveInventoryError:
        return _error(400, "mesh_drives_invalid_body")
    pairing = getattr(request.app.state, "pc_device_pairing_store", None)
    store = getattr(request.app.state, "mesh_device_drive_store", None)
    if not callable(getattr(pairing, "device_scope", None)) or store is None:
        return _error(503, "mesh_drives_unavailable")
    try:
        scope = await pairing.device_scope(device_id=wire["device_id"])
        # No owner in the wire and no legacy map fallback: active pairing is the
        # existing production authority, including pause/revocation behaviour.
        if not isinstance(scope, dict) or not is_pc_device_id(scope.get("device_id")):
            return _error(403, "mesh_drives_device_unlinked")
        received_at = datetime.now(timezone.utc)
        written = await store.upsert_drives(
            device_id=scope["device_id"], drives=drives, received_at=received_at,
        )
    except Exception:
        return _error(503, "mesh_drives_unavailable")
    if written is not True:
        return _error(503, "mesh_drives_unavailable")
    return _response({"ok": True, "received_at": received_at.isoformat().replace("+00:00", "Z")})


async def mesh_device_drive_targets(request: Request) -> JSONResponse:
    """Read-only executor target list; never reveals owners or approved roots."""
    source = _channel_source(request)
    if source is None:
        return _error(503, "oracle_mesh_unconfigured")
    if not _channel_proof(request, source):
        return _error(403, "oracle_mesh_channel_rejected")
    if await _read_body(request, frozenset()) is None:
        return _error(400, "mesh_drives_invalid_body")
    pairing = getattr(request.app.state, "pc_device_pairing_store", None)
    try:
        devices = await pairing.list_active_device_ids()
    except Exception:
        return _error(503, "mesh_drives_unavailable")
    return _response({"ok": True, "device_ids": devices})


__all__ = ["MESH_DEVICE_DRIVES_PATH", "MESH_DEVICE_DRIVE_TARGETS_PATH",
           "mesh_device_drive_report", "mesh_device_drive_targets"]
