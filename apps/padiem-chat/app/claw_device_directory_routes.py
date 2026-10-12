"""#4139 — owner/workspace-scoped read-only Claw Connect device directory.

This is a B62 consumer of the *existing* canonical Local Agent Broker
device_directory RPC (#4418), not a second online/identity authority.
No pairing, credentials, command, P01 grants or device writes occur here.
"""
from __future__ import annotations

import inspect
import re
from datetime import datetime, timezone
from typing import Any, Mapping

from kagent.local_agent_pairing import DeviceLifecycle
from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .claw_memory_routes import _resolve_memory_workspace
from .claw_local_access_source import CanonicalClawLocalAccessTruthSource
from .worker_config import (
    LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME,
    binding_value,
)

CLAW_DEVICE_DIRECTORY_PATH = "/api/claw/local-access/devices"
_DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_DEVICE_LIMIT = 24
_NO_STORE = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}

class UnconfiguredDeviceDirectorySource:
    configured = False

    async def list_devices(self, *, owner_id: str, workspace_id: str, now: datetime) -> Any:
        del owner_id, workspace_id, now
        return None


def _response(payload: Mapping[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(dict(payload), status_code=status, headers=_NO_STORE)


def _error(status: int, code: str) -> JSONResponse:
    return _response({"ok": False, "error": {"code": code, "message": "Device directory unavailable."}}, status)


class BrokerDeviceDirectorySource:
    """Single trusted service-binding reader; no private broker record escapes."""

    configured = True

    def __init__(self, binding: Any) -> None:
        port = getattr(binding, "device_directory", None)
        if not callable(port):
            raise TypeError("canonical broker directory RPC unavailable")
        self._port = port

    async def list_devices(
        self, *, owner_id: str, workspace_id: str, now: datetime
    ) -> list[dict[str, Any]] | None:
        if not isinstance(owner_id, str) or not owner_id or not isinstance(workspace_id, str) or not workspace_id:
            return None
        try:
            result = self._port({"account_ref": owner_id, "workspace_ref": workspace_id})
            if inspect.isawaitable(result):
                result = await result
        except Exception:
            return None
        if not isinstance(result, Mapping) or result.get("ok") is not True:
            return None
        if result.get("available") is False and result.get("reason") == "no_device_binding":
            return []
        if result.get("available") is not True or result.get("owner_scoped") is not True:
            return None
        raw = result.get("devices")
        if not isinstance(raw, list) or len(raw) > _DEVICE_LIMIT:
            return None
        if result.get("device_count") != len(raw):
            return None
        seen: set[str] = set()
        items: list[dict[str, Any]] = []
        for facts in raw:
            if not isinstance(facts, Mapping):
                return None
            binding = facts.get("binding")
            if not isinstance(binding, Mapping):
                return None
            device_id = binding.get("device_id")
            if not isinstance(device_id, str) or not _DEVICE_ID_PATTERN.fullmatch(device_id):
                return None
            if device_id in seen:
                return None
            seen.add(device_id)
            if binding.get("account_ref") != owner_id or binding.get("workspace_ref") != workspace_id:
                return None
            # Uses exactly the G4 source's authoritative server-backed ONLINE
            # algorithm. Offline/expired/revoked cannot be promoted by a stale
            # session or heartbeat. Unknown evidence fails closed.
            try:
                state = CanonicalClawLocalAccessTruthSource._canonical_state(facts, now=now)
            except Exception:
                return None
            if state is None:
                return None
            online = state is DeviceLifecycle.ONLINE
            revoked = state is DeviceLifecycle.REVOKED
            expired = state is DeviceLifecycle.CREDENTIAL_EXPIRED
            items.append({
                "deviceId": device_id,
                "deviceName": None,
                "platform": None,
                "state": "CONNECTED" if online else "REVOKED" if revoked else "OFFLINE",
                "usable": online,
                "revoked": revoked,
                "expired": expired,
            })
        return sorted(items, key=lambda row: row["deviceId"])


def build_broker_device_directory_source(env: Any) -> BrokerDeviceDirectorySource | None:
    """Trusted Worker composition only; missing/invalid binding is unconfigured."""
    binding = binding_value(env, LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME)
    if binding is None:
        return None
    try:
        return BrokerDeviceDirectorySource(binding)
    except Exception:
        return None


async def claw_device_directory(request: Request) -> JSONResponse:
    """Authenticated GET-only device listing; client cannot name any scope."""
    if request.query_params:
        return _error(400, "device_directory_query_not_allowed")
    uid = current_user_id(request) if auth_ready(request) else None
    if not uid:
        return _error(401, "device_directory_auth_required")
    workspace_id = await _resolve_memory_workspace(request, uid)
    if not workspace_id:
        return _error(503, "device_directory_workspace_unavailable")
    source = getattr(request.app.state, "claw_device_directory_source", None)
    if getattr(source, "configured", False) is not True:
        return _response({"ok": True, "available": False, "reason": "device_directory_unconfigured"})
    try:
        devices = source.list_devices(owner_id=uid, workspace_id=workspace_id, now=datetime.now(timezone.utc))
        if inspect.isawaitable(devices):
            devices = await devices
    except Exception:
        devices = None
    if devices is None:
        return _response({"ok": True, "available": False, "reason": "device_directory_read_failed"})
    if not isinstance(devices, list) or len(devices) > _DEVICE_LIMIT:
        return _response({"ok": True, "available": False, "reason": "device_directory_read_failed"})
    # Closed second serialization boundary: do not leak unexpected source
    # fields even if a future trusted source extends its internal objects.
    safe: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in devices:
        if not isinstance(row, Mapping):
            return _response({"ok": True, "available": False, "reason": "device_directory_read_failed"})
        ident = row.get("deviceId")
        state = row.get("state")
        usable, revoked, expired = row.get("usable"), row.get("revoked"), row.get("expired")
        if not isinstance(ident, str) or not _DEVICE_ID_PATTERN.fullmatch(ident) or ident in seen:
            return _response({"ok": True, "available": False, "reason": "device_directory_read_failed"})
        if state not in ("CONNECTED", "OFFLINE", "REVOKED") or any(
            type(value) is not bool for value in (usable, revoked, expired)
        ):
            return _response({"ok": True, "available": False, "reason": "device_directory_read_failed"})
        if (state == "CONNECTED") != (usable and not revoked and not expired):
            return _response({"ok": True, "available": False, "reason": "device_directory_read_failed"})
        if state == "REVOKED" and not revoked:
            return _response({"ok": True, "available": False, "reason": "device_directory_read_failed"})
        device_name = row.get("deviceName")
        platform = row.get("platform")
        if (device_name is not None and (not isinstance(device_name, str) or len(device_name) > 80)
            or platform is not None and (not isinstance(platform, str) or len(platform) > 40)):
            return _response({"ok": True, "available": False, "reason": "device_directory_read_failed"})
        seen.add(ident)
        safe.append({
            "deviceId": ident, "deviceName": device_name, "platform": platform,
            "state": state, "usable": usable, "revoked": revoked, "expired": expired,
        })
    # Even a valid sole connected PC is only a visual candidate; selection is
    # explicit in the browser and execution authority is never present here.
    return _response({
        "ok": True, "available": True, "ownerScoped": True,
        "devices": sorted(safe, key=lambda row: row["deviceId"]),
    })

MUTATION = False
PRODUCTION_MUTATION = False
NEW_ONLINE_AUTHORITY = False
PUBLIC_DEVICE_PAIRING = False
