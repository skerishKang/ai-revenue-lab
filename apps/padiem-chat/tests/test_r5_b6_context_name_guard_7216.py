"""R5 B6 — 공유 문맥 이름 보호 계약 (중복 이름 방지).

B6 리뷰: 모듈 API가 공유 상태 접근자와 같은 이름을 내놓으면 접근자를 조용히
가리는 문제를 막는다. 접근자와 겹치는 이름은 원칙적으로 오류이고, 예외는
chat-app-context.js의 ACCESSOR_SHADOW_ALLOWLIST뿐이다 — 각 이름마다 "모듈 값을
읽어도 app.js 실제 상태와 어긋나지 않는 이유"가 주석으로 기록되어 있다.

이 시험은 (1) 목록 밖 이름이 접근자와 겹치면 오류를 내고 접근자가 살아 남는지,
(2) 목록 안 이름은 모듈 값이 보이는지, (3) 문맥이 직접 소유한 참조(공유 DOM,
provide)와의 겹침도 오류인지, (4) 기존 중복 등록·중복 이름 오류가 그대로인지
확인한다.
"""
from __future__ import annotations

# #8060: shipped reads live in _support; assertions stay here.
from _support.r5_browser_golden_source import app_context_js, app_js, login_golden_json, strict_deps_js

import json
import subprocess
import tempfile
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
CONTEXT = app_context_js()

_HARNESS = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");

// create()는 공유 DOM 5개를 getElementById로 조회한다 — 최소 스텁.
const byId = new Map();
const fakeEl = () => ({ hidden: true, textContent: "", children: [] });
const document = {
  getElementById: (id) => { if (!byId.has(id)) byId.set(id, fakeEl()); return byId.get(id); },
};
const window = { document };

eval(fs.readFileSync(__CONTEXT_PATH__, "utf8"));

// app.js의 문맥 리터럴과 같은 모양: 접근자는 shared의 own property다.
// probeState는 목록 밖 대표 접근자, syncClawRunHistoryVisibility와
// closeSidebar는 ACCESSOR_SHADOW_ALLOWLIST의 이름이다.
const shared = {};
Object.defineProperty(shared, "probeState", {
  get() { return "app.js accessor value"; },
  set() {},
  enumerable: true, configurable: true,
});
Object.defineProperty(shared, "syncClawRunHistoryVisibility", {
  get() { return "app.js accessor value"; },
  set() {},
  enumerable: true, configurable: true,
});
Object.defineProperty(shared, "closeSidebar", {
  get() { return "app.js accessor value"; },
  set() {},
  enumerable: true, configurable: true,
});
Object.defineProperty(shared, "selectedProductTier", {
  get() { return "app.js accessor value"; },
  set() {},
  enumerable: true, configurable: true,
});
Object.defineProperty(shared, "closeSettings", {
  get() { return "app.js accessor value"; },
  set() {},
  enumerable: true, configurable: true,
});
Object.defineProperty(shared, "setNavActive", {
  get() { return "app.js accessor value"; },
  set() {},
  enumerable: true, configurable: true,
});
for (const k of ["setAuthFormError", "syncAuthDialogMethods", "openAuthDialog", "closeAuthDialog", "loadRecentConversations", "closeProfilePanel", "authMethodEnabled", "loadAuthStatus", "reviewedGoogleAuthorizationUrl", "uiT", "clawT", "mappedUiError", "idleNote", "setNote", "loadProjects", "renderProjectState"]) {
  Object.defineProperty(shared, k, {
    get() { return "app.js accessor value"; },
    set() {},
    enumerable: true, configurable: true,
  });
}

const newApp = () => window.PadiemChatAppContext.create(shared);
const checks = {};

// (1) 모듈 이름 중복 등록은 여전히 오류(기존 계약 유지).
const app1 = newApp();
app1.provide("modA", {});
let threw = null;
try { app1.provide("modA", {}); } catch (e) { threw = e; }
assert.ok(threw && /duplicate module registration/.test(String(threw)), String(threw));
checks.duplicate_module_throws = true;

// (2) 서로 다른 모듈이 같은 이름을 내놓으면 여전히 오류(기존 계약 유지).
const app2 = newApp();
app2.provide("modA", { sharedName: 1 });
threw = null;
try { app2.provide("modB", { sharedName: 2 }); } catch (e) { threw = e; }
assert.ok(threw && /duplicate name/.test(String(threw)), String(threw));
checks.duplicate_name_throws = true;

