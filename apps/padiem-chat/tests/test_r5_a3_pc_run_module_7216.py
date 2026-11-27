"""#7216 R5 A3 (pc-run) — PC 실행 대기·복구 모듈 계약 (7함수).

app.js의 PC 실행 대기·복구 구역 7개 함수(showPcRuntimeStatus,
waitForAcceptedPcRun, pcWaitElapsed, findUnfinishedPcRun,
resumeUnfinishedPcRun, renderStoredPcAnswer, recoverStoredPcResult)가
chat-pc-run-module.js로 이동했고, app.js는 같은 이름의 한 줄 전달 함수와
pcRunModule() 팩토리 호출만 유지한다.
"""
from __future__ import annotations

# #8060: shipped reads live in _support; assertions stay here.
from _support.r5_pcrun_auth_source import app_js, claw_status_module_js, index_html, pc_run_module_js, strict_deps_js

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from _r5_b6_wiring import context_names, create_receives_app_context

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = app_js()
MODULE = pc_run_module_js()
INDEX = index_html()

NAMES = (
    "showPcRuntimeStatus",
    "waitForAcceptedPcRun",
    "pcWaitElapsed",
    "findUnfinishedPcRun",
    "resumeUnfinishedPcRun",
    "renderStoredPcAnswer",
    "recoverStoredPcResult",
)

ASYNC_NAMES = {
    "waitForAcceptedPcRun",
    "findUnfinishedPcRun",
    "resumeUnfinishedPcRun",
    "recoverStoredPcResult",
}

EXPECTED_GETTERS = {
    "MESSAGE_LIFECYCLE",
    "authState",
    "conversationProduct",
    "conversationState",
    "findUnfinishedPcRun",
    "idleNote",
    "loadRecentConversations",
    "openSavedConversation",
    "pcWaitElapsed",
    "renderStoredPcAnswer",
    "renderStreamError",
    "setNote",
    "showPcRuntimeStatus",
    "uiT",
}

MOVED_MARKERS = (
    "window.PadiemChatPcRunModule = {",
    '"/api/claw/runs/" + encodeURIComponent(runId) + "/pending-result"',
    'result.answer_source !== "pc_command_result"',
    "pcResultRecovery.recoverOnce({",
    "pcResultRecovery.waitForResult({",
    "const resolvedPcRuns = new Set();",
    'const pcResultRecovery = window.PadiemChatPcRecovery?.create?.({',
)


def test_index_loads_pc_run_module_before_app() -> None:
    assert INDEX.count("./chat-pc-run-module.js") == 1
    assert INDEX.index("./chat-pc-run-module.js") < INDEX.index("./app.js")


def test_app_registers_pc_run_and_has_no_forwarders() -> None:
    assert 'app.provide("pcRun", window.PadiemChatPcRunModule.create(Object.setPrototypeOf({' in APP
    for name in NAMES:
        assert f"function {name}(" not in APP, name
        assert f"{name}," in MODULE, name
    assert "function pcRunModule() {" in APP
    assert "window.PadiemChatPcRunModule.create(Object.setPrototypeOf({" in APP


