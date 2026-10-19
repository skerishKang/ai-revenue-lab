/* B66 #3186 — 운영자에게 양식 만들기 맡기기 (고객 의뢰 경로).

   범위:
   - 고객 의뢰는 기존 문의 API(category=quote_skill_assist)로 접수된다.
   - 고객 계정의 양식 후보는 기존 후보/승인 계약으로 접수된다.
   - 후보 준비가 실패해도 의뢰는 접수되며 실패 사실이 운영자 문의에 남는다.
   - 승인·계정 배정은 이 모듈이 수행하지 않는다. */

const assert = require("node:assert");
const Assisted = require("../quote-skill-assisted.js");
const Auto = require("../quote-skill-auto.js");

const check = (condition, label) => assert.ok(condition, `contract failed: ${label}`);
const eq = (actual, expected, label) => assert.deepStrictEqual(actual, expected, `contract failed: ${label}`);
const NOW = "2026-10-19T02:00:00.000Z";
const CANDIDATE_ID = "b66cand_" + "d".repeat(32);
const INQUIRY_ID = "b66inq_" + "e".repeat(32);

const PROFILE = {
  company: "주식회사 파디엠",
  representative: "강혜림",
  businessNumber: "123-45-67890",
  address: "광주광역시 남구",
  phone: "062-000-0000",
  email: "quote@example.com",
  defaultValidityDays: 45,
  defaultTaxMode: "EXCLUSIVE"
};

