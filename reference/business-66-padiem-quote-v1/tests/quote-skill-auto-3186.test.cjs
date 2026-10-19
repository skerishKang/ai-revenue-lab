/* B66 #3186 — 기존 파일에서 양식 후보 만들기.

   범위:
   - 추출 결과가 편집 가능한 초안으로 매핑되고, 사용자가 확인한 값이 후보의
     고정 기본값이 되는지 확인한다.
   - 후보는 승인 상태가 아니며, 승인 요청은 기존 서버 계약만 사용한다.
   - 파일 자동 분석이 꺼져 있으면 실패를 숨기지 않고 직접 입력 경로를 연다.
   승인/거부 권한과 계정 배정 자체는 기존 서버 테스트가 담당한다. */

const assert = require("node:assert");
const Auto = require("../quote-skill-auto.js");
const Manual = require("../quote-skill-manual.js");

const check = (condition, label) => assert.ok(condition, `contract failed: ${label}`);
const eq = (actual, expected, label) => assert.deepStrictEqual(actual, expected, `contract failed: ${label}`);
const NOW = "2026-10-19T01:00:00.000Z";
const CANDIDATE_ID = "b66cand_" + "a".repeat(32);
const SAVED_SKILL_ID = "b66skill_" + "b".repeat(32);

const PROFILE = {
  company: "주식회사 파디엠",
  representative: "강혜림",
  businessNumber: "123-45-67890",
  address: "광주광역시 남구",
  phone: "062-000-0000",
  email: "quote@example.com",
  defaultValidityDays: 45,
  defaultTaxMode: "INCLUSIVE"
};

const FILE_META = { name: "old-quote.pdf", category: "native_document", displaySize: "12 KB" };

function extraction() {
  return {
    source: { kind: "native_document", filename: "old-quote.pdf" },
    sender: {
      company: "옛회사", rep: "김대표", bizNo: null,
      address: null, phone: null, email: null
    },
    recipient: { company: null, person: null, address: null, email: null },
    quote: { quoteNo: null, issueDate: null, validDays: 30, projectName: null },
    items: [],
    tax: { mode: "EXCLUSIVE" },
    memo: null,
    evidence: [],
    warnings: []
  };
}

function pendingReply() {
  return {
    status: 200,
    ok: true,
    data: {
      ok: true,
      duplicate: false,
      candidate: {
        candidate_id: CANDIDATE_ID,
        status: "pending",
        saved_skill_id: "",
        rejection_reason: "",
        decided_at: ""
      }
    }
  };
}

/* ── 1. 프로필 → 초안 ── */

const profileDraft = Auto.draftFromProfile(PROFILE);
eq(profileDraft.name, "주식회사 파디엠 견적서", "프로필 회사명으로 초안 이름을 만든다");
eq(profileDraft.sender.company, PROFILE.company, "회사명");
eq(profileDraft.sender.rep, PROFILE.representative, "대표자 매핑");
eq(profileDraft.sender.bizNo, PROFILE.businessNumber, "사업자번호 매핑");
eq(profileDraft.validDays, 45, "프로필 기본 유효기간");
eq(profileDraft.taxMode, "INCLUSIVE", "프로필 기본 세금 방식");
eq(Auto.draftFromProfile(null).validDays, 30, "프로필이 없으면 30일 기본값");

const extractedDraft = Auto.draftFromSources(extraction(), PROFILE);
eq(extractedDraft.sender.company, "옛회사", "추출된 회사명을 우선한다");
eq(extractedDraft.sender.rep, "김대표", "추출된 대표자");
eq(extractedDraft.sender.bizNo, PROFILE.businessNumber, "추출에 없는 값은 프로필로 채운다");
eq(extractedDraft.validDays, 30, "추출된 유효기간");
eq(extractedDraft.taxMode, "EXCLUSIVE", "추출된 세금 방식");

/* ── 2. 파일 없이: 기존 직접 입력 후보 계약 재사용 ── */

const manualBuild = Auto.buildCandidate(profileDraft, { now: NOW });
check(manualBuild.ok, "프로필만으로 후보를 만든다");
eq(manualBuild.source, "manual", "파일이 없으면 출처는 직접 입력이다");
eq(manualBuild.candidate.status, "candidate", "후보 상태는 승인이 아니다");
eq(manualBuild.candidate.provenance.sourceKind, "manual", "provenance 도 직접 입력");
check(manualBuild.candidate.approval === undefined, "후보에는 승인 객체가 없다");

/* ── 3. 파일 + 사용자 확인: 편집값이 고정 기본값이 된다 ── */

