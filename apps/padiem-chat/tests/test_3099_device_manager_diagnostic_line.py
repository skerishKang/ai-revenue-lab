"""#3099 the rendered PC diagnostic line in the computer panel.

These tests execute the real production-loaded device manager in Node against
a minimal DOM stub and read the text the user actually sees. The point is
the Korean wording itself: a wrong escape or a wrong phrase would leave the
user with a garbled instruction, so the rendered text is compared exactly.

The assertions are encoding-independent in the same way the reason contract
is: the file is loaded and executed as UTF-8, and the expected strings are
plain UTF-8 source literals.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "static" / "claw-device-manager.js"
HANDOFF = MODULE.with_name("claw-local-handoff.js")

_HARNESS = r"""
const directory = JSON.parse(process.env.CLAW_DM_PAYLOAD);
const handoff = require("node:fs").readFileSync(process.env.CLAW_DM_HANDOFF, "utf8");
// The projection the panel uses is the reviewed one.
global.window = globalThis;
global.addEventListener = () => {};
global.removeEventListener = () => {};
eval(handoff);

const element = (tag) => {
  const node = {
    tagName: tag.toUpperCase(), dataset: {}, textContent: "", hidden: false,
    value: "", type: "", id: "", className: "", handlers: {},
    children: [], attributes: {},
    setAttribute(name, value) { this.attributes[name] = value; },
    removeAttribute(name) { delete this.attributes[name]; },
    getAttribute(name) { return this.attributes[name] ?? null; },
    addEventListener(type, handler) { this.handlers[type] = handler; },
    removeEventListener(type) { delete this.handlers[type]; },
    append(...kids) { this.children.push(...kids); },
    appendChild(child) { this.children.push(child); return child; },
    prepend(...kids) { this.children.unshift(...kids); },
    replaceChildren(...kids) { this.children = kids; },
    insertBefore(child) { this.children.push(child); return child; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    closest() { return null; },
    contains() { return false; },
    focus() {},
    click() { if (this.handlers.click) this.handlers.click({preventDefault() {}}); },
    remove() {},
  };
  return node;
};

const shell = element("div");
const composer = element("form");
const composerParent = element("div");
composer.parentElement = composerParent;
const list = element("ul");
const status = element("p");
const mounted = [];

global.document = {
  readyState: "complete",
  documentElement: {lang: "ko", dataset: {}},
  hidden: false,
  querySelector(sel) {
    if (sel === ".app-shell") return shell;
    if (sel === "#composerForm") return composer;
    return null;
  },
  getElementById(id) {
    if (id === "composerForm") return composer;
    if (id === "clawDeviceManagerList") return list;
    if (id === "clawDeviceManagerStatus") return status;
    return null;
  },
  createElement(tag) { return element(tag); },
  addEventListener() {},
};
global.MutationObserver = class {
  observe() {} disconnect() {}
};
global.fetch = async (url) => {
  if (String(url).includes("/api/claw/local-access/devices")) {
    return {ok: true, status: 200, text: async () => JSON.stringify(directory)};
  }
  return {ok: true, status: 200, text: async () => JSON.stringify({})};
};
require("node:fs").readFileSync(process.env.CLAW_DM_MODULE, "utf8");
eval(require("node:fs").readFileSync(process.env.CLAW_DM_MODULE, "utf8"));
(async () => {
  // The panel reads when it is opened. Open it exactly like the surface does.
  const find = (node, predicate) => {
    if (!node) return null;
    if (predicate(node)) return node;
    for (const child of node.children || []) {
      const hit = find(child, predicate);
      if (hit) return hit;
    }
    return null;
  };
  const toggle = find(composerParent, (n) => n.id === "clawDeviceManagerToggle");
  if (!toggle) {
    console.log(JSON.stringify({lines: [], status: "no toggle", found: false}));
    return;
  }
  toggle.click();
  for (let i = 0; i < 80; i += 1) {
    const list = find(composerParent, (n) => n.id === "clawDeviceManagerList");
    if (list && list.children.length) break;
    await new Promise((r) => setTimeout(r, 25));
  }
  await new Promise((r) => setTimeout(r, 50));
  const lines = [];
  const walk = (node) => {
    if (!node) return;
    if (node.className === "claw-device-manager-diagnostic") {
      lines.push(node.textContent);
    }
    for (const child of node.children || []) walk(child);
  };
  walk(composerParent);
  console.log(JSON.stringify({lines, status: status.textContent, found: true}));
})();
"""


def panel(payload: dict) -> dict:
    harness = Path(__file__).with_name("_claw_device_manager_harness.js")
    harness.write_text(_HARNESS, encoding="utf-8")
    env = dict(os.environ)
    env["CLAW_DM_PAYLOAD"] = json.dumps(payload, ensure_ascii=False)
    env["CLAW_DM_MODULE"] = str(MODULE)
    env["CLAW_DM_HANDOFF"] = str(HANDOFF)
    result = subprocess.run(
        ["node", str(harness)], capture_output=True, check=True, env=env,
    )
    harness.unlink(missing_ok=True)
    stdout = result.stdout.decode("utf-8")
    return json.loads(stdout.strip().splitlines()[-1])


def directory(devices: list[dict]) -> dict:
    return {"ok": True, "available": True, "ownerScoped": True, "devices": devices}


def test_the_panel_shows_the_problem_and_the_fix():
    result = panel(directory([{
        "deviceId": "device-1", "state": "OFFLINE", "usable": False,
        "diagnostic": {
            "status": "reported",
            "checks": {
                "agent_source": "not_installed", "autostart": "disabled",
                "resident": "stopped",
            },
            "fixes": {
                "agent_source": "install_agent", "autostart": "enable_autostart",
                "resident": "start_connector",
            },
        },
    }]))
    assert len(result["lines"]) == 1
    line = result["lines"][0]
    assert "설치된 에이전트 파일을 찾을 수 없습니다" in line
    assert "설치 프로그램으로 에이전트를 다시 설치해 주세요" in line
    assert "Windows 자동 시작이 꺼져 있습니다" in line
    assert "Windows 자동 시작을 켜 주세요" in line
    assert "상주 실행기가 실행 중지 상태입니다" in line
    assert "커넥터를 다시 실행해 주세요" in line


def test_a_stale_diagnostic_says_it_cannot_be_confirmed():
    result = panel(directory([{
        "deviceId": "device-1", "state": "OFFLINE", "usable": False,
        "diagnostic": {"status": "stale", "checks": {}, "fixes": {}},
    }]))
    assert len(result["lines"]) == 1
    assert "진단 정보를 확인할 수 없습니다" in result["lines"][0]
    assert "최신 정보가 없습니다" in result["lines"][0]


def test_a_device_that_never_reported_says_it_cannot_be_confirmed():
    result = panel(directory([{
        "deviceId": "device-1", "state": "OFFLINE", "usable": False,
        "diagnostic": {"status": "unavailable", "checks": {}, "fixes": {}},
    }]))
    assert len(result["lines"]) == 1
    assert "진단 정보를 확인할 수 없습니다" in result["lines"][0]
    assert "아직 정보를 보내지 않았습니다" in result["lines"][0]


def test_a_healthy_pc_shows_no_diagnostic_line():
    result = panel(directory([{
        "deviceId": "device-1", "state": "CONNECTED", "usable": True,
        "diagnostic": {
            "status": "reported",
            "checks": {
                "agent_source": "ready", "autostart": "enabled", "resident": "running",
            },
            "fixes": {},
        },
    }]))
    assert result["lines"] == []