// (3) 목록 밖 이름이 공유 접근자와 겹치면 오류(조용한 덮어쓰기 금지) —
// 오류 뒤에도 접근자는 그대로 살아 있어야 한다.
const app3 = newApp();
threw = null;
try { app3.provide("modC", { probeState: "module value" }); } catch (e) { threw = e; }
assert.ok(threw && /collides with a shared accessor/.test(String(threw)), String(threw));
assert.equal(app3.probeState, "app.js accessor value", "접근자가 살아 있다");
checks.outside_allowlist_throws = true;

// (4) 목록 안 이름은 모듈 값이 보인다(소유자 위임 — 근거는 allowlist 주석).
const app4 = newApp();
const owner = () => "run-history owner";
app4.provide("runHistory", { syncClawRunHistoryVisibility: owner });
assert.equal(app4.syncClawRunHistoryVisibility, owner, "모듈 값이 보인다");
const sidebarOwner = () => "sidebar owner";
app4.provide("sidebar", { closeSidebar: sidebarOwner });
assert.equal(app4.closeSidebar, sidebarOwner, "allowlist된 두 번째 이름도 모듈 값이 보인다");
const settingsOwner = () => "settings owner";
app4.provide("settings", { selectedProductTier: settingsOwner, closeSettings: settingsOwner });
assert.equal(app4.selectedProductTier, settingsOwner, "allowlist된 세 번째 이름도 모듈 값이 보인다");
assert.equal(app4.closeSettings, settingsOwner, "allowlist된 네 번째 이름도 모듈 값이 보인다");
const navOwner = () => "nav owner";
app4.provide("nav", { setNavActive: navOwner });
assert.equal(app4.setNavActive, navOwner, "allowlist된 다섯 번째 이름도 모듈 값이 보인다");
const dialogOwner = () => "login-dialog owner";
app4.provide("loginDialog", {
  setAuthFormError: dialogOwner, syncAuthDialogMethods: dialogOwner,
  openAuthDialog: dialogOwner, closeAuthDialog: dialogOwner,
});
for (const k of ["setAuthFormError", "syncAuthDialogMethods", "openAuthDialog", "closeAuthDialog"]) {
  assert.equal(app4[k], dialogOwner, "allowlist된 로그인 대화상자 이름도 모듈 값이 보인다: " + k);
}
const historyOwner = () => "history owner";
app4.provide("history", { loadRecentConversations: historyOwner });
assert.equal(app4.loadRecentConversations, historyOwner, "allowlist된 열 번째 이름도 모듈 값이 보인다");
const authOwner = () => "auth owner";
app4.provide("auth", {
  closeProfilePanel: authOwner, authMethodEnabled: authOwner,
  loadAuthStatus: authOwner, reviewedGoogleAuthorizationUrl: authOwner,
});
for (const k of ["closeProfilePanel", "authMethodEnabled", "loadAuthStatus", "reviewedGoogleAuthorizationUrl"]) {
  assert.equal(app4[k], authOwner, "allowlist된 auth 이름도 모듈 값이 보인다: " + k);
}
const coreOwner = () => "core owner";
app4.provide("core", {
  uiT: coreOwner, clawT: coreOwner, mappedUiError: coreOwner,
  idleNote: coreOwner, setNote: coreOwner,
});
for (const k of ["uiT", "clawT", "mappedUiError", "idleNote", "setNote"]) {
  assert.equal(app4[k], coreOwner, "allowlist된 core 이름도 모듈 값이 보인다: " + k);
}
const projectOwner = () => "project owner";
app4.provide("project", { loadProjects: projectOwner, renderProjectState: projectOwner });
for (const k of ["loadProjects", "renderProjectState"]) {
  assert.equal(app4[k], projectOwner, "allowlist된 project 이름도 모듈 값이 보인다: " + k);
}
checks.allowlisted_name_shows_module_value = true;

// (5) 문맥이 직접 소유한 참조(공유 DOM·provide)와 겹쳐도 오류.
const app5 = newApp();
threw = null;
try { app5.provide("modD", { clawRunHistory: {} }); } catch (e) { threw = e; }
assert.ok(threw && /collides with a context-owned ref/.test(String(threw)), String(threw));
threw = null;
try { app5.provide("modE", { provide: () => {} }); } catch (e) { threw = e; }
assert.ok(threw && /collides with a context-owned ref/.test(String(threw)), String(threw));
checks.context_owned_ref_throws = true;

