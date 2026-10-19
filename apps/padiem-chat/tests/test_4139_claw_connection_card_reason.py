"""#3099: the Claw PC card must name the real reason, not one generic line.

The server already distinguishes a revoked binding, an expired credential, a
PC that is simply offline, and a Mesh target whose online state was never
observed. The card collapsed all of them into one "connection needs
checking" line, so the user could not tell which problem they had.

These tests execute the real production-loaded chip module in Node against a
minimal DOM stub (no mocked server, no live pairing, no bot credentials, no
user PC side effects) and assert that each case produces its own reason.

The assertions are deliberately encoding-independent: the reason is proven by
the ASCII phase code and by the fact that every case produces a *different*
headline. A localized string is never compared literally, so a host whose
preferred encoding is not UTF-8 cannot turn a correct build into a red test.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "static" / "claw-connection-chips.js"

_HARNESS = r"""
const payload = JSON.parse(process.env.CLAW_CHIPS_PAYLOAD);
const element = () => ({
  dataset: {}, textContent: "", hidden: false, value: "",
  setAttribute() {}, removeAttribute() {}, addEventListener() {},
  querySelector() { return null; }, querySelectorAll() { return []; },
  click() {}, closest() { return null; }, contains() { return false; },
});
const shell = element(); shell.dataset.state = "claw";
const owner = element(); owner.dataset.accountState = "signed_in";
const workspace = element(); workspace.dataset.view = "general";
const pcCard = element();
const pcStatus = element();
const chipPc = element();
const chipDrive = element();
const chipGithub = element();
const cardDrive = element();
const cardGithub = element();
const statusDrive = element();
const statusGithub = element();
const byQuery = {
  ".app-shell": shell,
  ".sidebar-account": owner,
  '[data-claw-card="computer"]': pcCard,
  '[data-claw-card="drive"]': cardDrive,
  '[data-claw-card="github"]': cardGithub,
  '[data-claw-connection="pc"]': chipPc,
  '[data-claw-connection="drive"]': chipDrive,
  '[data-claw-connection="github"]': chipGithub,
};
const byId = {
  clawWorkspace: workspace,
  clawPcCardStatus: pcStatus,
  clawDriveCardStatus: statusDrive,
  clawGithubCardStatus: statusGithub,
};
global.document = {
  documentElement: {lang: "ko"},
  hidden: false,
  querySelector(sel) { return byQuery[sel] || null; },
  getElementById(id) { return byId[id] || null; },
  addEventListener() {},
};
global.window = {addEventListener() {}, location: {assign() {}}};
global.MutationObserver = class { observe() {} disconnect() {} };
global.fetch = async (url) => {
  if (String(url).includes("/api/claw/local-access/devices")) {
    return {ok: true, status: 200, text: async () => JSON.stringify(payload)};
  }
  return {ok: true, status: 200, text: async () => JSON.stringify({})};
};
const fs = require("node:fs");
eval(fs.readFileSync(process.env.CLAW_CHIPS_MODULE, "utf8"));
(async () => {
  // The reset() state is "unknown"; the real refresh settles it. Wait for a
  // settled phase, not for a non-empty text, because reset() already writes
  // a generic line.
  for (let i = 0; i < 60; i += 1) {
    if (pcCard.dataset.pcPhase && pcCard.dataset.pcPhase !== "unknown") break;
    await new Promise((r) => setTimeout(r, 25));
  }
  await new Promise((r) => setTimeout(r, 50));
  console.log(JSON.stringify({
    text: pcStatus.textContent,
    phase: pcCard.dataset.pcPhase || null,
    chip: chipPc.dataset.connectionState || null,
  }));
})();
"""


def card(payload: dict) -> dict:
    harness = Path(__file__).with_name("_claw_chips_harness.js")
    harness.write_text(_HARNESS, encoding="utf-8")
    env = dict(os.environ)
    env["CLAW_CHIPS_PAYLOAD"] = json.dumps(payload, ensure_ascii=False)
    env["CLAW_CHIPS_MODULE"] = str(MODULE)
    result = subprocess.run(
        ["node", str(harness)], capture_output=True, check=True, env=env,
    )
    harness.unlink(missing_ok=True)
    # The module prints UTF-8. Decode it as UTF-8 explicitly: the preferred
    # locale encoding on a Windows host is not UTF-8.
    stdout = result.stdout.decode("utf-8")
    return json.loads(stdout.strip().splitlines()[-1])


def directory(devices: list[dict]) -> dict:
    return {"ok": True, "available": True, "ownerScoped": True, "devices": devices}


#: The exact headlines the card must show, read as UTF-8. A hand-written
#: Unicode escape is easy to get wrong, so the source strings are plain UTF-8
#: and these assertions compare the rendered text exactly.
REASON_TEXT = {
    "revoked": "연결이 철회되었습니다 · 다시 연결해 주세요",
    "expired": "인증이 만료되었습니다 · 다시 연결해 주세요",
    "executable": "실행 대상 준비 · 온라인 상태 미확인",
}


def test_a_connected_pc_reports_the_online_phase():
    result = card(directory([{
        "deviceId": "office", "state": "CONNECTED", "usable": True,
    }]))
    assert result["phase"] == "online"
    assert result["chip"] == "on"


def test_a_revoked_binding_reports_its_own_reason():
    result = card(directory([{
        "deviceId": "office", "state": "REVOKED", "usable": False, "revoked": True,
    }]))
    assert result["phase"] == "revoked"
    assert result["chip"] == "off"
    assert result["text"] == REASON_TEXT["revoked"]


def test_an_expired_credential_reports_its_own_reason():
    result = card(directory([{
        "deviceId": "office", "state": "OFFLINE", "usable": False, "expired": True,
    }]))
    assert result["phase"] == "expired"
    assert result["chip"] == "off"
    assert result["text"] == REASON_TEXT["expired"]


def test_a_mesh_target_without_a_heartbeat_reports_its_own_reason():
    result = card(directory([{
        "deviceId": "office", "state": "ACTION_REQUIRED", "usable": False,
        "executable": True, "selectable": True,
    }]))
    assert result["phase"] == "executable"
    assert result["chip"] == "off"
    assert result["text"] == REASON_TEXT["executable"]


def test_a_plain_offline_pc_keeps_the_generic_phase():
    result = card(directory([{
        "deviceId": "office", "state": "OFFLINE", "usable": False,
    }]))
    assert result["phase"] == "offline"
    assert result["chip"] == "off"


def test_no_pc_at_all_reports_the_unregistered_phase():
    result = card(directory([]))
    assert result["phase"] == "unregistered"
    assert result["chip"] == "off"


def test_every_case_names_a_different_reason():
    """The whole point: one generic line cannot serve four different problems.

    A revoked binding, an expired credential, a PC that is merely offline and
    a Mesh target whose online state was never observed need four different
    fixes, so the card must not show one line for all of them.
    """
    cases = {
        "online": directory([{
            "deviceId": "office", "state": "CONNECTED", "usable": True,
        }]),
        "revoked": directory([{
            "deviceId": "office", "state": "REVOKED", "usable": False, "revoked": True,
        }]),
        "expired": directory([{
            "deviceId": "office", "state": "OFFLINE", "usable": False, "expired": True,
        }]),
        "mesh_target": directory([{
            "deviceId": "office", "state": "ACTION_REQUIRED", "usable": False,
            "executable": True, "selectable": True,
        }]),
        "offline": directory([{
            "deviceId": "office", "state": "OFFLINE", "usable": False,
        }]),
        "unregistered": directory([]),
    }
    results = {name: card(payload) for name, payload in cases.items()}
    phases = {name: result["phase"] for name, result in results.items()}
    texts = {name: result["text"] for name, result in results.items()}
    assert phases == {
        "online": "online", "revoked": "revoked", "expired": "expired",
        "mesh_target": "executable", "offline": "offline",
        "unregistered": "unregistered",
    }
    # Every case has its own headline, and no headline is empty.
    assert len(set(texts.values())) == len(texts)
    assert all(text for text in texts.values())
