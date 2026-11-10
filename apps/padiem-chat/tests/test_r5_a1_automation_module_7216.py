"""R5 A1+B1 — 자동화 모듈 계약 (규칙 목록·토글 + 편집·생성 폼, 28함수).

A1: app.js의 자동화 구역 28개 함수가 chat-automation-module.js(13개)와
chat-automation-form-module.js(15개)로 이동했다. B1(시범): 규칙 보강 4가지를
이 구역에 적용했다 — (가) 모듈이 자기 선언(DOM 참조·상태)을 create() 안에
가진다, (나) 리스너 등록을 모듈 wire 메서드가 app.js의 원래 블록 자리에서
한다, (다) 두 모듈이 함께 쓰는 DOM 참조(clawAutomation, clawAutomationList)는
chat-app-context.js가 소유한다, (라) 한 줄 전달 함수 대신 모듈이 공유
컨텍스트에 API를 등록한다(중복 등록은 예외).

이 시험은 (1) 실제 모듈 본문을 Node vm에서 실행해 28개 함수를 전부 직접
호출하고, (2) create()가 deps를 읽지 않는 것과 wire 뒤 리스너가 달리는 것을
확인하며, (3) 등록부 경로(app.openClawAutomation)와 컨텍스트의 라이브 공유
읽기를 확인한다. 제품 코드는 읽기만 한다.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
CONTEXT = (STATIC / "chat-app-context.js").read_text(encoding="utf-8")
MODULE = (STATIC / "chat-automation-module.js").read_text(encoding="utf-8")
FORM = (STATIC / "chat-automation-form-module.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")

NAMES_A = (
    "resetClawAutomationState", "setClawAutomationLoading", "setClawAutomationError",
    "setClawAutomationForbidden", "renderClawAutomationRules", "loadClawAutomationRules",
    "setClawAutomationToggleStatus", "findRuleToggleButton", "focusRuleToggleAfterReload",
    "toggleClawAutomationRule", "mountAutomationView", "openClawAutomation",
    "setClawAutomationRetryVisible",
)
NAMES_B = (
    "setClawAutomationEditStatus", "syncClawAutomationEditFields", "clawAutomationEditExpression",
    "findRuleEditButton", "focusRuleEditAfterReload", "openClawAutomationEdit",
    "closeClawAutomationEdit", "submitClawAutomationEdit", "setClawAutomationCreateStatus",
    "syncClawAutomationCreateFields", "clawAutomationCreateExpression",
    "resetClawAutomationCreateForm", "closeClawAutomationCreate",
    "scrollClawAutomationCreateIntoView", "submitClawAutomationCreate",
)

MOVED_MARKERS = (
    'deps.uiT("claw-automation-forbidden");',
    'row.dataset.ruleAuthority = "legacy_quarantined";',
    'body: JSON.stringify({ enabled: nextEnabled }),',
    'clawAutomationInFlightRules.delete(ruleId);',
    'deps.shell.dataset.state = "automation";',
    'clawAutomationEditingRuleId = rule.rule_id;',
    'fetch("/api/claw/automation/rules", {',
)
# 보강 (가): 모듈이 소유한 선언 — app.js에는 없어야 한다
OWN_DECLARATIONS = (
    "const clawAutomationLoading = document.getElementById",
    "const clawAutomationInFlightRules = new Set();",
    "let automationViewMounted = false;",
    "const clawAutomationEditForm = document.getElementById",
    "let clawAutomationEditingRuleId = null;",
    "let clawAutomationCreateInFlight = false;",
)
# 보강 (나): 리스너 등록은 모듈 wire 메서드 안으로 — app.js에는 없어야 한다
LISTENER_LINES = (
    'clawAutomationEditForm.addEventListener("submit"',
    'clawAutomationEditKind.addEventListener("change", syncClawAutomationEditFields);',
    'clawAutomationCreateForm.addEventListener("submit"',
    'clawAutomationCreate.addEventListener("toggle"',
    'automationNavButton.addEventListener("click", openClawAutomation)',
    'clawAutomationRetry.addEventListener("click", () => void loadClawAutomationRules());',
)
# 보강 (라): 남은 app.js가 등록부로 부르는 지점들
REGISTRY_CALLS = (
    'app.provide("automation",',
    'app.provide("automationForm",',
    'app.provide("localPcPanel",',
    'if (window.location.hash === AUTOMATION_ROUTE_HASH) app.openClawAutomation();',
)
WIRE_CALLS = (
    "automationForm.wireEditListeners();",
    "automationForm.wireCreateListeners();",
    "automation.wireViewListeners();",
)
SHARED_READS = (
    "authState", "shell", "clawWorkspace", "uiT", "setNavActive", "closeSidebar",
    "clearClawWait", "syncClawRunHistoryVisibility",
)
# vm 하네스의 공유 접근자에는 컨텍스트 소유 DOM 참조도 포함한다(모듈이 deps로 읽는다).
HARNESS_SHARED = tuple(SHARED_READS) + ("clawAutomation", "clawAutomationList")


def test_index_loads_context_and_modules_before_app() -> None:
    for name in ("./chat-app-context.js", "./chat-automation-module.js",
                 "./chat-automation-form-module.js", "./chat-local-pc-panel-module.js"):
        assert INDEX.count(name) == 1, name
    assert INDEX.index("./chat-app-context.js") < INDEX.index("./chat-settings-module.js")
    assert INDEX.index("./chat-automation-form-module.js") < INDEX.index("./chat-local-pc-panel-module.js")
    assert INDEX.index("./chat-local-pc-panel-module.js") < INDEX.index("./app.js")


def test_moved_bodies_and_declarations_live_only_in_the_modules() -> None:
    for marker in MOVED_MARKERS:
        assert marker in MODULE or marker in FORM, marker
        assert marker not in APP, marker
    for decl in OWN_DECLARATIONS:
        in_module = decl in MODULE or decl in FORM
        assert in_module, decl
        assert decl not in APP, decl
    # 보강 (다): 컨텍스트가 소유한 공유 DOM 참조
    assert 'context.clawAutomation = document.getElementById("clawAutomation");' in CONTEXT
    assert 'context.clawAutomationList = document.getElementById("clawAutomationList");' in CONTEXT
    # 옮겨진 선언 블록의 주석도 모듈 쪽으로 갔다.
    assert "#3237: canonical automation rule catalogue" in MODULE
    assert "#3237: canonical automation rule catalogue" not in APP


def test_listeners_register_from_module_wire_not_from_app() -> None:
    for line in LISTENER_LINES:
        assert (line in MODULE) or (line in FORM), line
        assert line not in APP, line
    for call in WIRE_CALLS:
        assert call in APP, call
    assert "function wireViewListeners() {" in MODULE
    assert "function wireEditListeners() {" in FORM
    assert "function wireCreateListeners() {" in FORM


def test_registry_replaces_the_one_line_forwarders() -> None:
    # 보강 (라): 한 줄 전달 함수는 없다.
    assert not re.search(r"function \w+\(\.\.\.a\) \{ return automation(M|FormM)odule\(\)\.", APP)
    for call in REGISTRY_CALLS:
        assert call in APP, call
    assert "app.openClawAutomation();" in APP
    assert "app.clawAutomation.hidden = true;" in APP


def test_modules_expose_factories_and_stay_under_1000_lines() -> None:
    assert "window.PadiemChatAutomationModule = {" in MODULE
    assert "window.PadiemChatAutomationFormModule = {" in FORM
    assert "create(deps) {" in MODULE and "create(deps) {" in FORM
    assert len(MODULE.splitlines()) <= 1000 and len(FORM.splitlines()) <= 1000
    for name in NAMES_A:
        assert f"function {name}(" in MODULE, name
    for name in NAMES_B:
        assert f"function {name}(" in FORM, name


def test_context_is_the_single_registry_with_live_shared_reads() -> None:
    # 보강 (다): app.js가 공유 이름을 라이브 접근자로 올린다.
    for name in SHARED_READS:
        assert f"get {name}() {{ return {name}; }}" in APP, name
    # 보강 (라): 중복 등록은 예외다.
    assert "duplicate module registration" in CONTEXT
    assert "duplicate name" in CONTEXT
    # 모듈 본문은 공유 읽기를 deps로, 자기 소유는 클로저 이름으로 쓴다.
    assert "deps.authState.authenticated" in MODULE
    assert "deps.clawAutomationList.replaceChildren();" in MODULE
    assert "deps.clawAutomationList" in FORM  # 폼도 목록 DOM을 컨텍스트에서 읽는다
    assert "deps.clawAutomationRetry" not in MODULE + FORM
    assert "deps.clawAutomationEditingRuleId" not in MODULE + FORM
    assert "deps.automationViewMounted" not in MODULE
    # 모듈 간 경계 2개는 등록부를 거친다.
    assert "deps.openClawAutomationEdit(rule);" in MODULE
    assert "deps.loadClawAutomationRules();" in FORM


_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
__STRICT__

function makeElement(tag) {
  const node = {
    tagName: String(tag || "div").toUpperCase(),
    className: "", textContent: "", hidden: false, disabled: false, value: "",
    dataset: {}, children: [], listeners: {}, attrs: {},
    scrollTop: 0, scrollHeight: 0, clientHeight: 0,
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return this.attrs[k] === undefined ? null : this.attrs[k]; },
    append(...xs) { this.children.push(...xs); },
    appendChild(x) { this.children.push(x); return x; },
    replaceChildren(...xs) { this.children = xs; },
    focus() { this.focused = (this.focused || 0) + 1; },
    scrollIntoView() { this.scrolled = (this.scrolled || 0) + 1; },
    rect: { top: 10, bottom: 60 },
    getBoundingClientRect() { return this.rect; },
    closest(sel) { return sel === ".automation-view" ? this._view || null : null; },
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
  };
  return node;
}

const byId = {};
for (const id of ["automationViewBody", "automationViewTitle", "automationView", "automationViewSignedOut",
  "automationNavButton",
  "clawAutomation", "clawAutomationList", "clawAutomationLoading", "clawAutomationError",
  "clawAutomationForbidden", "clawAutomationEmpty", "clawAutomationRetry", "clawAutomationToggleStatus",
  "clawAutomationEditForm", "clawAutomationEditName", "clawAutomationEditKind", "clawAutomationEditTimezone",
  "clawAutomationEditDaypart", "clawAutomationEditDaypartField", "clawAutomationEditInterval",
  "clawAutomationEditIntervalField", "clawAutomationEditCron", "clawAutomationEditCronField",
  "clawAutomationEditStatus", "clawAutomationEditSubmit", "clawAutomationEditCancel",
  "clawAutomationCreateCancel", "clawAutomationCreate",
  "clawAutomationCreateForm", "clawAutomationCreateName", "clawAutomationCreateKind",
  "clawAutomationCreateTimezone", "clawAutomationCreateDaypart", "clawAutomationCreateDaypartField",
  "clawAutomationCreateInterval", "clawAutomationCreateIntervalField", "clawAutomationCreateCron",
  "clawAutomationCreateCronField", "clawAutomationCreateStatus", "clawAutomationCreateSubmit",
  "clawAutomationCreateToggle", "clawAutomationCreateOpen", "shell"]) {
  byId[id] = makeElement("div");
}
const documentShim = {
  getElementById: (id) => byId[id] || null,
  createElement: (tag) => makeElement(tag),
};

const requests = [];
let fetchImpl = async () => ({ ok: true, status: 200, json: async () => ({ ok: true, rules: [] }) });
const live = {
  authState: { authenticated: true },
  shell: byId.shell,
  clawWorkspace: makeElement("div"),
  uiT: (key) => "T:" + key,
  setNavActive() { live.calls.push("setNavActive"); },
  closeSidebar() { live.calls.push("closeSidebar"); },
  clearClawWait() { live.calls.push("clearClawWait"); },
  syncClawRunHistoryVisibility() { live.calls.push("syncClawRunHistoryVisibility"); },
  calls: [],
};
// 원래 app.js 클로저 getter가 읽던 DOM 참조들을 라이브로 노출한다.
for (const id of ["clawAutomation", "clawAutomationList", "clawAutomationLoading", "clawAutomationError",
  "clawAutomationForbidden", "clawAutomationEmpty", "clawAutomationRetry", "clawAutomationToggleStatus",
  "clawAutomationEditForm", "clawAutomationEditName", "clawAutomationEditKind", "clawAutomationEditTimezone",
  "clawAutomationEditDaypart", "clawAutomationEditDaypartField", "clawAutomationEditInterval",
  "clawAutomationEditIntervalField", "clawAutomationEditCron", "clawAutomationEditCronField",
  "clawAutomationEditStatus", "clawAutomationEditSubmit"]) {
  Object.defineProperty(live, id, { get: () => byId[id] || null });
}

const sandbox = {
  document: documentShim,
  fetch: (url, init) => { requests.push({ url: String(url), init }); return fetchImpl(url, init); },
  JSON, Set, Object, Array, Number, String, encodeURIComponent, Error,
  console: { error() {} }, setTimeout,
};
sandbox.window = { ...sandbox };
sandbox.__LIVE__ = live;
sandbox.r5StrictDeps = r5StrictDeps;
const __SHARED__ = '__SHARED_JSON__';
sandbox.__SHARED__ = __SHARED__;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(__CONTEXT__, "utf8"), sandbox, { filename: "chat-app-context.js" });
vm.runInContext(fs.readFileSync(__MODULE_A__, "utf8"), sandbox, { filename: "chat-automation-module.js" });
vm.runInContext(fs.readFileSync(__MODULE_B__, "utf8"), sandbox, { filename: "chat-automation-form-module.js" });
vm.runInContext(`
  const buildDeps = (label) => {
    // 컨텍스트 수준: 읽기는 누락 시 즉시 실패(strict get), 쓰기는 컨텍스트가
    // 자기 속성(provide·공유 DOM 참조)을 붙일 수 있어야 한다.
    const target = {};
    for (const n of __SHARED__) {
      Object.defineProperty(target, n, {
        get() {
          const v = __LIVE__[n];
          return typeof v === "function" ? v.bind(__LIVE__) : v;
        },
        set(value) { __LIVE__[n] = value; },
      });
    }
    return new Proxy(target, {
      get(obj, prop) {
        if (typeof prop === "symbol" || prop in obj) return Reflect.get(obj, prop);
        throw new Error((label || "deps") + "." + String(prop) + " is not defined in the test deps");
      },
      set(obj, prop, value) {
        obj[prop] = value;
        return true;
      },
    });
  };
  // app.js와 같은 순서(보강 라): 컨텍스트 생성 → 자동화 → 폼 제공.
  globalThis.app = window.PadiemChatAppContext.create(buildDeps("context.shared"));
  globalThis.automation = app.provide("automation",
    window.PadiemChatAutomationModule.create(app));
  globalThis.automationForm = app.provide("automationForm",
    window.PadiemChatAutomationFormModule.create(app));
`, sandbox);

(async () => {
  const assert = require("assert");
  // vm 내부의 globalThis는 샌드박스다 — 호스트 배터리는 sandbox에서 읽는다.
  const A = sandbox.automation;
  const B = sandbox.automationForm;
  const el = (id) => byId[id];
  const checks = {};

  // ── 보강 (가): create()는 deps를 읽지 않는다 (엄격 빈 deps로도 예외 없음) ──
  const strictEmpty = r5StrictDeps({}, "strict.empty");
  assert.ok(sandbox.window.PadiemChatAutomationModule.create(strictEmpty));
  assert.ok(sandbox.window.PadiemChatAutomationFormModule.create(strictEmpty));
  checks.create_reads_no_deps = true;

  // ── 보강 (라): 중복 등록은 예외 ────────────────────────────────────────────
  let threw = null;
  try { sandbox.app.provide("automation", A); } catch (e) { threw = e; }
  assert.ok(threw && /duplicate module registration/.test(String(threw)), String(threw));
  checks.duplicate_throws = true;

  // ── A: 상태 삼인조 + 재시도 규칙 ──────────────────────────────────────────
  A.setClawAutomationLoading();
  assert.equal(el("clawAutomationList").children.length, 0);
  assert.equal(el("clawAutomationLoading").hidden, false);
  assert.equal(el("clawAutomationLoading").textContent, "T:claw-automation-loading");
  A.setClawAutomationError();
  assert.equal(el("clawAutomationError").textContent, "T:claw-automation-error");
  assert.equal(el("clawAutomationRetry").hidden, false, "재시도는 실패 때만");
  A.setClawAutomationForbidden();
  assert.equal(el("clawAutomationForbidden").textContent, "T:claw-automation-forbidden");
  assert.equal(el("clawAutomationRetry").hidden, true, "권한 거절엔 재시도가 없다");
  A.resetClawAutomationState();
  assert.equal(el("clawAutomationError").hidden, true);
  checks.state_trio = true;

  // ── A: 렌더(빈 목록 / 정식 / 격리) ────────────────────────────────────────
  A.renderClawAutomationRules([]);
  assert.equal(el("clawAutomationEmpty").hidden, false);
  assert.equal(el("clawAutomationEmpty").textContent, "T:claw-automation-empty");
  const canonical = { rule_id: "r1", name: "견적 자동화", schedule_kind: "cron",
    schedule_expression: "0 9 * * 1-5", schedule_timezone: "Asia/Seoul",
    enabled: true, target_source: "manual", output_type: "docx",
    background_eligible: true, authority_status: "canonical" };
  const legacy = Object.assign({}, canonical, { rule_id: "r2", background_eligible: false });
  A.renderClawAutomationRules([canonical, legacy]);
  const list = el("clawAutomationList");
  assert.equal(list.children.length, 2);
  const row0Buttons = list.children[0].children.filter((n) => n.tagName === "BUTTON");
  assert.equal(row0Buttons.length, 2, "정식 행: 토글 + 편집");
  assert.equal(row0Buttons[0].dataset.ruleToggleRuleId, "r1");
  assert.equal(row0Buttons[1].dataset.ruleEditRuleId, "r1");
  A.renderClawAutomationRules([legacy]);
  assert.equal(list.children[0].dataset.ruleAuthority, "legacy_quarantined");
  assert.equal(list.children[0].children.filter((n) => n.tagName === "BUTTON").length, 0, "격리 행엔 토글이 없다");
  checks.render = true;

  // ── 보강 (나): wire 뒤 리스너가 달린다 ────────────────────────────────────
  assert.equal((el("automationNavButton").listeners.click || []).length, 0);
  assert.equal((el("clawAutomationRetry").listeners.click || []).length, 0);
  A.wireViewListeners();
  assert.equal(el("automationNavButton").listeners.click.length, 1);
  assert.equal(el("clawAutomationRetry").listeners.click.length, 1);
  assert.equal((el("clawAutomationEditForm").listeners.submit || []).length, 0);
  B.wireEditListeners();
  assert.equal(el("clawAutomationEditForm").listeners.submit.length, 1);
  assert.equal(el("clawAutomationEditKind").listeners.change.length, 1);
  assert.equal(el("clawAutomationEditCancel").listeners.click.length, 1);
  B.wireCreateListeners();
  assert.equal(el("clawAutomationCreateForm").listeners.submit.length, 1);
  assert.equal(el("clawAutomationCreateKind").listeners.change.length, 1);
  assert.equal(el("clawAutomationCreateCancel").listeners.click.length, 1);
  assert.equal(el("clawAutomationCreate").listeners.toggle.length, 1);
  assert.equal(el("clawAutomationCreateOpen").listeners.click.length, 1);
  checks.wire_attaches = true;

  // ── A: 토글 PATCH(정확한 payload + in-flight 중복 차단) ───────────────────
  let mark = requests.length;
  await A.toggleClawAutomationRule("r1", false, null);
  const patch = requests.slice(mark).find((r) => r.init && r.init.method === "PATCH");
  assert.ok(patch, "토글 PATCH 전송");
  assert.equal(patch.url, "/api/claw/automation/rules/r1/enabled");
  assert.deepEqual(JSON.parse(patch.init.body), { enabled: false });
  assert.equal(el("clawAutomationToggleStatus").textContent, "T:claw-automation-toggle-saved");
  // 진행 중인 규칙은 건너뛴다: 첫 토글을 게이트로 묶어 둔 채 같은 규칙을 다시
  // 토글하면 두 번째 요청은 나가지 않는다(Set은 이제 모듈 클로저 소유다).
  let releaseToggle;
  fetchImpl = () => new Promise((resolve) => { releaseToggle = resolve; });
  const inFlight = A.toggleClawAutomationRule("r1", true, null);
  mark = requests.length;
  await A.toggleClawAutomationRule("r1", false, null);
  assert.ok(!requests.slice(mark).some((r) => r.init && r.init.method === "PATCH"),
    "진행 중 규칙은 건너뛴다");
  fetchImpl = async () => ({ ok: true, status: 200, json: async () => ({ ok: true, rules: [] }) });
  releaseToggle({ ok: true, status: 200, json: async () => ({ ok: true }) });
  await inFlight;
  checks.toggle_patch = true;

  // ── A: 목록 적재(성공 / 403 / 실패) ───────────────────────────────────────
  fetchImpl = async () => ({ ok: true, status: 200, json: async () => ({ ok: true, rules: [canonical] }) });
  await A.loadClawAutomationRules();
  assert.equal(list.children.length, 1, "성공 시 규칙 렌더");
  fetchImpl = async () => ({ ok: false, status: 403, json: async () => ({ ok: false, error: { code: "owner_role_required" } }) });
  await A.loadClawAutomationRules();
  assert.equal(el("clawAutomationForbidden").hidden, false, "403은 권한 거절 안내");
  fetchImpl = async () => { throw new Error("network down"); };
  await A.loadClawAutomationRules();
  assert.equal(el("clawAutomationError").hidden, false, "실패는 오류 안내 + 재시도");
  checks.load_paths = true;

  // ── A: 마운트(setter 쓰기) + 열기(라이브 deps, 게스트/로그인) ─────────────
  // automationViewMounted는 이제 모듈 클로저 소유다(보강 가) — 행위로 검증:
  // mount는 한 번만 실행되고(가드), 실제로 섹션을 automationViewBody로 옮긴다.
  A.mountAutomationView();
  A.mountAutomationView();
  assert.ok(el("automationViewBody").children.includes(el("clawAutomation")));
  assert.equal(el("automationViewBody").children.length, 1, "두 번 마운트해도 하나만");
  assert.equal(el("clawAutomation").attrs["aria-labelledby"], "automationViewTitle");

  live.calls.length = 0;
  live.authState.authenticated = false;
  A.openClawAutomation();
  assert.equal(live.shell.dataset.state, "automation");
  assert.deepEqual(live.calls, ["clearClawWait", "syncClawRunHistoryVisibility", "setNavActive", "closeSidebar"]);
  assert.equal(el("clawAutomation").hidden, true, "로그아웃 상태는 섹션을 숨기고");
  assert.equal(el("automationViewSignedOut").hidden, false, "로그아웃 안내를 보인다");

  live.calls.length = 0;
  live.authState.authenticated = true;
  fetchImpl = async () => ({ ok: true, status: 200, json: async () => ({ ok: true, rules: [] }) });
  A.openClawAutomation();
  assert.equal(el("clawAutomation").hidden, false, "로그인 상태는 섹션을 보인다");
  assert.deepEqual(live.calls, ["clearClawWait", "syncClawRunHistoryVisibility", "setNavActive", "closeSidebar"]);
  checks.mount_open = true;

  // ── 보강 (라): 등록부 경로로 열기 ─────────────────────────────────────────
  live.calls.length = 0;
  fetchImpl = async () => ({ ok: true, status: 200, json: async () => ({ ok: true, rules: [] }) });
  await sandbox.app.openClawAutomation();
  assert.deepEqual(live.calls, ["clearClawWait", "syncClawRunHistoryVisibility", "setNavActive", "closeSidebar"]);
  checks.registry_path = true;

  // ── B: 편집 열기/채우기/종류 전환/닫기 ────────────────────────────────────
  el("clawAutomationEditKind").value = "interval";
  B.openClawAutomationEdit({ rule_id: "r1", name: "이름", schedule_kind: "interval",
    schedule_expression: "every 30m", schedule_timezone: "Asia/Seoul" });
  assert.equal(el("clawAutomationEditName").value, "이름");
  assert.equal(el("clawAutomationEditInterval").value, "every 30m");
  assert.equal(el("clawAutomationEditDaypartField").hidden, true);
  assert.equal(el("clawAutomationEditIntervalField").hidden, false);
  assert.equal(el("clawAutomationEditForm").hidden, false);
  assert.equal(B.clawAutomationEditExpression(), "every 30m");
  el("clawAutomationEditKind").value = "cron";
  B.syncClawAutomationEditFields();
  assert.equal(el("clawAutomationEditCronField").hidden, false);
  assert.equal(el("clawAutomationEditIntervalField").hidden, true);
  B.closeClawAutomationEdit();
  assert.equal(el("clawAutomationEditForm").hidden, true);
  checks.edit_form = true;

  // ── B: 편집 PATCH(4개 필드뿐) + 실패 시 폼 유지 ───────────────────────────
  B.openClawAutomationEdit({ rule_id: "r1", name: "n", schedule_kind: "daypart",
    schedule_expression: "아침", schedule_timezone: "Asia/Seoul" });
  mark = requests.length;
  fetchImpl = async () => ({ ok: true, status: 200, json: async () => ({ ok: true }) });
  const event = { preventDefault() {} };
  await B.submitClawAutomationEdit(event);
  const editPatch = requests.slice(mark).find((r) => r.init && r.init.method === "PATCH");
  assert.ok(editPatch, "편집 PATCH 전송");
  assert.equal(editPatch.url, "/api/claw/automation/rules/r1");
  assert.deepEqual(JSON.parse(editPatch.init.body), {
    name: "n", schedule_kind: "daypart", schedule_expression: "아침", schedule_timezone: "Asia/Seoul",
  });
  assert.equal(live.clawAutomationEditingRuleId, null, "성공 시 폼을 닫는다");

  B.openClawAutomationEdit({ rule_id: "r1", name: "n", schedule_kind: "daypart",
    schedule_expression: "아침", schedule_timezone: "Asia/Seoul" });
  fetchImpl = async () => ({ ok: false, status: 400, json: async () => ({ ok: false, error: { code: "automation_rule_not_mutable" } }) });
  await B.submitClawAutomationEdit(event);
  assert.equal(el("clawAutomationEditStatus").textContent, "T:claw-automation-toggle-not-mutable");
  assert.equal(el("clawAutomationEditForm").hidden, false, "실패 시 폼이 열려 있다");
  assert.equal(el("clawAutomationEditSubmit").disabled, false, "진행 표시가 풀려 제출 단추가 돌아온다");
  checks.edit_patch = true;

  // ── B: 생성 POST(권한 필드 없음) + 스크롤 ─────────────────────────────────
  el("clawAutomationCreateKind").value = "daypart";
  el("clawAutomationCreateName").value = "신규 규칙";
  el("clawAutomationCreateTimezone").value = "Asia/Seoul";
  el("clawAutomationCreateDaypart").value = "아침";
  mark = requests.length;
  fetchImpl = async () => ({ ok: true, status: 200, json: async () => ({ ok: true }) });
  await B.submitClawAutomationCreate(event);
  const createPost = requests.slice(mark).find((r) => r.init && r.init.method === "POST");
  assert.ok(createPost, "생성 POST 전송");
  assert.equal(createPost.url, "/api/claw/automation/rules");
  const createBody = JSON.parse(createPost.init.body);
  assert.equal(createBody.name, "신규 규칙");
  assert.ok(!("authority" in createBody) && !("rule_id" in createBody), "권한·id 필드를 만들지 않는다");
  assert.equal(el("clawAutomationCreateSubmit").disabled, false, "생성 진행 표시가 풀린다");

  const host = makeElement("div");
  host.rect = { top: 0, bottom: 60 };
  el("clawAutomation")._view = host;
  el("clawAutomationCreate").rect = { top: 500, bottom: 550 };
  B.scrollClawAutomationCreateIntoView();
  assert.equal(host.scrollTop, 492, "폼이 화면 아래면 host를 폼 높이만큼 올린다");
  el("clawAutomationCreate").rect = { top: 10, bottom: 60 };
  B.scrollClawAutomationCreateIntoView();
  assert.equal(host.scrollTop, 492, "이미 보이는 폼은 그대로 둔다");
  checks.create_post = true;

  return { ok: true, checks };
})().then((r) => console.log("RESULT_JSON " + JSON.stringify(r))).catch((e) => {
  console.log("RESULT_JSON " + JSON.stringify({ ok: false, error: String((e && e.stack) || e) }));
});
"""


