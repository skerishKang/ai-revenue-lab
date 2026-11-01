"""Read Windows drive changes through the existing authenticated Mesh agent.

The queue's channel secret never reaches the PC. A fixed, read-only Agent
Console expression installs one in-memory watcher in MeshAgent and returns
only drive metadata. WM_DEVICECHANGE is preferred; a 30-second timer also
detects capacity changes and supports agents without win-message-pump.

The small Node bridge uses MeshCtrl's installed ``ws`` dependency and its
existing control.ashx/x-meshauth protocol. MeshCentral attaches the source
nodeid to console replies; a PC-provided device/owner id is never trusted.
No shell child, full sysinfo query, file, scheduled task, or service is created.
"""
from __future__ import annotations

import json
import re
import subprocess
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit

from padiem_ai_core.pc_drive_inventory import (
    DriveInventoryError,
    validate_drive_inventory,
)

DRIVE_REFRESH_SECONDS = 30

# MeshAgent embeds Duktape, so this deliberately uses ES5. The request token is
# supplied by our bridge, not by a PC tool caller. Keeping state on the native
# MeshAgent module survives console evaluations and is reset on core restart.
_AGENT_WATCHER_JS = r"""
(function(requestId) {
    var agent = require('MeshAgent');
    if (process.platform !== 'win32') {
        return {protocol: 'padiem-drives-v1', request_id: requestId, ok: false};
    }
    var watcher = agent._padiemDriveInventoryV1;
    if (!watcher) {
        watcher = {ok: false, drives: null, serial: 0, fingerprint: null};
        agent._padiemDriveInventoryV1 = watcher;
        function capacity(value) {
            if (value === null || value === undefined || value === '') return null;
            var number = Number(value);
            if (!isFinite(number) || number < 0 || Math.floor(number) !== number) {
                throw new Error('drive capacity unavailable');
            }
            return number;
        }
        function collect() {
            var rows, wmi;
            try { wmi = require('win-wmi-fixed'); } catch (missing) {
                try { wmi = require('win-wmi'); } catch (alsoMissing) { wmi = null; }
            }
            if (wmi) {
                rows = wmi.query('ROOT\\CIMV2',
                    'SELECT DeviceID,VolumeName,DriveType,FreeSpace,Size FROM Win32_LogicalDisk',
                    ['DeviceID', 'VolumeName', 'DriveType', 'FreeSpace', 'Size'], false, 5000);
            } else {
                rows = require('fs').readDrivesSync();
            }
            if (!Array.isArray(rows)) throw new Error('drive inventory unavailable');
            var kinds = {2: 'removable', 3: 'fixed', 4: 'network', 5: 'cdrom',
                         6: 'ramdisk', REMOVABLE: 'removable', FIXED: 'fixed',
                         REMOTE: 'network', CDROM: 'cdrom', RAMDISK: 'ramdisk'};
            var drives = [], seen = {};
            for (var i = 0; i < rows.length; i++) {
                var row = rows[i], path = wmi ? row.DeviceID : row.name;
                if (typeof path !== 'string') throw new Error('drive path unavailable');
                path = path.replace(/\\/g, '/');
                if (!/^[a-zA-Z]:\/?$/.test(path)) continue;
                path = path.charAt(0).toUpperCase() + ':/';
                if (seen[path]) throw new Error('duplicate drive');
                seen[path] = true;
                drives.push({path: path,
                    name: wmi && typeof row.VolumeName === 'string' ? row.VolumeName : path,
                    kind: kinds[wmi ? row.DriveType : row.type] || 'unknown',
                    free_bytes: capacity(wmi ? row.FreeSpace : row.free),
                    total_bytes: capacity(wmi ? row.Size : row.size)});
            }
            drives.sort(function(a, b) { return a.path < b.path ? -1 : (a.path > b.path ? 1 : 0); });
            return drives;
        }
        watcher.refresh = function() {
            try {
                var drives = collect(), fingerprint = JSON.stringify(drives);
                if (fingerprint !== watcher.fingerprint) {
                    watcher.drives = drives;
                    watcher.fingerprint = fingerprint;
                    watcher.serial++;
                }
                watcher.ok = true;
            } catch (unavailable) {
                // A failed enumeration is not an empty replacement snapshot.
                watcher.ok = false;
            }
        };
        watcher.mode = 'poll';
        try {
            var Pump = require('win-message-pump');
            watcher.pump = new Pump({window: {exstyles: 0, winstyles: 0,
                                            width: 0, height: 0}});
            watcher.pump.on('message', function(message) {
                if (message.message === 0x219) watcher.refresh();
            });
            watcher.pump.on('hwnd', function() { watcher.mode = 'events+poll'; });
            watcher.pump.on('error', function() { watcher.mode = 'poll'; });
            watcher.pump.on('exit', function() { watcher.mode = 'poll'; });
        } catch (eventsUnavailable) { watcher.mode = 'poll'; }
        watcher.timer = setInterval(watcher.refresh, 30000);
    }
    watcher.refresh();
    // request_id also avoids MeshCentral's repeated-identical-console guard.
    return {protocol: 'padiem-drives-v1', request_id: requestId, ok: watcher.ok,
            mode: watcher.mode, serial: watcher.serial,
            drives: watcher.ok ? watcher.drives : null};
})(__PADIEM_REQUEST_ID__)
"""