function pendingReply() {
  return {
    status: 200,
    ok: true,
    data: {
      ok: true,
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

function inquiryReply() {
  return { status: 201, ok: true, data: { ok: true, inquiry_id: INQUIRY_ID } };
}

/* ── 1. 의뢰 입력 경계 ── */

eq(Assisted.normalizeRequest({ company: "  " }).code, "invalid_company", "회사명은 필수");
const normalized = Assisted.normalizeRequest({
  company: "  주식회사 파디엠 ",
  phone: "062-000-0000",
  email: "quote@example.com",
  note: "기존 견적서와 같은 모양으로 부탁드립니다."
});
check(normalized.ok, "정상 의뢰");
eq(normalized.request.company, "주식회사 파디엠", "회사명 정리");
eq(normalized.request.name, "주식회사 파디엠 견적서", "기본 이름");
check(normalized.request.note.indexOf("같은 모양") >= 0, "요청 내용 보존");

const controlled = Assisted.normalizeRequest({
  company: "회사" + String.fromCharCode(0) + "명",
  note: "요청" + String.fromCharCode(7) + "내용"
});
check(controlled.ok, "제어문자는 정리한다");
check(controlled.request.company.indexOf(String.fromCharCode(0)) === -1, "NUL 제거");
check(controlled.request.note.indexOf(String.fromCharCode(7)) === -1, "제어문자 제거");

const draft = Assisted.draftFor(normalized.request, PROFILE);
eq(draft.sender.company, normalized.request.company, "요청 회사명이 후보 회사명");
eq(draft.sender.rep, PROFILE.representative, "프로필 대표자");
eq(draft.sender.bizNo, PROFILE.businessNumber, "프로필 사업자번호");
eq(draft.sender.phone, "062-000-0000", "요청 연락처");
eq(draft.validDays, 45, "프로필 기본 유효기간");
eq(draft.memo, "", "요청 메모를 견적 기본 비고로 저장하지 않는다");

/* ── 2. 문의 본문: 후보/파일/실패 사실을 정직하게 담는다 ── */

const fileMeta = { name: "old-quote.pdf", category: "native_document", displaySize: "12 KB" };
const success = Assisted.buildInquiryPayload(
  normalized.request,
  { ok: true, candidateId: CANDIDATE_ID, status: "pending" },
  fileMeta,
  { ok: true }
);
check(success.ok, "성공 문의 본문");
eq(success.payload.category, "quote_skill_assist", "전용 문의 분류");
check(success.payload.subject.indexOf("[견적서 양식 의뢰]") === 0, "운영자 식별 제목");
check(success.payload.body.indexOf(CANDIDATE_ID) >= 0, "후보 번호 포함");
check(success.payload.body.indexOf("old-quote.pdf (자동 분석 완료)") >= 0, "파일 분석 상태");
check(success.payload.body.indexOf("관리자 승인 요청") >= 0, "운영자 처리 안내");
check(success.payload.body.length <= Assisted.LIMITS.body, "본문 길이 경계");

const failed = Assisted.buildInquiryPayload(
  Object.assign({}, normalized.request, { note: "N".repeat(5000) }),
  { ok: false, code: "invalid_extraction" },
  null,
  null
);
check(failed.ok, "후보 실패도 문의 본문을 만든다");
check(failed.payload.body.indexOf("준비 실패 (invalid_extraction)") >= 0, "실패 코드 보존");
check(failed.payload.body.indexOf("고객 계정에 후보가 없습니다") >= 0, "운영자 조치 안내");
check(failed.payload.body.length <= Assisted.LIMITS.body, "긴 요청도 경계 안으로 자른다");

/* ── 3. 문의 전송: 기존 API 계약 ── */

(async function () {
  const sent = [];
  const okInquiry = await Assisted.submitInquiry(success.payload, {
    transport: (request) => { sent.push(request); return Promise.resolve(inquiryReply()); }
  });
  eq(sent[0].method, "POST", "POST");
  eq(sent[0].url, "/api/padiem/b66/inquiries", "기존 문의 endpoint");
  eq(sent[0].body.category, "quote_skill_assist", "분류 전달");
  eq(okInquiry.ok, true, "접수 성공");
  eq(okInquiry.inquiryId, INQUIRY_ID, "의뢰번호");

  const unauthorized = await Assisted.submitInquiry(success.payload, {
    transport: () => Promise.resolve({ status: 401, ok: false, data: { ok: false } })
  });
  eq(unauthorized.code, "inquiry_unauthorized", "401 매핑");

  const limited = await Assisted.submitInquiry(success.payload, {
    transport: () => Promise.resolve({ status: 429, ok: false, data: { ok: false } })
  });
  eq(limited.code, "inquiry_rate_limited", "429 매핑");

  const malformed = await Assisted.submitInquiry(success.payload, {
    transport: () => Promise.resolve({ status: 201, ok: true, data: { ok: true, inquiry_id: "nope" } })
  });
  eq(malformed.ok, false, "잘못된 의뢰번호는 성공으로 보지 않는다");
  eq(malformed.code, "inquiry_response_invalid", "응답 형식 오류");

  const noTransport = await Assisted.submitInquiry(success.payload, {});
  eq(noTransport.code, "inquiry_transport_unavailable", "전송 경로 부재");

  /* ── 4. 전체 흐름: 후보 접수 → 의뢰 접수 ── */
  const requests = [];
  const result = await Assisted.run(normalized.request, {
    companyProfile: PROFILE,
    transport: (request) => {
      requests.push(request);
      if (request.url.indexOf("/saved-skill-candidates") >= 0) return Promise.resolve(pendingReply());
      return Promise.resolve(inquiryReply());
    }
  });
  eq(requests.length, 2, "후보 1건 + 의뢰 1건");
  eq(requests[0].url, "/api/padiem/b66/saved-skill-candidates", "후보가 먼저 접수된다");
  check(requests[0].body.client_ref.indexOf("auto-") === 0, "후보 요청 참조");
  eq(requests[1].url, "/api/padiem/b66/inquiries", "의뢰는 기존 문의 API");
  check(requests[1].body.body.indexOf(CANDIDATE_ID) >= 0, "의뢰 본문에 후보 번호");
  eq(result.ok, true, "의뢰 접수");
  eq(result.candidate.ok, true, "후보 접수");
  eq(result.candidate.status, "pending", "후보는 승인 대기");
  eq(result.inquiry.inquiryId, INQUIRY_ID, "의뢰번호");

  /* 후보 준비가 실패해도 의뢰는 접수한다. */
  const requests2 = [];
  const partial = await Assisted.run(normalized.request, {
    companyProfile: PROFILE,
    transport: (request) => {
      requests2.push(request);
      if (request.url.indexOf("/saved-skill-candidates") >= 0) {
        return Promise.resolve({
          status: 503, ok: false,
          data: { ok: false, error: { code: "candidate_store_unavailable" } }
        });
      }
      return Promise.resolve(inquiryReply());
    }
  });
  eq(requests2.length, 2, "실패해도 의뢰는 보낸다");
  eq(partial.ok, true, "의뢰 접수 성공");
  eq(partial.candidate.ok, false, "후보 실패 사실 보존");
  check(partial.payload.body.indexOf("준비 실패 (candidate_store_unavailable)") >= 0,
    "운영자 문의에 후보 실패 코드");

  /* ── 5. DOM: 입력 → 의뢰 접수 → 정직한 결과 ── */
  const doc = stubDocument();
  const view = Assisted.open(doc, {
    authState: () => ({ authenticated: true, privateStateReadable: true }),
    companyProfile: PROFILE,
    transport: (request) => {
      if (request.url.indexOf("/saved-skill-candidates") >= 0) return Promise.resolve(pendingReply());
      return Promise.resolve(inquiryReply());
    }
  });
  eq(view.state().signedIn, true, "로그인 상태");
  eq(doc.getElementById("skassist-company").value, PROFILE.company, "회사명 사전 채움");
  doc.getElementById("skassist-note").value = "기존 견적서와 같은 모양으로 부탁드립니다.";
  clickAction(doc, "skassist-submit");
  await tick();
  eq(view.state().result.ok, true, "DOM 의뢰 접수");
  eq(view.state().result.inquiry.inquiryId, INQUIRY_ID, "DOM 의뢰번호");
  check(bodyText(doc).indexOf(INQUIRY_ID) >= 0, "의뢰번호 표시");
  check(bodyText(doc).indexOf("승인 대기") >= 0, "후보 승인 대기 표시");

  const guest = Assisted.open(doc, {
    authState: () => ({ authenticated: false, privateStateReadable: false }),
    companyProfile: PROFILE
  });
  eq(guest.state().signedIn, false, "비로그인");
  check(bodyText(doc).indexOf("로그인한 계정에서만") >= 0, "로그인 안내");

  console.log("B66_ASSISTED_CANDIDATE_CONTRACT=PASS");
  console.log("ASSISTED_INQUIRY_CATEGORY=quote_skill_assist");
  console.log("ASSISTED_CANDIDATE_STAYS_PENDING=YES");
  console.log("ASSISTED_PARTIAL_FAILURE_VISIBLE=YES");
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
  return doc;
}

function clickAction(doc, action) {
  const dialog = doc.getElementById("skillAssistDialog");
  const node = dialog.querySelector('[data-action="' + action + '"]');
  check(Boolean(node), "action exists: " + action);
  node.click();
}

function bodyText(doc) {
  const body = doc.getElementById("skillAssistBody");
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
