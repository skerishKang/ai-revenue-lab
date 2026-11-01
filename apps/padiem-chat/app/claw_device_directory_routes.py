"""#4139 owner/workspace-scoped Claw device read + reversible PC use gate.

This is a B62 consumer of the *existing* canonical Local Agent Broker
device_directory RPC (#4418), not a second online/identity authority.
GET remains read-only. POST pause/resume changes only the canonical Broker's
owner-scoped use preference; command dispatch/admission is blocked there.
No pairing, credential rotation, P01 grant or device revocation occurs here.
"""
from __future__ import annotations

import inspect
import json
from datetime import datetime, timezone
from typing import Any, Mapping

from kagent.local_agent_pairing import DeviceLifecycle
from padiem_ai_core.pc_device_identity import is_pc_device_id
from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .same_origin_guard import expected_browser_origin
from .claw_memory_routes import _resolve_memory_workspace
from .claw_local_access_source import (
    CanonicalClawLocalAccessTruthSource,
    mesh_presence_facts,
    mesh_presence_online,
)
from .pc_work_context import (
    PC_SCOPE_OWNER_UNAVAILABLE,
    PcConnectorScope,
    resolve_pc_connector_scope,
    resolve_pc_mesh_target,
)
from .worker_config import (
    LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME,
    binding_value,
)

CLAW_DEVICE_DIRECTORY_PATH = "/api/claw/local-access/devices"
CLAW_PC_PAUSE_PATH = "/api/claw/local-access/devices/pause"
CLAW_PC_RESUME_PATH = "/api/claw/local-access/devices/resume"
CLAW_PC_SELECT_PATH = "/api/claw/local-access/devices/select"
_DEVICE_LIMIT = 24
_MAX_SELECT_BODY_BYTES = 1024
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

    def __init__(self, binding: Any, presence_store: Any = None) -> None:
        port = getattr(binding, "device_directory", None)
        if not callable(port):
            raise TypeError("canonical broker directory RPC unavailable")
        self._port = port
        self._set_usage = getattr(binding, "set_owner_usage", None)
        # #5080: same trusted service binding, additive presentation metadata
        # only. Absent on an older Broker and then simply omitted.
        self._android_profiles = getattr(binding, "android_saf_profiles", None)
        # #5553: the server-recorded Mesh presence receipt joins the same
        # canonical decision. Absent store keeps today's exact state.
        self._presence_store = presence_store

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
        paused = result.get("usage_paused")
        if paused is not None and type(paused) is not bool:
            return None
        seen: set[str] = set()
        binding_refs: dict[str, str] = {}
        items: list[dict[str, Any]] = []
        for facts in raw:
            if not isinstance(facts, Mapping):
                return None
            binding = facts.get("binding")
            if not isinstance(binding, Mapping):
                return None
            device_id = binding.get("device_id")
            if not is_pc_device_id(device_id):
                return None
            if device_id in seen:
                return None
            seen.add(device_id)
            if isinstance(binding.get("binding_ref"), str) and binding["binding_ref"]:
                binding_refs[device_id] = binding["binding_ref"]
            if binding.get("account_ref") != owner_id or binding.get("workspace_ref") != workspace_id:
                return None
            # Uses exactly the G4 source's authoritative server-backed ONLINE
            # algorithm. Offline/expired/revoked cannot be promoted by a stale
            # session or heartbeat. Unknown evidence fails closed.
            row_facts = facts
            if self._presence_store is not None:
                try:
                    presence_row = self._presence_store.load(device_id)
                    if inspect.isawaitable(presence_row):
                        presence_row = await presence_row
                except Exception:
                    presence_row = None
                block = mesh_presence_facts(presence_row, binding)
                if block is not None:
                    row_facts = dict(facts)
                    row_facts["mesh_presence"] = block
            try:
                state = CanonicalClawLocalAccessTruthSource._canonical_state(row_facts, now=now)
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
                **({"usagePaused": paused} if paused is not None else {}),
            })
        if callable(self._android_profiles) and items and binding_refs:
            try:
                profiles = self._android_profiles(
                    {"account_ref": owner_id, "workspace_ref": workspace_id})
                if inspect.isawaitable(profiles):
                    profiles = await profiles
            except Exception:
                profiles = None
            # Additive presentation metadata only. A failed or malformed
            # enrichment omits the Android label; it must not deny the whole
            # owner directory, and it can never change canonical state.
            if isinstance(profiles, list) and len(profiles) <= _DEVICE_LIMIT:
                by_device = {row["deviceId"]: row for row in items}
                for entry in profiles:
                    if not isinstance(entry, Mapping):
                        continue
                    device_id = entry.get("device_id")
                    row = by_device.get(device_id)
                    if (row is None
                            or entry.get("binding_ref") != binding_refs.get(device_id)
                            or entry.get("platform") != "android"
                            or entry.get("read_suffix") != ".txt"
                            or entry.get("capabilities") not in ([], ["local.filesystem.read"])
                            or type(entry.get("folder_count")) is not int
                            or not 0 <= entry["folder_count"] <= 8):
                        continue
                    row.update({
                        "platform": "android",
                        "androidCapabilities": list(entry["capabilities"]),
                        "androidReadSuffix": ".txt",
                        "androidFolderCount": entry["folder_count"],
                    })
        return sorted(items, key=lambda row: row["deviceId"])

    async def set_usage(self, *, owner_id: str, workspace_id: str, paused: bool) -> dict | None:
        # The browser cannot supply a device, owner, workspace or credential.
        if not callable(self._set_usage) or type(paused) is not bool:
            return None
        try:
            result = self._set_usage({
                "account_ref": owner_id,
                "workspace_ref": workspace_id,
                "paused": paused,
            })
            if inspect.isawaitable(result):
                result = await result
        except Exception:
            return None
        if (not isinstance(result, Mapping) or result.get("ok") is not True
            or result.get("paused") is not paused
            or result.get("dispatch_authorized") is not (not paused)):
            return None
        return {"ok": True, "usagePaused": paused}