const editedDraft = Object.assign({}, extractedDraft, {
  name: "새 견적서",
  sender: Object.assign({}, extractedDraft.sender, { company: "새회사" })
});
const fileBuild = Auto.buildCandidate(editedDraft, {
  extraction: extraction(),
  fileMeta: FILE_META,
  now: NOW
});
check(fileBuild.ok, "파일 추출 + 확인값으로 후보를 만든다");
eq(fileBuild.source, "file", "파일 경로 출처");
eq(fileBuild.candidate.fixedDefaults.sender.company, "새회사", "사용자가 확인한 회사명이 저장된다");
eq(fileBuild.candidate.name, "새 견적서", "사용자가 확인한 이름");
eq(fileBuild.candidate.provenance.sourceKind, "file", "Skill provenance 는 파일 출처");
eq(fileBuild.candidate.provenance.sourceName, FILE_META.name, "원본 파일 이름");
eq(fileBuild.candidate.provenance.sourceRef, Auto.AUTO_SOURCE_REF, "파일 intake 참조");
check(fileBuild.candidate.provenance.unknowns.indexOf("sender.company") === -1,
  "확인된 회사명을 미확인으로 남기지 않는다");
check(fileBuild.candidate.provenance.unknowns.indexOf("items") >= 0,
  "품목은 견적마다 바뀌므로 미확인으로 남는다");
check(/^[0-9a-f]{64}$/.test(fileBuild.candidate.skillFingerprint), "후보 지문");

const row = fileBuild.review.alwaysReusedOrDefault.find((entry) => entry.key === "sender.company");
eq(row.value, "새회사", "검토 화면에도 확인한 회사명이 보인다");

/* 유효기간 0은 추출 계약이 표현하지 못하므로 명시 보정으로 전달한다. */
const zeroDays = Auto.buildCandidate(Object.assign({}, editedDraft, { validDays: 0 }), {
  extraction: extraction(), fileMeta: FILE_META, now: NOW
});
check(zeroDays.ok, "유효기간 0도 후보로 만들 수 있다");
eq(zeroDays.candidate.fixedDefaults.validDays, 0, "유효기간 0이 보존된다");

/* ── 4. 요청 참조: 경로 접두 + 내용 결속 ── */

const ref = Auto.clientRefFor(fileBuild.candidate);
check(typeof ref === "string" && ref.indexOf("auto-") === 0, "자동 경로 요청 참조 접두");
check(ref.length <= 64, "요청 참조는 bounded");
eq(Auto.clientRefFor(fileBuild.candidate), ref, "같은 후보는 같은 참조");
const renamed = Auto.buildCandidate(Object.assign({}, editedDraft, { name: "다른 이름" }), {
  extraction: extraction(), fileMeta: FILE_META, now: NOW
});
eq(renamed.candidate.skillFingerprint, fileBuild.candidate.skillFingerprint,
  "이름은 Skill 지문 계산 기준이 아니다");
check(Auto.clientRefFor(renamed.candidate) !== ref, "이름이 바뀌면 참조도 바뀐다");
eq(Auto.clientRefFor({ skillFingerprint: "nope" }), null, "지문이 없으면 참조도 없다");

/* ── 5. 승인 요청은 기존 서버 계약으로만 ── */