def test_pc_run_apis_are_reachable_through_the_registry() -> None:
    """B7 보강: 등록부(app.provide("pcRun"))로 7개 이름을 조회한다.

    app.js 전달 함수가 없어도 호출자(복구 절편·deps getter)는 등록된 조각의
    같은 이름 API에 도달한다.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed in this runner")

    script = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const staticDir = process.argv[1];
const fakeEl = () => ({
  hidden: true, textContent: "", dataset: {}, children: [],
  classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
  addEventListener() {}, removeEventListener() {},
  setAttribute() {}, getAttribute() { return null; },
  appendChild(c) { this.children.push(c); return c; }, removeChild() {},
});
const byId = new Map();
const sandbox = {
  document: {
    documentElement: { lang: "ko" },
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
vm.runInContext(fs.readFileSync(staticDir + "/chat-pc-run-module.js", "utf8"), sandbox,
  { filename: "chat-pc-run-module.js" });
const names = %s;
const result = vm.runInContext(`
  const app = window.PadiemChatAppContext.create({});
  app.provide("pcRun", window.PadiemChatPcRunModule.create(app));
  const out = {};
  for (const n of ${JSON.stringify(names)}) out[n] = typeof app[n];
  out;
`, sandbox, { filename: "registry-lookup" });
for (const n of names) {
  assert.equal(result[n], "function", n + " must be reachable through the registry");
}
console.log("REGISTRY_OK");
"""
    completed = subprocess.run(
        [node, "-e", script.replace("%s", json.dumps(list(NAMES))), str(STATIC)],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "REGISTRY_OK" in completed.stdout


def test_moved_bodies_live_only_in_the_module_and_module_stays_under_500_lines() -> None:
    for marker in MOVED_MARKERS:
        assert marker in MODULE, marker
        assert marker not in APP, marker
    for name in NAMES:
        assert MODULE.count(f"function {name}(") == 1, name
    assert len(MODULE.splitlines()) <= 500


def test_deps_getters_and_setters_match_exact_closure_surface() -> None:
    block = create_receives_app_context(APP, "window.PadiemChatPcRunModule")
    gets = set(re.findall(r"get (\w+)\(\)", block))
    sets = set(re.findall(r"set (\w+)\(value\)", block))
    assert gets <= EXPECTED_GETTERS
    assert 'app.provide("entry", window.PadiemChatEntryModule.create(app))' in APP
    assert gets | (EXPECTED_GETTERS & (context_names(APP) | {"openSavedConversation"})) == EXPECTED_GETTERS
    assert sets == set()


def test_all_seven_functions_execute_in_node_vm_with_strict_live_deps() -> None:
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
const modSrc = fs.readFileSync(path.join(staticDir, "chat-pc-run-module.js"), "utf8");

const runtimeLabels = [];
const taskHints = [];
const lifecycleTransitions = [];
const committed = [];
const notes = [];
const reopened = [];
const streamErrors = [];
let recentReloads = 0;
let pollResponses = [];
let runsList = [];

const ctx = vm.createContext({
  fetch: async (url) => {
    if (url === "/api/claw/runs") {
      return { ok: true, json: async () => ({ ok: true, runs: runsList }) };
    }
    const next = pollResponses.shift();
    if (!next) return { ok: false, json: async () => ({}) };
    return { ok: true, json: async () => ({ result: next }) };
  },
  document: {
    documentElement: { lang: "ko" },
    createElement: (tag) => ({ tag, textContent: "" }),
  },
  window: {
    fetch: () => { throw new Error("no fetch in this scenario"); },
    setTimeout: (fn) => { fn(); return 1; },
    PadiemClawRunEventProjection: {
      label: (kind, lang) => kind === "unknown" ? "" : `${lang}:${kind}`,
    },
    PadiemChatPcScopeNotice: { render: () => {} },
    PadiemChatPcRecovery: {
      validRunId: (id) => typeof id === "string" && id.startsWith("chat_pcq_"),
      // R5 2부 B2: the recovery object is created inside the module's create()
      // from this stub, so the recovery scenarios drive the same fake.
      create: () => ({
        recoverOnce: async () => recoverOnceResult,
        waitForResult: async (opts) => {
          if (typeof opts.onPending === "function") opts.onPending();
          return waitForResultOutcome;
        },
      }),
    },
    PadiemChatLifecycle: {
      applyRuntimeLabel: (_a, text, mode) => runtimeLabels.push({ text, mode }),
      setTaskHint: (_a, hint) => taskHints.push(hint),
      releasePreparingRuntimeLabel: () => runtimeLabels.push({ text: "__released__", mode: "prep" }),
      elapsedClockText: (ms) => `${Math.floor(ms / 1000)}s`,
    },
  },
  PadiemChatLifecycle: {
    set: (_a, state) => lifecycleTransitions.push(state),
  },
  Date: {
    parse: (v) => Date.parse(v),
    now: () => Date.parse("2026-11-12T00:01:30Z"),
  },
  Math, Number, Array, Promise, Proxy, Reflect, encodeURIComponent,
});

vm.runInContext(strictSrc + "\n" + modSrc, ctx, { filename: "chat-pc-run-module.js" });

// 1. create() must not read any property on deps at creation time.
const emptyStrict = ctx.r5StrictDeps({}, "emptyCreateDeps");
const createdFromEmpty = ctx.window.PadiemChatPcRunModule.create(emptyStrict);
assert.equal(typeof createdFromEmpty.waitForAcceptedPcRun, "function");

// 2. Live getter state changed after create() is observed by all 7 functions.
let liveAuth = { authenticated: false, user: null };
let liveProduct = "chat";
let recoverOnceResult = { kind: "duplicate" };
let waitForResultOutcome = { kind: "completed", conversationId: "conv_resume" };
let mod = null;

const deps = ctx.r5StrictDeps({
  get MESSAGE_LIFECYCLE() { return { STREAMING: "streaming", COMPLETED: "completed", FAILED: "failed" }; },
  get authState() { return liveAuth; },
  get conversationProduct() { return liveProduct; },
  get conversationState() {
    return {
      getConversationId: (prod) => prod === "claw" ? "conv_claw" : "conv_chat",
      setProduct: () => {},
      setConversationId: () => {},
      commitAssistant: (_msgs, ans) => committed.push(ans),
    };
  },
  get findUnfinishedPcRun() { return (...a) => mod.findUnfinishedPcRun(...a); },
  get idleNote() { return () => "idle-note"; },
  get loadRecentConversations() { return () => { recentReloads += 1; }; },
  get openSavedConversation() { return async (id) => { reopened.push(id); }; },
  get pcWaitElapsed() { return (...a) => mod.pcWaitElapsed(...a); },
  get renderStoredPcAnswer() { return (...a) => mod.renderStoredPcAnswer(...a); },
  get renderStreamError() { return (...a) => streamErrors.push(a); },
  get setNote() { return (t, s) => notes.push({ t, s }); },
  get showPcRuntimeStatus() { return (...a) => mod.showPcRuntimeStatus(...a); },
  get uiT() { return (k, vars) => vars ? `${k}:${JSON.stringify(vars)}` : k; },
}, "liveDeps");

mod = ctx.window.PadiemChatPcRunModule.create(deps);

// Mutate closure variables AFTER create() before invoking methods.
liveAuth = { authenticated: true, user: { id: "usr_live" } };
liveProduct = "claw";

const makeArticle = () => {
  const children = [];
  return {
    isConnected: true,
    children,
    querySelector: (sel) => sel === ".assistant-content" ? {
      replaceChildren: () => { children.length = 0; },
      appendChild: (el) => { children.push(el); },
    } : null,
    scrollIntoView: () => {},
  };
};

(async () => {
  const art = makeArticle();

  // (a) showPcRuntimeStatus
  assert.equal(mod.showPcRuntimeStatus(art, "unknown"), false);
  assert.equal(mod.showPcRuntimeStatus(art, "tool_started"), true);
  assert.equal(runtimeLabels.at(-1).text, "ko:tool_started");

  // (b) pcWaitElapsed
  assert.equal(mod.pcWaitElapsed("not-a-date"), null);
  assert.equal(mod.pcWaitElapsed("2026-11-12T00:00:00Z"), "90s");

  // (c) findUnfinishedPcRun + resumeUnfinishedPcRun
  const rId = "chat_pcq_" + "1".repeat(32);
  runsList = [{
    run_id: rId,
    status: "running",
    created_at: "2026-11-12T00:01:00Z",
    session: { conversation_id: "conv_resume" },
  }];
  const found = await mod.findUnfinishedPcRun("conv_resume");
  assert.equal(found.run_id, rId);
  await mod.resumeUnfinishedPcRun("conv_resume");
  // R5 2부 B2: the resolved-run set is module-internal — the dedup is proven
  // behaviorally (a second resume for the same conversation is a no-op).
  await mod.resumeUnfinishedPcRun("conv_resume");
  assert.deepEqual(reopened, ["conv_resume"]);
  assert.equal(notes.at(-1).t, "idle-note");

  // (d) waitForAcceptedPcRun: running -> completed pc_command_result
  pollResponses = [
    { run_id: "r_poll", conversation_id: "conv_claw", status: "running" },
    {
      run_id: "r_poll",
      conversation_id: "conv_claw",
      status: "completed",
      answer: "PC 파일 목록입니다.",
      answer_source: "pc_command_result",
    },
  ];
  await mod.waitForAcceptedPcRun(art, { run_id: "r_poll", conversation_id: "conv_claw" }, [], { aborted: false }, "claw");
  // Behavioral dedup: the second wait for the same resolved run is a no-op.
  await mod.waitForAcceptedPcRun(art, { run_id: "r_poll", conversation_id: "conv_claw" }, [], { aborted: false }, "claw");
  assert.equal(art.children[0].textContent, "PC 파일 목록입니다.");
  assert.equal(committed.at(-1), "PC 파일 목록입니다.");
  assert.equal(recentReloads, 1);
  // #4485: a completed durable run releases the preparing chip.
  assert.ok(runtimeLabels.some((r) => r.text === "__released__"), "release on durable run completion");

  // (e) renderStoredPcAnswer + recoverStoredPcResult
  runtimeLabels.length = 0;
  recoverOnceResult = { kind: "completed", answer: "복구된 PC 응답", conversationId: "conv_claw" };
  const art2 = makeArticle();
  const ok = await mod.recoverStoredPcResult(
    art2,
    { pcRunId: "r_rec", conversationId: "conv_claw", product: "claw" },
    [],
    null,
    { aborted: false }
  );
  assert.equal(ok, true);
  // Behavioral dedup: a second recovery for the same stored run is refused.
  const okAgain = await mod.recoverStoredPcResult(
    art2,
    { pcRunId: "r_rec", conversationId: "conv_claw", product: "claw" },
    [],
    null,
    { aborted: false }
  );
  assert.equal(okAgain, false);
  assert.equal(art2.children[0].textContent, "복구된 PC 응답");
  // #4485: a recovered PC answer releases the preparing chip too.
  assert.ok(runtimeLabels.some((r) => r.text === "__released__"), "release on stored PC answer");
})().catch((err) => { console.error(err); process.exit(1); });
"""
    completed = subprocess.run(
        [node, "-e", script, str(STATIC)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
