"""#7987 — helper readiness rides the drive round: expression, bridge, relay, wiring.

No live PC, Mesh server or queue is contacted. The agent expression and the
bridge are the production text, executed by Node against fakes that stand in
for the MeshAgent modules and the control socket.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from kagent.local_agent_mesh_drive_inventory import (
    MeshDriveInventorySource, _AGENT_WATCHER_JS, _NODE_BRIDGE_JS,
)
from kagent.local_agent_mesh_drive_reporter import (
    DRIVES_PATH, DRIVE_TARGETS_PATH, MeshDriveReporter,
)
from kagent.local_agent_mesh_helper_ready import (
    AGENT_HELPER_READY_JS, HELPER_READY_PATH,
    HELPER_READY_PROTOCOL, HELPER_READY_SWITCH, HelperStatusReadFallback,
    MeshHelperReadyReporter, attach_helper_ready, helper_ready_enabled,
)
from kagent.local_agent_oracle_mesh_executor import OracleMeshExecutor, POLL_PATH
from kagent.local_agent_user_helper_guards import (
    USER_HELPER_SECRET_FOLDER, USER_HELPER_TASK_NAME, USER_HELPER_TASK_PATH,
)
from padiem_ai_core.pc_helper_ready import (
    HELPER_READY_KEYS, HELPER_READY_OPTIONAL_KEYS, HelperReadyError, validate_helper_ready,
)

NODE = "node//synthetic-pc-one"
OTHER = "node//unpaired-pc"
READY = {"task_present": True, "install_dir_present": True, "pipe_open": True,
         "interactive_session": True, "helper_build": "9f2acb5916c0"}
MISSING = {"task_present": False, "install_dir_present": False, "pipe_open": False,
           "interactive_session": True, "helper_build": None}
DRIVE = {"path": "C:/", "name": "System", "kind": "fixed",
         "free_bytes": 200, "total_bytes": 500}
needs_node = pytest.mark.skipif(not shutil.which("node"), reason="Node runs the real JS")


# ---- the wire shape --------------------------------------------------------
def test_the_wire_shape_is_five_closed_values_and_nothing_else():
    assert HELPER_READY_KEYS == set(READY)
    assert validate_helper_ready(dict(reversed(list(READY.items())))) == READY
    unknown = dict.fromkeys(READY)
    assert validate_helper_ready(unknown) == unknown


@pytest.mark.parametrize("value", [
    None, [], "ready", {},
    {key: READY[key] for key in READY if key != "pipe_open"},
    {**READY, "user": "PRIVATE-NAME"},
    {**READY, "path": "C:/Users/PRIVATE-NAME"},
    {**READY, "pipe_open": 1}, {**READY, "pipe_open": "true"},
    {**READY, "interactive_session": "PRIVATE-NAME"},
    {**READY, "helper_build": "9F2ACB5916C0"}, {**READY, "helper_build": "9f2acb"},
    {**READY, "helper_build": "9f2acb5916c0" * 6}, {**READY, "helper_build": 12},
])
def test_anything_outside_the_shape_is_refused_without_echoing_it(value):
    with pytest.raises(HelperReadyError) as caught:
        validate_helper_ready(value)
    assert "PRIVATE" not in str(caught.value)


# ---- the agent expression: what it may read --------------------------------
def test_expression_is_es5_and_names_only_read_modules():
    source = AGENT_HELPER_READY_JS
    assert set(re.findall(r"require\('([^']+)'\)", source)) == {"fs", "user-sessions", "SHA256Stream"}
    assert source.count("require(") == 3
    # Duktape is ES5: none of these parse there.
    for token in ("=>", "`", "let ", "const ", "class "):
        assert token not in source, token
    # Reads only. Nothing that writes, deletes, starts a process, opens a
    # socket or pipe, keeps state, or evaluates text.
    for token in ("write", "unlink", "mkdir", "rmdir", "rename", "copyFile", "chmod",
                  "child_process", "execFile", "spawn", "createConnection", "connect(",
                  "'net'", "'http", "setInterval", "setTimeout", "eval(", "Function(",
                  "helper.secret", "MeshAgent", "createReadStream", "openSync"):
        assert token not in source, token
    assert set(re.findall(r"fs\.([A-Za-z]+)\(", source)) == {
        "existsSync", "readdirSync", "statSync", "readFileSync"}
    assert len(source.encode("utf-8")) < len(_AGENT_WATCHER_JS.encode("utf-8"))


def test_expression_names_the_same_task_folder_and_pipe_the_executor_uses():
    source = AGENT_HELPER_READY_JS
    task = "\\Tasks" + USER_HELPER_TASK_PATH + USER_HELPER_TASK_NAME
    assert "'" + task.replace("\\", "\\\\") + "'" in source
    assert "+ '\\\\" + USER_HELPER_SECRET_FOLDER + "'" in source
    executor = Path(__file__).resolve().parents[1].joinpath(
        "src", "kagent", "local_agent_oracle_mesh_executor.py").read_text(encoding="utf-8")
    assert "$pipeName='padiem-user-helper-dev_'" in executor
    assert "indexOf('padiem-user-helper-dev_') === 0" in source
    assert "readdirSync('\\\\\\\\.\\\\pipe\\\\*')" in source
    assert "'" + HELPER_READY_PROTOCOL + "'" in source


HARNESS = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const source = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const TASK = 'C:\\Windows\\System32\\Tasks\\Padiem\\PadiemUserSessionHelper';
const WOW = 'C:\\Windows\\Sysnative\\Tasks\\Padiem\\PadiemUserSessionHelper';
const FOLDER = 'C:\\ProgramData\\Padiem';
const RECORD = FOLDER + '\\helper-status.json';
const SHA = '9F2ACB5916C0F1EB95120EB20851103EB703B902185FA281E5C0AE828445C3E5';
const SYSTEM_PIPES = ['InitShutdown', 'lsass', 'ntsvcs', 'wkssvc'];
const HELPER_PIPE = 'padiem-user-helper-dev_0123456789abcdef0123456789abcdef';
const SERVICES = {SessionId: 0, StationName: 'Services', State: 'Disconnected'};
const SIGNED_IN = {SessionId: 1, StationName: 'Console', State: 'Active',
                   Username: 'PRIVATE-USER', Domain: 'PRIVATE-DOMAIN'};
function record(fields) {
    return {text: JSON.stringify(Object.assign({
        device_id: 'PRIVATE-DEVICE', task: 'PadiemUserSessionHelper', status: 'installed',
        sha256: SHA, user: 'PRIVATE-DOMAIN\\PRIVATE-USER'}, fields || {}))};
}
function installed(extra) {
    const files = {};
    files[TASK] = true; files[FOLDER] = true; files[RECORD] = record();
    return Object.assign(files, extra || {});
}
function run(options) {
    options = options || {};
    const files = options.files || {};
    const calls = [], modules = [];
    const reads = {
        existsSync: path => {
            calls.push(['existsSync', path]);
            if (options.existsThrows) throw new Error('unavailable');
            return Object.prototype.hasOwnProperty.call(files, path);
        },
        readdirSync: path => {
            calls.push(['readdirSync', path]);
            if (options.pipes === 'throw') throw new Error('unavailable');
            return options.pipes;
        },
        statSync: path => {
            calls.push(['statSync', path]);
            const entry = files[path];
            return {size: entry.size !== undefined ? entry.size : Buffer.byteLength(entry.text)};
        },
        readFileSync: path => {
            calls.push(['readFileSync', path]);
            return Buffer.from(files[path].text, 'utf8');
        },
    };
    // Any other fs member - a write, a delete, a stream - fails the test.
    const fs = new Proxy(reads, {get(target, name) {
        if (!Object.prototype.hasOwnProperty.call(target, name)) {
            throw new Error('unexpected fs member ' + String(name));
        }
        return target[name];
    }});
    const env = options.env === null ? undefined
        : (options.env || {windir: 'C:\\Windows', ProgramData: 'C:\\ProgramData'});
    // No timers and no MeshAgent object exist here: the expression is stateless.
    const context = vm.createContext({Buffer, process: {platform: options.platform || 'win32', env, versions: options.versions},
        require: name => {
            modules.push(name);
            if (name === 'fs') return fs;
            if (name === 'SHA256Stream') return {create: () => ({syncHash: data =>
                require('node:crypto').createHash('sha256').update(data).digest()})};
            if (name === 'user-sessions') {
                if (options.sessions === 'missing') throw new Error('module unavailable');
                return {Current: () => options.sessions};
            }
            throw new Error('unexpected module ' + name);
        }});
    const raw = vm.runInContext(
        source.replace('__PADIEM_REQUEST_ID__', JSON.stringify(options.token || 'token-1')), context);
    const text = JSON.stringify(raw);
    return {result: JSON.parse(text), text, calls, modules};
}
function facts(result) {
    return [result.task_present, result.install_dir_present, result.pipe_open,
            result.interactive_session, result.helper_build];
}
"""


