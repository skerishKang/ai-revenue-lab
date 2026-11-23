"""#7216 R5 A4 (claw-status) — Claw 상태·대기·재시도 모듈 계약 (24함수).

app.js의 Claw 상태·대기·재시도 구역 24개 함수가 chat-claw-status-module.js로
이동했다. B7 14차+15차: 19개 전부 등록부(app.provide("clawStatus")) 경유로
연결되고 app.js에는 같은 이름 정의가 없다. 5개 내부 전용 함수는 모듈 안에만 있다.
"""
from __future__ import annotations

# #8060: shipped reads live in _support; assertions stay here.
from _support.final_share_source import locale_source, read

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from _r5_b6_wiring import context_names, create_receives_app_context

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = read(STATIC / "app.js")
MODULE = read(STATIC / "chat-claw-status-module.js")
INDEX = read(STATIC / "index.html")

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

# B7 14차+15차: all 19 one-line forwarders are gone — every name is reached
# through the registry (app.provide("clawStatus")) and app.js keeps no
# same-name definitions.
REGISTRY_NAMES = NAMES

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
    "clawExecuteButton",
    "clawChannel",
    "clawAction",
    "clawSender",
    "clawRetryBox",
    "clawRetryButton",
    "clawRetryHint",
    "clawWorkspace",
    "clawInFlight",
    "clawLastDispatchKey",
    "clawWaitStartedAt",
    "clawT",
    "localeOr",
    "selectedProductTier",
    "conversationState",
}

EXPECTED_SETTERS = {
    "clawInFlight",
    "clawWaitStartedAt",
}

MOVED_MARKERS = (
    "window.PadiemChatClawStatusModule = {",
    "clawUncertainKeys.has(clawExecuteWireKey(clawVisibleExecutePayload()))",
    "clawRetryTimer = setInterval(",
    "clawWaitTimer = setInterval(",
    'clawRetryHint.dataset.localeKey = "claw-error-check-runs"',
    "return clawWaitAnnouncedStage > 0;",
    'const clawGenerateBtn = document.getElementById("clawGenerateBtn");',
    'const clawRetryCopy = document.getElementById("clawRetryCopy");',
    'const clawWait = document.getElementById("clawWait");',
    "const clawUncertainKeys = new Set();",
    "let clawRetrySeconds = 0;",
    "let clawWaitTimer = null;",
)


def test_index_loads_claw_status_module_before_app() -> None:
    assert INDEX.count("./chat-claw-status-module.js") == 1
    assert INDEX.index("./chat-claw-status-module.js") < INDEX.index("./app.js")


def test_registry_chunk_lives_through_the_registry_and_forwarders_stay() -> None:
    """이동 본문은 모듈에만 살고 app.js는 등록부 경유로 연결한다(이중 소유 금지).

    실행 검사는 "어디에 살아 있는지"를 대신하지 못한다. 같은 본문이 양쪽에
    생기면 어느 쪽이 실제로 도는지 알 수 없으므로 구조 계약으로 유지한다.
    B7 14차+15차: 19개 전부 등록부(app.provide("clawStatus")) 경유로 대체됐다 —
    app.js에 같은 이름 정의가 없고 등록된 조각에 이름이 있다.
    """
    assert (
        'app.provide("clawStatus",' in APP
        and "function clawStatusModule() {" in APP
        and "window.PadiemChatClawStatusModule.create(Object.setPrototypeOf({" in APP
    )
    # the module-side single-definition check for all 19 names is owned by
    # test_moved_bodies_live_only_in_the_module_and_module_stays_under_500_lines
    assert all(
        f"function {name}(" not in APP for name in REGISTRY_NAMES
    ), "registry names must have no app.js definition"


