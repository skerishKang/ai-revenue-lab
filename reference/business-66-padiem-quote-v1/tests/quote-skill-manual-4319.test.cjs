/* B66 #4319 — 견적서 관리 → 새 견적서 만들기 → 직접 만들기
   후보 생성 / 검토 / 승인 요청(fail closed) 집중 계약 테스트.

   범위: 직접 만들기 경로만 검증한다. QuoteCore 계산·PDF 렌더·승인된 CGI 기본
   Skill 의 정상 흐름은 기존 테스트가 담당하며 여기서 변경하지 않는다. */

const assert = require("node:assert");
const Manual = require("../quote-skill-manual.js");
const SkillStore = require("../quote-skill-store.js");
const Scope = require("../quote-account-scope.js");

const check = (condition, label) => assert.ok(condition, `contract failed: ${label}`);
const eq = (actual, expected, label) => assert.deepStrictEqual(actual, expected, `contract failed: ${label}`);
const NOW = "2026-10-11T05:00:00.000Z";

/* ── 스텁 DOM (innerHTML 미사용 모듈을 실제 DOM API로 검증) ── */

function matches(node, selector) {
  if (!selector) return false;
  if (selector[0] === "#") return node.id === selector.slice(1);
  const dataAction = selector.match(/^\[data-action(?:="([^"]*)")?\]$/);
  if (dataAction) {
    const value = node.attributes ? node.attributes["data-action"] : undefined;
    if (value === undefined) return false;
    return dataAction[1] === undefined || value === dataAction[1];
  }
  return node.tagName === String(selector).toUpperCase();
}

function queryAll(root, selector) {
  const found = [];
  const visit = (node) => {
    (node.children || []).forEach((child) => {
      if (matches(child, selector)) found.push(child);
      visit(child);
    });
  };
  visit(root);
  return found;
}

function stubDocument(staticIds) {
  const byId = new Map();
  const doc = {
    activeElement: null,
    createElement(tag) { return makeNode(String(tag)); },
    createTextNode(text) { return { nodeType: 3, textContent: String(text), parent: null }; },
    getElementById(id) { return byId.get(String(id)) || null; }
  };
  function makeNode(tag) {
    const node = {
      tagName: tag.toUpperCase(),
      id: "",
      attributes: {},
      dataset: {},
      checked: false,
      hidden: false,
      selected: false,
      disabled: false,
      textContent: "",
      children: [],
      parent: null,
      listeners: {},
      focused: false,
      style: {},
      classList: { add() {}, remove() {}, toggle() {} },
      setAttribute(name, value) {
        this.attributes[name] = String(value);
        if (name === "id") { this.id = String(value); byId.set(this.id, this); }
        if (name.slice(0, 5) === "data-") {
          this.dataset[name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = String(value);
        }
      },
      getAttribute(name) { return this.attributes[name] === undefined ? null : this.attributes[name]; },
      appendChild(child) {
        child.parent = this;
        this.children.push(child);
        if (child.id) byId.set(child.id, child);
        return child;
      },
      removeChild(child) {
        this.children = this.children.filter((c) => c !== child);
        child.parent = null;
        return child;
      },
      get firstChild() { return this.children[0] || null; },
      addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
      click() {
        let node = this;
        const event = { target: this };
        while (node) {
          (node.listeners["click"] || []).slice().forEach((fn) => fn(event));
          node = node.parent;
        }
      },
      focus() { this.focused = true; doc.activeElement = this; },
      closest(selector) {
        let node = this;
        while (node) {
          if (matches(node, selector)) return node;
          node = node.parent;
        }
        return null;
      },
      querySelector(sel) { return queryAll(this, sel)[0] || null; },
      querySelectorAll(sel) { return queryAll(this, sel); }
    };
    if (node.tagName === "SELECT") {
      let explicit = null;
      Object.defineProperty(node, "value", {
        get() {
          if (explicit !== null) return explicit;
          const selected = this.children.find((c) => c.selected);
          return selected ? String(selected.value) : "";
        },
        set(v) {
          explicit = String(v);
          this.children.forEach((c) => { c.selected = String(c.value) === explicit; });
        },
        configurable: true
      });
    } else {
      node.value = "";
    }
    return node;
  }
  (staticIds || []).forEach((id) => {
    const node = makeNode("div");
    node.setAttribute("id", id);
  });
  return doc;
}

function countingStorage(seed) {
  const map = new Map();
  const writes = [];
  (seed ? Object.keys(seed) : []).forEach((key) => map.set(key, seed[key]));
  return {
    writes,
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => { writes.push(key); map.set(key, String(value)); },
    removeItem: (key) => { writes.push("remove:" + key); map.delete(key); },
    has: (key) => map.has(key)
  };
}

const STATIC_IDS = Object.keys(Manual.IDS).map((key) => Manual.IDS[key]);

function mount(envOverrides) {
  const doc = stubDocument(STATIC_IDS);
  const storage = countingStorage();
  let signedIn = false;
  const env = Object.assign({
    storage,
    authState: () => ({
      authenticated: signedIn,
      privateStateReadable: signedIn
    }),
    toast: () => {}
  }, envOverrides || {});
  const api = Manual.bindManualSection(doc, env);
  return {
    doc,
    storage,
    api,
    setSignedIn(value) { signedIn = value === true; },
    find(action) {
      const body = doc.getElementById(Manual.IDS.body);
      return body ? body.querySelector('[data-action="' + action + '"]') : null;
    },
    input(id) { return doc.getElementById(id); },
    set(id, value) { const node = doc.getElementById(id); if (node) node.value = value; },
    bodyText() {
      const body = doc.getElementById(Manual.IDS.body);
      const out = [];
      const visit = (node) => {
        (node.children || []).forEach((child) => {
          if (child.textContent) out.push(child.textContent);
          visit(child);
        });
      };
      visit(body);
      return out.join("\n");
    }
  };
}

function fillValidForm(view) {
  view.set("msk-name", "우리회사 견적서");
  view.set("msk-company", "주식회사 파디엠");
  view.set("msk-rep", "강혜림");
  view.set("msk-bizno", "123-45-67890");
  view.set("msk-address", "광주광역시 남구");
  view.set("msk-phone", "062-000-0000");
  view.set("msk-email", "quote@example.com");
  view.set("msk-valid-days", "30");
  view.set("msk-tax-mode", "EXCLUSIVE");
  view.set("msk-memo", "기본 비고");
}

/* ── 1. 승인 연결 contract: 없으면 없다고 말한다 ── */

check(Manual.APPROVAL_ENDPOINT === null, "고객용 승인 endpoint 는 현재 없음(null)이 계약이다");
const approvalState = Manual.approvalRequestState();
check(approvalState.connected === false, "승인 요청 상태는 미연결이다");
check(approvalState.code === "approval_endpoint_unavailable", "승인 미연결 코드가 명시된다");
check(typeof approvalState.backendPrerequisite === "string" && approvalState.backendPrerequisite.length > 0,
  "필요한 백엔드 작업이 코드에 남는다");
check(Manual.STATUS.APPROVAL_NOT_CONNECTED === "approval_not_connected", "승인 미연결 상태값이 정의된다");

/* ── 2. 입력값 검증 · 경계 ── */

const validEntry = {
  name: "우리회사 견적서",
  sender: {
    company: "주식회사 파디엠", rep: "강혜림", bizNo: "123-45-67890",
    address: "광주광역시 남구", phone: "062-000-0000", email: "quote@example.com"
  },
  validDays: 30, taxMode: "EXCLUSIVE", memo: "기본 비고",
  variableFlags: { memo: true, taxMode: true }
};
eq(Manual.normalizeManualEntry(validEntry).ok, true, "정상 직접 입력은 통과한다");
eq(Manual.normalizeManualEntry(null).code, "manual_entry_required", "값이 없으면 거부한다");
eq(Manual.normalizeManualEntry(Object.assign({}, validEntry, {
  sender: Object.assign({}, validEntry.sender, { company: "  " })
})).code, "invalid_manual_sender_company", "회사명은 필수다");
eq(Manual.normalizeManualEntry(Object.assign({}, validEntry, { validDays: "99999" })).code,
  "invalid_manual_valid_days", "유효기간 상한을 넘으면 거부한다");
eq(Manual.normalizeManualEntry(Object.assign({}, validEntry, { validDays: "-1" })).code,
  "invalid_manual_valid_days", "음수 유효기간을 거부한다");
eq(Manual.normalizeManualEntry(Object.assign({}, validEntry, { taxMode: "HACK" })).code,
  "invalid_manual_tax_mode", "정의되지 않은 세금 방식을 거부한다");
eq(Manual.normalizeManualEntry(Object.assign({}, validEntry, { name: "" })).code,
  "invalid_manual_name", "이름이 없으면 거부한다");

const oversized = Manual.normalizeManualEntry({
  name: "N".repeat(500),
  sender: {
    company: "C".repeat(500) + "유지",
    rep: "R".repeat(500),
    bizNo: "B".repeat(500),
    address: "A".repeat(500),
    phone: "P".repeat(500),
    email: "E".repeat(500)
  },
  validDays: "30", taxMode: "EXCLUSIVE", memo: "M".repeat(2000),
  variableFlags: { memo: true, taxMode: true }
});
check(oversized.ok, "과대 입력은 잘라서 저장한다(거부가 아니라 경계 적용)");
check(oversized.entry.sender.company.length <= Manual.LIMITS.company, "회사명 길이가 경계된다");
check(oversized.entry.sender.email.length <= Manual.LIMITS.email, "이메일 길이가 경계된다");
check(oversized.entry.memo.length <= Manual.LIMITS.memo, "비고 길이가 경계된다");
check(oversized.entry.name.length <= Manual.LIMITS.name, "이름 길이가 경계된다");

const controlled = Manual.normalizeManualEntry({
  name: "이름",
  sender: {
    company: "회사" + String.fromCharCode(0) + String.fromCharCode(7) + "사",
    rep: "대" + String.fromCharCode(0) + "표",
    bizNo: "1", address: "a", phone: "p", email: "e"
  },
  validDays: "30", taxMode: "EXCLUSIVE", memo: "메" + String.fromCharCode(0) + "모",
  variableFlags: { memo: true, taxMode: true }
});
check(controlled.ok, "제어문자가 있어도 정규화된다");
check(controlled.entry.sender.company.indexOf(String.fromCharCode(0)) === -1, "NUL 이 제거된다");
check(controlled.entry.sender.rep.indexOf(String.fromCharCode(0)) === -1, "대표자 NUL 이 제거된다");
check(controlled.entry.memo.indexOf(String.fromCharCode(0)) === -1, "비고 NUL 이 제거된다");

/* ── 3. 후보 생성: 기존 Saved Skill 계약 재사용, 승인 아님 ── */

const built = Manual.buildManualCandidate(validEntry, { now: NOW });
check(built.ok, "직접 입력 후보가 만들어진다");
eq(built.candidate.status, "candidate", "후보 상태는 승인(candidate)이 아니다");
check(built.candidate.approval === undefined, "후보에는 승인 객체가 없다");
eq(built.candidate.provenance.sourceKind, "manual", "출처 종류는 직접 입력(manual)이다");
check(built.candidate.internalTemplate && built.candidate.internalTemplate.id === "builtin-default",
  "양식은 내장 기본 양식을 재사용한다");
check(built.review.calculatedByCore.length > 0, "자동 계산 항목은 QuoteCore authority 로 표시된다");
check(built.review.alwaysReusedOrDefault.some((row) => row.value === "주식회사 파디엠"),
  "검토 화면에 입력한 회사명이 그대로 보인다");
check(built.candidate.provenance.unknowns.every((note) => note.indexOf("recipient.") !== 0 &&
  note !== "quote.quoteNo" && note !== "quote.issueDate" && note !== "items"),
  "견적마다 바뀌는 값은 미확인 목록에 남기지 않는다");
eq(Manual.buildManualCandidate(Object.assign({}, validEntry, { taxMode: "NOPE" }), { now: NOW }).ok,
  false, "잘못된 값으로는 후보를 만들지 않는다");

/* ── 4. 승인 요청은 항상 fail closed ── */

const request = Manual.requestApproval(built.candidate, { now: NOW });
eq(request.ok, false, "승인 요청은 성공하지 않는다");
eq(request.approved, false, "승인 결과는 항상 false 다");
eq(request.skill, null, "승인된 Skill 을 만들어내지 않는다");
eq(request.code, "approval_endpoint_unavailable", "미연결 사유가 코드로 남는다");
eq(request.status, Manual.STATUS.APPROVAL_NOT_CONNECTED, "상태는 승인 요청 연결 전이다");
eq(Manual.requestApproval(null, {}).code, "candidate_not_submittable", "후보 없이는 요청도 없다");
eq(Manual.requestApproval({ status: "approved" }, {}).code, "candidate_not_submittable",
  "후보가 아닌 객체는 접수되지 않는다");

/* ── 5. 초안 보존 bounded ── */

const store = countingStorage();
check(Manual.writeManualDraft(store, {
  schemaVersion: Manual.DRAFT_SCHEMA_VERSION,
  status: Manual.STATUS.DRAFT,
  entry: validEntry,
  updatedAt: NOW
}) === true, "초안을 저장한다");
const restored = Manual.readManualDraft(store);
check(restored && restored.entry.sender.company === "주식회사 파디엠", "저장한 초안을 다시 읽는다");
check(Manual.writeManualDraft(store, { schemaVersion: 1, entry: validEntry, memo: "M".repeat(20000) }) === false,
  "과대 초안은 저장하지 않는다");
const broken = countingStorage({ [Manual.MANUAL_DRAFT_STORAGE_KEY]: "{not json" });
eq(Manual.readManualDraft(broken), null, "깨진 초안은 null 이다(fail closed)");
const wrongVersion = countingStorage({
  [Manual.MANUAL_DRAFT_STORAGE_KEY]: JSON.stringify({ schemaVersion: 99, entry: validEntry })
});
eq(Manual.readManualDraft(wrongVersion), null, "스키마가 다른 초안은 무시한다");
const badEntry = countingStorage({
  [Manual.MANUAL_DRAFT_STORAGE_KEY]: JSON.stringify({ schemaVersion: 1, entry: { name: "" } })
});
eq(Manual.readManualDraft(badEntry), null, "검증되지 않는 초안 값은 복원하지 않는다");
eq(Manual.readManualDraft(null), null, "storage 가 없으면 읽지 않는다");

/* ── 6. 비로그인(게스트)은 입력 화면을 얻지 못한다 ── */

const guest = mount();
guest.api.open(null);
eq(guest.api.getState().signedIn, false, "게스트는 로그인 상태가 아니다");
check(guest.find("msk-signin") !== null, "게스트에게는 로그인 안내가 보인다");
check(guest.find("msk-review") === null, "게스트는 검토로 진행할 수 없다");
eq(guest.storage.writes.length, 0, "게스트 상태에서는 아무것도 저장하지 않는다");

/* ── 7. 로그인 사용자: 입력 → 검토 → 승인 요청 ── */

const view = mount();
view.setSignedIn(true);
view.api.open(null);
eq(view.api.getState().signedIn, true, "로그인 사용자는 입력 화면을 얻는다");
check(view.find("msk-review") !== null, "검토 버튼이 있다");

/* 필수값 없이 진행하면 막힌다 */
const statusNode = view.doc.getElementById(Manual.IDS.status);
view.find("msk-review").click();
check(statusNode.textContent.length > 0, "필수값이 없으면 안내 문구가 나온다");
eq(view.api.getState().status, Manual.STATUS.DRAFT, "필수값이 없으면 검토로 넘어가지 않는다");

fillValidForm(view);
view.find("msk-review").click();
eq(view.api.getState().status, Manual.STATUS.REVIEW, "검토 단계로 이동한다");
const reviewText = view.bodyText();
check(reviewText.indexOf("주식회사 파디엠") !== -1, "검토 화면에 입력값이 보인다");
check(reviewText.indexOf("강혜림") !== -1, "검토에 대표자가 보인다");
check(reviewText.indexOf("062-000-0000") !== -1, "검토 화면에 연락처가 보인다");
check(reviewText.indexOf("승인 전 후보") !== -1, "후보가 아직 승인 전임을 표시한다");
check(view.find("msk-request-approval") !== null, "승인 요청 버튼이 있다");
eq(view.api.getState().candidate.status, "candidate", "검토 대상은 승인 전 후보다");

/* ── 8. 승인 요청: 가짜 성공 없음 · 중복 제출 없음 ── */

view.find("msk-request-approval").click();
const afterRequest = view.api.getState();
eq(afterRequest.status, Manual.STATUS.APPROVAL_NOT_CONNECTED, "승인 요청 후 상태는 연결 전이다");
check(view.bodyText().indexOf("승인 요청 연결 전") !== -1, "사용자에게 연결 전 상태가 보인다");
check(view.bodyText().indexOf(Manual.BACKEND_PREREQUISITE) !== -1, "필요 백엔드 작업이 화면에 남는다");
eq(afterRequest.approvalRequests, 1, "승인 요청은 한 번만 접수된다");
/* 이미 결과 화면이므로 동일 버튼이 없지만, 재호출로 중복 제출을 확인한다 */
view.api.actions.handleAction("msk-request-approval");
eq(view.api.getState().approvalRequests, 2, "명시적 재요청만 카운트된다(자동 중복 아님)");
const approvalResultView = mount();
approvalResultView.setSignedIn(true);
approvalResultView.api.open(null);
fillValidForm(approvalResultView);
approvalResultView.find("msk-review").click();
const approvalButton = approvalResultView.find("msk-request-approval");
approvalButton.click();
approvalButton.click();
eq(approvalResultView.api.getState().approvalRequests, 1, "같은 버튼 연속 클릭은 1회로 처리된다");
eq(approvalResultView.api.getState().status, Manual.STATUS.APPROVAL_NOT_CONNECTED,
  "연속 클릭해도 승인으로 바뀌지 않는다");
check(!approvalResultView.storage.writes.includes(SkillStore.STORAGE_KEY),
  "미승인 후보는 승인된 내 견적서 저장소에 쓰지 않는다");
check(!approvalResultView.storage.has(SkillStore.STORAGE_KEY), "승인 Skill 저장소 키가 생성되지 않는다");
check(approvalResultView.storage.writes.every((key) => key === Manual.MANUAL_DRAFT_STORAGE_KEY),
  "직접 만들기 경로는 초안 키만 건드린다");

/* ── 9. 악의적 입력은 마크업이 아니라 텍스트로 남는다 ── */

const evil = mount();
evil.setSignedIn(true);
evil.api.open(null);
const payload = "<img src=x onerror=alert(1)>";
evil.set("msk-name", payload);
evil.set("msk-company", "</label><script>alert(1)</script>");
evil.set("msk-rep", "대표");
evil.set("msk-bizno", "123-45-67890");
evil.set("msk-address", "주소");
evil.set("msk-phone", "전화");
evil.set("msk-email", "e@example.com");
evil.set("msk-valid-days", "30");
evil.set("msk-tax-mode", "EXCLUSIVE");
evil.set("msk-memo", payload);
evil.find("msk-review").click();
eq(evil.api.getState().status, Manual.STATUS.REVIEW, "악의적 문자열도 값으로는 통과한다");
const evilCandidate = evil.api.getState().candidate;
check(evilCandidate.name.indexOf("<img") === 0, "값은 있는 그대로 보존된다(이스케이프된 텍스트)");
const evilBody = evil.doc.getElementById(Manual.IDS.body);
eq(queryAll(evilBody, "IMG").length, 0, "IMG 요소가 만들어지지 않는다");
eq(queryAll(evilBody, "SCRIPT").length, 0, "SCRIPT 요소가 만들어지지 않는다");
check(evil.bodyText().indexOf("<img src=x onerror=alert(1)>") !== -1, "문자열은 텍스트로만 렌더된다");

/* ── 10. 계정 전환 격리 ── */

const isolation = countingStorage();
check(Manual.writeManualDraft(isolation, {
  schemaVersion: Manual.DRAFT_SCHEMA_VERSION,
  status: Manual.STATUS.DRAFT,
  entry: validEntry,
  updatedAt: NOW
}) === true, "계정 A 초안이 저장된다");
const isolationKeys = Scope.privateKeys({
  SkillStore,
  manualDraftKey: Manual.MANUAL_DRAFT_STORAGE_KEY
});
check(isolationKeys.includes(Manual.MANUAL_DRAFT_STORAGE_KEY),
  "직접 만들기 초안 키가 계정 격리(private) 키 목록에 포함된다");
eq(Scope.removePrivateKeys(isolation, isolationKeys), true, "계정 전환 시 private 키가 삭제된다");
eq(Manual.readManualDraft(isolation), null, "다른 계정은 이전 계정 초안을 읽을 수 없다");

console.log("B66_MANUAL_SKILL_4319=PASS");
console.log("MANUAL_APPROVAL_CONNECTED=NO");
console.log("MANUAL_APPROVAL_FAIL_CLOSED=YES");
console.log("MANUAL_APPROVED_SKILL_STORE_WRITES=0");
console.log("MANUAL_DUPLICATE_APPROVAL_SUBMIT=0");
console.log("MANUAL_GUEST_ENTRY_BLOCKED=YES");
console.log("MANUAL_INJECTION_NODES=0");
console.log("MANUAL_ACCOUNT_SWITCH_ISOLATED=YES");