def run_js(body: str) -> None:
    completed = subprocess.run(
        ["node", "-e", HARNESS + body], input=json.dumps(AGENT_HELPER_READY_JS),
        text=True, encoding="utf-8", capture_output=True, timeout=20)
    assert completed.returncode == 0, completed.stderr


@needs_node
def test_agent_reports_mesh_build_timestamp_without_exposing_other_version_values():
    run_js(r"""
const seen = run({files: installed(), pipes: SYSTEM_PIPES.concat([HELPER_PIPE]),
                  sessions: {0: SERVICES, 1: SIGNED_IN},
                  versions: {commitDate: '2026-02-15T16:43:44-08:00', private: 'private-version'}});
assert.equal(seen.result.mesh_agent_version, '2026-02-16T00:43:44.000Z');
assert.equal(seen.result.helper_sha256, SHA.toLowerCase());
assert.equal(seen.text.includes('private-version'), false);
""")


@needs_node
def test_install_guid_is_reported_only_as_a_verified_digest():
    run_js(r"""
const guid = '0123456789ABCDEF0123456789ABCDEF';
const seen = run({files: installed({[RECORD]: record({device_id: guid})})});
assert.equal(seen.result.helper_install_ref_sha256,
    require('node:crypto').createHash('sha256').update(guid.toLowerCase()).digest('hex'));
assert.equal(seen.text.includes(guid), false);
assert.equal(seen.text.includes(guid.toLowerCase()), false);
""")


@needs_node
def test_ready_pc_reports_every_fact_and_no_name_path_or_identity():
    run_js(r"""
const seen = run({files: installed(), pipes: SYSTEM_PIPES.concat([HELPER_PIPE]),
                  sessions: {0: SERVICES, 1: SIGNED_IN}, token: 'nonce-7'});
assert.deepEqual(seen.result, {protocol: 'padiem-helper-ready-v1', request_id: 'nonce-7', ok: true,
    task_present: true, install_dir_present: true, pipe_open: true,
    interactive_session: true, helper_build: '9f2acb5916c0', helper_sha256: SHA.toLowerCase(),
    helper_status_present: true, updater_source_present: false, updater_task_present: false,
    self_heal_task_present: false});
for (const secret of ['PRIVATE', 'Padiem', 'C:\\\\', 'Console', 'Services', HELPER_PIPE]) {
    assert.equal(seen.text.includes(secret), false, secret);
}
""")


@needs_node
def test_updater_observation_reads_only_a_bounded_fixed_source():
    run_js(r"""
const updater = 'C:\\ProgramData\\PadiemHelperUpdater\\update.ps1';
const task = 'C:\\Windows\\System32\\Tasks\\Padiem\\PadiemUserHelperUpdater';
const files = installed({[updater]: {text: 'fixture-source'}, [task]: true});
const seen = run({files, pipes: SYSTEM_PIPES, sessions: {0: SERVICES}});
assert.equal(seen.result.updater_source_sha256, require('node:crypto').createHash('sha256').update('fixture-source').digest('hex'));
assert.equal(seen.result.updater_task_present, true);
assert.equal(seen.result.helper_status_present, true);
assert.equal(seen.text.includes('fixture-source'), false);
// #8359 F7: the SYSTEM self-heal watcher task (#8193) is observed the same way,
// under both the native and the 32-bit view of the task folder.
assert.equal(seen.result.self_heal_task_present, false);
const watcher = 'C:\\Windows\\System32\\Tasks\\Padiem\\PadiemPcSelfHeal';
const withWatcher = run({files: installed({[watcher]: true}), pipes: SYSTEM_PIPES, sessions: {0: SERVICES}});
assert.equal(withWatcher.result.self_heal_task_present, true);
const wowWatcher = 'C:\\Windows\\Sysnative\\Tasks\\Padiem\\PadiemPcSelfHeal';
const underWow = run({files: installed({[wowWatcher]: true}), pipes: SYSTEM_PIPES, sessions: {0: SERVICES}});
assert.equal(underWow.result.self_heal_task_present, true);
assert.equal(withWatcher.text.includes('PadiemPcSelfHeal'), false);
files[updater].size = 131073;
const large = run({files, pipes: SYSTEM_PIPES, sessions: {0: SERVICES}});
assert.equal(large.result.updater_source_sha256, undefined);
assert.equal(large.calls.some(call => call[0] === 'readFileSync' && call[1] === updater), false);
""")


