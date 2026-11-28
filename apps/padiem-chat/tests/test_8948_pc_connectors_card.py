"""#8948 — Connectors PC card follows the chip's signed-in pairing truth.

Run the shipped browser JS in a no-network Node DOM harness. No account,
connector or PC mutation is performed.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
HOME = APP / "static" / "claw-home-choices.js"


def _run(mode: str) -> dict:
    node = shutil.which("node")
    assert node, "Node.js is required for browser module contracts"
    script = r"""
const fs = require("fs");
const vm = require("vm");
const handlers = {};
global.window = globalThis;
window.addEventListener = (name, callback) => (handlers[name] ??= []).push(callback);
window.dispatchEvent = (event) => { for(const listener of handlers[event.type] || []) listener(event); };
const element = (props = {}) => ({
  dataset:{}, hidden:false, textContent:"", listeners:{}, ...props,
  addEventListener(event, fn) { (this.listeners[event] ??= []).push(fn); },
  querySelector() { return null; }, getClientRects() { return [{}]; },
  setAttribute() {}, getAttribute() {return null;}, click() {},
});
const shell = element({dataset:{state:"connectors"}});
const opener = element();
const dialog = element();
const view = element({hidden:false});
const staticLine = element({hidden:false});
const card = element({dataset:{connectorStatus:"preparing"}});
card.querySelector = name => name === ".capability-read" ? staticLine : null;
const cardText = element({textContent:"확인 중…",hidden:true});
const nodes = {
 connectorsNavButton:opener, connectorsDialog:dialog,
 connectorsView:view, connectorComputerCard:card,
 clawComputerLiveStatus:cardText,
};
global.document = {
 readyState:"complete", documentElement:{lang:"ko"},
 querySelector: name => name === ".app-shell" ? shell : null,
 getElementById: name => nodes[name] || null,
};
const nativeTimeout = global.setTimeout;
let expired = null;
global.setTimeout = (fn,ms,...args) => {
 if (ms === 13000) {expired=fn; return 894800;}
 return nativeTimeout(fn,ms,...args);
};
global.clearTimeout = id => { if(id===894800) {expired=null;return;} };
const pair = {read:"ok",state:"connected"};
window.PadiemPcConnectFlow = { current:()=>({...pair}), read:()=>new Promise(()=>{}) };
window.PadiemComputerConnectionState = {
 current:()=>({state:"connecting"}),requestRead:()=>true,
};
window.PadiemConnectorVocabulary = { status: s => ({
 connected:"● 연결됨", checking:"확인 중…",
 failed:"확인 실패 · 다시 시도", disconnected:"○ 연결 안 됨",
})[s] || s };
let observe;
global.MutationObserver = class { constructor(fn){observe=fn;} observe(){} };
vm.runInThisContext(fs.readFileSync(HOME, "utf8"),{filename:"claw-home-choices.js"});
if (MODE === "connected") {
 window.dispatchEvent({type:"padiem:pc-pairing-state",detail:{read:"ok",state:"connected"}});
 window.dispatchEvent({type:"padiem:computer-connection",detail:{state:"connecting"}});
} else {
 pair.read="idle";pair.state="connecting";
 observe(); // The Connectors view opened.
 if(typeof expired !== "function")throw new Error("missing PC card deadline");
 expired();
 window.dispatchEvent({type:"padiem:computer-connection",detail:{state:"connecting"}});
}
console.log(JSON.stringify({
 state:card.dataset.connectorStatus,text:cardText.textContent,
 hidden:cardText.hidden,staticHidden:staticLine.hidden
}));
"""
    script = "const HOME=" + json.dumps(str(HOME)) + ";const MODE=" + json.dumps(mode) + ";\n" + script
    result = subprocess.run(
        [node, "-e", script], check=True, capture_output=True, text=True,
        encoding="utf-8", timeout=15,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_connected_pairing_stays_connected_when_directory_is_still_checking() -> None:
    result = _run("connected")
    assert result == {
        "state": "connected", "text": "● 연결됨",
        "hidden": False, "staticHidden": True,
    }


def test_pc_status_timeout_never_stays_at_checking() -> None:
    result = _run("timeout")
    assert result == {
        "state": "unavailable", "text": "확인 실패 · 다시 시도",
        "hidden": False, "staticHidden": True,
    }