def build_broker_device_directory_source(
    env: Any, presence_store: Any = None,
) -> BrokerDeviceDirectorySource | None:
    """Trusted Worker composition only; missing/invalid binding is unconfigured."""
    binding = binding_value(env, LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME)
    if binding is None:
        return None
    try:
        return BrokerDeviceDirectorySource(binding, presence_store=presence_store)
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
    return await _read_device_directory(request, uid=uid, workspace_id=workspace_id)


async def _read_device_directory(
    request: Request, *, uid: str, workspace_id: str,
) -> JSONResponse:
    # The Broker binding is created by the connector under the canonical
    # connector owner scope (B54 session -> CP connector context), not under
    # the B62 product user/tenant. The product scope still keys the saved
    # preference and the user's authorization.
    try:
        connector = await resolve_pc_connector_scope(
            request, owner_id=uid, workspace_id=workspace_id,
        )
    except Exception:
        connector = PcConnectorScope(status=PC_SCOPE_OWNER_UNAVAILABLE)
    broker_owner = connector.account_ref if connector.ready else uid
    broker_workspace = connector.workspace_ref if connector.ready else workspace_id
    source = getattr(request.app.state, "claw_device_directory_source", None)
    broker_reason = None
    devices = []
    if getattr(source, "configured", False) is not True:
        broker_reason = "device_directory_unconfigured"
    else:
        try:
            devices = source.list_devices(
                owner_id=broker_owner, workspace_id=broker_workspace,
                now=datetime.now(timezone.utc),
            )
            if inspect.isawaitable(devices):
                devices = await devices
        except Exception:
            devices = None
        if not isinstance(devices, list) or len(devices) > _DEVICE_LIMIT:
            broker_reason = "device_directory_read_failed"
            devices = []
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
        if not is_pc_device_id(ident) or ident in seen:
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
        entry = {
            "deviceId": ident, "deviceName": device_name, "platform": platform,
            "state": state, "usable": usable, "revoked": revoked, "expired": expired,
        }
        if platform == "android":
            # #5080: only the one capability this adapter implements, and only
            # for a row the Broker actually declared as Android.
            capabilities = row.get("androidCapabilities")
            read_suffix = row.get("androidReadSuffix")
            folder_count = row.get("androidFolderCount")
            if (capabilities not in ([], ["local.filesystem.read"])
                    or read_suffix != ".txt"
                    or type(folder_count) is not int
                    or not 0 <= folder_count <= 8):
                return _response({"ok": True, "available": False, "reason": "device_directory_read_failed"})
            entry.update({
                "capabilities": list(capabilities),
                "readSuffix": read_suffix,
                "folderCount": folder_count,
            })
        seen.add(ident)
        safe.append(entry)
    # Even a valid sole connected PC is only a visual candidate; selection is
    # explicit in the browser and execution authority is never present here.
    pause_values = {row.get("usagePaused") for row in devices}
    if len(pause_values) > 1 or any(
        value is not None and type(value) is not bool for value in pause_values
    ):
        return _response({"ok": True, "available": False, "reason": "device_directory_read_failed"})
    paused = next(iter(pause_values), None)
    # A Mesh grant proves execution authority; a fresh source=mesh receipt
    # separately proves liveness. Neither a grant alone nor a browser flag
    # can claim ONLINE. Never mint an alias for a raw node reference.
    execution = await resolve_pc_mesh_target(
        request, owner_id=uid, workspace_id=workspace_id, connector=connector,
    )
    mesh_ids = {execution.device_id} if execution.ready else set()
    mesh_source = getattr(request.app.state, "oracle_mesh_return_source", None)
    enumerate_devices = getattr(mesh_source, "command_device_ids", None)
    if connector.ready and callable(enumerate_devices):
        for device_id in enumerate_devices(account_ref=connector.account_ref)[:_DEVICE_LIMIT]:
            target = await resolve_pc_mesh_target(
                request, owner_id=uid, workspace_id=workspace_id, connector=connector,
                device_id=device_id,
            )
            if target.ready:
                mesh_ids.add(target.device_id)
    for mesh_id in sorted(mesh_ids):
        if not is_pc_device_id(mesh_id) or paused is True:
            continue
        mesh_row = next((row for row in safe if row["deviceId"] == mesh_id), None)
        # Requirement 6: Broker registration is not a Mesh prerequisite.
        # Receipt lookup happens only AFTER the owner-scoped execution target
        # was verified. Never enumerate raw presence rows across owners.
        receipt = None
        store = getattr(request.app.state, "mesh_device_presence_store", None)
        if callable(getattr(store, "load", None)):
            try:
                receipt = store.load(mesh_id)
                if inspect.isawaitable(receipt):
                    receipt = await receipt
            except Exception:
                pass
        online = mesh_presence_online(receipt, device_id=mesh_id, now=datetime.now(timezone.utc))
        if mesh_row is None and len(safe) < _DEVICE_LIMIT:
            safe.append({
                "deviceId": mesh_id, "deviceName": None, "platform": None,
                "state": "CONNECTED" if online else "ACTION_REQUIRED", "usable": online,
                "revoked": False, "expired": False,
                "executable": True, "selectable": True,
            })
        elif mesh_row is not None:
            mesh_row["executable"] = True
            if online and not mesh_row["revoked"] and not mesh_row["expired"]:
                mesh_row.update(state="CONNECTED", usable=True)
            mesh_row["selectable"] = mesh_row["usable"] is True
    # #5573: a PC this account linked is this account's own device, so the
    # directory names it and the browser can select it. The link is the
    # ownership proof - it was made by a code only this account could issue -
    # and liveness still comes from the server's own receipt: a linked PC
    # nothing has observed is listed as not usable, never as online. Without
    # these rows a second PC had no selectable device at all, and choosing it
    # answered 403 as if it belonged to somebody else.
    pairing = getattr(request.app.state, "pc_device_pairing_store", None)
    links_reader = getattr(pairing, "links_for_owner", None)
    if callable(links_reader):
        try:
            linked = await links_reader(user_id=uid)
        except Exception:
            linked = None
        if isinstance(linked, list):
            known = {row["deviceId"] for row in safe}
            for link in linked:
                if len(safe) >= _DEVICE_LIMIT:
                    break
                if not isinstance(link, Mapping):
                    continue
                node_ref = link.get("mesh_node_id")
                if not is_pc_device_id(node_ref) or node_ref in known:
                    continue
                known.add(node_ref)
                label = link.get("label")
                receipt = None
                presence_store = getattr(
                    request.app.state, "mesh_device_presence_store", None,
                )
                if callable(getattr(presence_store, "load", None)):
                    try:
                        receipt = presence_store.load(node_ref)
                        if inspect.isawaitable(receipt):
                            receipt = await receipt
                    except Exception:
                        receipt = None
                online = mesh_presence_online(
                    receipt, device_id=node_ref, now=datetime.now(timezone.utc),
                )
                safe.append({
                    "deviceId": node_ref,
                    "deviceName": label if isinstance(label, str) and label else None,
                    "platform": None,
                    "state": "CONNECTED" if online else "ACTION_REQUIRED",
                    "usable": online, "revoked": False, "expired": False,
                    "executable": True, "selectable": True,
                })
    if broker_reason and not safe:
        return _response({
            "ok": True, "available": False, "reason": broker_reason,
            "scopeStatus": connector.status,
            "brokerScope": "connector" if connector.ready else "product_fallback",
            "targetStatus": execution.status,
        })
    # #5015: the saved target is a PREFERENCE, restored per owner/workspace so
    # a new conversation/session sees the same choice. It is never a grant and
    # is never substituted: a stale/offline/revoked stored device is returned
    # as such and execution re-verifies it.
    selection_store = getattr(request.app.state, "claw_pc_device_selection_store", None)
    selected_device_id = None
    selected_usable = False
    selected_state = None
    if selection_store is not None:
        try:
            selected_device_id = await selection_store.load(
                owner_id=uid, workspace_id=workspace_id,
            )
        except Exception:
            selected_device_id = None
    if is_pc_device_id(selected_device_id):
        selected_row = next(
            (row for row in safe if row["deviceId"] == selected_device_id), None,
        )
        if selected_row is None:
            selected_usable, selected_state = False, "NOT_REGISTERED"
        else:
            selected_usable = selected_row.get("selectable", selected_row["usable"])
            selected_state = selected_row["state"]
    else:
        selected_device_id = None
    # Drive inventory is read-only display data from the production Mesh
    # queue. Join only AFTER this request has proved its own device set;
    # never enumerate inventory rows or accept a device ID from the browser.
    drive_store = getattr(request.app.state, "mesh_device_drive_store", None)
    load_drives = getattr(drive_store, "load_drives", None)
    if callable(load_drives):
        for device in safe:
            if device["revoked"] or device["expired"]:
                continue
            try:
                snapshot = load_drives(device_id=device["deviceId"])
                if inspect.isawaitable(snapshot):
                    snapshot = await snapshot
                device.update(_drive_snapshot_projection(snapshot, device["deviceId"]))
            except Exception:
                # An unavailable inventory must not hide a usable computer or
                # invent an empty/current drive list.
                device["drivesStatus"] = "unavailable"
    return _response({
        "ok": True, "available": True, "ownerScoped": True,
        "scopeStatus": connector.status,
        "brokerScope": "connector" if connector.ready else "product_fallback",
        "targetStatus": execution.status,
        **({"usagePaused": paused} if paused is not None else {}),
        "devices": sorted(safe, key=lambda row: row["deviceId"]),
        **({"directoryReason": broker_reason} if broker_reason else {}),
        **({
            "selectedDeviceId": selected_device_id,
            "selectedUsable": selected_usable,
            "selectedState": selected_state,
        } if selected_device_id is not None else {}),
    })