@needs_node
def test_pc_without_the_helper_is_answered_for_instead_of_staying_silent():
    # The shape of the PC that started this work: connected, signed in, no helper.
    run_js(r"""
const seen = run({files: {}, pipes: SYSTEM_PIPES, sessions: {0: SERVICES, 1: SIGNED_IN}});
assert.equal(seen.result.ok, true);
assert.deepEqual(facts(seen.result), [false, false, false, true, null]);
""")


@needs_node
def test_installed_but_nobody_signed_in_and_installed_but_helper_stopped():
    run_js(r"""
const logonScreen = {SessionId: 1, StationName: 'Console', State: 'Connected'};
let seen = run({files: installed(), pipes: SYSTEM_PIPES, sessions: {0: SERVICES, 1: logonScreen}});
assert.deepEqual(facts(seen.result), [true, true, false, false, '9f2acb5916c0']);
seen = run({files: installed(), pipes: SYSTEM_PIPES, sessions: {0: SERVICES, 1: SIGNED_IN}});
assert.deepEqual(facts(seen.result), [true, true, false, true, '9f2acb5916c0']);
// The services session never counts as somebody signed in.
seen = run({files: installed(), pipes: SYSTEM_PIPES,
            sessions: {0: Object.assign({}, SERVICES, {State: 'Active'})}});
assert.equal(seen.result.interactive_session, false);
""")


@needs_node
def test_a_value_that_could_not_be_read_is_null_never_false():
    run_js(r"""
const base = {files: installed(), pipes: SYSTEM_PIPES.concat([HELPER_PIPE]),
              sessions: {0: SERVICES, 1: SIGNED_IN}};
// A listing that returns nothing did not work: Windows always has pipes.
for (const pipes of ['throw', [], undefined, null, 'lsass']) {
    const seen = run(Object.assign({}, base, {pipes}));
    assert.equal(seen.result.pipe_open, null, String(pipes));
    assert.equal(seen.result.ok, true);
}
for (const sessions of ['missing', undefined, null, {}, {1: {SessionId: 1}}]) {
    assert.equal(run(Object.assign({}, base, {sessions})).result.interactive_session, null);
}
const blind = run(Object.assign({}, base, {existsThrows: true})).result;
assert.equal(blind.task_present, null);
assert.equal(blind.install_dir_present, null);
assert.equal(blind.helper_build, null);
assert.equal(blind.pipe_open, true);
""")


@needs_node
def test_pipe_is_matched_by_its_prefix_only_and_without_case():
    run_js(r"""
const base = {files: installed(), sessions: {0: SERVICES, 1: SIGNED_IN}};
assert.equal(run(Object.assign({}, base, {pipes: ['lsass', 'PADIEM-USER-HELPER-DEV_AB']})).result.pipe_open, true);
for (const name of ['x-padiem-user-helper-dev_ab', 'padiem-user-helper-', 'padiem-user-helper-other']) {
    assert.equal(run(Object.assign({}, base, {pipes: ['lsass', name]})).result.pipe_open, false, name);
}
assert.equal(run(Object.assign({}, base, {pipes: ['lsass', 7, null]})).result.pipe_open, false);
""")


@needs_node
def test_task_file_is_found_under_the_32_bit_view_and_with_default_folders():
    run_js(r"""
const files = {}; files[WOW] = true; files[FOLDER] = true;
let seen = run({files, pipes: SYSTEM_PIPES, sessions: {0: SERVICES}});
assert.equal(seen.result.task_present, true);
// No environment at all: the documented Windows defaults are used.
seen = run({files: installed(), pipes: SYSTEM_PIPES, sessions: {0: SERVICES}, env: {}});
assert.deepEqual(facts(seen.result).slice(0, 2), [true, true]);
seen = run({files: installed(), pipes: SYSTEM_PIPES, sessions: {0: SERVICES},
            env: {SystemRoot: 'C:\\Windows', PROGRAMDATA: 'C:\\ProgramData'}});
assert.deepEqual(facts(seen.result).slice(0, 2), [true, true]);
// An agent whose process object has no environment table at all.
seen = run({files: installed(), pipes: SYSTEM_PIPES, sessions: {0: SERVICES}, env: null});
assert.deepEqual(facts(seen.result).slice(0, 2), [true, true]);
""")


@needs_node
def test_build_comes_only_from_a_small_valid_install_record():
    run_js(r"""
const base = {pipes: SYSTEM_PIPES, sessions: {0: SERVICES}};
function build(entry) {
    const files = installed(); if (entry === null) delete files[RECORD]; else files[RECORD] = entry;
    return run(Object.assign({files}, base));
}
assert.equal(build(record()).result.helper_build, '9f2acb5916c0');
assert.equal(build(record({update_result: 'rollback'})).result.update_result, 'rollback');
assert.equal(build(record({update_result: 'download_failed', update_target_sha256: 'b'.repeat(64)})).result.update_target_sha256, 'b'.repeat(64));
assert.equal(build(record({update_target_sha256: 'private path'})).result.update_target_sha256, undefined);
assert.equal(build(record({update_result: 'registration_failed', update_registration_error: 'updater_running'})).result.update_registration_error, 'updater_running');
assert.equal(build(record({update_result: 'registration_failed', update_registration_error: 'private path'})).result.update_registration_error, undefined);
assert.equal(build(record({update_result: 'private text'})).result.update_result, undefined);
assert.equal(build(record({update_result: ['success']})).result.update_result, undefined);
assert.equal(build({text: '\uFEFF' + record().text}).result.helper_build, '9f2acb5916c0');
assert.equal(build(null).result.helper_build, null);
assert.equal(build(record({status: 'not_installed'})).result.helper_build, null);
assert.equal(build(record({sha256: 'PRIVATE-USER'})).result.helper_build, null);
assert.equal(build(record({sha256: SHA + 'AB'})).result.helper_build, null);
assert.equal(build({text: 'not json'}).result.helper_build, null);
assert.equal(build({text: '[]'}).result.helper_build, null);
// An oversized file is never read at all.
const big = build(Object.assign(record(), {size: 4097}));
assert.equal(big.result.helper_build, null);
assert.equal(big.calls.some(call => call[0] === 'readFileSync'), false);
""")


@needs_node
def test_expression_only_reads_and_never_touches_the_secret_or_a_pipe():
    run_js(r"""
const seen = run({files: installed(), pipes: SYSTEM_PIPES.concat([HELPER_PIPE]),
                  sessions: {0: SERVICES, 1: SIGNED_IN}});
assert.deepEqual(Array.from(new Set(seen.modules)).sort(), ['fs', 'user-sessions']);
assert.deepEqual(seen.calls.filter(call => call[0] === 'readdirSync'), [['readdirSync', '\\\\.\\pipe\\*']]);
assert.deepEqual(seen.calls.filter(call => call[0] === 'readFileSync'), [['readFileSync', RECORD]]);
for (const call of seen.calls) {
    assert.equal(call[1].toLowerCase().includes('secret'), false);
    // The helper's pipe is never named to a file call: it is only listed.
    assert.equal(call[1].includes('padiem-user-helper'), false);
}
// Evaluating twice leaves nothing behind and answers the new request.
assert.equal(run({files: {}, pipes: SYSTEM_PIPES, sessions: {0: SERVICES}, token: 'second'})
    .result.request_id, 'second');
""")


