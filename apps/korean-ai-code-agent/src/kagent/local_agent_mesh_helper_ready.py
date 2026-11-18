"""#7987 — say whether a linked PC can take a user-mode command, before one is sent.

A PC can be connected (its Mesh agent answers) while the user-session helper is
not installed, nobody is signed in to Windows, or the helper is not listening.
The server could only learn that from a command that had already failed. This
module observes it instead, on the round that already reads the drive list
(#6460): the same authenticated Mesh agent connection, the same 30-second
cadence, one more fixed expression per PC, and the same queue channel upward.

Nothing new is opened. There is no PC command, no dispatch, no console window,
no new credential and no new port, and the helper itself is not changed - it
is looked at from outside, so a PC with an old helper or with none at all is
answered for too.

The expression only reads:

* whether the helper's scheduled-task file and its install folder exist;
* the names in the pipe namespace (a pipe is never opened or connected);
* the Windows session table, reduced on the PC to one boolean;
* the installed build's SHA-256 from the helper's own install record, of which
  the first twelve hex digits travel.

It creates no child process, file, task, timer or agent state, and it never
touches the helper's secret file. A value it could not read is ``None``; the
server treats that as "not known", never as "not ready".
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Iterable

from padiem_ai_core.pc_helper_ready import (
    HELPER_READY_KEYS, HelperReadyError, validate_helper_ready,
)

HELPER_READY_PATH = "/api/claw/connector/mesh-reads/helper-ready"
HELPER_READY_PROTOCOL = "padiem-helper-ready-v1"
#: The server reads a receipt older than 180 seconds as "not known", so an
#: unchanged observation is sent again on the first round a minute after the
#: last one the queue accepted.
HELPER_READY_HEARTBEAT_SECONDS = 60
#: A queue that predates this route answers 404. It is asked again after this
#: long instead of on every round.
HELPER_READY_UNSUPPORTED_PAUSE_SECONDS = 600
#: Off unless the deployment sets this to 1/true/on. Unset keeps the drive
#: round byte-for-byte what it was.
HELPER_READY_SWITCH = "ORACLE_MESH_HELPER_READY_REPORT"

# MeshAgent embeds Duktape, so this deliberately uses ES5. It is evaluated by
# the agent console's own ``eval`` and returns one object. It keeps no state:
# every evaluation reads the PC again and leaves nothing behind.
AGENT_HELPER_READY_JS = r"""
(function(requestId) {
    var out = {protocol: 'padiem-helper-ready-v1', request_id: requestId, ok: false,
               task_present: null, install_dir_present: null, pipe_open: null,
               interactive_session: null, helper_build: null};
    if (process.platform !== 'win32') return out;
    var fs;
    try { fs = require('fs'); } catch (noFileModule) { return out; }
    function env(names, fallback) {
        try {
            for (var i = 0; i < names.length; i++) {
                var value = process.env[names[i]];
                if (typeof value === 'string' && value) return value;
            }
        } catch (unreadable) {}
        return fallback;
    }
    function exists(path) {
        var value = fs.existsSync(path);
        if (value === true || value === false) return value;
        if (typeof value === 'number') return value !== 0;
        throw new Error('existence unavailable');
    }
    var windows = env(['windir', 'SystemRoot', 'WINDIR', 'SYSTEMROOT'], 'C:\\Windows');
    var folder = env(['ProgramData', 'PROGRAMDATA', 'ALLUSERSPROFILE'], 'C:\\ProgramData') + '\\Padiem';
    var task = '\\Tasks\\Padiem\\PadiemUserSessionHelper';
    try {
        // Existence only. A 32-bit agent on 64-bit Windows may see System32
        // redirected, so the task file is asked for under both names.
        out.task_present = exists(windows + '\\System32' + task) ||
                           exists(windows + '\\Sysnative' + task);
    } catch (taskUnreadable) { out.task_present = null; }
    try { out.install_dir_present = exists(folder); }
    catch (folderUnreadable) { out.install_dir_present = null; }
    try {
        // The names in the pipe namespace are listed; no pipe is opened or
        // connected. Windows always has pipes of its own, so an empty list
        // means the listing did not work and nothing is concluded from it.
        var names = fs.readdirSync('\\\\.\\pipe\\*');
        if (Array.isArray(names) && names.length > 0) {
            var open = false;
            for (var n = 0; n < names.length; n++) {
                if (typeof names[n] === 'string' &&
                    names[n].toLowerCase().indexOf('padiem-user-helper-dev_') === 0) {
                    open = true;
                    break;
                }
            }
            out.pipe_open = open;
        }
    } catch (pipesUnreadable) { out.pipe_open = null; }
    try {
        // One boolean leaves this block: no user name, domain or station
        // name is copied into the answer.
        var sessions = require('user-sessions').Current();
        var counted = 0, active = false;
        for (var id in sessions) {
            var session = sessions[id];
            if (!session || typeof session.State !== 'string') continue;
            counted++;
            if (session.State === 'Active' && Number(session.SessionId) !== 0) active = true;
        }
        // The services session is always listed, so no rows means no answer.
        if (counted > 0) out.interactive_session = active;
    } catch (sessionsUnreadable) { out.interactive_session = null; }
    try {
        // The installer's own record of what it installed. One field is read
        // from it, and twelve hex digits of that field are all that travel.
        var record = folder + '\\helper-status.json';
        if (exists(record) && fs.statSync(record).size <= 4096) {
            var text = fs.readFileSync(record).toString();
            if (text.charCodeAt(0) === 0xFEFF) text = text.substring(1);
            var status = JSON.parse(text);
            if (status && status.status === 'installed' && typeof status.sha256 === 'string' &&
                /^[0-9a-fA-F]{64}$/.test(status.sha256)) {
                out.helper_build = status.sha256.substring(0, 12).toLowerCase();
            }
        }
    } catch (recordUnreadable) { out.helper_build = null; }
    out.ok = true;
    return out;
})(__PADIEM_REQUEST_ID__)
"""


def helper_ready_enabled(env: Any) -> bool:
    """Whether this deployment turned the observation on."""
    getter = getattr(env, "get", None)
    value = getter(HELPER_READY_SWITCH, "") if callable(getter) else ""
    return isinstance(value, str) and value.strip().lower() in {"1", "true", "on"}


class MeshHelperReadyReporter:
    """Forward changed observations, and an unchanged one once a minute.

    It is handed the rows the drive round already fetched; it never asks a PC
    for anything itself. A failed delivery stays unacknowledged and is offered
    again on the next round, and nothing here can raise into the drive round.
    """

    def __init__(self, *, post: Callable[[str, dict[str, Any]], tuple[int, Any]],
                 clock: Callable[[], float] = time.monotonic) -> None:
        if not callable(post) or not callable(clock):
            raise ValueError("a channel post and a clock are required")
        self._post = post
        self._clock = clock
        self._accepted: dict[str, tuple[str, float]] = {}
        self._paused_until: float | None = None

    def observe(self, rows: Any, targets: Iterable[str]) -> int:
        """One round's rows for the PCs the queue named. Returns the reports accepted."""
        reported = 0
        try:
            allowed = {value for value in targets if isinstance(value, str) and value}
            self._accepted = {key: value for key, value in self._accepted.items()
                              if key in allowed}
            now = self._clock()
            if self._paused_until is not None:
                if now < self._paused_until:
                    return reported
                self._paused_until = None
            seen: set[str] = set()
            for row in rows if isinstance(rows, list) else ():
                if not isinstance(row, dict) or set(row) != {"device_id", "helper"}:
                    continue
                node = row["device_id"]
                if not isinstance(node, str) or node not in allowed or node in seen:
                    continue
                seen.add(node)
                try:
                    state = validate_helper_ready(row["helper"])
                except HelperReadyError:
                    continue
                fingerprint = json.dumps(state, sort_keys=True, separators=(",", ":"))
                previous = self._accepted.get(node)
                if (previous is not None and previous[0] == fingerprint
                        and now - previous[1] < HELPER_READY_HEARTBEAT_SECONDS):
                    continue
                try:
                    status, ack = self._post(HELPER_READY_PATH,
                                             {"device_id": node, "helper": state})
                except Exception:
                    continue
                if status == 404:
                    # The queue does not serve this route yet. Asking it again
                    # for every PC on every round would only make noise.
                    self._paused_until = now + HELPER_READY_UNSUPPORTED_PAUSE_SECONDS
                    return reported
                if status == 200 and isinstance(ack, dict) and ack.get("ok") is True:
                    self._accepted[node] = (fingerprint, now)
                    reported += 1
        except Exception:
            # Readiness is evidence for a screen. It must never stop the drive
            # round it rides on, and a failed read is not "not ready".
            pass
        return reported


def attach_helper_ready(source: Any, env: Any, *, post: Any) -> MeshHelperReadyReporter | None:
    """Ride the drive round when the deployment asks for it; otherwise change nothing."""
    if not helper_ready_enabled(env):
        return None
    observe = getattr(source, "observe_helper_ready", None)
    if not callable(observe) or not callable(post):
        return None
    reporter = MeshHelperReadyReporter(post=post)
    observe(reporter.observe, source=AGENT_HELPER_READY_JS,
            protocol=HELPER_READY_PROTOCOL, keys=sorted(HELPER_READY_KEYS))
    return reporter


__all__ = [
    "AGENT_HELPER_READY_JS", "HELPER_READY_HEARTBEAT_SECONDS", "HELPER_READY_PATH",
    "HELPER_READY_PROTOCOL", "HELPER_READY_SWITCH", "HELPER_READY_UNSUPPORTED_PAUSE_SECONDS",
    "MeshHelperReadyReporter", "attach_helper_ready", "helper_ready_enabled",
]
