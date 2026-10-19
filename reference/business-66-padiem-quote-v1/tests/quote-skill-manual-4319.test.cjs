/* B66 #4319 / #3186 — 견적서 관리 → 새 견적서 만들기 → 직접 만들기
   후보 생성 / 검토 / 인증된 서버 승인 요청 계약 집중 테스트.

   범위: 직접 만들기 경로와 승인 *요청* 만 검증한다. 승인/거부 권한은 서버
   운영자 전용이며 브라우저 테스트는 그 경계를 확인하는 데 그친다.
   QuoteCore 계산·PDF 렌더·승인된 CGI 기본 Skill 의 정상 흐름은 기존 테스트가 담당한다. */

const assert = require("node:assert");
const Manual = require("../quote-skill-manual.js");
const SkillStore = require("../quote-skill-store.js");
const Scope = require("../quote-account-scope.js");

const check = (condition, label) => assert.ok(condition, `contract failed: ${label}`);
const eq = (actual, expected, label) => assert.deepStrictEqual(actual, expected, `contract failed: ${label}`);
const NOW = "2026-10-11T05:00:00.000Z";
const CANDIDATE_ID = "b66cand_" + "a".repeat(32);
const SAVED_SKILL_ID = "b66skill_" + "b".repeat(32);

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
  const requests = [];
  let signedIn = false;
  const overrides = envOverrides || {};
  const env = Object.assign({
    storage,
    authState: () => ({
      authenticated: signedIn,
      privateStateReadable: signedIn
    }),
    toast: () => {},
    /* 기본 전송: 서버 저장소 장애를 흉내 낸다. 성공 경로는 테스트가 주입한다. */
    transport: () => Promise.resolve({
      status: 503, ok: false,
      data: { ok: false, error: { code: "candidate_store_unavailable" } }
    })
  }, overrides);
  /* 주입 여부와 무관하게 모든 전송을 기록해 중복 제출을 셀 수 있게 한다. */
  const inner = env.transport;
  env.transport = (request) => {
    requests.push(request);
    return inner(request);
  };
  const api = Manual.bindManualSection(doc, env);
  return {
    doc,
    storage,
    api,
    requests,
    env,
    setSignedIn(value) { signedIn = value === true; },
    find(action) {
      const body = doc.getElementById(Manual.IDS.body);
      return body ? body.querySelector('[data-action="' + action + '"]') : null;
    },
    set(id, value) { const node = doc.getElementById(id); if (node) node.value = value; },
    status() { return doc.getElementById(Manual.IDS.status).textContent; },
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

function serverReply(overrides) {
  const candidate = Object.assign({
    candidate_id: CANDIDATE_ID,
    status: "pending",
    saved_skill_id: "",
    rejection_reason: "",
    decided_at: ""
  }, (overrides && overrides.candidate) || {});
  return {
    status: 200,
    ok: true,
    data: Object.assign({
      ok: true,
      duplicate: false,
      candidate: candidate,
      approval: { requested: true, status: candidate.status, approved: false, decided_by_customer: false }
    }, (overrides && overrides.top) || {})
  };
}

const validEntry = {
  name: "우리회사 견적서",
  sender: {
    company: "주식회사 파디엠", rep: "강혜림", bizNo: "123-45-67890",
    address: "광주광역시 남구", phone: "062-000-0000", email: "quote@example.com"
  },
  validDays: 30, taxMode: "EXCLUSIVE", memo: "기본 비고",
  variableFlags: { memo: true, taxMode: true }
};

/* ── 1. 승인 요청 경계: 서버가 승인 권한을 소유한다 ── */

const approvalState = Manual.approvalRequestState();
check(approvalState.connected === true, "승인 요청 endpoint 가 구성되어 있다");
eq(approvalState.endpoint, "/api/padiem/b66/saved-skill-candidates", "승인 요청 endpoint 경로");
eq(approvalState.approvalAuthority, "server-operator", "승인 주체는 서버 운영자다");
eq(approvalState.customerCanApprove, false, "고객은 스스로 승인할 수 없다");
check(Manual.STATUS.APPROVAL_PENDING === "approval_pending", "승인 대기 상태가 정의된다");
check(Manual.STATUS.APPROVAL_APPROVED === "approval_approved", "승인 완료 상태가 정의된다");
check(Manual.STATUS.APPROVAL_REJECTED === "approval_rejected", "승인 거부 상태가 정의된다");
check(Manual.STATUS.APPROVAL_FAILED === "approval_failed", "승인 실패 상태가 정의된다");

/* ── 2. 입력값 검증 · 경계 ── */

eq(Manual.normalizeManualEntry(validEntry).ok, true, "정상 직접 입력은 통과한다");
eq(Manual.normalizeManualEntry(null).code, "manual_entry_required", "값이 없으면 거부한다");
eq(Manual.normalizeManualEntry(Object.assign({}, validEntry, {
  sender: Object.assign({}, validEntry.sender, { company: "  " })
})).code, "invalid_manual_sender_company", "회사명은 필수다");
eq(Manual.normalizeManualEntry(Object.assign({}, validEntry, { validDays: "99999" })).code,
  "invalid_manual_valid_days", "유효기간 상한을 넘으면 거부한다");
eq(Manual.normalizeManualEntry(Object.assign({}, validEntry, { taxMode: "HACK" })).code,
  "invalid_manual_tax_mode", "정의되지 않은 세금 방식을 거부한다");

const oversized = Manual.normalizeManualEntry({
  name: "N".repeat(500),
  sender: {
    company: "C".repeat(500) + "유지",
    rep: "R".repeat(500), bizNo: "B".repeat(500), address: "A".repeat(500),
    phone: "P".repeat(500), email: "E".repeat(500)
  },
  validDays: "30", taxMode: "EXCLUSIVE", memo: "M".repeat(2000),
  variableFlags: { memo: true, taxMode: true }
});
check(oversized.ok, "과대 입력은 잘라서 저장한다(거부가 아니라 경계 적용)");
check(oversized.entry.sender.company.length <= Manual.LIMITS.company, "회사명 길이가 경계된다");
check(oversized.entry.memo.length <= Manual.LIMITS.memo, "비고 길이가 경계된다");

const controlled = Manual.normalizeManualEntry({
  name: "이름",
  sender: {
    company: "회사" + String.fromCharCode(0) + String.fromCharCode(7) + "사",
    rep: "대" + String.fromCharCode(0) + "표", bizNo: "1", address: "a", phone: "p", email: "e"
  },
  validDays: "30", taxMode: "EXCLUSIVE", memo: "메" + String.fromCharCode(0) + "모",
  variableFlags: { memo: true, taxMode: true }
});
check(controlled.ok, "제어문자가 있어도 정규화된다");
check(controlled.entry.sender.company.indexOf(String.fromCharCode(0)) === -1, "NUL 이 제거된다");

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

/* ── 4. 요청 참조: 내용에 결속되고 멱등하다 ── */

const ref = Manual.clientRefFor(built.candidate);
check(typeof ref === "string" && ref.length <= 64, "요청 참조는 bounded 다");
check(ref.indexOf("manual-") === 0, "요청 참조 접두");
eq(Manual.clientRefFor(built.candidate), ref, "같은 내용은 같은 요청 참조를 갖는다");
const other = Manual.buildManualCandidate(Object.assign({}, validEntry, { name: "다른 견적서" }), { now: NOW });
/* 이름은 계산 기준 밖이므로 지문은 그대로다. 그래도 요청 참조는 달라져야
   이름만 바꾼 재제출이 같은 승인 요청으로 합쳐지지 않는다. */
eq(other.candidate.skillFingerprint, built.candidate.skillFingerprint,
  "이름은 Skill 지문 계산 기준이 아니다");
check(Manual.clientRefFor(other.candidate) !== ref, "이름이 바뀌면 요청 참조도 바뀐다");
eq(Manual.clientRefFor({ skillFingerprint: "not-hex" }), null, "지문이 없으면 요청 참조를 만들지 않는다");
eq(Manual.clientRefFor(null), null, "후보가 없으면 요청 참조도 없다");

(async function () {
  /* ── 5. 승인 요청: 실패는 실패로 남는다 ── */
  const noTransport = await Manual.submitApprovalRequest(built.candidate, {});
  eq(noTransport.ok, false, "전송 경로가 없으면 승인 요청은 성공하지 않는다");
  eq(noTransport.code, "approval_transport_unavailable", "전송 경로 부재 코드");
  eq(noTransport.approved, false, "승인 결과는 항상 false 다");

  const noCandidate = await Manual.submitApprovalRequest(null, { transport: () => Promise.resolve({}) });
  eq(noCandidate.code, "candidate_not_submittable", "후보 없이는 요청도 없다");

  const sent = [];
  const accepted = await Manual.submitApprovalRequest(built.candidate, {
    transport: (request) => { sent.push(request); return Promise.resolve(serverReply()); }
  });
  eq(accepted.ok, true, "서버가 접수하면 성공이다");
  eq(accepted.status, "pending", "접수 직후 상태는 승인 대기다");
  eq(accepted.approved, false, "접수는 승인이 아니다");
  eq(accepted.candidateId, CANDIDATE_ID, "서버가 발급한 승인 요청 ID 를 보존한다");
  eq(sent.length, 1, "전송은 한 번이다");
  eq(sent[0].method, "POST", "제출은 POST 다");
  eq(sent[0].url, Manual.APPROVAL_ENDPOINT, "제출 경로는 승인 요청 endpoint 다");
  eq(sent[0].body.client_ref, ref, "요청 참조를 그대로 보낸다");
  eq(sent[0].body.candidate, built.candidate, "후보 envelope 를 그대로 보낸다");

  const unauthorized = await Manual.submitApprovalRequest(built.candidate, {
    transport: () => Promise.resolve({ status: 401, ok: false, data: { ok: false, error: { code: "unauthorized" } } })
  });
  eq(unauthorized.code, "approval_unauthorized", "만료 세션은 인증 오류로 보고된다");

  const storeDown = await Manual.submitApprovalRequest(built.candidate, {
    transport: () => Promise.resolve({
      status: 503, ok: false, data: { ok: false, error: { code: "candidate_store_unavailable" } }
    })
  });
  eq(storeDown.code, "candidate_store_unavailable", "서버 장애 코드를 그대로 보고한다");

  const thrown = await Manual.submitApprovalRequest(built.candidate, {
    transport: () => Promise.reject(new Error("network down"))
  });
  eq(thrown.ok, false, "전송 예외는 성공으로 바뀌지 않는다");
  eq(thrown.code, "approval_request_failed", "전송 예외 코드");

  const approved = await Manual.submitApprovalRequest(built.candidate, {
    transport: () => Promise.resolve(serverReply({
      candidate: { status: "approved", saved_skill_id: SAVED_SKILL_ID, decided_at: NOW },
      top: { duplicate: true }
    }))
  });
  eq(approved.approved, true, "서버가 승인했다고 하면 승인으로 표시한다");
  eq(approved.savedSkillId, SAVED_SKILL_ID, "배정된 내 견적서 id 를 보존한다");
  eq(approved.duplicate, true, "멱등 재요청을 구분한다");

  /* 승인이라고 하면서 배정된 Skill 이 없으면 승인으로 보여 주지 않는다. */
  const fakeApproved = await Manual.submitApprovalRequest(built.candidate, {
    transport: () => Promise.resolve(serverReply({ candidate: { status: "approved", saved_skill_id: "" } }))
  });
  eq(fakeApproved.ok, false, "배정 없는 승인 응답은 거부한다");
  eq(fakeApproved.code, "approval_response_invalid", "배정 없는 승인 코드");
  eq(fakeApproved.approved, false, "가짜 승인을 표시하지 않는다");

  const badId = await Manual.submitApprovalRequest(built.candidate, {
    transport: () => Promise.resolve(serverReply({ candidate: { candidate_id: "not-a-row-id" } }))
  });
  eq(badId.ok, false, "형식이 틀린 승인 요청 ID 는 거부한다");

  const unknownStatus = await Manual.submitApprovalRequest(built.candidate, {
    transport: () => Promise.resolve(serverReply({ candidate: { status: "activated" } }))
  });
  eq(unknownStatus.ok, false, "정의되지 않은 승인 상태는 거부한다");

  /* ── 6. 상태 조회 ── */
  const badLookup = await Manual.fetchApprovalStatus("nope", { transport: () => Promise.resolve({}) });
  eq(badLookup.code, "invalid_candidate", "형식이 틀린 승인 요청 ID 는 조회하지 않는다");
  const looked = [];
  const found = await Manual.fetchApprovalStatus(CANDIDATE_ID, {
    transport: (request) => { looked.push(request); return Promise.resolve(serverReply()); }
  });
  eq(found.ok, true, "승인 상태를 조회한다");
  eq(looked[0].method, "GET", "상태 조회는 GET 이다");
  eq(looked[0].url, Manual.APPROVAL_ENDPOINT + "/" + CANDIDATE_ID, "상태 조회 경로");

  /* ── 7. 초안 보존 bounded ── */
  const store = countingStorage();
  check(Manual.writeManualDraft(store, {
    schemaVersion: Manual.DRAFT_SCHEMA_VERSION,
    status: Manual.STATUS.APPROVAL_PENDING,
    entry: validEntry,
    approval: {
      candidateId: CANDIDATE_ID, serverStatus: "pending",
      savedSkillId: "", rejectionReason: "", decidedAt: ""
    },
    updatedAt: NOW
  }) === true, "초안을 저장한다");
  const restored = Manual.readManualDraft(store);
  check(restored && restored.entry.sender.company === "주식회사 파디엠", "저장한 초안을 다시 읽는다");
  eq(restored.status, Manual.STATUS.APPROVAL_PENDING, "승인 대기 상태가 복원된다");
  eq(restored.approval.candidateId, CANDIDATE_ID, "승인 요청 ID 가 복원된다");

  const legacy = countingStorage({
    [Manual.MANUAL_DRAFT_STORAGE_KEY]: JSON.stringify({ schemaVersion: 1, entry: validEntry, status: "draft" })
  });
  const upgraded = Manual.readManualDraft(legacy);
  check(upgraded && upgraded.entry.sender.company === "주식회사 파디엠", "구버전 초안도 복원한다");
  eq(upgraded.approval.candidateId, "", "구버전 초안은 승인 상태를 지어내지 않는다");
  eq(upgraded.status, Manual.STATUS.DRAFT, "구버전 초안은 초안 상태다");

  check(Manual.writeManualDraft(store, { schemaVersion: 2, entry: validEntry, memo: "M".repeat(40000) }) === false,
    "과대 초안은 저장하지 않는다");
  const broken = countingStorage({ [Manual.MANUAL_DRAFT_STORAGE_KEY]: "{not json" });
  eq(Manual.readManualDraft(broken), null, "깨진 초안은 null 이다(fail closed)");
  const wrongVersion = countingStorage({
    [Manual.MANUAL_DRAFT_STORAGE_KEY]: JSON.stringify({ schemaVersion: 99, entry: validEntry })
  });
  eq(Manual.readManualDraft(wrongVersion), null, "스키마가 다른 초안은 무시한다");
  eq(Manual.readManualDraft(null), null, "storage 가 없으면 읽지 않는다");

  /* ── 8. 비로그인(게스트)은 입력 화면을 얻지 못한다 ── */
  const guest = mount();
  guest.api.open(null);
  eq(guest.api.getState().signedIn, false, "게스트는 로그인 상태가 아니다");
  check(guest.find("msk-signin") !== null, "게스트에게는 로그인 안내가 보인다");
  check(guest.find("msk-review") === null, "게스트는 검토로 진행할 수 없다");
  eq(guest.storage.writes.length, 0, "게스트 상태에서는 아무것도 저장하지 않는다");

  /* ── 9. 로그인 사용자: 입력 → 검토 → 승인 요청 ── */
  const view = mount();
  view.setSignedIn(true);
  view.api.open(null);
  eq(view.api.getState().signedIn, true, "로그인 사용자는 입력 화면을 얻는다");

  view.find("msk-review").click();
  check(view.status().length > 0, "필수값이 없으면 안내 문구가 나온다");
  eq(view.api.getState().status, Manual.STATUS.DRAFT, "필수값이 없으면 검토로 넘어가지 않는다");

  fillValidForm(view);
  view.find("msk-review").click();
  eq(view.api.getState().status, Manual.STATUS.REVIEW, "검토 단계로 이동한다");
  check(view.bodyText().indexOf("주식회사 파디엠") !== -1, "검토 화면에 입력값이 보인다");
  check(view.bodyText().indexOf("승인 전 후보") !== -1, "후보가 아직 승인 전임을 표시한다");
  eq(view.api.getState().candidate.status, "candidate", "검토 대상은 승인 전 후보다");

  /* 서버 장애 → 실제 오류 표시, 승인 표시 금지 */
  await view.api.actions.handleAction("msk-request-approval");
  const failed = view.api.getState();
  eq(failed.status, Manual.STATUS.APPROVAL_UNAVAILABLE, "저장소 장애는 사용 불가로 표시된다");
  eq(failed.lastErrorCode, "candidate_store_unavailable", "실제 오류 코드가 남는다");
  check(view.bodyText().indexOf("candidate_store_unavailable") !== -1, "오류 코드가 화면에 보인다");
  check(view.bodyText().indexOf("승인 완료") === -1, "실패했는데 승인으로 표시하지 않는다");
  eq(failed.approvalRequests, 1, "승인 요청은 한 번 전송된다");

  /* 같은 버튼 연속 클릭 → 중복 전송 없음 */
  const dupView = mount({ transport: () => Promise.resolve(serverReply()) });
  dupView.setSignedIn(true);
  dupView.api.open(null);
  fillValidForm(dupView);
  dupView.find("msk-review").click();
  const approvalButton = dupView.find("msk-request-approval");
  approvalButton.click();
  approvalButton.click();
  await new Promise((resolve) => setImmediate(resolve));
  eq(dupView.api.getState().approvalRequests, 1, "같은 버튼 연속 클릭은 1회로 처리된다");
  eq(dupView.requests.length, 1, "서버로도 한 번만 전송된다");
  eq(dupView.api.getState().status, Manual.STATUS.APPROVAL_PENDING, "접수 후 승인 대기 상태다");
  check(dupView.bodyText().indexOf("승인 대기") !== -1, "승인 대기가 화면에 보인다");
  check(dupView.bodyText().indexOf("아직 사용할 수 없음") !== -1, "승인 전에는 사용할 수 없음을 표시한다");
  check(dupView.storage.writes.every((key) => key === Manual.MANUAL_DRAFT_STORAGE_KEY),
    "직접 만들기 경로는 초안 키만 건드린다");
  check(!dupView.storage.has(SkillStore.STORAGE_KEY), "미승인 후보는 승인 Skill 저장소에 쓰지 않는다");

  /* 상태 새로고침 → 승인 완료 */
  let refreshed = 0;
  const approveView = mount({
    transport: (request) => {
      if (request.method === "POST") return Promise.resolve(serverReply());
      return Promise.resolve(serverReply({
        candidate: { status: "approved", saved_skill_id: SAVED_SKILL_ID, decided_at: NOW }
      }));
    },
    refreshAssignedSkills: () => { refreshed += 1; }
  });
  approveView.setSignedIn(true);
  approveView.api.open(null);
  fillValidForm(approveView);
  approveView.find("msk-review").click();
  await approveView.api.actions.handleAction("msk-request-approval");
  eq(approveView.api.getState().status, Manual.STATUS.APPROVAL_PENDING, "먼저 승인 대기다");
  await approveView.api.actions.handleAction("msk-refresh-status");
  eq(approveView.api.getState().status, Manual.STATUS.APPROVAL_APPROVED, "서버가 승인하면 승인 완료다");
  eq(refreshed, 1, "승인 완료 시 배정된 내 견적서 목록을 새로 읽는다");
  check(approveView.bodyText().indexOf("승인 완료") !== -1, "승인 완료가 화면에 보인다");
  check(approveView.bodyText().indexOf(SAVED_SKILL_ID) !== -1, "배정된 내 견적서 id 가 보인다");

  /* 거부 */
  const rejectView = mount({
    transport: () => Promise.resolve(serverReply({
      candidate: { status: "rejected", rejection_reason: "회사 정보가 부족합니다", decided_at: NOW }
    }))
  });
  rejectView.setSignedIn(true);
  rejectView.api.open(null);
  fillValidForm(rejectView);
  rejectView.find("msk-review").click();
  await rejectView.api.actions.handleAction("msk-request-approval");
  eq(rejectView.api.getState().status, Manual.STATUS.APPROVAL_REJECTED, "거부는 거부로 표시된다");
  check(rejectView.bodyText().indexOf("승인 거부") !== -1, "승인 거부가 화면에 보인다");
  check(rejectView.bodyText().indexOf("회사 정보가 부족합니다") !== -1, "거부 사유가 화면에 보인다");
  check(rejectView.bodyText().indexOf("승인 완료") === -1, "거부를 승인으로 표시하지 않는다");

  /* ── 10. 악의적 입력은 마크업이 아니라 텍스트로 남는다 ── */
  const evil = mount({ transport: () => Promise.resolve(serverReply()) });
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
  const evilBody = evil.doc.getElementById(Manual.IDS.body);
  eq(queryAll(evilBody, "IMG").length, 0, "IMG 요소가 만들어지지 않는다");
  eq(queryAll(evilBody, "SCRIPT").length, 0, "SCRIPT 요소가 만들어지지 않는다");
  check(evil.bodyText().indexOf(payload) !== -1, "문자열은 텍스트로만 렌더된다");
  await evil.api.actions.handleAction("msk-request-approval");
  eq(queryAll(evilBody, "IMG").length, 0, "승인 요청 후에도 마크업이 생기지 않는다");

  /* ── 11. 계정 전환 격리 ── */
  const isolation = countingStorage();
  check(Manual.writeManualDraft(isolation, {
    schemaVersion: Manual.DRAFT_SCHEMA_VERSION,
    status: Manual.STATUS.APPROVAL_PENDING,
    entry: validEntry,
    approval: {
      candidateId: CANDIDATE_ID, serverStatus: "pending",
      savedSkillId: "", rejectionReason: "", decidedAt: ""
    },
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
  console.log("MANUAL_APPROVAL_ENDPOINT=BOUNDED");
  console.log("MANUAL_APPROVAL_CUSTOMER_CAN_APPROVE=NO");
  console.log("MANUAL_APPROVAL_FAIL_CLOSED=YES");
  console.log("MANUAL_FAKE_APPROVAL_RENDERED=0");
  console.log("MANUAL_APPROVED_SKILL_STORE_WRITES=0");
  console.log("MANUAL_DUPLICATE_APPROVAL_SUBMIT=0");
  console.log("MANUAL_GUEST_ENTRY_BLOCKED=YES");
  console.log("MANUAL_INJECTION_NODES=0");
  console.log("MANUAL_ACCOUNT_SWITCH_ISOLATED=YES");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