@needs_node
def test_other_platform_answers_not_ok_and_reads_nothing():
    run_js(r"""
const seen = run({platform: 'linux', files: installed(), pipes: SYSTEM_PIPES, sessions: {0: SERVICES}});
assert.equal(seen.result.ok, false);
assert.deepEqual(facts(seen.result), [null, null, null, null, null]);
assert.deepEqual(seen.modules, []);
""")


# ---- the bridge: one session, two expressions -------------------------------
FAKE_WS = r"""
const {EventEmitter} = require('node:events');
const vm = require('node:vm');
module.exports = class FakeSocket extends EventEmitter {
    constructor(url, options) {
        super();
        const parsed = new URL(url);
        if (parsed.origin + parsed.pathname !== 'wss://127.0.0.1:4443/control.ashx') throw new Error('wrong endpoint');
        if (parsed.searchParams.has('auth')) {
            if (options.headers['x-meshauth']) throw new Error('password downgrade');
            const crypto = require('node:crypto');
            const cookie = Buffer.from(parsed.searchParams.get('auth').replace(/@/g, '+').replace(/\$/g, '/'), 'base64');
            const decipher = crypto.createDecipheriv('aes-256-gcm', Buffer.alloc(32, 0x42), cookie.subarray(0, 12));
            decipher.setAuthTag(cookie.subarray(12, 28));
            const auth = JSON.parse(Buffer.concat([decipher.update(cookie.subarray(28)), decipher.final()]).toString());
            if (auth.userid !== 'user//operator' || auth.domainid !== '' ||
                Math.abs(auth.time - Date.now()/1000) > 10) throw new Error('invalid test cookie');
        } else if (!options.headers['x-meshauth']) {
            throw new Error('missing existing authentication');
        }
        setImmediate(() => this.emit('message', Buffer.from(JSON.stringify({
            action: 'userinfo', userinfo: {_id: 'user//operator'}}))));
    }
    terminate() {}
    send(raw) {
        const command = JSON.parse(raw);
        if (!command.nodeid.startsWith('node//')) throw new Error('foreign domain requested');
        const parsed = [...command.value.matchAll(/[^\s"]+|"([^"]*)"/g)].map(x => x[1] || x[0]);
        if (parsed[0] !== 'eval' || parsed.length !== 2) throw new Error('invalid console command');
        const context = vm.createContext({Buffer, process: {platform: 'win32', env: {}},
            setInterval: () => 1, require: name => {
                if (name === 'MeshAgent') return {};
                if (name === 'user-sessions') return {Current: () => ({
                    1: {SessionId: 1, State: 'Active', Username: 'PRIVATE-USER'}})};
                if (name === 'fs') return {
                    readDrivesSync: () => {
                        if (command.nodeid === 'node//failed') throw new Error('probe failed');
                        return [{name: 'C:\\', type: 'FIXED', size: 100, free: 0}];
                    },
                    existsSync: path => !path.endsWith('helper-status.json'),
                    readdirSync: () => ['lsass', 'padiem-user-helper-dev_00'],
                };
                throw new Error('module unavailable');
            }});
        const result = vm.runInContext(parsed[1], context);
        const emit = (nodeid, payload) => this.emit('message', Buffer.from(JSON.stringify({
            action: 'msg', type: 'console', nodeid,
            value: typeof payload === 'string' ? payload : JSON.stringify(payload)})));
        if (result.protocol === 'padiem-helper-ready-v1') {
            // An agent whose console fails answers text, not the protocol object.
            if (command.nodeid === 'node//pc-2') return emit(command.nodeid, 'Error: unavailable');
            emit('node//intruder', result);
            emit(command.nodeid, Object.assign({}, result, {request_id: 'stale', pipe_open: false}));
            emit(command.nodeid, Object.assign({}, result, {extra: 'PRIVATE-EXTRA'}));
            return;
        }
        emit(command.nodeid, result);
    }
};
"""


def run_bridge(request: dict) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as temporary:
        module = Path(temporary) / "node_modules/ws"
        module.mkdir(parents=True)
        (module / "index.js").write_text(FAKE_WS)
        payload = {"meshctrl_js": str(Path(temporary) / "meshctrl.js"),
                   "mesh_url": "wss://127.0.0.1:4443", "login_user": "operator",
                   "password": "test-only-placeholder", "timeout_ms": 4000,
                   "agent_source": _AGENT_WATCHER_JS, **request}
        return subprocess.run(["node", "-e", _NODE_BRIDGE_JS], input=json.dumps(payload),
                              text=True, encoding="utf-8", capture_output=True, timeout=15)


@needs_node
def test_bridge_sends_both_expressions_in_one_session_and_binds_each_answer():
    completed = run_bridge({
        "device_ids": ["pc-1", "node//pc-2", "failed"],
        "helper_source": AGENT_HELPER_READY_JS, "helper_protocol": HELPER_READY_PROTOCOL,
        "helper_keys": sorted(HELPER_READY_KEYS), "helper_grace_ms": 150})
    assert completed.returncode == 0, completed.stderr
    answer = json.loads(completed.stdout)
    assert set(answer) == {"drives", "helper"}
    # Drives are exactly what they were: the PC whose probe failed is omitted,
    # and the PC whose second answer never came still reports its drives.
    assert [row["device_id"] for row in answer["drives"]] == ["pc-1", "node//pc-2"]
    assert [row["device_id"] for row in answer["helper"]] == ["pc-1", "failed"]
    for row in answer["helper"]:
        assert set(row) == {"device_id", "helper"}
        # The stale request id and the foreign node did not win, and a key the
        # caller did not declare is not copied.
        assert row["helper"] == {"task_present": True, "install_dir_present": True,
                                 "pipe_open": True, "interactive_session": True,
                                 "helper_build": None}
    assert "PRIVATE" not in completed.stdout + completed.stderr
    assert "test-only-placeholder" not in completed.stdout + completed.stderr


@needs_node
def test_bridge_without_the_second_expression_prints_the_drive_list_as_before():
    completed = run_bridge({"device_ids": ["pc-1"]})
    assert completed.returncode == 0, completed.stderr
    rows = json.loads(completed.stdout)
    assert isinstance(rows, list) and [row["device_id"] for row in rows] == ["pc-1"]
    assert set(rows[0]) == {"device_id", "drives"}


