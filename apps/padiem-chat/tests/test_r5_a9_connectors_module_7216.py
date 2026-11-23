"""#7216 R5 A9 (connectors) — 앱 연결(커넥터) 모듈 계약 (23함수 + wire).

app.js의 앱 연결(커넥터) 구역 23개 함수가 chat-connectors-module.js로 이동했고,
app.js는 같은 이름의 한 줄 전달 함수 5개, connectorsModule() 팩토리, 원래
리스너 블록 자리의 wire 호출 1회, 선언과 OAuth 복귀 처리를 유지한다.
"""
from __future__ import annotations

# #8060: shipped reads live in _support; assertions stay here.
from _support.calendar_connectors_firstscreen_source import (
    app_js, connectors_module_js, index_html, locale_source, read, util_app_css, util_app_js,
)

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from _r5_b6_wiring import context_names, create_receives_app_context

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = app_js()
MODULE = connectors_module_js()
INDEX = index_html()

NAMES = (
    "setConnectorCopy",
    "connectorSupportKey",
    "connectorWorkspaceKey",
    "connectorUnavailableCopyKeys",
    "liveConnectorCards",
    "googleDriveConnectButton",
    "googleDriveCard",
    "gmailConnectButton",
    "driveConnectOffered",
    "syncGoogleDriveConnectButton",
    "connectorTicketErrorKey",
    "beginGoogleDriveConnect",
    "syncGmailConnectButton",
    "beginGmailConnect",
    "setConnectorCardsLoading",
    "setConnectorCardsUnavailable",
    "renderConnectorStatus",
    "loadConnectorStatus",
    "connectorsScope",
    "mountConnectorsView",
    "openConnectorsView",
    "openConnectorsDialog",
    "closeConnectorsDialog",
)

ASYNC_NAMES = {
    "beginGoogleDriveConnect",
    "beginGmailConnect",
    "loadConnectorStatus",
}

FORWARDERS = (
    "setConnectorCopy",
    "connectorTicketErrorKey",
    "connectorsScope",
    "openConnectorsView",
    "openConnectorsDialog",
)

EXPECTED_GETTERS = {
    "uiT",
    "authState",
    "openAuthDialog",
    "reviewedGoogleAuthorizationUrl",
    "syncGoogleCalendarConnectButton",
    "activateGoogleCalendarRead",
    "googleCalendarConnectButton",
    "beginGoogleCalendarConnect",
    "googleConnectorConnectInFlight",
    "googleCalendarReadActivationAfterConnectReturn",
    "connectorsError",
    "shell",
    "setNavActive",
    "closeSidebar",
}

EXPECTED_SETTERS = {
    "googleConnectorConnectInFlight",
    "googleCalendarReadActivationAfterConnectReturn",
}

# 이동한 본문의 표식 — 모듈에는 있고 app.js에는 없어야 한다.
MOVED_MARKERS = (
    "window.PadiemChatConnectorsModule = {",
    "connectors-support-source-ready",
    "connectors-workspace-ambiguous",
    'PadiemChatTransport.fetchStatusWithRetry("/api/connectors/status"',
    "connectors-connect-drive-error",
    "authorization.connector_id === GOOGLE_DRIVE_CONNECTOR",
    "data-google-connector-connect",
    "connector_ticket_origin_not_canonical",
    'const connectorsNavButton = document.getElementById("connectorsNavButton");',
    'let connectorStatusInFlight = false;',
    'let connectorsViewMounted = false;',
)


def test_index_loads_connectors_module_before_app() -> None:
    assert INDEX.count("./chat-connectors-module.js") == 1
    assert INDEX.index("./chat-connectors-module.js") < INDEX.index("./app.js")


def test_app_registers_connectors_and_keeps_a_single_wire_call() -> None:
    assert 'app.provide("connectors", window.PadiemChatConnectorsModule.create(Object.setPrototypeOf({' in APP
    for name in FORWARDERS:
        assert f"function {name}(" not in APP, name
        assert f"{name}," in MODULE, name
    assert "function connectorsModule() { return connectors; }" in APP
    assert "window.PadiemChatConnectorsModule.create(Object.setPrototypeOf({" in APP
    # 리스너 등록 10개는 모듈 wire로 옮겨졌고 app.js는 원래 자리에서 1회 호출한다.
    assert APP.count("connectorsModule().wireConnectorsListeners();") == 1
    # 옮긴 함수의 정의는 app.js에 남지 않는다.
    for name in NAMES:
        prefix = "async function" if name in ASYNC_NAMES else "function"
        assert APP.count(f"{prefix} {name}(") == 0, name