# This bridge has one operation: request the fixed inventory expression from
# the target nodes. Credentials and source enter on stdin, never OS argv.
# MeshCentral's official CLI accepts a self-signed local tunnel certificate;
# preserve that behavior only on loopback, and verify TLS for remote hosts.
_NODE_BRIDGE_JS = r"""
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
let input;
try { input = JSON.parse(fs.readFileSync(0, 'utf8')); } catch (_) { process.exit(2); }
const WebSocket = require(require.resolve('ws', {paths: [path.dirname(input.meshctrl_js)]}));
const url = new URL(input.mesh_url);
url.pathname = url.pathname.replace(/\/$/, '') + '/control.ashx';
const local = ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname);
const socket = new WebSocket(url.toString(), {rejectUnauthorized: !local, headers: {
    'x-meshauth': Buffer.from(input.login_user).toString('base64') + ',' +
                  Buffer.from(input.password).toString('base64')
}});
input.password = '';
const pending = new Map();
const rows = [];
let finished = false;
let requested = false;
function finish() {
    if (finished) return;
    finished = true;
    clearTimeout(deadline);
    try { socket.terminate(); } catch (_) {}
    process.stdout.write(JSON.stringify(rows), () => process.exit(0));
}
const deadline = setTimeout(finish, input.timeout_ms);
socket.on('error', finish);
socket.on('close', finish);
function request(domain) {
    if (requested) return;
    requested = true;
    const commands = [];
    for (const deviceId of input.device_ids) {
        const nodeId = deviceId.startsWith('node/') ? deviceId : 'node/' + domain + '/' + deviceId;
        if (nodeId.split('/')[1] !== domain || pending.has(nodeId)) continue;
        const requestId = crypto.randomBytes(16).toString('hex');
        pending.set(nodeId, {requestId: requestId, deviceId: deviceId});
        const source = input.agent_source.replace('__PADIEM_REQUEST_ID__', JSON.stringify(requestId));
        const encoded = Buffer.from(source, 'utf8').toString('base64');
        // MeshAgent's console parser does not support escaped double quotes.
        const value = 'eval "eval(Buffer.from(\'' + encoded + '\',\'base64\').toString())"';
        commands.push(JSON.stringify({action: 'msg', type: 'console', nodeid: nodeId, value: value}));
    }
    if (!pending.size) finish();
    for (const command of commands) socket.send(command);
}
socket.on('message', function(raw) {
    let message, result;
    try { message = JSON.parse(raw.toString()); } catch (_) { return; }
    // Server sends this authenticated account record automatically on connect.
    if (message.action === 'userinfo' && message.userinfo &&
        typeof message.userinfo._id === 'string') {
        const parts = message.userinfo._id.split('/');
        if (parts.length === 3 && parts[0] === 'user') request(parts[1]);
        return;
    }
    if (message.action !== 'msg' || message.type !== 'console' ||
        !pending.has(message.nodeid) || typeof message.value !== 'string') return;
    try { result = JSON.parse(message.value); } catch (_) { return; }
    if (!result || result.protocol !== 'padiem-drives-v1' ||
        result.request_id !== pending.get(message.nodeid).requestId) return;
    const deviceId = pending.get(message.nodeid).deviceId;
    pending.delete(message.nodeid);
    if (result.ok === true && Array.isArray(result.drives)) {
        rows.push({device_id: deviceId, drives: result.drives});
    }
    if (!pending.size) finish();
});
"""