# ---- the source: additive only ----------------------------------------------
@needs_node
def test_bridge_login_key_matches_meshctrl_and_never_falls_back(tmp_path):
    key = tmp_path / "synthetic-key"
    key.write_text("42" * 80)
    request = {"device_ids": ["pc-1"], "login_key_file": str(key), "password": ""}
    completed = run_bridge(request)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)[0]["device_id"] == "pc-1"
    key.write_text("invalid")
    completed = run_bridge(request)
    assert completed.returncode != 0
    assert not completed.stdout


def test_source_configured_key_does_not_read_password():
    password = Mock(side_effect=AssertionError("password must not be requested"))
    runner = Mock(return_value=SimpleNamespace(returncode=0, stdout="[]"))
    source = MeshDriveInventorySource(
        meshctrl_js="/mesh/meshctrl.js", mesh_url="wss://127.0.0.1:4443",
        login_user="operator", password_provider=password,
        login_key_file="/configured/key", command_runner=runner)
    source(["pc-1"])
    password.assert_not_called()
    payload = json.loads(runner.call_args.kwargs["input"])
    assert payload["login_key_file"] == "/configured/key" and payload["password"] == ""


def make_source(runner):
    return MeshDriveInventorySource(
        meshctrl_js="/mesh/node_modules/meshcentral/meshctrl.js",
        mesh_url="wss://127.0.0.1:4443", login_user="operator",
        password_provider=lambda: "test-only-placeholder", command_runner=runner)


def test_unattached_source_sends_no_second_expression():
    calls = []
    def runner(argv, **kwargs):
        calls.append(json.loads(kwargs["input"]))
        return SimpleNamespace(returncode=0, stdout=json.dumps(
            [{"device_id": "pc-1", "drives": [DRIVE]}]))
    assert make_source(runner)(["pc-1"]) == [{"device_id": "pc-1", "drives": [DRIVE]}]
    assert not [key for key in calls[0] if key.startswith("helper")]


def test_attached_source_hands_rows_and_targets_to_the_observer_and_keeps_drives():
    calls, observed = [], []
    def runner(argv, **kwargs):
        calls.append(json.loads(kwargs["input"]))
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            "drives": [{"device_id": "pc-1", "drives": [DRIVE]}],
            "helper": [{"device_id": "pc-1", "helper": READY}]}))
    source = make_source(runner)
    source.observe_helper_ready(lambda rows, targets: observed.append((rows, targets)),
                                source=AGENT_HELPER_READY_JS, protocol=HELPER_READY_PROTOCOL,
                                keys=sorted(HELPER_READY_KEYS))
    assert source(["pc-1", "pc-2"]) == [{"device_id": "pc-1", "drives": [DRIVE]}]
    assert observed == [([{"device_id": "pc-1", "helper": READY}], ["pc-1", "pc-2"])]
    assert calls[0]["helper_source"] == AGENT_HELPER_READY_JS
    assert calls[0]["helper_protocol"] == HELPER_READY_PROTOCOL
    assert calls[0]["helper_keys"] == sorted(HELPER_READY_KEYS)
    assert calls[0]["agent_source"] == _AGENT_WATCHER_JS


@pytest.mark.parametrize("helper", [None, "broken", {"device_id": "pc-1"}])
def test_a_failing_or_missing_second_answer_never_costs_the_drives(helper):
    def runner(argv, **kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            "drives": [{"device_id": "pc-1", "drives": [DRIVE]}], "helper": helper}))
    source = make_source(runner)
    observer = Mock(side_effect=RuntimeError("observer failed"))
    source.observe_helper_ready(observer, source="x", protocol="p", keys=["pipe_open"])
    assert source(["pc-1"]) == [{"device_id": "pc-1", "drives": [DRIVE]}]
    observer.assert_called_once_with([], ["pc-1"])


def test_attached_source_refuses_an_old_shaped_answer_rather_than_guessing():
    source = make_source(lambda argv, **kw: SimpleNamespace(
        returncode=0, stdout=json.dumps([{"device_id": "pc-1", "drives": [DRIVE]}])))
    observer = Mock()
    source.observe_helper_ready(observer, source="x", protocol="p", keys=["pipe_open"])
    assert source(["pc-1"]) == []
    # No invented console evidence, but the independent fixed-path read can run.
    observer.assert_called_once_with([], ["pc-1"])


@pytest.mark.parametrize("arguments", [
    {"observer": None}, {"source": ""}, {"source": "  "}, {"protocol": ""},
    {"keys": []}, {"keys": ["not a name"]},
])
def test_incomplete_observation_is_refused_when_attached(arguments):
    values = {"observer": Mock(), "source": "x", "protocol": "p", "keys": ["pipe_open"]}
    values.update(arguments)
    with pytest.raises(ValueError):
        make_source(Mock()).observe_helper_ready(
            values["observer"], source=values["source"], protocol=values["protocol"],
            keys=values["keys"])


# ---- the relay ---------------------------------------------------------------
class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def relay(status=200, ack=None):
    sent, clock = [], Clock()
    answer = {"status": status, "ack": {"ok": True} if ack is None else ack}

    def post(path, payload):
        assert path == HELPER_READY_PATH
        sent.append(copy.deepcopy(payload))
        return answer["status"], answer["ack"]

    return MeshHelperReadyReporter(post=post), sent, clock, answer


def test_relay_reports_unchanged_and_changed_observations_every_round():
    reporter, sent, clock, _ = relay()
    rows = [{"device_id": NODE, "helper": dict(MISSING)}]
    assert reporter.observe(rows, [NODE]) == 1
    clock.now += 30
    assert reporter.observe(rows, [NODE]) == 1
    rows[0]["helper"] = dict(READY)
    assert reporter.observe(rows, [NODE]) == 1
    assert [row["helper"] for row in sent] == [MISSING, MISSING, READY]


def test_relay_retries_a_refused_report_and_never_acknowledges_it():
    reporter, sent, clock, answer = relay(status=503, ack={"ok": False})
    rows = [{"device_id": NODE, "helper": dict(READY)}]
    assert reporter.observe(rows, [NODE]) == 0
    answer.update(status=200, ack={"ok": False})
    assert reporter.observe(rows, [NODE]) == 0
    answer.update(ack={"ok": True})
    assert reporter.observe(rows, [NODE]) == 1
    assert len(sent) == 3


def test_relay_forwards_only_named_pcs_and_only_the_closed_shape():
    reporter, sent, _, _ = relay()
    rows = [
        {"device_id": OTHER, "helper": dict(READY)},
        {"device_id": NODE, "helper": {**READY, "user": "PRIVATE-NAME"}},
        {"device_id": NODE, "helper": dict(READY), "owner": "PRIVATE-NAME"},
        "not a row", {"device_id": 7, "helper": dict(READY)},
    ]
    assert reporter.observe(rows, [NODE]) == 0
    assert sent == []
    assert reporter.observe([{"device_id": NODE, "helper": dict(READY)},
                             {"device_id": NODE, "helper": dict(MISSING)}], [NODE]) == 1
    assert sent == [{"device_id": NODE, "helper": READY}]  # The first row for a PC wins.
    assert "PRIVATE" not in json.dumps(sent)
    for unusable in (None, {}, "rows"):
        assert reporter.observe(unusable, [NODE]) == 0


