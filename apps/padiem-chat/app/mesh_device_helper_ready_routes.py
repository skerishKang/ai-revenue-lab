"""#7987 — authenticated Mesh executor -> production queue helper readiness receipt.

The same door the drive snapshot uses (#6460), one path over. Only the COM2
executor holds the queue channel secret, so a PC cannot post here and nothing
is installed on a customer's PC to make this work. The executor names the
device from the authenticated Mesh node; this door resolves its current active
pairing and stamps its own receipt time. Neither an owner, a receipt time nor
any free text is accepted from the wire.

The row is display evidence. Storing it sends nothing to the PC and changes no
command's authorization; a missing or old row means "not known".
"""
from __future__ import annotations

from datetime import datetime, timezone

from starlette.requests import Request
from starlette.responses import JSONResponse

from padiem_ai_core.pc_device_identity import is_pc_device_id
from padiem_ai_core.pc_helper_ready import HelperReadyError, validate_helper_ready

from .oracle_mesh_read_return_routes import (
    _channel_proof, _channel_source, _error, _read_body, _response,
)

MESH_DEVICE_HELPER_READY_PATH = "/api/claw/connector/mesh-reads/helper-ready"
_REPORT_KEYS = frozenset({"device_id", "helper"})


async def mesh_device_helper_ready_report(request: Request) -> JSONResponse:
    source = _channel_source(request)
    if source is None:
        return _error(503, "oracle_mesh_unconfigured")
    if not _channel_proof(request, source):
        return _error(403, "oracle_mesh_channel_rejected")
    wire = await _read_body(request, _REPORT_KEYS)
    if wire is None or not is_pc_device_id(wire.get("device_id")):
        return _error(400, "mesh_helper_ready_invalid_body")
    try:
        state = validate_helper_ready(wire["helper"])
        # Accept legacy agents but never retain obsolete watcher evidence.
        state.pop("self_heal_task_present", None)
    except HelperReadyError:
        return _error(400, "mesh_helper_ready_invalid_body")
    pairing = getattr(request.app.state, "pc_device_pairing_store", None)
    store = getattr(request.app.state, "mesh_device_drive_store", None)
    if (not callable(getattr(pairing, "device_scope", None))
            or not callable(getattr(store, "upsert_helper_ready", None))):
        return _error(503, "mesh_helper_ready_unavailable")
    try:
        scope = await pairing.device_scope(device_id=wire["device_id"])
        # No owner in the wire and no legacy map fallback: an active, unpaused
        # pairing is the only authority, exactly as for the drive snapshot.
        if not isinstance(scope, dict) or not is_pc_device_id(scope.get("device_id")):
            return _error(403, "mesh_helper_ready_device_unlinked")
        received_at = datetime.now(timezone.utc)
        written = await store.upsert_helper_ready(
            device_id=scope["device_id"], state=state, received_at=received_at,
        )
    except Exception:
        return _error(503, "mesh_helper_ready_unavailable")
    if written is not True:
        return _error(503, "mesh_helper_ready_unavailable")
    return _response({"ok": True, "received_at": received_at.isoformat().replace("+00:00", "Z")})


__all__ = ["MESH_DEVICE_HELPER_READY_PATH", "mesh_device_helper_ready_report"]