(async function () {
  const sent = [];
  const accepted = await Auto.submitCandidate(fileBuild.candidate, {
    transport: (request) => { sent.push(request); return Promise.resolve(pendingReply()); }
  });
  eq(sent.length, 1, "승인 요청 1건");
  eq(sent[0].method, "POST", "POST");
  eq(sent[0].url, "/api/padiem/b66/saved-skill-candidates", "기존 후보 endpoint");
  check(sent[0].body.client_ref.indexOf("auto-") === 0, "자동 요청 참조가 전달된다");
  eq(sent[0].body.candidate.skillFingerprint, fileBuild.candidate.skillFingerprint, "후보 지문");
  check(sent[0].body.candidate.approval === undefined, "브라우저는 승인 객체를 보내지 않는다");
  eq(accepted.ok, true, "서버 접수");
  eq(accepted.status, "pending", "승인 대기");
  eq(accepted.approved, false, "승인 전");

  const noTransport = await Auto.submitCandidate(fileBuild.candidate, {});
  eq(noTransport.ok, false, "전송 경로가 없으면 실패");
  eq(noTransport.code, "approval_transport_unavailable", "전송 경로 부재 코드");

  const approved = await Auto.submitCandidate(fileBuild.candidate, {
    transport: () => Promise.resolve({
      status: 200,
      ok: true,
      data: {
        ok: true,
        candidate: {
          candidate_id: CANDIDATE_ID, status: "approved",
          saved_skill_id: SAVED_SKILL_ID, rejection_reason: "", decided_at: NOW
        }
      }
    })
  });
  eq(approved.ok, true, "승인 완료 응답");
  eq(approved.status, "approved", "승인 상태");
  eq(approved.savedSkillId, SAVED_SKILL_ID, "배정된 Skill id");

  const missingSkill = await Auto.submitCandidate(fileBuild.candidate, {
    transport: () => Promise.resolve({
      status: 200, ok: true,
      data: { ok: true, candidate: { candidate_id: CANDIDATE_ID, status: "approved", saved_skill_id: "" } }
    })
  });
  eq(missingSkill.ok, false, "배정 id 없는 승인은 승인으로 표시하지 않는다");

  const status = await Auto.fetchCandidateStatus(CANDIDATE_ID, {
    transport: (request) => {
      eq(request.method, "GET", "상태 조회는 GET");
      eq(request.url, "/api/padiem/b66/saved-skill-candidates/" + CANDIDATE_ID, "상태 조회 경로");
      return Promise.resolve(pendingReply());
    }
  });
  eq(status.status, "pending", "상태 새로고침");

  /* ── 6. DOM: 분석 성공 → 편집 → 검토 → 승인 요청 ── */
  const doc = stubDocument();
  const view = Auto.open(doc, {
    authState: () => ({ authenticated: true, privateStateReadable: true }),
    companyProfile: PROFILE,
    analyzeFile: () => Promise.resolve({ ok: true, extraction: extraction() }),
    transport: () => Promise.resolve(pendingReply())
  }, { file: { name: "old-quote.pdf", size: 1200, type: "application/pdf" } });

  await tick();
  eq(view.state().step, "edit", "파일 분석 뒤 편집 단계");
  eq(doc.getElementById("skauto-company").value, "옛회사", "분석값이 편집 폼에 채워진다");

  clickAction(doc, "skauto-review");
  eq(view.state().step, "review", "검토 단계");
  check(bodyText(doc).indexOf("승인 전 후보") >= 0, "후보 상태를 정직하게 표시한다");

  clickAction(doc, "skauto-submit");
  await tick();
  eq(view.state().step, "pending", "서버 승인 대기 상태");
  check(bodyText(doc).indexOf(CANDIDATE_ID) >= 0, "승인 요청 ID 표시");

  /* ── 7. DOM: 분석 불가 → 실패를 숨기지 않고 직접 입력 ── */
  const offline = Auto.open(doc, {
    authState: () => ({ authenticated: true, privateStateReadable: true }),
    companyProfile: PROFILE,
    analyzeFile: () => Promise.resolve({ ok: false, code: "intake_disabled" }),
    transport: () => Promise.resolve(pendingReply())
  }, { file: { name: "old-quote.pdf", size: 1200, type: "application/pdf" } });
  await tick();
  eq(offline.state().step, "edit", "분석 실패 후 직접 입력 단계");
  eq(doc.getElementById("skauto-company").value, PROFILE.company, "프로필 회사명으로 시작한다");
  check(doc.getElementById("skillAutoStatus").textContent.indexOf("사용할 수 없습니다") >= 0,
    "분석 불가는 그대로 표시한다");

  /* ── 8. 로그인 게이트 ── */
  const guest = Auto.open(doc, {
    authState: () => ({ authenticated: false, privateStateReadable: false }),
    companyProfile: PROFILE
  }, {});
  eq(guest.state().signedIn, false, "비로그인 상태");
  check(bodyText(doc).indexOf("로그인한 계정에서만") >= 0, "로그인 안내");

  console.log("B66_AUTO_FILE_CANDIDATE_CONTRACT=PASS");
  console.log("AUTO_CANDIDATE_NOT_APPROVED=YES");
  console.log("AUTO_APPROVAL_REUSES_EXISTING_SERVER=YES");
  console.log("AUTO_INTAKE_FAILURE_VISIBLE=YES");
})();

/* ── 스텁 DOM ── */

function tick() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

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

function stubDocument() {
  const byId = new Map();
  const doc = {
    activeElement: null,
    createElement(tag) { return makeNode(String(tag)); },
    createTextNode(text) { return { nodeType: 3, textContent: String(text), children: [], parent: null }; },
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
      ownerDocument: doc,
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
        let current = this;
        const event = { target: this };
        while (current) {
          (current.listeners["click"] || []).slice().forEach((fn) => fn(event));
          current = current.parent;
        }
      },
      focus() { this.focused = true; doc.activeElement = this; },
      closest(selector) {
        let current = this;
        while (current) {
          if (matches(current, selector)) return current;
          current = current.parent;
        }
        return null;
      },
      querySelector(selector) { return queryAll(this, selector)[0] || null; },
      querySelectorAll(selector) { return queryAll(this, selector); }
    };
    if (node.tagName === "SELECT") {
      let explicit = null;
      Object.defineProperty(node, "value", {
        get() {
          if (explicit !== null) return explicit;
          const selected = this.children.find((child) => child.selected);
          return selected ? String(selected.value) : "";
        },
        set(value) {
          explicit = String(value);
          this.children.forEach((child) => { child.selected = String(child.value) === explicit; });
        },
        configurable: true
      });
    } else {
      node.value = "";
    }
    return node;
  }
  doc.body = makeNode("body");
  doc.app = doc.body;
  return doc;
}

function clickAction(doc, action) {
  const dialog = doc.getElementById("skillAutoDialog");
  const node = dialog.querySelector('[data-action="' + action + '"]');
  check(Boolean(node), "action exists: " + action);
  node.click();
}

function bodyText(doc) {
  const body = doc.getElementById("skillAutoBody");
  const out = [];
  const visit = (node) => {
    (node.children || []).forEach((child) => {
      if (child.textContent) out.push(child.textContent);
      visit(child);
    });
  };
  if (body) visit(body);
  return out.join("\n");
}