def test_relay_forgets_an_unlinked_pc_and_reports_it_again_when_relinked():
    reporter, sent, _, _ = relay()
    rows = [{"device_id": NODE, "helper": dict(READY)}]
    assert reporter.observe(rows, [NODE]) == 1
    assert reporter.observe(rows, []) == 0
    assert reporter.observe(rows, [NODE]) == 1
    assert len(sent) == 2


def test_relay_logs_404_per_pc_without_suppressing_the_next_report(capsys):
    reporter, sent, _, answer = relay(status=404, ack={})
    rows = [{"device_id": NODE, "helper": dict(READY)},
            {"device_id": OTHER, "helper": dict(READY)}]
    assert reporter.observe(rows, [NODE, OTHER]) == 0
    assert len(sent) == 2
    assert capsys.readouterr().out.count("report=rejected status=404") == 2
    answer.update(status=200, ack={"ok": True})
    assert reporter.observe(rows, [NODE, OTHER]) == 2


def test_relay_never_raises_into_the_drive_round():
    reporter = MeshHelperReadyReporter(post=Mock(side_effect=OSError("queue down")))
    assert reporter.observe([{"device_id": NODE, "helper": dict(READY)}], [NODE]) == 0
    assert reporter.observe([], None) == 0
    with pytest.raises(ValueError):
        MeshHelperReadyReporter(post=None)


# ---- the switch and the executor wiring ---------------------------------------
@pytest.mark.parametrize("value,expected", [
    (None, False), ("", False), ("0", False), ("off", False), ("yes", False),
    ("1", True), (" true ", True), ("ON", True),
])
def test_the_switch_is_off_unless_the_deployment_sets_it(value, expected):
    env = {} if value is None else {HELPER_READY_SWITCH: value}
    assert helper_ready_enabled(env) is expected
    assert helper_ready_enabled(None) is False


def test_switch_off_leaves_the_drive_source_untouched():
    source = Mock()
    assert attach_helper_ready(source, {}, post=Mock()) is None
    assert attach_helper_ready(source, {HELPER_READY_SWITCH: "0"}, post=Mock()) is None
    source.observe_helper_ready.assert_not_called()
    assert attach_helper_ready(object(), {HELPER_READY_SWITCH: "1"}, post=Mock()) is None
    assert attach_helper_ready(source, {HELPER_READY_SWITCH: "1"}, post=None) is None
    source.observe_helper_ready.assert_not_called()


def test_switch_on_attaches_the_fixed_expression_to_the_drive_round():
    source = Mock()
    reporter = attach_helper_ready(source, {HELPER_READY_SWITCH: "1"}, post=Mock())
    assert isinstance(reporter, MeshHelperReadyReporter)
    source.observe_helper_ready.assert_called_once_with(
        reporter.observe, source=AGENT_HELPER_READY_JS, protocol=HELPER_READY_PROTOCOL,
        keys=sorted(HELPER_READY_KEYS | HELPER_READY_OPTIONAL_KEYS))


def executor(**kwargs):
    return OracleMeshExecutor(chat_origin="https://chat.example.test",
        channel_secret="synthetic-channel-secret", read_port=Mock(), **kwargs)


def test_only_a_queue_executor_with_the_switch_reports_readiness():
    on = {HELPER_READY_SWITCH: "1"}
    assert executor().start_helper_ready_reporting(Mock(), on) is None
    lane = executor(queue_origin="http://127.0.0.1:8797")
    assert lane.start_helper_ready_reporting(Mock(), {}) is None
    source = Mock()
    reporter = lane.start_helper_ready_reporting(source, on)
    assert isinstance(reporter, MeshHelperReadyReporter)
    source.observe_helper_ready.assert_called_once()


def test_report_uses_the_authenticated_queue_leg_and_does_not_feed_the_watchdog(capsys):
    lane = executor(queue_origin="http://127.0.0.1:8797")
    lane._last_round_at = 1
    response = Mock(status=200)
    response.read.return_value = b'{"ok":true}'
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    opener = Mock()
    opener.open.return_value = response
    with patch("urllib.request.build_opener", return_value=opener):
        lane._https_post(HELPER_READY_PATH, {"device_id": NODE, "helper": READY})
        request = opener.open.call_args.args[0]
        assert request.full_url == "http://127.0.0.1:8797" + HELPER_READY_PATH
        assert dict(request.header_items())["X-oracle-mesh-secret"] == "synthetic-channel-secret"
        assert lane._last_round_at == 1  # Inventory traffic cannot hide a stalled loop.
        lane._https_post(POLL_PATH, None)
        assert lane._last_round_at > 1
    assert "synthetic-channel-secret" not in str(capsys.readouterr())


def test_readiness_rides_the_same_gated_drive_round_end_to_end():
    lane = executor(queue_origin="http://127.0.0.1:8797")
    sent, allowed = [], {"value": True}

    def post(path, payload):
        if path == DRIVE_TARGETS_PATH:
            return 200, {"ok": True, "device_ids": [NODE]}
        sent.append((path, copy.deepcopy(payload)))
        return 200, {"ok": True}

    lane._post = post
    runs = []
    def runner(argv, **kwargs):
        runs.append(json.loads(kwargs["input"]))
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            "drives": [{"device_id": NODE, "drives": [DRIVE]}],
            "helper": [{"device_id": NODE, "helper": MISSING},
                       {"device_id": OTHER, "helper": READY}]}))
    source = make_source(runner)
    assert lane.start_helper_ready_reporting(source, {HELPER_READY_SWITCH: "1"}) is not None
    reporter = MeshDriveReporter(post=post, source=source, may_report=lambda: allowed["value"])
    assert reporter.tick() == 1
    assert sent == [(HELPER_READY_PATH, {"device_id": NODE, "helper": MISSING}),
                    (DRIVES_PATH, {"device_id": NODE, "drives": [DRIVE]})]
    assert len(runs) == 1 and runs[0]["device_ids"] == [NODE]  # One round, one sign-in.
    # A paused executor reads no PC, so it reports no readiness either.
    allowed["value"] = False
    assert reporter.tick() == 0
    assert len(runs) == 1 and len(sent) == 2


ENTRY_ENV = {"ORACLE_MESH_PASSWORD_FILE": "fixture-password-path",
             "ORACLE_MESH_CHANNEL_SECRET_FILE": "fixture-channel-path",
             "ORACLE_MESH_MESHCTRL_JS": "fixture-meshctrl.js",
             "ORACLE_MESH_LOGIN_USER": "synthetic",
             "ORACLE_MESH_CHAT_ORIGIN": "https://chat.example.test",
             "ORACLE_MESH_QUEUE_ORIGIN": "http://127.0.0.1:8797"}