def test_claw_status_registry_chunk_is_reachable_through_the_registry() -> None:
    """B7 보강: 등록부(app.provide("clawStatus"))로 같은 이름을 찾을 수 있다.

    app.js 전달 함수가 없어도 소비자(app.js 호출자·clawRun deps getter·공유
    접근자)는 등록된 조각의 같은 이름 API에 도달한다. 실제 모듈 본문을 node vm에서
    문맥에 등록해 19개 이름이 전부 함수로 조회되는지 본다(동작 단언은
    node vm 하네스와 브라우저 하네스가 직접 호출로 증명한다).
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed in this runner")

    script = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const staticDir = process.argv[1];
const byId = new Map();
const fakeEl = () => ({
  hidden: true, textContent: "", children: [], dataset: {},
  classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
  addEventListener() {}, removeEventListener() {},
  setAttribute() {}, getAttribute() { return null; },
  appendChild(c) { this.children.push(c); return c; }, removeChild() {},
});
const sandbox = {
  document: {
    getElementById: (id) => { if (!byId.has(id)) byId.set(id, fakeEl()); return byId.get(id); },
    querySelectorAll: () => [], querySelector: () => null,
    addEventListener() {}, removeEventListener() {},
    createElement: (tag) => ({ tag, textContent: "", className: "", dataset: {}, appendChild() {}, setAttribute() {} }),
  },
  fetch: () => new Promise(() => {}),
  console: { error() {} },
  setTimeout,
};
sandbox.window = { ...sandbox };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(staticDir + "/chat-app-context.js", "utf8"), sandbox,
  { filename: "chat-app-context.js" });
vm.runInContext(fs.readFileSync(staticDir + "/chat-claw-status-module.js", "utf8"), sandbox,
  { filename: "chat-claw-status-module.js" });
const names = __NAMES_JSON__;
const result = vm.runInContext(`
  const app = window.PadiemChatAppContext.create({});
  app.provide("clawStatus", window.PadiemChatClawStatusModule.create(Object.setPrototypeOf({}, app)));
  const out = {};
  for (const n of __NAMES_JSON__) out[n] = typeof app[n];
  out;
`, sandbox, { filename: "registry-lookup" });
for (const n of names) {
  assert.equal(result[n], "function", n + " must be reachable through the registry");
}
console.log("REGISTRY_OK");
"""
    completed = subprocess.run(
        [node, "-e", script.replace("__NAMES_JSON__", json.dumps(list(REGISTRY_NAMES))), str(STATIC)],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


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
    block = create_receives_app_context(APP, "window.PadiemChatClawStatusModule")
    gets = set(re.findall(r"get (\w+)\(\)", block))
    sets = set(re.findall(r"set (\w+)\(value\)", block))
    assert gets <= EXPECTED_GETTERS
    assert gets | (EXPECTED_GETTERS & context_names(APP)) == EXPECTED_GETTERS
    assert sets <= EXPECTED_SETTERS
    assert sets | (EXPECTED_SETTERS & context_names(APP)) == EXPECTED_SETTERS


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

const registry = new Map();
const reg = (id, elm) => { registry.set(id, elm); return elm; };

const input = el(); input.value = "hello";
const shell = el();
const clawWorkspace = el(); clawWorkspace.dataset.view = "manual";
const clawStatus = el();
const clawResultArea = el();
const clawGenerateBtn = reg("clawGenerateBtn", el());
const clawExecuteButton = el();
const clawChannel = el(); clawChannel.value = "sms";
const clawAction = el(); clawAction.value = "quote";
const clawSender = el(); clawSender.value = "sender";
const clawRetryBox = el();
const clawRetryCopy = reg("clawRetryCopy", el());
const clawRetryButton = el();
const clawRetryHint = el();
const clawWait = reg("clawWait", el());

let clawInFlight = false;
let clawWaitStartedAt = 0;
let clawLastDispatchKey = null;

const intervals = new Map();
let nextTimer = 1;
const setIntervalFn = (fn, ms) => { const id = nextTimer++; intervals.set(id, { fn, ms }); return id; };
const clearIntervalFn = (id) => { intervals.delete(id); };
const tick = () => { for (const { fn } of [...intervals.values()]) fn(); };

const ctx = vm.createContext({
  window: {},
  document: {
    documentElement: { lang: "ko" },
    getElementById: (id) => registry.get(id) || null,
  },
  setInterval: setIntervalFn,
  clearInterval: clearIntervalFn,
});
vm.runInContext(strictSrc, ctx);
vm.runInContext(modSrc, ctx);

const deps = ctx.r5StrictDeps({
  input, shell, clawStatus, clawResultArea, clawExecuteButton,
  clawChannel, clawAction, clawSender, clawRetryBox, clawRetryButton,
  clawRetryHint, clawWorkspace,
  get clawInFlight() { return clawInFlight; },
  set clawInFlight(v) { clawInFlight = v; },
  get clawLastDispatchKey() { return clawLastDispatchKey; },
  get clawWaitStartedAt() { return clawWaitStartedAt; },
  set clawWaitStartedAt(v) { clawWaitStartedAt = v; },
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

// R5 2부 B2: the uncertainty set is module-internal. Its only production
// writer is the ambiguous-hint path, driven by the shared dispatch-key dep.
// Use a distinct request identity so a latched key never blocks the cooldown
// scenarios below.
input.value = "uncertain-only";
const uncertainKey = mod.clawExecuteWireKey(mod.clawVisibleExecutePayload());
assert.equal(mod.clawCurrentDispatchIsUncertain(), false);
clawLastDispatchKey = uncertainKey;
mod.showClawAmbiguousRecoveryHint();
assert.equal(mod.clawCurrentDispatchIsUncertain(), true);
mod.noteClawContentEdited();
assert.equal(mod.clawCurrentDispatchIsUncertain(), true); // one edit does not clear the latch
input.value = "edited-request";
assert.equal(mod.clawCurrentDispatchIsUncertain(), false); // a different request is unblocked
input.value = "hello";

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
assert.equal(mod.clawRetryRemaining(), 0);
tick(); // a cleared ticker cannot change the settled copy
assert.equal(clawRetryCopy.textContent, "claw-retry-ready");
assert.equal(clawExecuteButton.disabled, false);

clawLastDispatchKey = "dispatch-key";
mod.showClawAmbiguousRecoveryHint();
assert.equal(clawRetryHint.hidden, false);
assert.equal(clawRetryHint.textContent, "claw-error-check-runs");
assert.equal(clawRetryHint.dataset.localeKey, "claw-error-check-runs");
assert.equal(clawRetryBox.hidden, true);

mod.beginClawWait();
assert.equal(clawWaitStartedAt > 0, true);
assert.equal(mod.renderClawWait(), false);
clawWaitStartedAt = Date.now() - 31000;
tick(); // the module registered the interval: a tick renders from state
assert.equal(clawWait.hidden, false);
assert.equal(mod.renderClawWait(), true);
assert.equal(clawStatus.dataset.localeKey, "claw-wait-very-long");
mod.applyClawWaitStageCopy();
assert.equal(clawStatus.textContent, "claw-wait-very-long");
assert.equal(clawWait.textContent.length > 0, true);
mod.clearClawWait();
tick(); // teardown left no ticker: a tick cannot resurrect the wait
assert.equal(clawWaitStartedAt, 0);
assert.equal(clawWait.hidden, true);
assert.equal(clawWait.textContent, "");

mod.beginClawRetryCooldown(1);
mod.clearClawRecovery({ syncControls: true });
assert.equal(clawRetryBox.hidden, true);
assert.equal(clawRetryCopy.textContent, "");
assert.equal(clawRetryButton.disabled, true);
assert.equal(clawRetryHint.hidden, true);
assert.equal(mod.clawRetryRemaining(), 0);
tick();
assert.equal(clawRetryCopy.textContent, "");

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
