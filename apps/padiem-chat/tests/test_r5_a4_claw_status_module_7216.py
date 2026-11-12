"""#7216 R5 A4 (claw-status) — Claw 상태·대기·재시도 모듈 계약 (24함수).

app.js의 Claw 상태·대기·재시도 구역 24개 함수가 chat-claw-status-module.js로
이동했고, app.js는 19개 한 줄 전달 함수와 clawStatusModule() 팩토리 호출만
유지한다. 5개 내부 전용 함수는 모듈 안에만 있다.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
MODULE = (STATIC / "chat-claw-status-module.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")

NAMES = (
    "syncComposerForClaw",
    "setClawStatus",
    "setClawAreaState",
    "setClawButtonsBusy",
    "clawRetryRemaining",
    "clawVisibleExecutePayload",
    "clawExecuteWireKey",
    "clawCurrentDispatchIsUncertain",
    "noteClawContentEdited",
    "clawRetryAfterFromResponse",
    "isAmbiguousClawFailure",
    "clearClawRecovery",
    "renderClawRetryBox",
    "beginClawRetryCooldown",
    "showClawAmbiguousRecoveryHint",
    "applyClawWaitStageCopy",
    "renderClawWait",
    "beginClawWait",
    "clearClawWait",
)

INTERNAL_NAMES = (
    "parseClawRetryAfter",
    "stopClawRetryTimer",
    "clawWaitElapsedSeconds",
    "clawWaitStageFor",
    "clawWaitStageKey",
)

EXPECTED_GETTERS = {
    "input",
    "shell",
    "clawStatus",
    "clawResultArea",
    "clawGenerateBtn",
    "clawExecuteButton",
    "clawChannel",
    "clawAction",
    "clawSender",
    "clawRetryBox",
    "clawRetryCopy",
    "clawRetryButton",
    "clawRetryHint",
    "clawWait",
    "clawWorkspace",
    "clawInFlight",
    "clawRetrySeconds",
    "clawRetryTimer",
    "clawUncertainKeys",
    "clawLastDispatchKey",
    "clawWaitStartedAt",
    "clawWaitTimer",
    "clawWaitRevealed",
    "clawWaitAnnouncedStage",
    "clawT",
    "localeOr",
    "selectedProductTier",
    "conversationState",
}

EXPECTED_SETTERS = {
    "clawInFlight",
    "clawRetrySeconds",
    "clawRetryTimer",
    "clawWaitStartedAt",
    "clawWaitTimer",
    "clawWaitRevealed",
    "clawWaitAnnouncedStage",
}

MOVED_MARKERS = (
    "window.PadiemChatClawStatusModule = {",
    "deps.clawUncertainKeys.has(clawExecuteWireKey(clawVisibleExecutePayload()))",
    "deps.clawRetryTimer = setInterval(",
    "deps.clawWaitTimer = setInterval(",
    'clawRetryHint.dataset.localeKey = "claw-error-check-runs"',
    "return deps.clawWaitAnnouncedStage > 0;",
)


def test_index_loads_claw_status_module_before_app() -> None:
    assert INDEX.count("./chat-claw-status-module.js") == 1
    assert INDEX.index("./chat-claw-status-module.js") < INDEX.index("./app.js")


def test_app_keeps_one_line_forwarders_for_every_moved_function() -> None:
    for name in NAMES:
        line = f"function {name}(...a) {{ return clawStatusModule().{name}(...a); }}"
        assert line in APP, name
        assert APP.count(f"function {name}(") == 1, name
    assert "function clawStatusModule() {" in APP
    assert "window.PadiemChatClawStatusModule.create({" in APP


def test_moved_bodies_live_only_in_the_module_and_module_stays_under_500_lines() -> None:
    for marker in MOVED_MARKERS:
        assert marker in MODULE, marker
        assert marker not in APP, marker
    for name in NAMES:
        assert MODULE.count(f"function {name}(") == 1, name
    for name in INTERNAL_NAMES:
        assert MODULE.count(f"function {name}(") == 1, name
        assert f"function {name}(" not in APP, name
    assert len(MODULE.splitlines()) <= 500


def test_deps_getters_and_setters_match_exact_closure_surface() -> None:
    start = APP.index("window.PadiemChatClawStatusModule.create({")
    block = APP[start:APP.index("});", start)]
    gets = set(re.findall(r"get (\w+)\(\)", block))
    sets = set(re.findall(r"set (\w+)\(value\)", block))
    assert gets == EXPECTED_GETTERS
    assert sets == EXPECTED_SETTERS


def test_all_nineteen_functions_execute_in_node_vm_with_strict_live_deps() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed in this runner")

    script = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const staticDir = process.argv[1];
const strictSrc = fs.readFileSync(path.join(staticDir, "..", "tests", "_r5_strict_deps.js"), "utf8");
const modSrc = fs.readFileSync(path.join(staticDir, "chat-claw-status-module.js"), "utf8");

const el = () => ({
  hidden: false,
  textContent: "",
  value: "",
  disabled: false,
  dataset: {},
  attrs: {},
  classList: { toggle() {}, remove() {} },
  setAttribute(name, value) { this.attrs[name] = String(value); },
  removeAttribute(name) { delete this.attrs[name]; },
});

const input = el(); input.value = "hello";
const shell = el();
const clawWorkspace = el(); clawWorkspace.dataset.view = "manual";
const clawStatus = el();
const clawResultArea = el();
const clawGenerateBtn = el();
const clawExecuteButton = el();
const clawChannel = el(); clawChannel.value = "sms";
const clawAction = el(); clawAction.value = "quote";
const clawSender = el(); clawSender.value = "sender";
const clawRetryBox = el();
const clawRetryCopy = el();
const clawRetryButton = el();
const clawRetryHint = el();
const clawWait = el();

let clawInFlight = false;
let clawRetrySeconds = 0;
let clawRetryTimer = null;
let clawWaitStartedAt = 0;
let clawWaitTimer = null;
let clawWaitRevealed = false;
let clawWaitAnnouncedStage = 0;
const clawUncertainKeys = new Set();
let clawLastDispatchKey = null;

const intervals = new Map();
let nextTimer = 1;
const setIntervalFn = (fn, ms) => { const id = nextTimer++; intervals.set(id, { fn, ms }); return id; };
const clearIntervalFn = (id) => { intervals.delete(id); };
const tick = () => { for (const { fn } of [...intervals.values()]) fn(); };

const ctx = vm.createContext({
  window: {},
  document: { documentElement: { lang: "ko" } },
  setInterval: setIntervalFn,
  clearInterval: clearIntervalFn,
});
vm.runInContext(strictSrc, ctx);
vm.runInContext(modSrc, ctx);

const deps = ctx.r5StrictDeps({
  input, shell, clawStatus, clawResultArea, clawGenerateBtn, clawExecuteButton,
  clawChannel, clawAction, clawSender, clawRetryBox, clawRetryCopy, clawRetryButton,
  clawRetryHint, clawWait, clawWorkspace,
  get clawInFlight() { return clawInFlight; },
  set clawInFlight(v) { clawInFlight = v; },
  get clawRetrySeconds() { return clawRetrySeconds; },
  set clawRetrySeconds(v) { clawRetrySeconds = v; },
  get clawRetryTimer() { return clawRetryTimer; },
  set clawRetryTimer(v) { clawRetryTimer = v; },
  clawUncertainKeys,
  get clawLastDispatchKey() { return clawLastDispatchKey; },
  get clawWaitStartedAt() { return clawWaitStartedAt; },
  set clawWaitStartedAt(v) { clawWaitStartedAt = v; },
  get clawWaitTimer() { return clawWaitTimer; },
  set clawWaitTimer(v) { clawWaitTimer = v; },
  get clawWaitRevealed() { return clawWaitRevealed; },
  set clawWaitRevealed(v) { clawWaitRevealed = v; },
  get clawWaitAnnouncedStage() { return clawWaitAnnouncedStage; },
  set clawWaitAnnouncedStage(v) { clawWaitAnnouncedStage = v; },
  clawT: (key, vars) => vars ? key + ":" + vars.seconds : key,
  localeOr: (key, fallback) => fallback || key,
  selectedProductTier: () => "pro",
  conversationState: { getConversationId: () => "conv_a4" },
}, "a4");

const mod = ctx.window.PadiemChatClawStatusModule.create(deps);
const empty = ctx.window.PadiemChatClawStatusModule.create(ctx.r5StrictDeps({}, "empty"));
assert.ok(empty);

mod.syncComposerForClaw(true);
assert.equal(shell.dataset.clawTier, "pro");
assert.equal(input.placeholder, "Paste a business request you received by chat, SMS, or email.");
assert.equal(input.attrs["aria-describedby"], "clawStatus");
mod.syncComposerForClaw(false);
assert.equal(shell.dataset.clawTier, "pro");
assert.equal(input.placeholder, "Ask anything");

mod.setClawStatus("running", "running", "run-key");
assert.equal(clawStatus.hidden, false);
assert.equal(clawStatus.textContent, "running");
assert.equal(clawStatus.dataset.state, "running");
assert.equal(clawStatus.dataset.localeKey, "run-key");
mod.setClawStatus("", null, null);
assert.equal(clawStatus.hidden, true);
assert.equal(input.attrs["aria-invalid"], undefined);

mod.setClawAreaState("ready");
assert.equal(clawResultArea.dataset.clawState, "ready");

mod.setClawButtonsBusy(true);
assert.equal(clawInFlight, true);
assert.equal(clawGenerateBtn.disabled, true);
assert.equal(clawExecuteButton.disabled, true);
mod.setClawButtonsBusy(false);
assert.equal(clawInFlight, false);
assert.equal(clawExecuteButton.disabled, false);

const payload = mod.clawVisibleExecutePayload();
assert.deepEqual(JSON.parse(JSON.stringify(payload)), {
  content: "hello",
  channel: "sms",
  action: "quote",
  sender_hint: "sender",
  tier: "pro",
  conversation_id: "conv_a4",
});
const wireKey = mod.clawExecuteWireKey(payload);
assert.equal(typeof wireKey, "string");
assert.equal(mod.clawRetryRemaining(), 0);

clawUncertainKeys.add(wireKey);
assert.equal(mod.clawCurrentDispatchIsUncertain(), true);
mod.noteClawContentEdited();
clawUncertainKeys.clear();
assert.equal(mod.clawCurrentDispatchIsUncertain(), false);

assert.equal(mod.clawRetryAfterFromResponse({ headers: { get: () => "5" } }), 5);
assert.equal(mod.clawRetryAfterFromResponse({ headers: { get: () => "0" } }), null);
assert.equal(mod.clawRetryAfterFromResponse({ headers: { get: () => "Wed, 21 Oct 2015 07:28:00 GMT" } }), null);
assert.equal(mod.isAmbiguousClawFailure({}, { status: 502 }), true);
assert.equal(mod.isAmbiguousClawFailure({ error: { code: "engine_execution_failed" } }, { status: 400 }), true);
assert.equal(mod.isAmbiguousClawFailure({ error: { code: "bad_request" } }, { status: 400 }), false);

mod.renderClawRetryBox();
assert.equal(clawRetryCopy.textContent, "claw-retry-ready");
mod.beginClawRetryCooldown(2);
assert.equal(clawRetryBox.hidden, false);
assert.equal(clawRetryCopy.textContent, "claw-retry-waiting:2");
assert.equal(clawExecuteButton.disabled, true);
tick();
assert.equal(clawRetryCopy.textContent, "claw-retry-waiting:1");
tick();
assert.equal(clawRetrySeconds, 0);
assert.equal(clawRetryTimer, null);
assert.equal(clawRetryCopy.textContent, "claw-retry-ready");
assert.equal(clawExecuteButton.disabled, false);

clawLastDispatchKey = "dispatch-key";
mod.showClawAmbiguousRecoveryHint();
assert.equal(clawRetryHint.hidden, false);
assert.equal(clawRetryHint.textContent, "claw-error-check-runs");
assert.equal(clawUncertainKeys.has("dispatch-key"), true);
assert.equal(clawRetryBox.hidden, true);

mod.beginClawWait();
assert.equal(clawWaitStartedAt > 0, true);
assert.equal(clawWaitTimer !== null, true);
assert.equal(mod.renderClawWait(), false);
clawWaitStartedAt = Date.now() - 31000;
assert.equal(mod.renderClawWait(), true);
assert.equal(clawWait.hidden, false);
assert.equal(clawWaitAnnouncedStage, 2);
assert.equal(clawStatus.dataset.localeKey, "claw-wait-very-long");
mod.applyClawWaitStageCopy();
assert.equal(clawStatus.textContent, "claw-wait-very-long");
mod.clearClawWait();
assert.equal(clawWaitTimer, null);
assert.equal(clawWaitStartedAt, 0);
assert.equal(clawWait.hidden, true);

mod.beginClawRetryCooldown(1);
mod.clearClawRecovery({ syncControls: true });
assert.equal(clawRetryBox.hidden, true);
assert.equal(clawRetryCopy.textContent, "");
assert.equal(clawRetryButton.disabled, true);
assert.equal(clawRetryHint.hidden, true);
assert.equal(clawRetrySeconds, 0);
assert.equal(clawRetryTimer, null);

console.log("a4 claw-status module contract ok");
"""
    completed = subprocess.run(
        [node, "-e", script, str(STATIC)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
