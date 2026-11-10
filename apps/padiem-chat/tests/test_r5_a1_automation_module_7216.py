"""R5 A1 — 자동화 모듈 계약 (규칙 목록·토글 + 편집·생성 폼, 28함수).

app.js의 자동화 구역 28개 함수가 chat-automation-module.js(13개)와
chat-automation-form-module.js(15개)로 이동했고, app.js는 남은 코드가 참조하는
이름에 한해 같은 이름의 한 줄 전달 함수를 유지한다(deps를 거치는 모듈 간·모듈 내
호출에는 전달 함수가 필요하다 — 5b 관례). 이 시험은 (1) 실제 모듈 본문을 Node
vm에서 실행해 28개 함수를 전부 직접 호출하고, (2) deps getter 읽기와 setter
쓰기를 확인하며, (3) index.html 로드 순서·전달 함수·남아 있는 선언·리스너를
확인한다. 선언 블록과 최상위 리스너 등록은 R5 B1에서 옮긴다 — 여기서는 app.js에
남아 있어야 한다(동작 불변).
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
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
ASYNC_NAMES = {"loadClawAutomationRules", "toggleClawAutomationRule",
               "submitClawAutomationEdit", "submitClawAutomationCreate"}
# deps를 거쳐 호출되는 옮긴 함수(모듈 내·모듈 간) + 남은 app.js가 참조하는 이름
FORWARDER_NAMES = tuple(sorted(set(NAMES_A) | set(NAMES_B) - {"focusRuleEditAfterReload"}))

MOVED_MARKERS = (
    'deps.uiT("claw-automation-forbidden");',
    'row.dataset.ruleAuthority = "legacy_quarantined";',
    'body: JSON.stringify({ enabled: nextEnabled }),',
    'deps.clawAutomationInFlightRules.delete(ruleId);',
    'deps.shell.dataset.state = "automation";',
    'deps.clawAutomationEditingRuleId = rule.rule_id;',
    'fetch("/api/claw/automation/rules", {',
)


def test_index_loads_both_automation_modules_before_app() -> None:
    for name in ("./chat-automation-module.js", "./chat-automation-form-module.js"):
        assert INDEX.count(name) == 1, name
    assert INDEX.index("./chat-streaming-module.js") < INDEX.index("./chat-automation-module.js")
    assert INDEX.index("./chat-automation-module.js") < INDEX.index("./chat-automation-form-module.js")
    assert INDEX.index("./chat-automation-form-module.js") < INDEX.index("./app.js")


def test_app_keeps_one_line_forwarders_for_every_reachable_moved_function() -> None:
    for name in FORWARDER_NAMES:
        prefix = "async function" if name in ASYNC_NAMES else "function"
        mod = "automationFormModule()" if name in NAMES_B else "automationModule()"
        line = f"{prefix} {name}(...a) {{ return {mod}.{name}(...a); }}"
        assert line in APP, name
        assert APP.count(f"function {name}(") == 1, name
    # deps 호출이 없는 미호출 함수(focusRuleEditAfterReload)는 전달 함수 없이 본문째 이동한다.
    assert APP.count("function focusRuleEditAfterReload(") == 0


def test_moved_bodies_live_only_in_the_modules() -> None:
    for marker in MOVED_MARKERS:
        assert marker in MODULE or marker in FORM, marker
        assert marker not in APP, marker


def test_declaration_block_and_listeners_stay_in_app_until_b1() -> None:
    assert "let clawAutomationCreateInFlight = false;" in APP
    assert "const clawAutomationInFlightRules = new Set();" in APP
    assert 'clawAutomationEditForm.addEventListener("submit"' in APP
    assert 'clawAutomationEditKind.addEventListener("change", syncClawAutomationEditFields);' in APP
    assert 'clawAutomationEditCancel.addEventListener("click", () => closeClawAutomationEdit());' in APP
    assert 'clawAutomationCreateForm.addEventListener("submit"' in APP
    assert 'clawAutomationCreateKind.addEventListener("change", syncClawAutomationCreateFields);' in APP
    assert 'automationNavButton.addEventListener("click", openClawAutomation)' in APP
    assert 'clawAutomationRetry.addEventListener("click", () => void loadClawAutomationRules());' in APP
    assert "if (window.location.hash === AUTOMATION_ROUTE_HASH) openClawAutomation();" in APP


def test_modules_expose_one_factory_each_and_stay_under_1000_lines() -> None:
    assert "window.PadiemChatAutomationModule = {" in MODULE
    assert "window.PadiemChatAutomationFormModule = {" in FORM
    assert "create(deps) {" in MODULE and "create(deps) {" in FORM
    assert len(MODULE.splitlines()) <= 1000 and len(FORM.splitlines()) <= 1000
    for name in NAMES_A:
        assert f"function {name}(" in MODULE, name
    for name in NAMES_B:
        assert f"function {name}(" in FORM, name


A_GETTERS = {
    # 옮긴 함수(모듈 내 호출도 deps를 거친다 — 5b 관례) + 모듈 간 경계 1개
    # (openClawAutomation은 deps로 호출되지 않는다 — 남은 app.js만 부른다)
    "resetClawAutomationState", "setClawAutomationLoading", "setClawAutomationError",
    "setClawAutomationForbidden", "renderClawAutomationRules", "loadClawAutomationRules",
    "setClawAutomationToggleStatus", "findRuleToggleButton", "focusRuleToggleAfterReload",
    "toggleClawAutomationRule", "mountAutomationView",
    "setClawAutomationRetryVisible", "openClawAutomationEdit",
    # 남은 클로저 이름
    "authState", "automationViewMounted", "clawAutomation", "clawAutomationEmpty",
    "clawAutomationError", "clawAutomationForbidden", "clawAutomationInFlightRules",
    "clawAutomationList", "clawAutomationLoading", "clawAutomationRetry",
    "clawAutomationToggleStatus", "clawWorkspace", "clearClawWait", "closeSidebar",
    "setNavActive", "shell", "syncClawRunHistoryVisibility", "uiT",
}
A_SETTERS = {"automationViewMounted"}
B_GETTERS = {
    # 옮긴 함수 + 규칙 목록 재적재(모듈 간 경계)
    "setClawAutomationEditStatus", "syncClawAutomationEditFields", "clawAutomationEditExpression",
    "findRuleEditButton", "closeClawAutomationCreate", "closeClawAutomationEdit",
    "resetClawAutomationCreateForm", "setClawAutomationCreateStatus",
    "syncClawAutomationCreateFields", "clawAutomationCreateExpression", "loadClawAutomationRules",
    # 남은 클로저 이름
    "clawAutomation", "clawAutomationCreate", "clawAutomationCreateCron",
    "clawAutomationCreateCronField", "clawAutomationCreateDaypart", "clawAutomationCreateDaypartField",
    "clawAutomationCreateForm", "clawAutomationCreateInFlight", "clawAutomationCreateInterval",
    "clawAutomationCreateIntervalField", "clawAutomationCreateKind", "clawAutomationCreateName",
    "clawAutomationCreateOpen", "clawAutomationCreateOutput", "clawAutomationCreateStatus",
    "clawAutomationCreateSubmit", "clawAutomationCreateTarget", "clawAutomationCreateTask",
    "clawAutomationCreateTimezone", "clawAutomationCreateToggle", "clawAutomationEditCron",
    "clawAutomationEditCronField", "clawAutomationEditDaypart", "clawAutomationEditDaypartField",
    "clawAutomationEditForm", "clawAutomationEditInFlight", "clawAutomationEditInterval",
    "clawAutomationEditIntervalField", "clawAutomationEditKind", "clawAutomationEditName",
    "clawAutomationEditStatus", "clawAutomationEditSubmit", "clawAutomationEditTimezone",
    "clawAutomationEditingRuleId", "clawAutomationList", "uiT",
}
B_SETTERS = {"clawAutomationCreateInFlight", "clawAutomationEditInFlight", "clawAutomationEditingRuleId"}


def _connect_block(module_global: str) -> tuple[set[str], set[str]]:
    start = APP.index(f"window.{module_global}.create({{")
    block = APP[start:APP.index("});", start)]
    return set(re.findall(r"get (\w+)\(\)", block)), set(re.findall(r"set (\w+)\(value\)", block))


def test_deps_count_matches_the_mover_analysis() -> None:
    a_get, a_set = _connect_block("PadiemChatAutomationModule")
    assert a_get == A_GETTERS, sorted(a_get ^ A_GETTERS)
    assert a_set == A_SETTERS, sorted(a_set ^ A_SETTERS)
    b_get, b_set = _connect_block("PadiemChatAutomationFormModule")
    assert b_get == B_GETTERS, sorted(b_get ^ B_GETTERS)
    assert b_set == B_SETTERS, sorted(b_set ^ B_SETTERS)


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
  "clawAutomation", "clawAutomationList", "clawAutomationLoading", "clawAutomationError",
  "clawAutomationForbidden", "clawAutomationEmpty", "clawAutomationRetry", "clawAutomationToggleStatus",
  "clawAutomationEditForm", "clawAutomationEditName", "clawAutomationEditKind", "clawAutomationEditTimezone",
  "clawAutomationEditDaypart", "clawAutomationEditDaypartField", "clawAutomationEditInterval",
  "clawAutomationEditIntervalField", "clawAutomationEditCron", "clawAutomationEditCronField",
  "clawAutomationEditStatus", "clawAutomationEditSubmit", "clawAutomationCreateForm",
  "clawAutomationCreateName", "clawAutomationCreateKind", "clawAutomationCreateTimezone",
  "clawAutomationCreateDaypart", "clawAutomationCreateDaypartField", "clawAutomationCreateInterval",
  "clawAutomationCreateIntervalField", "clawAutomationCreateCron", "clawAutomationCreateCronField",
  "clawAutomationCreateStatus", "clawAutomationCreateSubmit", "clawAutomationCreateToggle",
  "clawAutomationCreate",
  "clawAutomationCreateOpen", "shell"]) {
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
  automationViewMounted: false,
  clawAutomationInFlightRules: new Set(),
  clawAutomationEditingRuleId: null,
  clawAutomationCreateInFlight: false,
  clawAutomationEditInFlight: false,
  shell: byId.shell,
  clawWorkspace: makeElement("div"),
  uiT: (key) => "T:" + key,
  setNavActive() { live.calls.push("setNavActive"); },
  closeSidebar() { live.calls.push("closeSidebar"); },
  clearClawWait() { live.calls.push("clearClawWait"); },
  syncClawRunHistoryVisibility() { live.calls.push("syncClawRunHistoryVisibility"); },
  calls: [],
};
// 남은 app.js의 연결부처럼 DOM 참조는 getter로 살아 있는 값을 읽는다.
for (const id of Object.keys(byId)) {
  if (live[id] === undefined) {
    Object.defineProperty(live, id, { get: () => byId[id] || null });
  }
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
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(__MODULE_A__, "utf8"), sandbox, { filename: "chat-automation-module.js" });
vm.runInContext(fs.readFileSync(__MODULE_B__, "utf8"), sandbox, { filename: "chat-automation-form-module.js" });
vm.runInContext(`
  let apiA = null;
  let apiB = null;
  const buildDeps = (names, label) => {
    const target = {};
    for (const n of names) {
      Object.defineProperty(target, n, {
        get() {
          // 옮긴 함수는 모듈 API(전달 함수와 같은 대상), 나머지는 live 기록.
          if (n === "loadClawAutomationRules") return apiA.loadClawAutomationRules;
          if (n === "openClawAutomationEdit") return apiB.openClawAutomationEdit;
          if (apiA && n in apiA) return apiA[n];
          if (apiB && n in apiB) return apiB[n];
          const v = __LIVE__[n];
          return typeof v === "function" ? v.bind(__LIVE__) : v;
        },
        set(value) { __LIVE__[n] = value; },
      });
    }
    return r5StrictDeps(target, label);
  };
  apiA = window.PadiemChatAutomationModule.create(buildDeps(__A_DEPS__, "automationDeps"));
  apiB = window.PadiemChatAutomationFormModule.create(buildDeps(__B_DEPS__, "automationFormDeps"));
  globalThis.A = apiA;
  globalThis.B = apiB;
`, sandbox);

(async () => {
  const assert = require("assert");
  // vm 컨텍스트(sandbox)의 전역에 기록된 모듈 인스턴스를 호스트에서 읽는다.
  const A = sandbox.A;
  const B = sandbox.B;
  const el = (id) => byId[id];
  const checks = {};

  // ── A: 상태 삼인조 + 재시도 표시 규칙 ─────────────────────────────────────
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

  // ── A: 렌더(빈 목록 / 정식 / 격리) + 토글 위임 ────────────────────────────
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
  A.renderClawAutomationRules([]); // 토글 위임 검사용 리렌더 직전 정리
  A.renderClawAutomationRules([canonical]);
  const button = list.children[0].children.filter((n) => n.tagName === "BUTTON")[0];
  assert.equal(list.children[0].dataset.ruleAuthority, undefined);
  A.renderClawAutomationRules([legacy]);
  assert.equal(list.children[0].dataset.ruleAuthority, "legacy_quarantined");
  assert.equal(list.children[0].children.filter((n) => n.tagName === "BUTTON").length, 0, "격리 행엔 토글이 없다");
  checks.render = true;

  // ── A: 토글 위임(행 버튼 클릭 → deps.toggleClawAutomationRule → PATCH) ────
  // fetch를 게이트로 걸어 클릭이 즉시 PATCH를 낸다는 것만 확인하고 푼다.
  let mark = requests.length;
  let releaseDelegated;
  fetchImpl = () => new Promise((resolve) => { releaseDelegated = resolve; });
  button.listeners.click[0]();
  assert.ok(requests.slice(mark).some((r) => r.init && r.init.method === "PATCH"), "버튼 클릭이 토글 PATCH로 이어진다");
  releaseDelegated({ ok: true, status: 200, json: async () => ({ ok: true }) });
  // 위임 토글의 성공 경로는 목록 재적재(GET)까지 이어진다 — 즉답으로 바꾸고
  // 진행 표시가 풀릴 때까지 대기한다.
  fetchImpl = async () => ({ ok: true, status: 200, json: async () => ({ ok: true, rules: [] }) });
  for (let i = 0; i < 100 && live.clawAutomationInFlightRules.has("r1"); i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  assert.equal(live.clawAutomationInFlightRules.has("r1"), false, "위임 토글이 끝나면 진행 표시가 풀린다");

  // ── A: 토글 PATCH(정확한 payload + in-flight 중복 차단) ───────────────────
  fetchImpl = async () => ({ ok: true, status: 200, json: async () => ({ ok: true, rules: [] }) });
  mark = requests.length;
  await A.toggleClawAutomationRule("r1", false, null);
  const patch = requests.slice(mark).find((r) => r.init && r.init.method === "PATCH");
  assert.ok(patch, "토글 PATCH 전송");
  assert.equal(patch.url, "/api/claw/automation/rules/r1/enabled");
  assert.deepEqual(JSON.parse(patch.init.body), { enabled: false });
  assert.equal(el("clawAutomationToggleStatus").textContent, "T:claw-automation-toggle-saved");
  live.clawAutomationInFlightRules.add("rX");
  await A.toggleClawAutomationRule("rX", true, null);
  assert.ok(!requests.some((r) => String(r.url).includes("/rules/rX/")), "진행 중 규칙은 건너뛴다");
  live.clawAutomationInFlightRules.delete("rX");
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
  assert.equal(el("clawAutomationRetry").hidden, false);
  checks.load_paths = true;

  // ── A: 마운트(setter 쓰기) + 열기(라이브 deps, 게스트/로그인) ─────────────
  live.automationViewMounted = false;
  A.mountAutomationView();
  assert.equal(live.automationViewMounted, true, "setter가 클로저 기록에 쓴다");
  assert.ok(el("automationViewBody").children.includes(el("clawAutomation")));
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

  // ── B: 편집 열기/채우기/종류 전환/닫기 ────────────────────────────────────
  el("clawAutomationEditKind").value = "interval";
  B.openClawAutomationEdit({ rule_id: "r1", name: "이름", schedule_kind: "interval",
    schedule_expression: "every 30m", schedule_timezone: "Asia/Seoul" });
  assert.equal(live.clawAutomationEditingRuleId, "r1", "편집 규칙 id가 deps로 기록된다");
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
  assert.equal(live.clawAutomationEditingRuleId, null);
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
  assert.equal(live.clawAutomationEditInFlight, false, "진행 표시가 풀린다");
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
  assert.equal(live.clawAutomationCreateInFlight, false);

  // 스크롤: 폼 상단이 화면 밖(아래)일 때 host.scrollTop이 목표로 이동한다.
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
               .replace("__MODULE_A__", json.dumps(str(STATIC / "chat-automation-module.js")))
               .replace("__MODULE_B__", json.dumps(str(STATIC / "chat-automation-form-module.js")))
               .replace("__A_DEPS__", json.dumps(sorted(A_GETTERS)))
               .replace("__B_DEPS__", json.dumps(sorted(B_GETTERS))))
    with tempfile.TemporaryDirectory() as directory:
        harness_path = Path(directory) / "a1_module_harness.cjs"
        harness_path.write_text(harness, encoding="utf-8")
        node = "node"
        result = subprocess.run([node, str(harness_path)], capture_output=True, text=True, encoding="utf-8", timeout=120)
    lines = [l for l in result.stdout.splitlines() if l.startswith("RESULT_JSON ")]
    assert lines, f"harness produced no result: {result.stdout[-800:]} {result.stderr[-400:]}"
    payload = json.loads(lines[-1][len("RESULT_JSON "):])
    assert payload.get("ok") is True, payload
    assert set(payload["checks"]) == {
        "state_trio", "render", "toggle_patch", "load_paths", "mount_open",
        "edit_form", "edit_patch", "create_post",
    }, payload["checks"]