def test_module_behavior_in_node_vm() -> None:
    strict = (Path(__file__).resolve().parent / "_r5_strict_deps.js").read_text(encoding="utf-8")
    harness = (_HARNESS
               .replace("__STRICT__", strict)
               .replace("__CONTEXT__", json.dumps(str(STATIC / "chat-app-context.js")))
               .replace("__MODULE_A__", json.dumps(str(STATIC / "chat-automation-module.js")))
               .replace("__MODULE_B__", json.dumps(str(STATIC / "chat-automation-form-module.js")))
               .replace("'__SHARED_JSON__'", json.dumps(sorted(HARNESS_SHARED))))
    with tempfile.TemporaryDirectory() as directory:
        harness_path = Path(directory) / "a1_module_harness.cjs"
        harness_path.write_text(harness, encoding="utf-8")
        result = subprocess.run(["node", str(harness_path)], capture_output=True, text=True,
                                encoding="utf-8", timeout=120)
    lines = [l for l in result.stdout.splitlines() if l.startswith("RESULT_JSON ")]
    assert lines, f"harness produced no result: {result.stdout[-800:]} {result.stderr[-400:]}"
    payload = json.loads(lines[-1][len("RESULT_JSON "):])
    assert payload.get("ok") is True, payload
    assert set(payload["checks"]) == {
        "create_reads_no_deps", "duplicate_throws", "state_trio", "render",
        "wire_attaches", "toggle_patch", "load_paths", "mount_open", "registry_path",
        "edit_form", "edit_patch", "create_post",
    }, payload["checks"]