def run_entry(lane, env):
    import kagent.local_agent_mesh_drive_inventory as inventory
    import kagent.local_agent_oracle_mesh_executor as entry

    class Stop(Exception):
        pass

    lane.load_pending.return_value = False
    lane.run_once.side_effect = Stop
    with patch.object(entry, "deployment_secret_password_provider", return_value=Mock()), \
         patch.object(entry, "_read_secret_file", return_value="synthetic-channel-secret"), \
         patch.object(entry, "make_oracle_mesh_executor", return_value=lane), \
         patch.object(inventory, "MeshDriveInventorySource") as source:
        with pytest.raises(Stop):
            entry.main(env)
    return source


@pytest.mark.parametrize("extra", [{}, {HELPER_READY_SWITCH: "0"}, {HELPER_READY_SWITCH: ""}])
def test_production_entrypoint_without_the_switch_starts_exactly_as_before(extra):
    # An executor object that has never heard of this feature still starts: the
    # entrypoint asks for the new method only when the deployment turned it on.
    lane = Mock(spec=["load_pending", "run_once", "start_drive_reporting",
                      "start_channel_watchdog", "last_round"])
    source = run_entry(lane, {**ENTRY_ENV, **extra})
    lane.start_drive_reporting.assert_called_once_with(source.return_value)
    source.return_value.observe_helper_ready.assert_not_called()


def test_production_entrypoint_offers_the_drive_source_and_environment_to_the_switch():
    lane = Mock()
    env = {**ENTRY_ENV, HELPER_READY_SWITCH: "1"}
    source = run_entry(lane, env)
    offered_source, offered_env = lane.start_helper_ready_reporting.call_args.args
    assert offered_source is source.return_value
    assert offered_env[HELPER_READY_SWITCH] == "1"
    # The same object then starts the drive round it rides on.
    lane.start_drive_reporting.assert_called_once_with(source.return_value)
    names = [call[0] for call in lane.method_calls]
    assert names.index("start_helper_ready_reporting") < names.index("start_drive_reporting")


def test_private_file_read_fallback_posts_when_the_console_round_is_silent():
    from kagent.local_agent_mesh_helper_ready import HelperStatusReadFallback

    digest = "9f2acb5916c0" + "a" * 52
    raw = json.dumps({"status": "installed", "sha256": digest,
                      "version": "0.3.0-rc2", "user": "private-account"}).encode("utf-8")

    class Port:
        def read_bytes(self, *, node_ref, file_path, timeout_seconds, max_bytes=None):
            assert file_path.endswith("helper-status.json")
            assert timeout_seconds > 0
            return raw

    sent = []

    def post(path, payload):
        sent.append((path, payload))
        return 200, {"ok": True}

    fallback = HelperStatusReadFallback(post=post, read_port=Port())
    assert fallback.observe([], [NODE]) == 1
    assert sent[0][0] == HELPER_READY_PATH
    state = sent[0][1]["helper"]
    assert state["helper_version"] == "0.3.0-rc2"
    assert state["helper_build"] == digest[:12]
    assert "user" not in state and "private-account" not in repr(state)
    assert fallback.observe([], [NODE]) == 1
    assert len(sent) == 2


def test_file_fallback_uses_the_bare_node_reference_without_truncating_at_sign():
    from kagent.local_agent_mesh_helper_ready import HelperStatusReadFallback

    digest = "9f2acb5916c0" + "a" * 52
    raw = json.dumps({"status": "installed", "sha256": digest,
                      "version": "0.3.0-rc2"}).encode("utf-8")

    class Port:
        def read_bytes(self, *, node_ref, file_path, timeout_seconds, max_bytes=None):
            assert node_ref == "synthetic@opaque"
            return raw

    sent = []

    def post(path, payload):
        sent.append((path, payload))
        return 200, {"ok": True}

    fallback = HelperStatusReadFallback(post=post, read_port=Port())
    target = "node//synthetic@opaque"
    assert fallback.observe([], [target]) == 1
    assert sent[0][1]["device_id"] == target
    assert sent[0][1]["helper"]["helper_build"] == digest[:12]


@pytest.mark.parametrize("probe_ok", [True, False])
def test_file_fallback_observes_updater_hash_and_tasks_without_console(probe_ok, capsys):
    import hashlib
    from kagent.local_agent_mesh_helper_ready import (
        HELPER_STATUS_READ_PATH, _UPDATER_SOURCE_READ_PATH, _UPDATER_TASK_READ_PATH,
        _WATCHER_TASK_READ_PATH,
    )
    raw = json.dumps({"status": "installed", "sha256": "a" * 64,
                      "version": "0.3.0-rc2"}).encode()
    source = b"PRIVATE-FIXTURE-SOURCE"
    task = b"PRIVATE-FIXTURE-TASK"
    files = {HELPER_STATUS_READ_PATH: raw, _UPDATER_SOURCE_READ_PATH: source,
             _UPDATER_TASK_READ_PATH: task, _WATCHER_TASK_READ_PATH: task}

    def read_bytes(*, node_ref, file_path, max_bytes, timeout_seconds):
        assert node_ref == NODE.rsplit("/", 1)[-1]
        assert file_path in files and timeout_seconds == 15
        assert max_bytes <= 131072
        if file_path != HELPER_STATUS_READ_PATH and not probe_ok:
            raise PermissionError("PRIVATE-FIXTURE-ERROR")
        return files[file_path]

    port = Mock(read_bytes=Mock(side_effect=read_bytes))
    post = Mock(return_value=(200, {"ok": True}))
    fallback = HelperStatusReadFallback(post=post, read_port=port)
    assert fallback.observe([], [NODE]) == 1
    state = post.call_args.args[1]["helper"]
    assert validate_helper_ready(state) == state
    if probe_ok:
        assert state["updater_source_present"] is True
        assert state["updater_source_sha256"] == hashlib.sha256(source).hexdigest()
        assert state["updater_task_present"] is True
        assert state["self_heal_task_present"] is True
    else:
        assert not any(k in state for k in ("updater_source_present", "updater_source_sha256",
                                            "updater_task_present", "self_heal_task_present"))
    assert port.read_bytes.call_count == 4
    assert "PRIVATE-FIXTURE" not in repr(state)
    assert "PRIVATE-FIXTURE" not in capsys.readouterr().out