// Shipped owner map: no eager evaluation, exact function identity and receiver.
let creates = 0;
let core;
const app6 = window.PadiemChatAppContext.create({}, {core: () => {
  if (!core) {
    creates++;
    core = app6.provide("core", {uiT: key => "translated:" + key});
  }
  return core;
}});
assert.equal(creates, 0);
const inherited = Object.create(app6);
const translate = inherited.uiT;
assert.equal(creates, 1);
assert.equal(translate("probe"), "translated:probe");
assert.equal(inherited.uiT, core.uiT);
assert.equal(app6.uiT, translate);
assert.equal(creates, 1);
const app7 = window.PadiemChatAppContext.create({}, {project: () => {throw Error("too early");}});
assert.throws(() => app7.provide("wrong", {loadProjects() {}}), /duplicate name/);
const app8 = window.PadiemChatAppContext.create({}, {project: () => {throw Error("too early");}});
const project = {loadProjects: () => "loaded", renderProjectState: () => "rendered"};
app8.provide("project", project);
assert.equal(app8.loadProjects, project.loadProjects);
assert.equal(app8.renderProjectState(), "rendered");
// All three memory/run-history dependency groups must preserve identity.
for (const [owner, names] of Object.entries({
  core: ["uiT", "clawT", "mappedUiError"],
  clawRun: ["downloadClawArtifact", "renderClawApprovalControls"],
  conversation: ["approvedMemoryErrorMessage", "safeLocalUiMessage", "failureCodeNote"],
})) {
  let calls = 0, piece;
  const expected = Object.fromEntries(names.map(name => [name, () => name]));
  const context = window.PadiemChatAppContext.create({}, {[owner]: () => {
    calls++;
    return piece ||= context.provide(owner, expected);
  }});
  assert.equal(calls, 0);
  const deps = Object.create(context);
  for (const name of names) {
    assert.equal(deps[name], expected[name]);
    assert.equal(deps[name](), name);
  }
  assert.equal(calls, 1);
}
checks.deferred_owner_contract = true;
// 4B: one mutable slot per context, shared by every derived module deps.
const live = window.PadiemChatAppContext.create({});
const a = Object.create(live), b = Object.create(live);
const oldAuth = a.authState;
assert.equal(oldAuth.authenticated, false);
assert.equal(a.authViewEpoch, 0);
assert.equal(a.authDialogView, "login");
assert.equal(a.passwordResetToken, "");
assert.equal(a.projectsReady, false);
assert.equal(a.activeProject, null);
assert.equal(a.activeProjectFileCount, 0);
const replacement = {authenticated: true, user: {id: "u1"}};
a.authState = replacement;
assert.equal(b.authState, replacement);
assert.notEqual(oldAuth, b.authState);
assert.equal(oldAuth.authenticated, false);
b.authState.user.name = "updated";
assert.equal(a.authState.user.name, "updated");
a.authViewEpoch += 1;
assert.equal(b.authViewEpoch, 1);
a.authDialogView = "confirm";
b.passwordResetToken = "fixture";
a.projectsReady = true;
const project1 = {id: "p1"}, project2 = {id: "p2"};
a.activeProject = project1;
assert.equal(b.activeProject, project1);
b.activeProject = project2;
assert.equal(a.activeProject, project2);
a.activeProjectFileCount = 3;
assert.equal(b.activeProjectFileCount, 3);
assert.equal(b.authDialogView, "confirm");
assert.equal(a.passwordResetToken, "fixture");
assert.equal(b.projectsReady, true);
for (const key of ["authState", "authViewEpoch", "authDialogView", "passwordResetToken", "projectsReady", "activeProject", "activeProjectFileCount"]) {
  assert.equal(Object.hasOwn(a, key), false);
  assert.equal(Object.hasOwn(b, key), false);
}
const another = window.PadiemChatAppContext.create({});
assert.equal(another.authState.authenticated, false);
assert.equal(another.activeProject, null);
assert.throws(() => live.provide("other", {authState: {}}), /context-owned ref/);
checks.shared_state_contract = true;

console.log("RESULT_JSON " + JSON.stringify({ ok: true, checks }));
"""


def test_context_name_guard_in_node_vm() -> None:
    harness = _HARNESS.replace("__CONTEXT_PATH__", json.dumps(str(STATIC / "chat-app-context.js")))
    with tempfile.TemporaryDirectory() as directory:
        harness_path = Path(directory) / "b6_context_name_guard.cjs"
        harness_path.write_text(harness, encoding="utf-8")
        result = subprocess.run(["node", str(harness_path)], capture_output=True, text=True,
                                encoding="utf-8", timeout=60)
    lines = [l for l in result.stdout.splitlines() if l.startswith("RESULT_JSON ")]
    assert lines, f"harness produced no result: {result.stdout[-800:]} {result.stderr[-400:]}"
    payload = json.loads(lines[-1][len("RESULT_JSON "):])
    assert payload.get("ok") is True, payload
    assert set(payload["checks"]) == {
        "duplicate_module_throws", "duplicate_name_throws",
        "outside_allowlist_throws", "allowlisted_name_shows_module_value",
        "context_owned_ref_throws", "deferred_owner_contract", "shared_state_contract",
    }, payload["checks"]
