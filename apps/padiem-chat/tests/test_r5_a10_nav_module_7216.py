"""#7216 R5 A10 (nav) — 화면 전환 모듈 계약 (8함수 + wire 2개).

app.js의 화면 전환 구역 8개 함수(pageViewFor·syncRouteHash·setNavActive·
switchConversationProduct·openClawWorkspace·openChatWorkspace·openClawManual·
openClawRunTarget)가 chat-nav-module.js로 이동했고, app.js는 같은 이름의 한 줄
전달 함수 7개, 원래 선언 자리에서 바로 만드는 생성 블록 1개, 원래 리스너 블록 자리의 wire 호출 2회
(padiem:calendar-open-link / Claw 진입 단추 묶음), 선언과 창 공개 계약 2종
(PadiemChatRouting·PadiemAppSwitch)을 유지한다. 본문은 위치만 옮겨졌다.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from _r5_b6_wiring import context_names, create_block

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
MODULE = (STATIC / "chat-nav-module.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")

NAMES = (
    "pageViewFor",
    "syncRouteHash",
    "setNavActive",
    "switchConversationProduct",
    "openClawWorkspace",
    "openChatWorkspace",
    "openClawManual",
    "openClawRunTarget",
)

FORWARDERS = (
    "syncRouteHash",
    "setNavActive",
    "switchConversationProduct",
    "openClawWorkspace",
    "openChatWorkspace",
    "openClawManual",
    "openClawRunTarget",
)

EXPECTED_GETTERS = {
    "AUTOMATION_ROUTE_HASH",
    "CLAW_ROUTE_HASH",
    "CONNECTORS_ROUTE_HASH",
    "CALENDAR_ROUTE_HASH",
    "LIBRARY_ROUTE_HASH",
    "MEETING_ROUTE_HASH",
    "ADVANCED_SETTINGS_ROUTE_HASH",
    "shell",
    "automationDestinationReady",
    "syncComposerForClaw",
    "uiT",
    "PRODUCT_CLAW",
    "PRODUCT_CHAT",
    "conversationProduct",
    "conversationState",
    "messageList",
    "emptyState",
    "clawArtifactShownFor",
    "conversationArtifactContext",
    "clawWorkspace",
    "clawManualForm",
    "clawResultArea",
    "app",
    "input",
    "closeSidebar",
    "syncClawRunHistoryVisibility",
    "openSavedConversation",
    "downloadClawArtifact",
    "authState",
}

EXPECTED_SETTERS = {
    "conversationProduct",
    "clawArtifactShownFor",
    "pendingClawRunFocusId",
}

# 이동한 본문의 표식 — 모듈에는 있고 app.js에는 없어야 한다.
MOVED_MARKERS = (
    "window.PadiemChatNavModule = {",
    'pageViewFor(state) {',
    "const desired = panelRouteHashes()[state]",
    "const PAGE_VIEWS = Object.freeze([",
    'const clawNavButton = document.getElementById("clawNavButton");',
    "calendar: deps.CALENDAR_ROUTE_HASH,",
    "settings: deps.ADVANCED_SETTINGS_ROUTE_HASH,",
    "deps.shell.dataset.pageId = page.pageId;",
    "clawNav.dataset.modeHint = deps.uiT(\"nav-claw-hint\")",
    'deps.shell.dataset.state = "claw";',
    'deps.shell.dataset.state = "home";',
    'deps.shell.dataset.state = "meeting";',
    'padiem:calendar-open-link',
    'deps.pendingClawRunFocusId = runId;',
)


def test_index_loads_nav_module_before_app() -> None:
    assert INDEX.count("./chat-nav-module.js") == 1
    assert INDEX.index("./chat-nav-module.js") < INDEX.index("./app.js")
    # 모듈 의존 해석은 호출 시점이라 로드 순서 제약은 없지만, 창 계약이 app.js
    # 원래 자리에 유지되는지와 함께 로드 순서 자체는 고정한다.


def test_app_keeps_forwarders_instance_and_two_wire_calls() -> None:
    for name in FORWARDERS:
        line = f"function {name}(...a) {{ return navModuleInstance.{name}(...a); }}"
        assert line in APP, name
    # B2-4: 모듈은 원래 선언 자리에서 바로 만든다(첫 호출 때 만드는 lazy 팩토리 제거).
    assert "const navModuleInstance = window.PadiemChatNavModule.create(" in APP
    assert "function navModule() {" not in APP
    # 리스너 등록 4개는 모듈 wire 2개로 옮겨졌고 app.js는 각각 원래 블록 자리에서
    # 1회씩 호출한다(등록 시점·순서 보존).
    assert APP.count("navModuleInstance.wireNavRouteListener();") == 1
    assert APP.count("navModuleInstance.wireNavEntryListeners();") == 1
    # 옮긴 함수의 정의는 app.js에 남지 않는다(전달 함수는 ...a 한 줄뿐).
    for name in NAMES:
        assert APP.count(f"function {name}(") == (1 if name in FORWARDERS else 0), name


def test_window_contracts_stay_in_app_js_at_their_original_shape() -> None:
    # 창 공개 2종은 모듈 도입으로 시점이 바뀌면 안 되므로 app.js 원래 자리에 둔다.
    assert APP.count("window.PadiemChatRouting = Object.freeze({ syncRouteHash });") == 1
    assert APP.count("window.PadiemAppSwitch = Object.freeze({") == 1
    assert "openChat: openChatWorkspace," in APP
    assert "openClaw: openClawWorkspace," in APP


def test_moved_bodies_live_only_in_the_module_and_module_stays_under_500_lines() -> None:
    for marker in MOVED_MARKERS:
        assert marker in MODULE, marker
        assert marker not in APP, marker
    for name in NAMES:
        assert MODULE.count(f"function {name}(") == 1, name
    assert MODULE.count("function wireNavRouteListener(") == 1
    assert MODULE.count("function wireNavEntryListeners(") == 1
    assert len(MODULE.splitlines()) <= 500


def test_nav_owned_declarations_live_only_in_the_module() -> None:
    # B2-4: Nav만 쓰는 선언(페이지 계약·조각 표·Claw 단추)은 모듈 안에만 있다.
    for line in (
        "const PAGE_VIEWS = Object.freeze([",
        "const PAGE_VIEW_BY_ID = Object.freeze(",
        'const clawNavButton = document.getElementById("clawNavButton");',
        "calendar: deps.CALENDAR_ROUTE_HASH,",
        "settings: deps.ADVANCED_SETTINGS_ROUTE_HASH,",
    ):
        assert line in MODULE, line
        assert line not in APP, line
    assert "PANEL_ROUTE_HASH_BY_STATE" not in APP
    assert "OWNED_PANEL_HASHES" not in APP


def test_deps_getters_and_setters_match_exact_closure_surface() -> None:
    start = APP.index("window.PadiemChatNavModule.create(")
    block = create_block(APP, start)
    gets = set(re.findall(r"get (\w+)\(\)", block))
    sets = set(re.findall(r"set (\w+)\(value\)", block))
    assert gets <= EXPECTED_GETTERS and EXPECTED_GETTERS - gets <= context_names(APP)
    assert sets <= EXPECTED_SETTERS and EXPECTED_SETTERS - sets <= context_names(APP)


def _extract_decl(pattern: str) -> str:
    m = re.search(pattern, APP, re.S)
    assert m, pattern
    return m.group(0)


def test_all_8_functions_execute_in_node_vm_with_strict_live_deps() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed in this runner")

    route_consts = "\n".join(
        _extract_decl(rf'const {name} = "[^"]+";')
        for name in ("AUTOMATION_ROUTE_HASH", "CLAW_ROUTE_HASH", "CONNECTORS_ROUTE_HASH",
                     "CALENDAR_ROUTE_HASH", "LIBRARY_ROUTE_HASH", "MEETING_ROUTE_HASH",
                     "ADVANCED_SETTINGS_ROUTE_HASH")
    )
    products = "\n".join(
        _extract_decl(rf'const {name} = "[^"]+";') for name in ("PRODUCT_CHAT", "PRODUCT_CLAW")
    )

    script = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

(async () => {
const staticDir = process.argv[1];
const strictSrc = fs.readFileSync(path.join(staticDir, "..", "tests", "_r5_strict_deps.js"), "utf8");
const modSrc = fs.readFileSync(path.join(staticDir, "chat-nav-module.js"), "utf8");
vm.runInThisContext(strictSrc, { filename: "_r5_strict_deps.js" });

// --- 결정적 DOM 스텁: dataset·hidden·children·listeners·focus·attrs. ---
function makeEl(id) {
  const el = {
    id, dataset: {}, hidden: false, children: [], listeners: {}, attrs: {},
  };
  el.addEventListener = (t, fn) => { (el.listeners[t] ??= []).push(fn); };
  el.setAttribute = (k, v) => { el.attrs[k] = String(v); };
  el.getAttribute = (k) => (k in el.attrs ? el.attrs[k] : null);
  el.focus = () => { el.focused = true; };
  el.click = () => { for (const fn of el.listeners.click || []) fn({ preventDefault() {} }); };
  return el;
}

const registry = new Map();
function reg(id) { const el = makeEl(id); registry.set(id, el); return el; }

const shell = reg("appShell");
const messageList = reg("messageList");
const emptyState = reg("emptyState");
const clawWorkspace = reg("clawWorkspace");
const clawManualForm = reg("clawManualForm");
const clawResultArea = reg("clawResultArea");
const input = reg("messageInput");
const clawNavButton = reg("clawNavButton");
const newChatButton = reg("newChatButton");
const utilNav = reg("utilNavButton");
const meetingNav = reg("meetingNavButton");
const connectorsNav = reg("connectorsNavButton");
const automationNav = reg("automationNavButton");
const clawManualEntryBar = reg("clawManualEntryBar");
const clawManualEntryButton = reg("clawManualEntryButton");
const meetingView = reg("meetingView");

const documentStub = {
  getElementById: (id) => registry.get(id) || null,
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener: () => {},
};

const historyState = { index: 1 };
const replaceCalls = [];
const windowListeners = {};
const windowStub = {
  history: {
    state: historyState,
    replaceState(s, t, url) {
      replaceCalls.push({ state: s, url });
      // 실제 브라우저와 같이: replaceState 뒤 location은 주어진 URL을 반영한다.
      const u = String(url);
      const i = u.indexOf("#");
      windowStub.location.hash = i >= 0 ? u.slice(i) : "";
    },
  },
  location: { hash: "", pathname: "/chat", search: "?x=1" },
  addEventListener: (type, fn) => { (windowListeners[type] ??= []).push(fn); },
};

// --- app.js 라이브 값: 선언을 app.js 소스에서 그대로 가져온다(원본 순서 유지). ---
__ROUTE_CONSTS_DECL__
__PRODUCTS_DECL__

const uiTCalls = [];
const syncComposerCalls = [];
const closeSidebarCalls = [];
const historyVisibilityCalls = [];
const savedOpens = [];
const artifactDownloads = [];
const memorySyncs = [];
const contextShows = [];
const contextClears = [];
const setProductCalls = [];
const productIds = { claw: "conv-claw-1", chat: "conv-chat-1" };
let conversationProduct = "chat";
let clawArtifactShownFor = "";
let automationDestinationReady = false;
let authState = { authenticated: true };

const conversationState = {
  setProduct: (p) => setProductCalls.push(p),
  getConversationId: (p) => productIds[p],
};
const conversationArtifactContext = {
  show: (id) => contextShows.push(id),
  clear: () => contextClears.push(1),
};
const app = {
  clawAutomation: reg("clawAutomationPanel"),
  syncApprovedMemoryVisibility: () => memorySyncs.push(1),
};

const deps = r5StrictDeps({
  get AUTOMATION_ROUTE_HASH() { return AUTOMATION_ROUTE_HASH; },
  get CLAW_ROUTE_HASH() { return CLAW_ROUTE_HASH; },
  get CONNECTORS_ROUTE_HASH() { return CONNECTORS_ROUTE_HASH; },
  get CALENDAR_ROUTE_HASH() { return CALENDAR_ROUTE_HASH; },
  get LIBRARY_ROUTE_HASH() { return LIBRARY_ROUTE_HASH; },
  get MEETING_ROUTE_HASH() { return MEETING_ROUTE_HASH; },
  get ADVANCED_SETTINGS_ROUTE_HASH() { return ADVANCED_SETTINGS_ROUTE_HASH; },
  get shell() { return shell; },
  get automationDestinationReady() { return automationDestinationReady; },
  get syncComposerForClaw() { return syncComposerForClaw; },
  get uiT() { return uiT; },
  get PRODUCT_CLAW() { return PRODUCT_CLAW; },
  get PRODUCT_CHAT() { return PRODUCT_CHAT; },
  get conversationProduct() { return conversationProduct; },
  set conversationProduct(value) { conversationProduct = value; },
  get conversationState() { return conversationState; },
  get messageList() { return messageList; },
  get emptyState() { return emptyState; },
  get clawArtifactShownFor() { return clawArtifactShownFor; },
  set clawArtifactShownFor(value) { clawArtifactShownFor = value; },
  get conversationArtifactContext() { return conversationArtifactContext; },
  get clawWorkspace() { return clawWorkspace; },
  get clawManualForm() { return clawManualForm; },
  get clawResultArea() { return clawResultArea; },
  get app() { return app; },
  get input() { return input; },
  get closeSidebar() { return closeSidebar; },
  get syncClawRunHistoryVisibility() { return syncClawRunHistoryVisibility; },
  get openSavedConversation() { return openSavedConversation; },
  get downloadClawArtifact() { return downloadClawArtifact; },
  get authState() { return authState; },
  set pendingClawRunFocusId(value) { pendingClawRunFocusId = value; },
}, "nav-deps");

function uiT(key) { uiTCalls.push(key); return "T:" + key; }
function syncComposerForClaw(value) { syncComposerCalls.push(value); }
function closeSidebar() { closeSidebarCalls.push(1); }
function syncClawRunHistoryVisibility() { historyVisibilityCalls.push(1); }
function openSavedConversation(id) { savedOpens.push(id); }
function downloadClawArtifact(id, name) { artifactDownloads.push([id, name]); }
let pendingClawRunFocusId = "";

const sandbox = {
  document: documentStub,
  window: windowStub,
  location: windowStub.location,
  history: windowStub.history,
  console,
  deps,
  uiT, syncComposerForClaw, closeSidebar, syncClawRunHistoryVisibility,
  openSavedConversation, downloadClawArtifact,
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(modSrc, sandbox, { filename: "chat-nav-module.js" });

// create()는 deps를 읽지 않는다(엄격 빈 deps로 create만 통과).
const emptyModule = sandbox.window.PadiemChatNavModule.create(r5StrictDeps({}, "emptyCreateDeps"));
assert.equal(typeof emptyModule.setNavActive, "function");

const mod = sandbox.window.PadiemChatNavModule.create(deps);

const reset = () => {
  replaceCalls.length = 0;
  uiTCalls.length = 0;
  syncComposerCalls.length = 0;
  closeSidebarCalls.length = 0;
  historyVisibilityCalls.length = 0;
  savedOpens.length = 0;
  artifactDownloads.length = 0;
  memorySyncs.length = 0;
  contextShows.length = 0;
  contextClears.length = 0;
  setProductCalls.length = 0;
  windowStub.location.hash = "";
  shell.dataset = {};
  clawWorkspace.dataset = {};
  messageList.children.length = 0;
  messageList.hidden = true;
  emptyState.hidden = false;
  input.focused = false;
  conversationProduct = "chat";
  clawArtifactShownFor = "";
  pendingClawRunFocusId = "";
};

// (a) pageViewFor: 알려든 상태 매핑, 모르는 상태는 home.
assert.equal(mod.pageViewFor("home").pageId, "home");
assert.equal(mod.pageViewFor("claw").pageId, "claw");
assert.equal(mod.pageViewFor("connectors").pageId, "connectors");
assert.equal(mod.pageViewFor("util").pageId, "util");
assert.equal(mod.pageViewFor("no-such-state").pageId, "home");

// (b) syncRouteHash: 게이트가 닫히면 주소를 만지지 않는다.
reset();
mod.syncRouteHash();
assert.deepEqual(replaceCalls, []);

// (c) syncRouteHash: 패널 화면이 자기 조각을 얻는다(주소는 destination 뿐).
automationDestinationReady = true;
shell.dataset.state = "calendar";
mod.syncRouteHash();
assert.equal(replaceCalls.length, 1);
assert.equal(replaceCalls[0].state, historyState);
assert.equal(replaceCalls[0].url, "/chat?x=1#padiem-calendar");
assert.deepEqual(replaceCalls[0].state, historyState);

// (d) syncRouteHash: 소유한 조각은 걷어내고 남의 조각은 그대로 둔다.
shell.dataset.state = "home";
windowStub.location.hash = "#padiem-calendar";
mod.syncRouteHash();
assert.equal(replaceCalls.at(-1).url, "/chat?x=1");
windowStub.location.hash = "#youtube";
mod.syncRouteHash();
assert.equal(replaceCalls.length, 2); // 남의 조각이면 replaceState 없음

// (e) setNavActive(claw): 조각 #padiem-claw, pageId/layout, 패널 표시, aria-current.
// openClawWorkspace가 setNavActive 직전에 view="general"을 지정하는 운영 순서를 따른다.
reset();
shell.dataset.state = "claw";
clawWorkspace.dataset.view = "general";
mod.setNavActive();
assert.equal(shell.dataset.pageId, "claw");
assert.equal(shell.dataset.layoutVariant, "conversation"); // Claw general 화면은 대화 서사를 공유한다
assert.equal(windowStub.location.hash, "#padiem-claw");
assert.equal(meetingView.hidden, true);
assert.equal(clawWorkspace.hidden, false);
assert.equal(clawManualForm.hidden, true);
assert.equal(clawManualEntryBar.hidden, false);
assert.deepEqual(syncComposerCalls, [true]);
assert.deepEqual(uiTCalls, ["nav-claw-hint"]);
assert.equal(clawNavButton.dataset.modeHint, "T:nav-claw-hint");
assert.equal(clawNavButton.attrs["aria-current"], "page");
assert.equal(newChatButton.attrs["aria-current"], "false");
assert.equal(utilNav.attrs["aria-current"], "false");
assert.equal(meetingNav.attrs["aria-current"], "false");
assert.equal(connectorsNav.attrs["aria-current"], "false");
assert.equal(automationNav.attrs["aria-current"], "false");
assert.deepEqual(closeSidebarCalls, []);

// (f) setNavActive(home): 첫 화면은 대화 서사, 새 대화만 current.
reset();
shell.dataset.state = "home";
mod.setNavActive();
assert.equal(shell.dataset.pageId, "home");
assert.equal(shell.dataset.layoutVariant, "conversation");
assert.deepEqual(syncComposerCalls, [false]);
assert.equal(newChatButton.attrs["aria-current"], "page");
assert.equal(clawManualEntryBar.hidden, true);
assert.equal(windowStub.location.hash, ""); // 소유하지 않은 상태는 조각을 걷어냄

// (g) setNavActive(util): 유틸 화면 강조 계약(사람 그림·유틸 화면 자체는 건드리지 않음).
reset();
shell.dataset.state = "util";
mod.setNavActive();
assert.equal(shell.dataset.pageId, "util");
assert.equal(utilNav.attrs["aria-current"], "page");
assert.equal(newChatButton.attrs["aria-current"], "false");

// (h) switchConversationProduct: 같은 레인이면 아무 것도 하지 않는다.
reset();
mod.switchConversationProduct("chat");
assert.deepEqual(setProductCalls, []);
assert.deepEqual(contextShows, []);
assert.deepEqual(contextClears, []);

// (i) switchConversationProduct: Chat → Claw, 대화와 artifact 인덱스를 유지한다.
messageList.children.push({});
mod.switchConversationProduct("claw");
assert.deepEqual(setProductCalls, ["claw"]);
assert.equal(conversationProduct, "claw");
assert.equal(messageList.hidden, false);
assert.equal(emptyState.hidden, true); // 턴이 있으므로 빈 상태는 숨겨진다(emptyState.hidden = hasTurns)
assert.equal(clawArtifactShownFor, "conv-claw-1");
assert.deepEqual(contextShows, ["conv-claw-1"]);

// (j) switchConversationProduct: Claw → Chat, artifact 인덱스를 내린다.
mod.switchConversationProduct("chat");
assert.deepEqual(setProductCalls, ["claw", "chat"]);
assert.equal(conversationProduct, "chat");
assert.equal(clawArtifactShownFor, "");
assert.deepEqual(contextClears, [1]);

// (k) openClawWorkspace: general 진입, 같은 대화 유지, 닫기·초점·기억 표시.
reset();
mod.openClawWorkspace();
assert.equal(shell.dataset.state, "claw");
assert.equal(conversationProduct, "claw");
assert.equal(clawWorkspace.dataset.view, "general");
assert.equal(app.clawAutomation.hidden, true);
assert.equal(clawManualForm.hidden, true);
assert.equal(clawResultArea.hidden, false);
assert.equal(input.focused, true);
assert.deepEqual(closeSidebarCalls, [1]);
assert.deepEqual(memorySyncs, [1]);
assert.deepEqual(historyVisibilityCalls, [1]);
assert.equal(shell.dataset.pageId, "claw");

// (l) openChatWorkspace: 같은 대화로 Chat 레인 복귀.
reset();
mod.openChatWorkspace();
assert.equal(shell.dataset.state, "home");
assert.equal(conversationProduct, "chat");
assert.equal(input.focused, true);
assert.deepEqual(closeSidebarCalls, [1]);
assert.equal(shell.dataset.pageId, "home");

// (m) openClawManual: 문서 작업 흐름은 명시 진입에서만 연다.
reset();
mod.openClawManual();
assert.equal(shell.dataset.state, "claw");
assert.equal(clawWorkspace.dataset.view, "manual");
assert.equal(clawManualForm.hidden, false);
assert.equal(clawResultArea.hidden, false);
assert.equal(shell.dataset.pageId, "claw");
assert.equal(shell.dataset.layoutVariant, "workspace"); // manual 뷰는 hero 대상이 아니다
assert.deepEqual(closeSidebarCalls, [1]);
assert.deepEqual(memorySyncs, [1]);

// (n) openClawRunTarget: 실행 초점을 남기고 general Claw로 연다.
reset();
mod.openClawRunTarget("run-77");
assert.equal(pendingClawRunFocusId, "run-77");
assert.equal(clawWorkspace.dataset.view, "general");
assert.equal(shell.dataset.state, "claw");

// (o) wireNavRouteListener: padiem:calendar-open-link 3종 분기.
reset();
mod.wireNavRouteListener();
const routeListener = (windowListeners["padiem:calendar-open-link"] || [])[0];
assert.equal(typeof routeListener, "function");
const session32 = "a".repeat(32);
routeListener({ detail: { kind: "claw_session", targetId: "chat_" + session32 } });
assert.deepEqual(savedOpens, ["chat_" + session32]);
reset();
routeListener({ detail: { kind: "run", targetId: "run-9" } });
assert.equal(pendingClawRunFocusId, "run-9");
assert.equal(shell.dataset.state, "claw");
reset();
const doc32 = "b".repeat(32);
routeListener({ detail: { kind: "artifact", targetId: "doc_" + doc32 } });
assert.equal(shell.dataset.state, "claw");
assert.deepEqual(artifactDownloads, [["doc_" + doc32, ""]]);

// (p) wireNavEntryListeners: clawNavButton·meeting-open·clawManualEntryButton.
reset();
mod.wireNavEntryListeners();
assert.equal(typeof (clawNavButton.listeners.click || [])[0], "function");
clawNavButton.click();
assert.equal(shell.dataset.state, "claw");
assert.deepEqual(closeSidebarCalls, [1]);

reset();
const meetingListener = (windowListeners["padiem:meeting-open"] || [])[0];
authState = { authenticated: false };
meetingListener();
assert.notEqual(shell.dataset.state, "meeting");
authState = { authenticated: true };
meetingListener();
assert.equal(shell.dataset.state, "meeting");
assert.equal(shell.dataset.pageId, "meeting");
assert.equal(meetingView.hidden, false);
assert.deepEqual(closeSidebarCalls, [1]);

reset();
assert.equal(typeof (clawManualEntryButton.listeners.click || [])[0], "function");
clawManualEntryButton.click();
assert.equal(clawWorkspace.dataset.view, "manual");
assert.equal(clawManualForm.hidden, false);

// (q) strict deps: 정의되지 않은 deps 읽기는 즉시 예외(스텁 누락 시험 무효화 방지).
assert.throws(() => deps.notARealDep);
})().catch((err) => { console.error(err); process.exit(1); });
"""

    script = script.replace("__ROUTE_CONSTS_DECL__", route_consts)
    script = script.replace("__PRODUCTS_DECL__", products)

    completed = subprocess.run(
        [node, "-e", script, str(STATIC)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