class MeshDriveInventorySource:
    """Callable snapshots for queue-authorized, canonical MeshCentral node IDs.

    Construction performs no I/O. Each call installs the watcher if absent, so
    new connections and agent/core restarts recover without a PC reinstall.
    Failed probes are omitted; a successfully observed empty list is retained.
    """

    def __init__(
        self, *, meshctrl_js: str, mesh_url: str, login_user: str,
        password_provider: Callable[[], str],
        command_runner: Callable[..., Any] | None = None,
        node_executable: str = "node", timeout_seconds: int = 15,
    ) -> None:
        parsed = urlsplit(mesh_url)
        if (parsed.scheme not in {"ws", "wss"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.fragment):
            raise ValueError("invalid MeshCentral control URL")
        if parsed.scheme == "ws" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("MeshCentral remote transport requires TLS")
        if not meshctrl_js or not login_user or not callable(password_provider):
            raise ValueError("MeshCentral inventory configuration is required")
        self._meshctrl_js, self._mesh_url = meshctrl_js, mesh_url
        self._login_user, self._password_provider = login_user, password_provider
        self._command_runner = command_runner or subprocess.run
        self._node_executable, self._timeout_seconds = node_executable, timeout_seconds

    def __call__(self, device_ids: Iterable[str]) -> list[dict[str, Any]]:
        # MeshCtrl listdevices uses a bare hash; other callers already hold the
        # full server nodeid. The bridge binds either form to authenticated domain.
        targets = sorted({value for value in device_ids if isinstance(value, str)
                          and re.fullmatch(r"(?:node/[A-Za-z0-9_.-]*/)?[A-Za-z0-9_@$+.-]+", value)})
        if not targets:
            return []
        try:
            password = self._password_provider()
            if not isinstance(password, str) or not password or "\n" in password or "\r" in password:
                return []
            request = {"meshctrl_js": self._meshctrl_js, "mesh_url": self._mesh_url,
                       "login_user": self._login_user, "password": password,
                       "device_ids": targets, "agent_source": _AGENT_WATCHER_JS,
                       "timeout_ms": self._timeout_seconds * 1000}
            result = self._command_runner(
                [self._node_executable, "-e", _NODE_BRIDGE_JS],
                input=json.dumps(request, ensure_ascii=True), capture_output=True,
                text=True, timeout=self._timeout_seconds + 5,
            )
            if result.returncode != 0:
                return []
            values = json.loads(result.stdout)
        except Exception:
            # Never attach child stderr/stdout or credentials to an exception/log.
            return []
        if not isinstance(values, list):
            return []
        rows, seen = [], set()
        for value in values:
            if not isinstance(value, dict) or set(value) != {"device_id", "drives"}:
                continue
            device_id = value["device_id"]
            if not isinstance(device_id, str) or device_id not in targets or device_id in seen:
                continue
            try:
                drives = validate_drive_inventory(value["drives"])
            except DriveInventoryError:
                continue
            seen.add(device_id)
            rows.append({"device_id": device_id, "drives": drives})
        return rows
