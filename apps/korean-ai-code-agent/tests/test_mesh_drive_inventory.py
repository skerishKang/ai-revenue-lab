"""Drive watcher + authenticated Mesh console transport, with no live PC I/O."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

from kagent.local_agent_mesh_drive_inventory import (
    MeshDriveInventorySource, _AGENT_WATCHER_JS, _NODE_BRIDGE_JS,
)

DRIVE = {"path": "C:/", "name": "자료", "kind": "fixed",
         "free_bytes": 0, "total_bytes": 100}


class MeshDriveInventorySourceTests(unittest.TestCase):
    def source(self, runner, password_provider=lambda: "test-only-placeholder"):
        return MeshDriveInventorySource(
            meshctrl_js="/mesh/node_modules/meshcentral/meshctrl.js",
            mesh_url="wss://127.0.0.1:4443", login_user="operator",
            password_provider=password_provider, command_runner=runner,
        )

    def test_constructor_does_not_read_credential_or_probe(self):
        def unexpected(*args, **kwargs):
            self.fail("constructor performed I/O")
        self.source(unexpected, unexpected)

    def test_stdin_secret_and_strict_target_filter(self):
        calls = []
        def runner(argv, **kwargs):
            calls.append((argv, kwargs))
            return SimpleNamespace(returncode=0, stdout=json.dumps([
                {"device_id": "node//pc-1", "drives": [DRIVE]},
                {"device_id": "pc-2", "drives": []},
                {"device_id": "node//other-user", "drives": [DRIVE]},
                {"device_id": "node//pc-1", "drives": []},
            ]))
        result = self.source(runner)(["node//pc-1", "pc-2", "unsafe\nidentity"])
        self.assertEqual(result, [{"device_id": "node//pc-1", "drives": [DRIVE]},
                                  {"device_id": "pc-2", "drives": []}])
        argv, kwargs = calls[0]
        self.assertNotIn("test-only-placeholder", " ".join(argv))
        request = json.loads(kwargs["input"])
        self.assertEqual(request["password"], "test-only-placeholder")
        self.assertEqual(request["device_ids"], ["node//pc-1", "pc-2"])
        self.assertNotIn("8799", request["agent_source"])
        self.assertNotIn("CHANNEL_SECRET", request["agent_source"])

    def test_probe_failure_is_omitted_not_empty(self):
        def runner(*args, **kwargs):
            raise subprocess.TimeoutExpired("node", 1, stderr="private diagnostic")
        self.assertEqual(self.source(runner)(["pc-1"]), [])

    def test_invalid_inventory_and_nonzero_exit_are_omitted(self):
        for completed in [
            SimpleNamespace(returncode=1, stdout="secret diagnostic"),
            SimpleNamespace(returncode=0, stdout="not json"),
            SimpleNamespace(returncode=0, stdout=json.dumps([
                {"device_id": "pc-1", "drives": [{**DRIVE, "free_bytes": -1}]},
                {"device_id": "pc-1", "drives": None},
            ])),
        ]:
            with self.subTest(completed=completed.returncode):
                self.assertEqual(self.source(lambda *a, **kw: completed)(["pc-1"]), [])

    def test_empty_targets_do_not_fetch_credentials(self):
        def unexpected(*args, **kwargs):
            self.fail("empty probe performed I/O")
        self.assertEqual(self.source(unexpected, unexpected)([]), [])


@unittest.skipUnless(shutil.which("node"), "Node is required for the actual JS watcher")
class WindowsWatcherTests(unittest.TestCase):
    def run_js(self, test_body):
        harness = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const source = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
function setup(options) {
    options = options || {};
    const agent = {}, timers = [], messages = {}, queries = [];
    let reads = 0, failure = false;
    let rows = [{DeviceID: 'C:', VolumeName: '자료', DriveType: 3, FreeSpace: '0', Size: '100'}];
    function Pump() { this.on = (name, callback) => { messages[name] = callback; }; }
    const context = vm.createContext({Buffer, process: {platform: 'win32'},
        setInterval: (callback, ms) => { timers.push({callback, ms}); return timers.length; },
        require: function(name) {
            if (name === 'MeshAgent') return agent;
            if (name === 'win-message-pump' && !options.noEvents) return Pump;
            if (name === 'win-wmi-fixed' && !options.noWmi) return {query: (...args) => {
                queries.push(args); reads++; if (failure) throw new Error('unavailable'); return rows;
            }};
            if (name === 'fs') return {readDrivesSync: () => {
                reads++; if (failure) throw new Error('unavailable'); return rows;
            }};
            throw new Error('module unavailable');
        }
    });
    return {agent, timers, messages, queries, reads: () => reads,
            setRows: value => { rows = value; }, fail: value => { failure = value; },
            read: token => JSON.parse(JSON.stringify(vm.runInContext(
                source.replace('__PADIEM_REQUEST_ID__', JSON.stringify(token)), context)))};
}
"""
        completed = subprocess.run(["node", "-e", harness + test_body],
                                   input=json.dumps(_AGENT_WATCHER_JS), text=True,
                                   capture_output=True, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_device_event_add_remove_updates_before_next_poll(self):
        self.run_js(r"""
const s = setup();
assert.equal(s.read('first').drives[0].free_bytes, 0);
assert.equal(s.timers[0].ms, 30000);
s.messages.hwnd();
s.setRows([{DeviceID: 'C:', VolumeName: '자료', DriveType: 3, FreeSpace: '0', Size: '100'},
           {DeviceID: 'D:', VolumeName: 'USB', DriveType: 2, FreeSpace: '20', Size: '30'}]);
s.messages.message({message: 0x219});
assert.equal(s.agent._padiemDriveInventoryV1.serial, 2);
assert.equal(s.agent._padiemDriveInventoryV1.drives[1].kind, 'removable');
assert.equal(s.reads(), 2); // Event, without a timer tick or a COM2 read.
s.setRows([{DeviceID: 'D:', VolumeName: 'USB', DriveType: 2, FreeSpace: '20', Size: '30'}]);
s.messages.message({message: 0x219});
assert.equal(s.agent._padiemDriveInventoryV1.drives.length, 1);
assert.equal(s.agent._padiemDriveInventoryV1.drives[0].path, 'D:/');
assert.equal(s.read('second').mode, 'events+poll');
assert.equal(s.timers.length, 1); // Idempotent ensure did not add another watcher.
assert.equal(s.queries[0][1], 'SELECT DeviceID,VolumeName,DriveType,FreeSpace,Size FROM Win32_LogicalDisk');
assert.deepEqual(Array.from(s.queries[0][2]), ['DeviceID', 'VolumeName', 'DriveType', 'FreeSpace', 'Size']);
""")

    def test_timer_fallback_detects_removal_and_capacity_without_events(self):
        self.run_js(r"""
const s = setup({noEvents: true});
assert.equal(s.read('first').mode, 'poll');
s.setRows([{DeviceID: 'C:', DriveType: 3, FreeSpace: '50', Size: '100'}]);
s.timers[0].callback();
assert.equal(s.agent._padiemDriveInventoryV1.drives[0].free_bytes, 50);
s.setRows([]);
s.timers[0].callback();
assert.deepEqual(s.read('empty').drives, []);
""")

    def test_failed_probe_never_returns_stale_or_empty_success(self):
        self.run_js(r"""
const s = setup();
s.read('first'); s.fail(true); s.messages.message({message: 0x219});
const failed = s.read('failure');
assert.equal(failed.ok, false); assert.equal(failed.drives, null);
s.fail(false);
assert.equal(s.read('recovered').ok, true);
s.messages.error();
assert.equal(s.read('event-failed').mode, 'poll');
""")

    def test_native_fs_fallback_and_agent_restart_reinstall(self):
        self.run_js(r"""
const s = setup({noWmi: true});
s.setRows([{name: 'D:\\', type: 'REMOVABLE', free: 0, size: 40}]);
const first = s.read('first');
assert.equal(first.drives[0].path, 'D:/');
assert.equal(first.drives[0].kind, 'removable');
assert.equal(first.drives[0].free_bytes, 0);
assert.equal(s.read('second').serial, 1);
const restarted = setup();
assert.equal(restarted.read('restarted').ok, true);
assert.equal(restarted.timers.length, 1);
""")


@unittest.skipUnless(shutil.which("node"), "Node is required for the actual bridge")
class MeshConsoleBridgeTests(unittest.TestCase):
    def test_authenticated_server_node_binding_nonce_and_console_envelope(self):
        # Execute the real bridge with a fake ws transport. Its server frame and
        # console parser match official MeshCentral/meshcore, including full IDs.
        fake_ws = r"""
const {EventEmitter} = require('node:events');
const vm = require('node:vm');
module.exports = class FakeSocket extends EventEmitter {
    constructor(url, options) {
        super();
        if (url !== 'wss://127.0.0.1:4443/control.ashx') throw new Error('wrong endpoint');
        if (!options.headers['x-meshauth']) throw new Error('missing existing authentication');
        setImmediate(() => this.emit('message', Buffer.from(JSON.stringify({
            action: 'userinfo', userinfo: {_id: 'user//operator'}}))));
    }
    terminate() {}
    send(raw) {
        const command = JSON.parse(raw);
        if (!command.nodeid.startsWith('node//')) throw new Error('foreign domain requested');
        // Official meshcore splitArgs + eval -> JSON.stringify(result).
        const parsed = [...command.value.matchAll(/[^\s"]+|"([^"]*)"/g)].map(x => x[1] || x[0]);
        if (parsed[0] !== 'eval' || parsed.length !== 2) throw new Error('invalid console command');
        const context = vm.createContext({Buffer, process: {platform: 'win32'},
            setInterval: () => 1, require: name => {
                if (name === 'MeshAgent') return {};
                if (name === 'fs') return {readDrivesSync: () => {
                    if (command.nodeid === 'node//failed') throw new Error('probe failed');
                    return [{name: 'C:\\', type: 'FIXED', size: 100, free: 0}];
                }};
                throw new Error('module unavailable');
            }});
        const result = vm.runInContext(parsed[1], context);
        const emit = (nodeid, payload) => this.emit('message', Buffer.from(JSON.stringify({
            action: 'msg', type: 'console', nodeid, value: JSON.stringify(payload)})));
        // Correct nonce from another node and wrong nonce from the target cannot win.
        emit('node//intruder', result);
        emit(command.nodeid, {...result, request_id: 'stale-request', drives: []});
        emit(command.nodeid, result);
    }
};
"""
        with tempfile.TemporaryDirectory() as temporary:
            module = Path(temporary) / "node_modules/ws"
            module.mkdir(parents=True)
            (module / "index.js").write_text(fake_ws)
            request = {"meshctrl_js": str(Path(temporary) / "meshctrl.js"),
                       "mesh_url": "wss://127.0.0.1:4443", "login_user": "operator",
                       "password": "test-only-placeholder", "timeout_ms": 1000,
                       "device_ids": ["pc-1", "node//pc-2", "failed", "node/foreign/pc-3"],
                       "agent_source": _AGENT_WATCHER_JS}
            completed = subprocess.run(["node", "-e", _NODE_BRIDGE_JS],
                                       input=json.dumps(request), text=True,
                                       capture_output=True, timeout=5)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        rows = json.loads(completed.stdout)
        self.assertEqual([row["device_id"] for row in rows], ["pc-1", "node//pc-2"])
        self.assertTrue(all(row["drives"][0]["path"] == "C:/" for row in rows))
        self.assertNotIn("test-only-placeholder", completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
