"""#7216 R5 A6 (android-handoff) — 안드로이드 로그인 넘기기 모듈 계약.

app.js의 넘기기 9함수(시작·claim·poll·패널 렌더)와 제어 4개가
chat-android-handoff-module.js로 이동했고, app.js는 선언·sessionStorage
읽기/쓰기·resumeAndroidHandoff(R-06)만 유지한다. B7 20차: 9개 전달 함수는
등록부(app.provide("androidHandoff")) 경유로 대체됐다.
이 시험은 리스너와 함수를 직접 호출해 요청·상태 전환을 본다.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from _r5_b6_wiring import context_names, create_receives_app_context

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
MODULE = (STATIC / "chat-android-handoff-module.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")

NAMES = (
    "isAndroidWebView",
    "stopAndroidHandoffPolling",
    "clearAndroidHandoff",
    "androidHandoffPhaseKey",
    "renderAndroidHandoff",
    "claimAndroidHandoff",
    "pollAndroidHandoff",
    "startAndroidHandoffPolling",
    "startAndroidHandoff",
)

EXPECTED_GETTERS = {
    "androidHandoff", "androidHandoffTimer", "androidHandoffClaiming", "androidHandoffStarting",
    "androidHandoffPanel", "androidHandoffCode", "androidHandoffNote", "androidHandoffOpen",
    "androidHandoffCopy", "androidHandoffCopied", "androidHandoffCancel", "androidHandoffError",
    "ANDROID_HANDOFF_POLL_MS", "storeAndroidHandoff", "setAuthFormError", "loadAuthStatus",
    "closeAuthDialog", "uiT", "authState",
}
EXPECTED_SETTERS = {
    "androidHandoff", "androidHandoffTimer", "androidHandoffClaiming", "androidHandoffStarting",
}

MOVED_MARKERS = (
    "window.PadiemChatAndroidHandoffModule = {",
    'fetch(`/auth/android/handoff/${encodeURIComponent(current.handoffId)}/claim`, {',
    'fetch(`/auth/android/handoff/${encodeURIComponent(current.handoffId)}`, {',
    'fetch("/auth/android/handoff", {',
    'if (document.visibilityState === "visible" && deps.androidHandoff) {',
    "navigator.clipboard.writeText(code)",
)


def test_index_loads_android_handoff_module_before_app() -> None:
    assert INDEX.count("./chat-android-handoff-module.js") == 1
    assert INDEX.index("./chat-android-handoff-module.js") < INDEX.index("./app.js")
    assert INDEX.index("./chat-claw-form-module.js") < INDEX.index(
        "./chat-android-handoff-module.js"
    )


def test_app_keeps_forwarders_factory_and_one_wire_call() -> None:
    # B7 20차: 9개 전부 등록부(app.provide("androidHandoff")) 경유로 대체됐다 —
    # app.js에 같은 이름 정의가 없고 등록된 조각에 이름이 있다.
    for name in NAMES:
        assert (f"function {name}(" not in APP
                and f"{name}," in MODULE
                and 'app.provide("androidHandoff",' in APP), name
    assert "function androidHandoffModule() {" in APP
    assert "window.PadiemChatAndroidHandoffModule.create(Object.setPrototypeOf({" in APP
    assert APP.count("androidHandoffModule().wireAndroidHandoffListeners();") == 1
    # Original registration position: after the Google entry listener block and
    # before the remaining auth-panel wiring. #7729 removed the password-form
    # listeners, so the next shipped auth wiring is the account module's
    # wireAccountControls() (B7 16차: renamed from wire() — localPcPanel owns
    # the registry name "wire").
    wire_at = APP.index("androidHandoffModule().wireAndroidHandoffListeners();")
    dialog = (STATIC / "chat-login-dialog-module.js").read_text(encoding="utf-8")
    assert 'window.location.assign("/auth/google/start");' in (APP + dialog)
    assert 'loginDialogModule().wireGoogleLogin();' in APP
    assert wire_at < APP.index("accountModule().wireAccountControls();")


def test_factory_is_declared_before_the_wire_call_and_before_resume() -> None:
    # A let/const factory must execute before any wire/forwarder call (TDZ).
    assert APP.index("let androidHandoffModuleInstance = null;") < APP.index(
        "androidHandoffModule().wireAndroidHandoffListeners();"
    )
    assert APP.index("let androidHandoffModuleInstance = null;") < APP.index(
        "function resumeAndroidHandoff()"
    )


def test_session_storage_access_stays_in_app_js() -> None:
    # R-06: the storage reader/writer and resumeAndroidHandoff stay in app.js.
    assert "function readStoredAndroidHandoff()" in APP
    assert "function storeAndroidHandoff()" in APP
    assert "function resumeAndroidHandoff()" in APP
    assert "sessionStorage." not in MODULE
    assert APP.count("sessionStorage.") == 5


def test_moved_bodies_live_only_in_the_module_and_module_stays_under_500_lines() -> None:
    for marker in MOVED_MARKERS:
        assert marker in MODULE, marker
        assert marker not in APP, marker
    for name in NAMES:
        assert MODULE.count(f"function {name}(") == 1, name
    assert len(MODULE.splitlines()) <= 500


def test_deps_getters_and_setters_match_the_exact_closure_surface() -> None:
    block = create_receives_app_context(APP, "window.PadiemChatAndroidHandoffModule")
    gets = set(re.findall(r"get (\w+)\(\)", block))
    sets = set(re.findall(r"set (\w+)\(value\)", block))
    assert gets <= EXPECTED_GETTERS
    assert gets | (EXPECTED_GETTERS & context_names(APP)) == EXPECTED_GETTERS
    assert sets <= EXPECTED_SETTERS
    assert sets | (EXPECTED_SETTERS & context_names(APP)) == EXPECTED_SETTERS


def test_start_poll_claim_and_controls_run_in_node_vm() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed in this runner")

    script = r"""