def _drive_snapshot_projection(snapshot: Any, device_id: str) -> dict[str, Any]:
    """Keep the device response closed even if the internal store grows."""
    if snapshot is None:
        return {"drivesStatus": "pending"}
    if not isinstance(snapshot, Mapping) or snapshot.get("device_id") != device_id:
        raise ValueError("Invalid drive snapshot")
    drives = snapshot.get("drives")
    received_at = snapshot.get("received_at")
    if not isinstance(drives, list) or not isinstance(received_at, str):
        raise ValueError("Invalid drive snapshot")
    stamp = datetime.fromisoformat(received_at.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Invalid drive timestamp")
    projected = []
    seen = set()
    for drive in drives:
        if not isinstance(drive, Mapping):
            raise ValueError("Invalid drive")
        path, name, kind = (drive.get(key) for key in ("path", "name", "kind"))
        free, total = drive.get("free_bytes"), drive.get("total_bytes")
        if (not isinstance(path, str) or not path or path in seen
                or not isinstance(name, str)
                or kind not in ("fixed", "removable", "network", "cdrom", "ramdisk", "unknown")
                or any(value is not None and (type(value) is not int or value < 0)
                       for value in (free, total))
                or (free is not None and total is not None and free > total)):
            raise ValueError("Invalid drive")
        seen.add(path)
        projected.append({"path": path, "name": name, "kind": kind,
                          "free_bytes": free, "total_bytes": total})
    return {"drivesStatus": "ready", "drives": projected, "drivesUpdatedAt": received_at}


async def _owner_usage_mutation(request: Request, *, paused: bool) -> JSONResponse:
    # Same-origin, zero-body authenticated owner gesture, matching GitHub's
    # established CSRF/mutation contract. No client-chosen device identity.
    if (request.query_params or request.headers.get("content-length") not in (None, "", "0")
        or request.headers.get("transfer-encoding")
        or request.headers.get("origin") != expected_browser_origin(request.app.state.settings)):
        return _error(403, "pc_usage_request_rejected")
    uid = current_user_id(request) if auth_ready(request) else None
    if not uid:
        return _error(401, "pc_usage_auth_required")
    workspace_id = await _resolve_memory_workspace(request, uid)
    if not workspace_id:
        return _error(503, "pc_usage_workspace_unavailable")
    # The pause flag is stored on the canonical connector binding, so the
    # Broker write uses the same connector scope as the directory read.
    try:
        connector = await resolve_pc_connector_scope(
            request, owner_id=uid, workspace_id=workspace_id,
        )
    except Exception:
        connector = PcConnectorScope(status=PC_SCOPE_OWNER_UNAVAILABLE)
    broker_owner = connector.account_ref if connector.ready else uid
    broker_workspace = connector.workspace_ref if connector.ready else workspace_id
    source = getattr(request.app.state, "claw_device_directory_source", None)
    port = getattr(source, "set_usage", None)
    if not callable(port) or getattr(source, "configured", False) is not True:
        return _error(503, "pc_usage_unavailable")
    try:
        result = port(owner_id=broker_owner, workspace_id=broker_workspace, paused=paused)
        if inspect.isawaitable(result):
            result = await result
    except Exception:
        result = None
    if (not isinstance(result, Mapping) or result.get("ok") is not True
        or result.get("usagePaused") is not paused):
        return _error(503, "pc_usage_not_confirmed")
    return _response({"ok": True, "usagePaused": paused})


async def claw_pc_pause(request: Request) -> JSONResponse:
    return await _owner_usage_mutation(request, paused=True)


async def claw_pc_resume(request: Request) -> JSONResponse:
    return await _owner_usage_mutation(request, paused=False)


async def claw_pc_select(request: Request) -> JSONResponse:
    """Persist one owner-scoped target preference from an explicit choice.

    The browser may name a device id, but the directory read (owner+workspace
    scoped) decides whether it belongs to this account and is currently usable.
    The saved row is not an execution grant; every execution re-checks the
    Broker directory and the Mesh target.
    """
    if (
        request.query_params
        or request.headers.get("origin") != expected_browser_origin(request.app.state.settings)
    ):
        return _error(403, "pc_selection_request_rejected")
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return _error(415, "pc_selection_json_required")
    try:
        raw = await request.body()
    except Exception:
        return _error(400, "pc_selection_invalid")
    if not raw or len(raw) > _MAX_SELECT_BODY_BYTES:
        return _error(413 if raw else 400, "pc_selection_invalid")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(400, "pc_selection_invalid")
    if not isinstance(data, dict) or set(data) != {"device_id"}:
        return _error(422, "pc_selection_invalid")
    device_id = data.get("device_id")
    if not is_pc_device_id(device_id):
        return _error(422, "pc_selection_device_invalid")

    uid = current_user_id(request) if auth_ready(request) else None
    if not uid:
        return _error(401, "pc_selection_auth_required")
    workspace_id = await _resolve_memory_workspace(request, uid)
    if not workspace_id:
        return _error(503, "pc_selection_workspace_unavailable")
    directory_response = await _read_device_directory(request, uid=uid, workspace_id=workspace_id)
    directory = json.loads(directory_response.body)
    if directory.get("available") is not True:
        return _error(503, directory.get("reason", "device_directory_read_failed"))
    devices = directory["devices"]
    selected_row = next(
        (row for row in devices
         if isinstance(row, Mapping) and row.get("deviceId") == device_id),
        None,
    )
    if selected_row is None:
        return _error(403, "pc_selection_not_owned")
    if (
        selected_row.get("revoked") is True
        or selected_row.get("selectable", selected_row.get("usable")) is not True
    ):
        return _error(409, "pc_selection_not_online")

    store = getattr(request.app.state, "claw_pc_device_selection_store", None)
    if store is None:
        return _error(503, "pc_selection_unavailable")
    try:
        saved = await store.save(
            owner_id=uid, workspace_id=workspace_id, device_id=device_id,
            now=datetime.now(timezone.utc),
        )
    except Exception:
        saved = False
    if saved is not True:
        return _error(503, "pc_selection_not_confirmed")
    return _response({
        "ok": True,
        "selectedDeviceId": device_id,
        "selectedUsable": True,
        "selectedState": selected_row["state"],
    })


MUTATION = True
PRODUCTION_MUTATION = True
NEW_ONLINE_AUTHORITY = False
PUBLIC_DEVICE_PAIRING = False
