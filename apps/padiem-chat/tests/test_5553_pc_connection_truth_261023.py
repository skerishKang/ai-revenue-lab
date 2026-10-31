"""#5553 — a server-confirmed execution target is not a disconnected PC.

The owner saw "컴퓨터 미연결" in the web surface while the Mesh execution path
was working. The directory marks that PC `executable` (a Mesh target with no
observed Broker heartbeat), which is not an online state and never becomes
one here. It also must not read as "no computer connected", because the server
already granted execution to it.

These contracts run the shipped module in node, so the classification itself
is exercised rather than only its source text.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"

STATE_JS = (STATIC / "claw-connection-state.js").read_text(encoding="utf-8")
COMPOSER_JS = (STATIC / "claw-composer-connection-status.js").read_text(encoding="utf-8")

NODE_HARNESS = r"""
const fs = require("node:fs");
const source = fs.readFileSync(0, "utf8");
const dispatched = [];
globalThis.window = {
  addEventListener() {},
  dispatchEvent(event) { dispatched.push(event); return true; },
};
globalThis.document = { readyState: "complete" };
globalThis.CustomEvent = class {
  constructor(type, options) { this.type = type; this.detail = options && options.detail; }
};
eval(source);
const shared = window.PadiemComputerConnectionState;
const device = (over) => Object.assign({
  deviceId: "pc-1", deviceName: "COM1", platform: "windows",
  state: "OFFLINE", online: false, revoked: false, expired: false,
  executable: false, selectable: false,
}, over);
const snapshot = (devices) => ({
  readCompleted: true, statusCode: "ok", available: true, devices,
});
const answer = (snapshotValue) => shared.classify(snapshotValue);
const meshOnly = snapshot([device({ executable: true, state: "ACTION_REQUIRED" })]);
const result = {
  online: answer(snapshot([device({ state: "CONNECTED", online: true })])),
  executableOnly: answer(snapshot([device({ executable: true, state: "ACTION_REQUIRED" })])),
  meshRowOffline: answer(snapshot([device({ executable: true, state: "OFFLINE" })])),
  offline: answer(snapshot([device({})])),
  revokedOnly: answer(snapshot([device({ revoked: true, state: "REVOKED" })])),
  empty: answer(snapshot([])),
  readFailed: answer(Object.assign(snapshot([]), { statusCode: "readFailed" })),
  unread: answer({ readCompleted: false, devices: [] }),
  savedExecutable: answer(Object.assign(
    snapshot([device({ executable: true, state: "OFFLINE" })]),
    { savedTargetId: "pc-1" },
  )),
  savedOnline: answer(Object.assign(
    snapshot([device({ state: "CONNECTED", online: true })]),
    { savedTargetId: "pc-1" },
  )),
};
window.PadiemClawDeviceDirectory = meshOnly;
result.detail = shared.current();
process.stdout.write(JSON.stringify(result));
"""


def _run_harness() -> dict:
    outcome = subprocess.run(
        ["node", "-e", NODE_HARNESS],
        input=STATE_JS,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert outcome.returncode == 0, outcome.stderr
    return json.loads(outcome.stdout)


def test_an_execution_target_is_unconfirmed_not_disconnected():
    result = _run_harness()
    assert result["executableOnly"] == "unavailable"
    assert result["meshRowOffline"] == "unavailable"
    assert result["savedExecutable"] == "unavailable"
    # The same directory without the execution grant is a real "not connected".
    assert result["offline"] == "disconnected"


def test_only_a_server_confirmed_online_row_reads_as_connected():
    result = _run_harness()
    assert result["online"] == "connected"
    assert result["savedOnline"] == "connected"
    assert result["readFailed"] == "unavailable"
    assert result["unread"] == "connecting"
    assert result["revokedOnly"] == "unavailable"
    assert result["empty"] == "disconnected"
    # The execution grant never turns into an online claim.
    assert result["detail"]["state"] != "connected"
    assert result["detail"]["executableReady"] is True


def test_the_composer_names_the_unconfirmed_online_state():
    assert '"상태 확인 불가"' in COMPOSER_JS
    assert "executableHint" in COMPOSER_JS
    assert "executableReady" in COMPOSER_JS
    # The control still never paints connected from the execution grant.
    assert 'if (next === "connected") return vocabStatus("connected", t.connected);' in COMPOSER_JS


def test_the_shared_state_still_has_one_reader_and_no_fetch():
    assert "fetch(" not in STATE_JS
    assert "/api/" not in STATE_JS