@needs_node
def test_bridge_production_key_set_preserves_absence_of_optional_fields():
    completed = run_bridge({
        "device_ids": ["pc-1"], "helper_source": AGENT_HELPER_READY_JS,
        "helper_protocol": HELPER_READY_PROTOCOL,
        "helper_keys": sorted(HELPER_READY_KEYS | HELPER_READY_OPTIONAL_KEYS)})
    assert completed.returncode == 0, completed.stderr
    state = json.loads(completed.stdout)["helper"][0]["helper"]
    assert validate_helper_ready(state) == state
    assert state["helper_status_present"] is False
    assert "auto_update" not in state and "update_result" not in state


def test_three_pcs_missing_file_legacy_record_and_current_record_each_report(capsys):
    from kagent.local_agent_meshcentral_private_reader import MeshCentralReadRefused

    missing, legacy, current = ("node//private-missing", "node//private-legacy",
                                "node//private-current")
    digest = "a" * 64
    def read_bytes(*, node_ref, **kwargs):
        if node_ref.endswith("missing"):
            raise MeshCentralReadRefused("the official meshcentral client wrote no staged read")
        record = {"status": "installed", "sha256": digest, "user": "PRIVATE-USER"}
        if node_ref.endswith("current"):
            record.update(version="1.2.3", auto_update=True, update_result="current")
        return json.dumps(record).encode()

    port = Mock(read_bytes=Mock(side_effect=read_bytes))
    sent = []
    def post(path, payload):
        assert path == HELPER_READY_PATH
        sent.append(payload)
        return 200, {"ok": True}

    fallback = HelperStatusReadFallback(post=post, read_port=port)
    # Formerly an invalid console observation suppressed the file fallback.
    invalid = [{"device_id": legacy, "helper": {**READY, "update_result": None}}]
    for _ in range(2):
        assert fallback.observe(invalid, [missing, legacy, current]) == 3
    assert len(sent) == 6
    records = {row["device_id"]: row["helper"] for row in sent}
    assert records[missing] == dict.fromkeys(HELPER_READY_KEYS)
    assert records[legacy]["helper_sha256"] == digest
    # #8359 F7: a valid console round's watcher fact survives the file read.
    console = [{"device_id": current, "helper": {**READY, "self_heal_task_present": False}}]
    assert fallback.observe(console, [current]) == 1
    assert sent[-1]["helper"]["self_heal_task_present"] is False
    assert sent[-1]["helper"]["helper_version"] == "1.2.3"
    sent.clear()
    assert records[legacy]["helper_status_present"] is True
    assert "helper_version" not in records[legacy]
    assert records[current]["helper_version"] == "1.2.3"
    assert records[current]["update_result"] == "current"
    assert records[current]["auto_update"] is True
    assert "PRIVATE-USER" not in repr(sent)
    logs = capsys.readouterr().out
    assert "reason=no_staged_read" in logs
    assert "reason=version_unknown report=accepted status=200" in logs
    assert logs.count("reports=3 report_failed=0") == 2
    for value in (missing, legacy, current, digest, "PRIVATE-USER"):
        assert value not in logs


@pytest.mark.parametrize("raw,reason", [
    (b"broken", "invalid_json"),
    (b'{"status":"not_installed"}', "not_installed_record"),
    (b'{"status":"installed","sha256":"secret"}', "invalid_digest"),
])
def test_read_success_with_incomplete_file_reports_only_proven_facts(raw, reason, capsys):
    port = Mock(read_bytes=Mock(return_value=raw))
    post = Mock(return_value=(200, {"ok": True}))
    fallback = HelperStatusReadFallback(post=post, read_port=port)
    assert fallback.observe([], [NODE]) == 1
    state = post.call_args.args[1]["helper"]
    assert state["helper_status_present"] is True
    assert state["helper_build"] is None
    assert reason in capsys.readouterr().out


def test_console_missing_file_is_a_report_not_an_installation_request(capsys):
    port = Mock()
    post = Mock(return_value=(200, {"ok": True}))
    fallback = HelperStatusReadFallback(post=post, read_port=port)
    state = {**MISSING, "helper_status_present": False}
    assert fallback.observe([{"device_id": NODE, "helper": state}], [NODE]) == 1
    port.read_bytes.assert_not_called()
    assert post.call_args.args[1]["helper"] == state
    assert "reason=file_missing report=accepted status=200" in capsys.readouterr().out


def test_server_refusal_is_logged_and_retried_without_echoing_response(capsys):
    port = Mock(read_bytes=Mock(return_value=b"broken"))
    post = Mock(side_effect=[(403, {"error": "PRIVATE-SECRET"}), (200, {"ok": True})])
    fallback = HelperStatusReadFallback(post=post, read_port=port)
    assert fallback.observe([], [NODE]) == 0
    assert fallback.observe([], [NODE]) == 1
    logs = capsys.readouterr().out
    assert "report=rejected status=403" in logs
    assert "report=accepted status=200" in logs
    assert NODE not in logs and "PRIVATE-SECRET" not in logs


def test_bridge_failure_still_offers_targets_for_independent_read():
    source = make_source(lambda argv, **kw: SimpleNamespace(returncode=1, stdout=""))
    observer = Mock()
    source.observe_helper_ready(observer, source="x", protocol="p", keys=["pipe_open"])
    assert source(["pc-1"]) == []
    observer.assert_called_once_with([], ["pc-1"])


@pytest.mark.parametrize("failure,reason", [
    (PermissionError("PRIVATE-PATH"), "permission_denied"),
    (TimeoutError("PRIVATE-PATH"), "timeout"),
])
def test_read_failure_reports_unknown_and_logs_only_bounded_reason(failure, reason, capsys):
    port = Mock(read_bytes=Mock(side_effect=failure))
    post = Mock(return_value=(200, {"ok": True}))
    fallback = HelperStatusReadFallback(post=post, read_port=port)
    assert fallback.observe([], [NODE]) == 1
    assert post.call_args.args[1]["helper"] == dict.fromkeys(HELPER_READY_KEYS)
    log = capsys.readouterr().out
    assert f"read=unavailable reason={reason} report=accepted status=200" in log
    assert "PRIVATE-PATH" not in log and NODE not in log


def test_new_file_release_never_inherits_incompatible_console_release_fields():
    state = {**READY, "helper_status_present": True,
             "update_result": "registration_failed",
             "update_registration_error": "updater_running"}
    raw = json.dumps({"status": "installed", "sha256": "a" * 64,
                      "version": "1.2.3", "update_result": "current"}).encode()
    post = Mock(return_value=(200, {"ok": True}))
    fallback = HelperStatusReadFallback(post=post, read_port=Mock(
        read_bytes=Mock(return_value=raw)))
    assert fallback.observe([{"device_id": NODE, "helper": state}], [NODE]) == 1
    seen = post.call_args.args[1]["helper"]
    assert seen["update_result"] == "current"
    assert "update_registration_error" not in seen
    assert seen["pipe_open"] is True
    assert seen["helper_sha256"] == "a" * 64