def test_connector_apis_are_reachable_through_the_registry() -> None:
    """B7 보강: 등록부(app.provide("connectors"))로 5개 이름을 조회한다.

    app.js 전달 함수가 없어도 app.js 호출자(라우트 복귀·OAuth 복귀)와
    calendar deps getter는 등록된 조각의 같은 이름 API에 도달한다.
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
vm.runInContext(fs.readFileSync(staticDir + "/chat-connectors-module.js", "utf8"), sandbox,
  { filename: "chat-connectors-module.js" });
const names = %s;
const result = vm.runInContext(`
  const app = window.PadiemChatAppContext.create({});
  app.provide("connectors", window.PadiemChatConnectorsModule.create(app));
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
        [node, "-e", script.replace("%s", json.dumps(list(FORWARDERS))), str(STATIC)],
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
    assert MODULE.count("function wireConnectorsListeners(") == 1
    assert len(MODULE.splitlines()) <= 500


def test_deps_getters_and_setters_match_exact_closure_surface() -> None:
    block = create_receives_app_context(APP, "window.PadiemChatConnectorsModule")
    gets = set(re.findall(r"get (\w+)\(\)", block))
    sets = set(re.findall(r"set (\w+)\(value\)", block))
    assert gets <= EXPECTED_GETTERS
    assert gets | (EXPECTED_GETTERS & context_names(APP)) == EXPECTED_GETTERS
    assert sets <= EXPECTED_SETTERS
    assert sets | (EXPECTED_SETTERS & context_names(APP)) == EXPECTED_SETTERS


def test_all_23_functions_execute_in_node_vm_with_strict_live_deps() -> None:
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
const modSrc = fs.readFileSync(path.join(staticDir, "chat-connectors-module.js"), "utf8");

// --- 결정적 DOM 스텁: textContent만 허용(HTML 싱크는 예외). ---
function makeEl(id) {
  const el = {
    id, dataset: { connectorId: id || "" }, hidden: false, disabled: false,
    children: [], listeners: {}, attrs: {}, texts: [], open: false,
  };
  el.querySelector = (sel) => el.bySel.get(sel) || null;
  el.querySelectorAll = (sel) => el.bySelAll.get(sel) || [];
  el.appendChild = (c) => { el.children.push(c); return c; };
  el.addEventListener = (t, fn) => { (el.listeners[t] ??= []).push(fn); };
  el.setAttribute = (k, v) => { el.attrs[k] = String(v); };
  el.getAttribute = (k) => (k in el.attrs ? el.attrs[k] : null);
  el.removeAttribute = (k) => { delete el.attrs[k]; };
  el.focus = () => { el.focused = true; };
  el.click = () => { for (const fn of el.listeners.click || []) fn({ preventDefault() {} }); };
  el.close = () => { el.open = false; el.closed = true; };
  Object.defineProperty(el, "textContent", {
    set(v) { el.texts.push(String(v)); },
    get() { return el.texts.at(-1) ?? ""; },
  });
  for (const sink of ["innerHTML", "outerHTML"]) {
    Object.defineProperty(el, sink, {
      set() { throw new Error("HTML sink used: " + sink); },
      get() { throw new Error("HTML sink read: " + sink); },
    });
  }
  el.bySel = new Map();
  el.bySelAll = new Map();
  return el;
}

const registry = new Map();
function reg(id) { const el = makeEl(id); registry.set(id, el); return el; }
const viewBody = reg("connectorsViewBody");
const dialog = reg("connectorsDialog");
const navButton = reg("connectorsNavButton");
const dialogClose = reg("connectorsDialogClose");
const loading = reg("connectorsLoading");
const errorEl = reg("connectorsError");
const retry = reg("connectorsRetry");
const shell = reg("appShell");

function card(slug, connectorId) {
  const el = makeEl(slug);
  el.dataset.connector = slug;
  el.dataset.connectorId = connectorId;
  const support = makeEl(slug + "-support");
  const workspace = makeEl(slug + "-workspace");
  el.bySel.set("[data-connector-support]", support);
  el.bySel.set("[data-connector-workspace]", workspace);
  el.bySel.set("[data-connector-id]", el);
  const connectButton = makeEl(slug + "-connect");
  el.appendChild(connectButton);
  // 연결 단추 속성은 슬러그(프로덕션: google-drive/gmail/google-calendar),
  // 상태 카드 속성은 상태 ID(connector:google:*@1)를 쓴다.
  viewBody.bySel.set(`[data-google-connector-connect="${slug}"]`, connectButton);
  viewBody.bySel.set(`[data-connector-id="${connectorId}"]`, el);
  return { el, connectButton };
}
const driveCard = card("google-drive", "connector:google:drive@1");
const gmailCard = card("gmail", "connector:google:gmail@1");
const calendarCard = card("google-calendar", "connector:google:calendar@1");
const cards = [driveCard.el, gmailCard.el, calendarCard.el];
viewBody.bySelAll.set("[data-connector-id]", cards);
// connectorsScope()는 값 없는 [data-connector-id] 셀렉터로 뷰 본문을 확인한다.
viewBody.bySel.set("[data-connector-id]", cards[0]);
// mountConnectorsView는 대화상자 안에서 격자를 찾고, 상태 표시를 함께 옮긴다.
dialog.bySel.set(".capability-grid", makeEl("grid"));
reg("connectorsLiveStatus");
reg("connectorsView");

const documentStub = {
  getElementById: (id) => registry.get(id) || null,
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener: () => {},
  removeEventListener: () => {},
  activeElement: null,
};

const postBodies = [];
const transportCalls = [];
const assigned = [];
const calendarSyncs = [];
const navActiveCalls = [];
const closeSidebarCalls = [];
const authDialogOpens = [];
const reviewedUrls = [];
const calendarActivations = [];
const calendarClicks = [];
let authState = { authenticated: false };
let driveInFlight = false;
let calendarActivationAfterReturn = false;

const ctx = vm.createContext({
  document: documentStub,
  fetch: async (url, init) => {
    postBodies.push({ url, body: init && init.body });
    return { ok: true, json: async () => ({ authorization: { connector_id: "google-drive", authorization_url: "https://reviewed.example/auth" } }) };
  },
  JSON, Math, Number, Array, Boolean, Map, Promise, Proxy, Reflect, String, Set,
  window: {
    location: { assign: (url) => assigned.push(url) },
    PadiemChatTransport: {
      fetchStatusWithRetry: async (url) => { transportCalls.push(url); return transportNext(); },
    },
  },
  setTimeout: (fn) => { fn(); return 1; },
});

function transportNext() {
  if (transportShouldFail) throw new Error("front loss");
  return { ok: true, json: async () => statusDocument() };
}
let transportShouldFail = false;
function statusDocument() {
  return {
    static_support_vs_workspace_state_separated: true,
    send_write_authorized: false,
    connectors: [
      { connector_id: "connector:google:drive@1", read_availability: "complete", workspace_state: "not_connected" },
      { connector_id: "connector:google:gmail@1", read_availability: "complete", workspace_state: "not_connected" },
      { connector_id: "connector:google:calendar@1", read_availability: "complete", workspace_state: "connected" },
    ],
  };
}

vm.runInContext(strictSrc + "\n" + modSrc, ctx, { filename: "chat-connectors-module.js" });

// 1. create()는 deps를 읽지 않는다(엄격 빈 deps로 create만 통과).
const emptyStrict = ctx.r5StrictDeps({}, "emptyCreateDeps");
const emptyModule = ctx.window.PadiemChatConnectorsModule.create(emptyStrict);
assert.equal(typeof emptyModule.loadConnectorStatus, "function");

const mod = ctx.window.PadiemChatConnectorsModule.create(ctx.r5StrictDeps({
  get uiT() { return (k) => `T:${k}`; },
  get authState() { return authState; },
  get openAuthDialog() { return () => { authDialogOpens.push(1); }; },
  get reviewedGoogleAuthorizationUrl() { return (url) => { reviewedUrls.push(url); return `reviewed:${url}`; }; },
  get syncGoogleCalendarConnectButton() { return (row) => { calendarSyncs.push(row); }; },
  get activateGoogleCalendarRead() { return async () => { calendarActivations.push(1); }; },
  get googleCalendarConnectButton() { return calendarCard; },
  get beginGoogleCalendarConnect() { return async () => {}; },
  get googleConnectorConnectInFlight() { return driveInFlight; },
  set googleConnectorConnectInFlight(value) { driveInFlight = value; },
  get googleCalendarReadActivationAfterConnectReturn() { return calendarActivationAfterReturn; },
  set googleCalendarReadActivationAfterConnectReturn(value) { calendarActivationAfterReturn = value; },
  get connectorsError() { return errorEl; },
  get shell() { return shell; },
  get setNavActive() { return () => { navActiveCalls.push(1); }; },
  get closeSidebar() { return () => { closeSidebarCalls.push(1); }; },
}, "liveDeps"));

(async () => {
  // (a) 문구·상태 키 산출
  mod.setConnectorCopy(driveCard.el, "connectors-connect-drive");
  assert.equal(driveCard.el.texts.at(-1), "T:connectors-connect-drive");
  assert.equal(driveCard.el.dataset.localeKey, "connectors-connect-drive");
  assert.equal(mod.connectorSupportKey("complete"), "connectors-support-complete");
  assert.equal(mod.connectorSupportKey("source_ready"), "connectors-support-source-ready");
  assert.equal(mod.connectorSupportKey("deferred"), "connectors-support-deferred");
  assert.equal(mod.connectorSupportKey("other"), "connectors-status-unavailable");
  assert.equal(mod.connectorWorkspaceKey("connected"), "connectors-workspace-connected");
  assert.equal(mod.connectorWorkspaceKey("not_connected"), "connectors-workspace-not-connected");
  assert.equal(mod.connectorWorkspaceKey("ambiguous"), "connectors-workspace-ambiguous");
  authState = { authenticated: false };
  assert.equal(mod.connectorWorkspaceKey("unverified"), "connectors-workspace-sign-in");
  authState = { authenticated: true };
  assert.equal(mod.connectorWorkspaceKey("unverified"), "connectors-workspace-unverified");
  const deferredKeys = mod.connectorUnavailableCopyKeys("connector:telegram:bot@1");
  assert.equal(deferredKeys.support, "connectors-workspace-unverified");
  assert.equal(deferredKeys.workspace, "connectors-workspace-unverified");
  const plainKeys = mod.connectorUnavailableCopyKeys("connector:github:x@1");
  assert.equal(plainKeys.support, "connectors-status-unavailable");
  assert.equal(plainKeys.workspace, "connectors-workspace-unavailable");
  assert.equal(mod.driveConnectOffered(true, "not_connected"), true);
  assert.equal(mod.driveConnectOffered(false, "not_connected"), false);
  assert.equal(mod.connectorTicketErrorKey({ error: { code: "connector_ticket_origin_not_canonical" } }, "fb"), "connectors-connect-canonical-only");
  assert.equal(mod.connectorTicketErrorKey({}, "fb"), "fb");

  // (b) 연결 단추 동기화: 게스트는 숨김, 로그인+미연결은 노출
  assert.equal(mod.googleDriveCard(), driveCard.el);
  authState = { authenticated: false };
  mod.syncGoogleDriveConnectButton({ workspace_state: "not_connected" });
  assert.equal(driveCard.connectButton.hidden, true);
  authState = { authenticated: true };
  mod.syncGoogleDriveConnectButton({ workspace_state: "not_connected" });
  assert.equal(driveCard.connectButton.hidden, false);
  assert.equal(driveCard.connectButton.disabled, false);
  assert.equal(driveCard.connectButton.texts.at(-1), "T:connectors-connect-drive");
  mod.syncGmailConnectButton(null);
  assert.equal(gmailCard.connectButton.hidden, true);

  // (c) 로딩·불가 카드 갱신(달력 동기화 훅 함께 호출)
  mod.setConnectorCardsLoading();
  assert.equal(driveCard.el.dataset.connectorStatus, "loading");
  assert.equal(calendarSyncs.at(-1), undefined);
  mod.setConnectorCardsUnavailable();
  assert.equal(driveCard.el.dataset.connectorStatus, "unavailable");
  assert.equal(calendarSyncs.length >= 2, true);

  // (d) 상태 투영: 서버 문서 가드, 카드 상태·문구, 달력 연결됨 축
  assert.throws(() => mod.renderConnectorStatus({ static_support_vs_workspace_state_separated: false, send_write_authorized: false, connectors: [] }));
  mod.renderConnectorStatus(statusDocument());
  assert.equal(driveCard.el.dataset.connectorStatus, "not_connected");
  assert.equal(driveCard.el.bySel.get("[data-connector-support]").texts.at(-1), "T:connectors-support-complete");
  assert.equal(driveCard.el.bySel.get("[data-connector-workspace]").texts.at(-1), "T:connectors-workspace-not-connected");
  assert.equal(calendarCard.el.dataset.connectorStatus, "connected");
  assert.deepEqual(calendarSyncs.at(-1).connector_id, "connector:google:calendar@1");

  // (e) 상태 읽기: 전송 헬퍼 1회, 성공 투영, 재시도 단추 복구
  await mod.loadConnectorStatus();
  assert.deepEqual(transportCalls, ["/api/connectors/status"]);
  assert.equal(loading.hidden, true);
  assert.equal(retry.disabled, false);

  // (f) 실패 경로: 카드 불가 표시 + 오류·재시도 노출, in-flight 해제.
  // R5 2부 B2: the status/mount state is module-internal — the release is
  // proven behaviorally (the in-flight guard lets a second load run).
  transportShouldFail = true;
  await mod.loadConnectorStatus();
  assert.equal(driveCard.el.dataset.connectorStatus, "unavailable");
  assert.equal(errorEl.hidden, false);
  assert.equal(retry.hidden, false);
  transportShouldFail = false;
  await mod.loadConnectorStatus();
  assert.equal(transportCalls.length, 3); // 누적 3회: (e) 성공 + (f) 실패 + 해제 증명용 재시도

  // (g) 드라이브 연결: 게스트는 로그인 대화상자, 티켓 1회, 검토된 주소로 이동
  authState = { authenticated: false };
  await mod.beginGoogleDriveConnect();
  assert.deepEqual(authDialogOpens, [1]);
  assert.deepEqual(postBodies, []);
  authState = { authenticated: true };
  await mod.beginGoogleDriveConnect();
  assert.equal(postBodies.length, 1);
  assert.equal(postBodies[0].url, "/api/connectors/google/ticket");
  assert.deepEqual(JSON.parse(postBodies[0].body), { connector_id: "google-drive", begin_oauth: true });
  assert.equal(assigned.at(-1), "reviewed:https://reviewed.example/auth");
  assert.equal(reviewedUrls.at(-1), "https://reviewed.example/auth");
  // 성공 경로는 페이지 이동으로 끝나므로 in-flight 플래그는 해제되지 않는다(원래 본문 계약).
  assert.equal(driveInFlight, true);
  driveInFlight = false; // (h)의 새 시도를 위해 이동 뒤 상태를 재현한다.

  // (h) 지메일 연결: 티켓 1회(엔드포인트·본문 계약)
  await mod.beginGmailConnect();
  assert.equal(postBodies.length, 2);
  assert.equal(postBodies[1].url, "/api/connectors/google/ticket");
  assert.deepEqual(JSON.parse(postBodies[1].body), { connector_id: "gmail", begin_oauth: true });

  // (i) 독립 화면 마운트·전환: 한 번만 마운트, 상태 전환, 내비 표시.
  // R5 2부 B2: the mount flag is module-internal — the guard is proven
  // behaviorally (a second open does not re-mount the grid).
  mod.openConnectorsView();
  assert.equal(viewBody.children.length, 2); // status + grid
  assert.equal(viewBody.children.includes(calendarCard), false);
  mod.openConnectorsView();
  assert.equal(viewBody.children.length, 2); // 마운트 한 번 보존(가드)
  assert.equal(shell.dataset.state, "connectors");
  assert.equal(navActiveCalls.length >= 1, true);
  assert.equal(closeSidebarCalls.length >= 1, true);
  assert.equal(navButton.attrs["aria-expanded"], "false");
  mod.openConnectorsDialog();
  assert.equal(navActiveCalls.length >= 2, true);
  dialog.open = true; // 열린 <dialog>의 close() 경로를 검증한다.
  mod.closeConnectorsDialog();
  assert.equal(dialog.closed, true);
  assert.equal(navButton.focused, true);
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