(async () => {
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const staticDir = process.argv[1];
const strictSrc = fs.readFileSync(path.join(staticDir, "..", "tests", "_r5_strict_deps.js"), "utf8");
const modSrc = fs.readFileSync(path.join(staticDir, "chat-android-handoff-module.js"), "utf8");

const el = () => ({
  hidden: false, textContent: "", disabled: false, dataset: {}, attrs: {},
  listeners: {},
  setAttribute(n, v) { this.attrs[n] = String(v); },
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
  fire(type, ev) { return Promise.all((this.listeners[type] || []).map((fn) => fn(ev))); },
});
const panel = el(), code = el(), note = el(), openBtn = el(), copyBtn = el(),
      copied = el(), cancelBtn = el(), errorBox = el();

let androidHandoff = null;
let androidHandoffTimer = null;
let androidHandoffClaiming = false;
let androidHandoffStarting = false;
let authState = { authenticated: false };
const notes = [];
const stores = [];
const intervals = [];
const redirects = [];
const clipboard = { ok: true, writes: [] };
let fetchQueue = [];
const fetchCalls = [];
const queue = (status, body) => fetchQueue.push({ status, body });
const fetchImpl = (url, opts) => {
  fetchCalls.push({ url: String(url), method: (opts && opts.method) || "GET", headers: (opts && opts.headers) || {} });
  const next = fetchQueue.length ? fetchQueue.shift() : { status: 500, body: {} };
  return Promise.resolve({
    ok: next.status >= 200 && next.status < 400,
    status: next.status,
    json: () => Promise.resolve(next.body),
  });
};
const windowObj = {
  location: { assign: (url) => redirects.push(url) },
  sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  isSecureContext: true,
  setInterval: (fn, ms) => { intervals.push({ fn, ms }); return intervals.length; },
  clearInterval: (id) => { notes.push(["cleared", id]); },
  getSelection: () => null,
};
const documentObj = {
  visibilityState: "visible",
  listeners: {},
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
  createRange: () => ({ selectNodeContents() {} }),
};

const ctx = vm.createContext({
  window: windowObj, document: documentObj,
  navigator: { userAgent: "Mozilla/5.0 (Linux; Android 14; wv) Chrome/120",
    clipboard: { writeText: (text) => { clipboard.writes.push(text); return Promise.resolve(); } } },
  fetch: fetchImpl, JSON, Promise, Array, String, Object, Number, Date, Error, console, encodeURIComponent,
  setTimeout,
});
vm.runInContext(strictSrc, ctx);
vm.runInContext(modSrc, ctx);

const mod = ctx.window.PadiemChatAndroidHandoffModule.create(ctx.r5StrictDeps({
  get androidHandoff() { return androidHandoff; },
  set androidHandoff(v) { androidHandoff = v; },
  get androidHandoffTimer() { return androidHandoffTimer; },
  set androidHandoffTimer(v) { androidHandoffTimer = v; },
  get androidHandoffClaiming() { return androidHandoffClaiming; },
  set androidHandoffClaiming(v) { androidHandoffClaiming = v; },
  get androidHandoffStarting() { return androidHandoffStarting; },
  set androidHandoffStarting(v) { androidHandoffStarting = v; },
  androidHandoffPanel: panel, androidHandoffCode: code, androidHandoffNote: note,
  androidHandoffOpen: openBtn, androidHandoffCopy: copyBtn, androidHandoffCopied: copied,
  androidHandoffCancel: cancelBtn, androidHandoffError: errorBox,
  ANDROID_HANDOFF_POLL_MS: 5000,
  storeAndroidHandoff: () => stores.push(androidHandoff ? { ...androidHandoff } : null),
  setAuthFormError: (box, message) => notes.push(["form-error", message || null]),
  loadAuthStatus: async () => { notes.push(["auth-status"]); },
  closeAuthDialog: () => notes.push(["dialog-closed"]),
  uiT: (key) => key,
  get authState() { return authState; },
}, "a6"));

// create() must not read deps; wiring registers the four controls once.
const empty = ctx.window.PadiemChatAndroidHandoffModule.create(ctx.r5StrictDeps({}, "empty"));
assert.equal(typeof empty.wireAndroidHandoffListeners, "function");
mod.wireAndroidHandoffListeners();
assert.equal((openBtn.listeners.click || []).length, 1);
assert.equal((copyBtn.listeners.click || []).length, 1);
assert.equal((cancelBtn.listeners.click || []).length, 1);
assert.equal((documentObj.listeners.visibilitychange || []).length, 1);
assert.equal(Object.keys(panel.listeners).length, 0);

// UA detection.
assert.equal(mod.isAndroidWebView(), true);
ctx.navigator.userAgent = "Mozilla/5.0 (Windows NT 10.0) Chrome/120";
assert.equal(mod.isAndroidWebView(), false);
ctx.navigator.userAgent = "Mozilla/5.0 (Linux; Android 14; wv) Chrome/120";

// Phase copy table.
assert.equal(mod.androidHandoffPhaseKey("waiting"), "auth-android-waiting");
assert.equal(mod.androidHandoffPhaseKey("claiming"), "auth-android-claiming");
assert.equal(mod.androidHandoffPhaseKey("nope"), "auth-android-code-help");

// start: POST, state, persist, render, poll, redirect.
queue(200, { handoff_id: "aho_" + "a".repeat(24), claim_secret: "s".repeat(20),
  user_code: "ABCD-2345", authorization_url: "https://accounts.example/start", expires_in: 600 });
await mod.startAndroidHandoff();
assert.equal(fetchCalls[0].url, "/auth/android/handoff");
assert.equal(fetchCalls[0].method, "POST");
assert.equal(androidHandoff.phase, "waiting");
assert.equal(code.textContent, "ABCD-2345");
assert.equal(panel.hidden, false);
assert.equal(intervals.length, 1);
assert.equal(intervals[0].ms, 5000);
assert.equal(redirects[0], "https://accounts.example/start");
assert.equal(stores.length >= 1, true);
assert.equal(androidHandoffStarting, false);

// open control re-opens the authorization URL.
openBtn.hidden = false;
await openBtn.fire("click", {});
assert.equal(redirects[1], "https://accounts.example/start");

// copy control writes the code and shows the copied note.
await copyBtn.fire("click", {});
assert.deepEqual(clipboard.writes, ["ABCD-2345"]);
assert.equal(copied.hidden, false);

// poll: ready -> claim POST; 200 + authenticated -> clear + close dialog.
authState = { authenticated: true };
queue(200, { status: "ready" });
queue(200, {});
await mod.pollAndroidHandoff();
assert.equal(fetchCalls[1].url, "/auth/android/handoff/aho_" + "a".repeat(24));
assert.equal(fetchCalls[2].method, "POST");
assert.equal(fetchCalls[2].headers["X-Padiem-Handoff-Secret"], "s".repeat(20));
assert.equal(androidHandoff, null);
assert.equal(panel.hidden, true);
assert.equal(notes.some((n) => n[0] === "dialog-closed"), true);

// poll 404 -> expired, polling stopped, persisted.
androidHandoff = { handoffId: "aho_" + "b".repeat(24), claimSecret: "t".repeat(20),
  userCode: "WXYZ-2345", authorizationUrl: "https://x/y", expiresAt: Date.now() + 60000, phase: "waiting" };
queue(404, {});
await mod.pollAndroidHandoff();
assert.equal(androidHandoff.phase, "error");
assert.equal(androidHandoffTimer, null);
assert.equal(stores[stores.length - 1].phase, "error");

// expiry in poll: no request, phase expired.
androidHandoff = { handoffId: "aho_" + "c".repeat(24), claimSecret: "u".repeat(20),
  userCode: "WXYZ-3456", authorizationUrl: "https://x/y", expiresAt: Date.now() - 1, phase: "waiting" };
const before = fetchCalls.length;
await mod.pollAndroidHandoff();
assert.equal(fetchCalls.length, before);
assert.equal(androidHandoff.phase, "expired");

// cancel control clears state, persists and re-renders.
await cancelBtn.fire("click", {});
assert.equal(androidHandoff, null);
assert.equal(androidHandoffClaiming, false);
assert.equal(panel.hidden, true);
assert.equal(stores[stores.length - 1], null);

// visibilitychange re-polls only while a handoff exists.
androidHandoff = { handoffId: "aho_" + "d".repeat(24), claimSecret: "v".repeat(20),
  userCode: "WXYZ-4567", authorizationUrl: "https://x/y", expiresAt: Date.now() + 60000, phase: "waiting" };
queue(200, { status: "awaiting_confirmation" });
documentObj.listeners.visibilitychange[0]({});
await new Promise((r) => setTimeout(r, 0));
assert.equal(androidHandoff.phase, "confirm");
console.log("A6_VM_CONTRACT_OK");
})().catch((error) => { console.error(error); process.exit(1); });
"""
    result = subprocess.run(
        [node, "-e", script, str(STATIC)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "A6_VM_CONTRACT_OK" in result.stdout


def test_handoff_apis_are_reachable_through_the_registry() -> None:
    """B7 20차 보강: 등록부(app.provide("androidHandoff"))로 9개 이름을 조회한다.

    app.js 전달 함수가 없어도 소비자(deps getter·resume·session bind·localechange)는
    등록된 조각의 같은 이름 API에 도달한다. 실제 모듈 본문을 node vm에서 문맥에
    등록해 9개 이름이 전부 함수로 조회되는지 본다(동작 단언은 vm 하네스가 증명).
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
  hidden: true, textContent: "", dataset: {}, children: [], value: "",
  classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
  addEventListener() {}, removeEventListener() {},
  setAttribute() {}, getAttribute() { return null; },
  appendChild(c) { this.children.push(c); return c; }, append() {}, removeChild() {},
});
const byId = new Map();
const sandbox = {
  document: {
    getElementById: (id) => { if (!byId.has(id)) byId.set(id, fakeEl()); return byId.get(id); },
    querySelectorAll: () => [], querySelector: () => null,
    addEventListener() {}, removeEventListener() {},
    createElement: (tag) => ({ tag, textContent: "", className: "", dataset: {}, appendChild() {}, append() {}, setAttribute() {} }),
  },
  navigator: { userAgent: "" },
  location: { search: "", hash: "", pathname: "/", href: "https://example.test/" },
  fetch: () => new Promise(() => {}),
  console: { error() {} },
  setTimeout, clearTimeout, setInterval, clearInterval,
};
sandbox.window = { ...sandbox };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(staticDir + "/chat-app-context.js", "utf8"), sandbox,
  { filename: "chat-app-context.js" });
vm.runInContext(fs.readFileSync(staticDir + "/chat-android-handoff-module.js", "utf8"), sandbox,
  { filename: "chat-android-handoff-module.js" });
const names = %s;
const result = vm.runInContext(`
  const app = window.PadiemChatAppContext.create({});
  app.provide("androidHandoff", window.PadiemChatAndroidHandoffModule.create(Object.setPrototypeOf({}, app)));
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
