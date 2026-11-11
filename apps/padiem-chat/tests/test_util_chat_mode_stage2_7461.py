"""#7461 (2/2) — 유틸 대화 방식 4종(sns·meeting·quote·pdfmd) 및 라이브러리 저장 연동 시험.

검증 범위:
1. 4종(sns·meeting·quote·pdfmd) 각각:
   - 매니페스트(util-manifest.js) 입력 칸 정의만으로 빠진 필수 칸 질문 순서 결정(하드코딩 금지)
   - 빈 답 입력 시 서버 요청 0건, 마지막 필수 칸 입력 시에만 기존 생성 경로 1건 호출
   - 폼 ↔ 대화 양방향 값 유지 및 '폼으로 열기'·'대화로 다듬기'·?mode=chat 딥링크 동작
2. 도구별 계약:
   - quote(견적서 초안): 대화로 항목만 모으고 계산·결과 형식은 기존 폼 경로(/api/util/quote/preview)만 사용(/api/chat/stream 호출 0건)
   - pdfmd(PDF→Markdown): 파일 첨부를 질문 1개로 다루고 기존 업로드 경로(/api/document-conversions, .../files)만 사용(신규 업로드 경로 없음)
   - excel: 변경 없음(모드 스위치 미노출)
3. 결과 영역 '라이브러리에 저장'(#7508)과 '대화로 다듬기' 동시 동작:
   - 다듬기 실행 후에도 저장 버튼 활성 유지 및 다듬어진 최종 본문이 라이브러리에 저장됨.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
TOOLS_JS = (STATIC / "util-tools.js").read_text(encoding="utf-8")
CHAT_MODE_JS = (STATIC / "util-chat-mode.js").read_text(encoding="utf-8")
QUOTE_JS = (STATIC / "util-quote.js").read_text(encoding="utf-8")
PDFMD_JS = (STATIC / "util-pdfmd.js").read_text(encoding="utf-8")


def test_stage2_scope_and_pinned_boundaries() -> None:
    assert 'const LIBRARY_PROJECT_NAME = "유틸";' in TOOLS_JS
    assert 'const CHAT_MODE_TOOLS = Object.freeze(["speech", "sns", "meeting"]);' in TOOLS_JS
    for token in ("PadiemUtilChatMode", "util-chat-intake", "util-mode-switch", "bindPdfmd"):
        assert token not in APP_JS
    for mod_src in (CHAT_MODE_JS, TOOLS_JS, QUOTE_JS, PDFMD_JS):
        for sink in (".innerHTML", ".outerHTML", "insertAdjacentHTML", "document.write"):
            assert sink not in mod_src
    # No hardcoded tool questions in util-chat-mode.js: questions come strictly from util-manifest.js
    for manifest_question in (
        "홍보할 행사나 소식 이름을 알려 주세요.",
        "정리할 회의 이름을 알려 주세요.",
        "견적서·발주서·답장 초안을 만들 요청 원문을 알려 주세요.",
        "Markdown으로 변환할 PDF 또는 ZIP 파일을 첨부해 주세요.",
    ):
        assert manifest_question not in CHAT_MODE_JS


NODE_HARNESS = r'''
const fs = require("node:fs");
const vm = require("node:vm");

const [manifestFile, markdownFile, contractFile, chatModeFile, toolsFile, quoteFile, pdfmdFile, appFile] = process.argv.slice(2);

const registry = [];
function El(tag) {
  return {
    tagName: String(tag || "div").toUpperCase(),
    id: "",
    className: "",
    type: "",
    name: "",
    value: "",
    textContent: "",
    placeholder: "",
    accept: "",
    multiple: false,
    rows: 0,
    maxLength: 0,
    tabIndex: 0,
    required: false,
    disabled: false,
    hidden: false,
    checked: false,
    open: false,
    focused: false,
    noValidate: false,
    isConnected: true,
    scrollTop: 0,
    scrollHeight: 100,
    style: {},
    children: [],
    attrs: {},
    dataset: {},
    listeners: {},
    parentElement: null,
    files: null,
    get classList() {
      const self = this;
      return {
        add: (...c) => { self.className = [...new Set([...String(self.className).split(/\s+/).filter(Boolean), ...c])].join(" "); },
        remove: (...c) => { const d = new Set(c); self.className = String(self.className).split(/\s+/).filter((x) => x && !d.has(x)).join(" "); },
        toggle: (c, on) => { if (on) self.classList.add(c); else self.classList.remove(c); },
        contains: (c) => String(self.className).split(/\s+/).includes(c),
      };
    },
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
    setAttribute(k, v) {
      this.attrs[k] = String(v);
      if (k === "id") this.id = String(v);
      if (k.startsWith("data-")) {
        const camel = k.slice(5).replace(/-([a-z])/g, (_, ch) => ch.toUpperCase());
        this.dataset[camel] = String(v);
      }
    },
    removeAttribute(k) { delete this.attrs[k]; },
    hasAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k); },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; },
    appendChild(child) {
      if (child.parentElement && child.parentElement !== this) {
        const idx = child.parentElement.children.indexOf(child);
        if (idx >= 0) child.parentElement.children.splice(idx, 1);
      }
      this.children.push(child);
      child.parentElement = this;
      return child;
    },
    insertBefore(child, refNode) {
      if (!refNode) return this.appendChild(child);
      if (child.parentElement) {
        const oldIdx = child.parentElement.children.indexOf(child);
        if (oldIdx >= 0) child.parentElement.children.splice(oldIdx, 1);
      }
      const idx = this.children.indexOf(refNode);
      if (idx < 0) return this.appendChild(child);
      this.children.splice(idx, 0, child);
      child.parentElement = this;
      return child;
    },
    replaceChildren(...nodes) { this.children = []; nodes.forEach((n) => this.appendChild(n)); },
    focus() { this.focused = true; },
    scrollIntoView() {},
    getBoundingClientRect() { return { top: 0, left: 0, width: 300, height: 44 }; },
    click() { (this.listeners.click || []).slice().forEach((fn) => fn({ target: this, preventDefault() {} })); },
    dispatchChange() { (this.listeners.change || []).slice().forEach((fn) => fn({ target: this })); },
    dispatchInput() { (this.listeners.input || []).slice().forEach((fn) => fn({ target: this })); },
    dispatchKeydown(ev) { (this.listeners.keydown || []).slice().forEach((fn) => fn(ev)); },
    submitForm() { (this.listeners.submit || []).slice().forEach((fn) => fn({ preventDefault() {} })); },
    closest(sel) {
      let cur = this;
      while (cur) { if (matches(cur, sel)) return cur; cur = cur.parentElement; }
      return null;
    },
    querySelector(sel) { return find(this, sel); },
    querySelectorAll(sel) { return findAll(this, sel); },
  };
}

function matches(el, sel) {
  if (!sel || !el || el.tagName === "#TEXT") return false;
  if (sel.startsWith(".")) return String(el.className || "").split(/\s+/).includes(sel.slice(1));
  if (sel.startsWith("#")) return el.id === sel.slice(1);
  const attr = /^\[([a-zA-Z0-9_-]+)(?:="([^"]*)")?\]$/.exec(sel);
  if (attr) {
    if (attr[1] === "name") return Boolean(el.name) && (attr[2] === undefined || el.name === attr[2]);
    const val = el.getAttribute(attr[1]);
    return val !== null && (attr[2] === undefined || val === attr[2]);
  }
  return el.tagName === sel.toUpperCase();
}
function walk(el, fn) { if (!el) return; fn(el); (el.children || []).forEach((c) => walk(c, fn)); }
function find(root, sel) { let out = null; walk(root, (e) => { if (!out && e !== root && matches(e, sel)) out = e; }); return out; }
function findAll(root, sel) { const out = []; walk(root, (e) => { if (e !== root && matches(e, sel)) out.push(e); }); return out; }
function fullText(el) { let out = ""; walk(el, (e) => { if (e.tagName === "#TEXT" || (!e.children.length && e.textContent)) out += e.textContent + " "; }); return out.trim(); }
function tick() { return new Promise((resolve) => setImmediate(resolve)); }
async function settle(n = 5) { for (let i = 0; i < n; i += 1) await tick(); }

const shell = El("div"); shell.className = "app-shell"; shell.dataset.state = "home";
const utilView = El("section"); utilView.id = "utilView"; utilView.hidden = true; registry.push(utilView);
const utilHeader = El("header"); utilHeader.className = "util-header"; utilView.appendChild(utilHeader);
const utilTitle = El("h2"); utilTitle.id = "utilTitle"; utilHeader.appendChild(utilTitle); registry.push(utilTitle);
const utilKicker = El("p"); utilKicker.id = "utilKicker"; utilHeader.appendChild(utilKicker); registry.push(utilKicker);
const utilTagline = El("p"); utilTagline.id = "utilTagline"; utilHeader.appendChild(utilTagline); registry.push(utilTagline);
const root = El("div"); root.id = "utilAppRoot"; utilView.appendChild(root); registry.push(root);

const requests = [];
let streamTurnCounter = 0;
let pdfJobCounter = 0;
const pdfJobs = new Map();
const listeners = {};

const loc = {
  _hash: "",
  pathname: "/index.html",
  search: "",
  get hash() { return this._hash; },
  set hash(v) {
    this._hash = String(v || "");
    (listeners.hashchange || []).forEach((fn) => fn());
  },
};
const historyObj = {
  state: null,
  replaceState(_s, _t, url) {
    const idx = String(url).indexOf("#");
    loc._hash = idx >= 0 ? String(url).slice(idx) : "";
  },
};

function fakeFetch(url, init) {
  const method = (init && init.method) || "GET";
  let parsedBody = null;
  if (init && typeof init.body === "string") {
    try { parsedBody = JSON.parse(init.body); } catch (_) { parsedBody = init.body; }
  }
  requests.push({ url, method, headers: (init && init.headers) || {}, body: parsedBody });

  if (url === "/api/chat/stream") {
    streamTurnCounter += 1;
    const isRefine = parsedBody && parsedBody.messages && String(parsedBody.messages[0].content || "").includes("추가 다듬기 요청:");
    const text = isRefine
      ? `[다듬은 결과 #${streamTurnCounter}] ${parsedBody.util} 최종 문안`
      : `[초안 결과 #${streamTurnCounter}] ${parsedBody.util} 첫 문안`;
    return Promise.resolve({
      ok: true,
      status: 200,
      headers: { get: () => "application/json" },
      json: () => Promise.resolve({ answer: text }),
    });
  }
  if (url === "/api/projects" && method === "GET") {
    return Promise.resolve({
      ok: true,
      status: 200,
      headers: { get: () => "application/json" },
      json: () => Promise.resolve({ projects: [{ id: "proj_util_1", name: "유틸" }] }),
    });
  }
  if (url.startsWith("/api/projects/") && url.endsWith("/files") && method === "POST") {
    return Promise.resolve({
      ok: true,
      status: 201,
      headers: { get: () => "application/json" },
      json: () => Promise.resolve({ file: { id: "file_saved_" + requests.length, name: parsedBody.name } }),
    });
  }
  if (url === "/api/util/quote/preview" && method === "POST") {
    const calcSummary = `# 견적서 계산 결과\n\n- 채널: ${parsedBody.channel}\n- 작업: ${parsedBody.action}\n- 발신자: ${parsedBody.sender_hint || "-"}\n- 원문: ${parsedBody.content}\n\n| 합계 |\n|---|\n| 220,000원 |`;
    return Promise.resolve({
      ok: true,
      status: 200,
      headers: { get: () => "application/json" },
      json: () => Promise.resolve({
        ok: true,
        preview: { title: "견적서 초안 (DRAFT)", result_text: calcSummary },
      }),
    });
  }
  if (url.startsWith("/api/pc/pairings")) {
    return Promise.resolve({
      ok: true,
      status: 200,
      headers: { get: () => "application/json" },
      json: () => Promise.resolve({ ok: true, links: [] }),
    });
  }
  if (url.startsWith("/api/document-conversions?limit=")) {
    return Promise.resolve({
      ok: true,
      status: 200,
      headers: { get: () => "application/json" },
      json: () => Promise.resolve({ new_work_enabled: true, jobs: Array.from(pdfJobs.values()) }),
    });
  }
  if (url === "/api/document-conversions" && method === "POST") {
    pdfJobCounter += 1;
    const jobId = "job_7461_" + pdfJobCounter;
    const job = { id: jobId, mode: parsedBody.mode, status: "queued", item_count: 0, created_at: "2026-11-12T01:00:00Z", items: [] };
    pdfJobs.set(jobId, job);
    return Promise.resolve({
      ok: true,
      status: 200,
      headers: { get: () => "application/json" },
      json: () => Promise.resolve({ job }),
    });
  }
  const uploadMatch = /^\/api\/document-conversions\/([^/]+)\/files$/.exec(url);
  if (uploadMatch && method === "POST") {
    const job = pdfJobs.get(uploadMatch[1]);
    const fname = decodeURIComponent((init.headers && init.headers["X-Padiem-Filename"]) || "doc.pdf");
    const item = { id: "item_" + pdfJobCounter, name: fname, status: "queued", has_markdown: false, page_count: 2 };
    job.items.push(item);
    job.item_count = job.items.length;
    return Promise.resolve({
      ok: true,
      status: 200,
      headers: { get: () => "application/json" },
      json: () => Promise.resolve({ items: [item], rejected: [] }),
    });
  }
  const jobGetMatch = /^\/api\/document-conversions\/([^/?]+)$/.exec(url);
  if (jobGetMatch && method === "GET") {
    const job = pdfJobs.get(jobGetMatch[1]) || { items: [] };
    return Promise.resolve({
      ok: true,
      status: 200,
      headers: { get: () => "application/json" },
      json: () => Promise.resolve({ job, items: job.items }),
    });
  }
  return Promise.resolve({ ok: true, status: 200, headers: { get: () => "application/json" }, json: () => Promise.resolve({}) });
}

const windowObj = {
  location: loc,
  history: historyObj,
  fetch: fakeFetch,
  addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
  dispatchEvent(ev) { (listeners[ev.type] || []).forEach((fn) => fn(ev)); },
  PadiemAuthSession: { get: () => ({ authenticated: true }) },
  PadiemAuthGate: { authenticated: () => true },
  PadiemTierSelection: { get: () => "plus" },
  PadiemAppSwitch: { openChat() { shell.dataset.state = "home"; }, openClaw() { shell.dataset.state = "claw"; } },
};
const document = {
  readyState: "complete",
  documentElement: { lang: "ko" },
  body: El("body"),
  head: El("head"),
  createElement(tag) { const n = El(tag); registry.push(n); return n; },
  createTextNode(t) { const n = El("#text"); n.textContent = String(t); return n; },
  getElementById(id) { const hits = registry.filter((e) => e.id === id); return hits.length ? hits[hits.length - 1] : null; },
  querySelector(sel) { return sel === ".app-shell" ? shell : null; },
  addEventListener() {},
};

const ctx = {
  document,
  window: windowObj,
  fetch: fakeFetch,
  location: loc,
  history: historyObj,
  URL: { createObjectURL: () => "blob:test", revokeObjectURL: () => {} },
  URLSearchParams,
  MutationObserver: class { observe() {} },
  CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } },
  console,
  setTimeout: () => 0,
  clearTimeout: () => {},
};
ctx.globalThis = ctx;
vm.createContext(ctx);
[manifestFile, markdownFile, contractFile, chatModeFile, toolsFile, quoteFile, pdfmdFile, appFile].forEach((file) => {
  vm.runInContext(fs.readFileSync(file, "utf8"), ctx, { filename: file });
});

(async () => {
  // ── 0. Manifest-driven proof (mutating manifest question changes rendered bubble) ──
  const injectedManifest = {
    getTool: () => ({ id: "probe", fields: [{ key: "k1", type: "text", required: true, label: { ko: "항목" }, placeholder: { ko: "" }, question: { ko: "매니페스트에서 읽은 동적 질문?" }, options: [] }] }),
    missingFields: (_id, v) => (!v || !v.k1 ? [{ key: "k1" }] : []),
    nextQuestion: (_id, v) => (!v || !v.k1 ? { fieldKey: "k1", field: { key: "k1", type: "text", options: [] }, question: "매니페스트에서 읽은 동적 질문?" } : null),
  };
  const probe = windowObj.PadiemUtilChatMode.create({ toolId: "probe", manifest: injectedManifest });
  probe.enter({});
  const manifestDrivenQuestion = fullText(probe.root);

  // ── 1. SNS 홍보 (#util/sns) + 라이브러리에 저장 & 대화로 다듬기 ──
  requests.length = 0;
  loc.hash = "#util/sns";
  await settle();
  const snsForm = find(root, "#utilToolForm-sns");
  const snsChat = find(root, '[data-util-chat-intake="sns"]');
  find(snsForm, "#utilToolField-whenwhere").value = "11월 20일 구청 광장";
  find(snsForm, '[data-platform="instagram"]').click();
  find(root, '[data-util-mode="chat"]').click();
  const snsAsked1 = findAll(snsChat, "[data-question-field]").map((n) => n.getAttribute("data-question-field"));
  const snsInput = find(snsChat, "#utilChatInput-sns");
  // Empty submit -> 0 requests
  snsInput.value = "   ";
  find(snsChat, ".util-chat-composer").submitForm();
  await settle();
  const snsReqAfterEmpty = requests.length;
  // 1st required answer ("event") -> 0 requests, asks "content" next
  snsInput.value = "겨울 김장 나눔 한마당";
  find(snsChat, ".util-chat-composer").submitForm();
  await settle();
  const snsAsked2 = findAll(snsChat, "[data-question-field]").map((n) => n.getAttribute("data-question-field"));
  const snsReqAfterFirst = requests.length;
  // 2nd required answer ("content") -> 1 request to /api/chat/stream
  snsInput.value = "봉사자 모집 및 현장 배부 안내";
  find(snsChat, ".util-chat-composer").submitForm();
  await settle();
  const snsReqAfterSecond = requests.length;
  const snsFirstPrompt = requests[0].body.messages[0].content;

  // Open in Form -> values preserved
  find(snsChat, "[data-util-open-form]").click();
  const snsFormSync = {
    formVisible: snsForm.hidden === false,
    event: find(snsForm, "#utilToolField-event").value,
    content: find(snsForm, "#utilToolField-content").value,
    whenwhere: find(snsForm, "#utilToolField-whenwhere").value,
    instaPressed: find(snsForm, '[data-platform="instagram"]').getAttribute("aria-pressed"),
  };

  // Refine via Chat + Save to Library (#7508)
  const snsSaveBtn = find(root, "[data-util-save-library]");
  const snsRefineBtn = find(root, "[data-util-refine-chat]");
  const snsSaveEnabledBeforeRefine = snsSaveBtn.disabled === false;
  snsRefineBtn.click();
  snsInput.value = "이모지 없이 담백하게 다듬어 주세요";
  find(snsChat, ".util-chat-composer").submitForm();
  await settle();
  const snsSaveEnabledAfterRefine = snsSaveBtn.disabled === false;
  snsSaveBtn.click();
  await settle();
  const snsSavedReq = requests.find((r) => r.url.endsWith("/files") && r.method === "POST");

  // ── 2. 회의정리 (#util/meeting) + 라이브러리에 저장 & 대화로 다듬기 ──
  requests.length = 0;
  loc.hash = "#util/meeting";
  await settle();
  const meetForm = find(root, "#utilToolForm-meeting");
  const meetChat = find(root, '[data-util-chat-intake="meeting"]');
  find(meetForm, "#utilToolField-attendees").value = "정책팀장, 예산담당";
  find(root, '[data-util-mode="chat"]').click();
  const meetAsked1 = findAll(meetChat, "[data-question-field]").map((n) => n.getAttribute("data-question-field"));
  const meetInput = find(meetChat, "#utilChatInput-meeting");
  meetInput.value = "";
  find(meetChat, ".util-chat-composer").submitForm();
  await settle();
  const meetReqAfterEmpty = requests.length;
  meetInput.value = "11월 예산 점검 회의";
  find(meetChat, ".util-chat-composer").submitForm();
  await settle();
  const meetAsked2 = findAll(meetChat, "[data-question-field]").map((n) => n.getAttribute("data-question-field"));
  const meetReqAfterFirst = requests.length;
  meetInput.value = "내년도 도로 보수 예산 2억 편성 합의";
  find(meetChat, ".util-chat-composer").submitForm();
  await settle();
  const meetReqAfterSecond = requests.length;
  find(meetChat, "[data-util-open-form]").click();
  const meetFormSync = {
    title: find(meetForm, "#utilToolField-title").value,
    content: find(meetForm, "#utilToolField-content").value,
    attendees: find(meetForm, "#utilToolField-attendees").value,
  };
  find(root, "[data-util-refine-chat]").click();
  meetInput.value = "결정 사항을 맨 위로 올려 주세요";
  find(meetChat, ".util-chat-composer").submitForm();
  await settle();
  const meetSaveBtn = find(root, "[data-util-save-library]");
  const meetSaveEnabledAfterRefine = meetSaveBtn.disabled === false;
  meetSaveBtn.click();
  await settle();
  const meetSavedReq = requests.find((r) => r.url.endsWith("/files") && r.method === "POST");

  // ── 3. 견적서 초안 (#util/quote) — 계산형, /api/util/quote/preview 동일 경로, AI 재계산 0건 ──
  requests.length = 0;
  loc.hash = "#util/quote";
  await settle();
  const quoteForm = find(root, "#utilToolForm-quote");
  const quoteChat = find(root, '[data-util-chat-intake="quote"]');
  find(quoteForm, "#utilQuoteField-channel").value = "kakao";
  find(quoteForm, "#utilQuoteField-action").value = "order";
  find(quoteForm, "#utilQuoteField-sender_hint").value = "한빛상사";
  find(root, '[data-util-mode="chat"]').click();
  const quoteAsked = findAll(quoteChat, "[data-question-field]").map((n) => n.getAttribute("data-question-field"));
  const quoteInput = find(quoteChat, "#utilChatInput-quote");
  // Empty submit -> 0 requests
  quoteInput.value = "  ";
  find(quoteChat, ".util-chat-composer").submitForm();
  await settle();
  const quoteReqAfterEmpty = requests.length;
  // Answer required "content" -> 1 POST to /api/util/quote/preview, 0 to /api/chat/stream
  quoteInput.value = "복사지 10박스 박스당 22,000원 발주 요청";
  find(quoteChat, ".util-chat-composer").submitForm();
  await settle();
  const quoteChatPayload = Object.assign({}, requests[0].body);
  const quoteChatOutput = fullText(find(root, "#utilQuoteOutput"));
  // Switch back to Form ("폼으로 열기") and run Form submit directly -> identical payload & output!
  find(quoteChat, "[data-util-open-form]").click();
  const quoteFormValues = {
    content: find(quoteForm, "#utilQuoteField-content").value,
    channel: find(quoteForm, "#utilQuoteField-channel").value,
    action: find(quoteForm, "#utilQuoteField-action").value,
    sender: find(quoteForm, "#utilQuoteField-sender_hint").value,
  };
  quoteForm.submitForm();
  await settle();
  const quoteFormPayload = Object.assign({}, requests[1].body);
  const quoteFormOutput = fullText(find(root, "#utilQuoteOutput"));
  // Refine via Chat on quote -> still uses /api/util/quote/preview, 0 /api/chat/stream calls!
  find(root, "[data-util-refine-chat]").click();
  quoteInput.value = "토너 2개 추가";
  find(quoteChat, ".util-chat-composer").submitForm();
  await settle();
  const quoteStreamCalls = requests.filter((r) => r.url === "/api/chat/stream").length;
  const quotePreviewCalls = requests.filter((r) => r.url === "/api/util/quote/preview").length;
  const quoteRefinedBody = requests[2].body.content;

  // ── 4. PDF → Markdown (#util/pdfmd) — 파일 첨부 질문 1개, 기존 업로드 경로 재사용 ──
  requests.length = 0;
  loc.hash = "#util/pdfmd";
  await settle(8); // allow initial GET /api/document-conversions?limit=50 -> "open" repaint
  const pdfPanel = find(root, "#utilPdfmdPanel");
  const pdfModeSel = find(pdfPanel, "#pdfmdMode");
  pdfModeSel.value = "verify";
  pdfModeSel.dispatchChange();
  find(pdfPanel, '[data-util-mode="chat"]').click();
  const pdfChat = find(pdfPanel, '[data-util-chat-intake="pdfmd"]');
  const pdfAsked = findAll(pdfChat, "[data-question-field]").map((n) => n.getAttribute("data-question-field"));
  const pdfHasFileTrigger = Boolean(find(pdfChat, "[data-util-chat-file-trigger]"));
  const pdfSummaryBefore = fullText(find(pdfChat, ".util-chat-summary"));
  const pdfPostsBefore = requests.filter((r) => r.method === "POST").length;
  // Empty submit & plain-text submit without file -> 0 POST requests!
  const pdfInput = find(pdfChat, "#utilChatInput-pdfmd");
  pdfInput.value = "";
  find(pdfChat, ".util-chat-composer").submitForm();
  await settle();
  pdfInput.value = "파일 없이 텍스트만 입력";
  find(pdfChat, ".util-chat-composer").submitForm();
  await settle();
  const pdfPostsAfterNoFile = requests.filter((r) => r.method === "POST").length;
  // Attach PDF file via chat file input -> triggers existing POST /api/document-conversions + POST .../files
  const pdfFileInput = find(pdfChat, "[data-util-chat-file]");
  pdfFileInput.files = [{ name: "구의회_회의자료.pdf", type: "application/pdf", arrayBuffer: () => Promise.resolve(new ArrayBuffer(8)) }];
  pdfFileInput.dispatchChange();
  await settle(10);
  const pdfPostUrls = requests.filter((r) => r.method === "POST").map((r) => r.url);
  const pdfJobPost = requests.find((r) => r.url === "/api/document-conversions" && r.method === "POST");
  // Open in Form -> mode "verify" and file name reflected on dropzone
  find(pdfChat, "[data-util-open-form]").click();
  const pdfBackToForm = {
    formVisible: find(pdfPanel, "#utilToolForm-pdfmd").hidden === false,
    modeValue: find(pdfPanel, "#pdfmdMode").value,
    dropTitle: fullText(find(pdfPanel, ".pdfmd-drop-title")),
    refineEnabled: find(pdfPanel, "[data-util-refine-chat]").disabled === false,
  };

  // Deep links ?mode=chat for all 4 tools
  const deepLinks = {};
  for (const tid of ["sns", "meeting", "quote", "pdfmd"]) {
    loc.hash = `#util/${tid}?mode=chat`;
    await settle(6);
    const intake = find(root, `[data-util-chat-intake="${tid}"]`);
    deepLinks[tid] = Boolean(intake && intake.hidden === false);
  }

  console.log(JSON.stringify({
    manifestDrivenQuestion,
    sns: {
      asked1: snsAsked1,
      asked2: snsAsked2,
      reqAfterEmpty: snsReqAfterEmpty,
      reqAfterFirst: snsReqAfterFirst,
      reqAfterSecond: snsReqAfterSecond,
      instaInPrompt: snsFirstPrompt.includes("인스타그램"),
      formSync: snsFormSync,
      saveBeforeRefine: snsSaveEnabledBeforeRefine,
      saveAfterRefine: snsSaveEnabledAfterRefine,
      savedDocKind: snsSavedReq && snsSavedReq.body.doc_kind,
      savedRefinedText: snsSavedReq && snsSavedReq.body.text,
    },
    meeting: {
      asked1: meetAsked1,
      asked2: meetAsked2,
      reqAfterEmpty: meetReqAfterEmpty,
      reqAfterFirst: meetReqAfterFirst,
      reqAfterSecond: meetReqAfterSecond,
      formSync: meetFormSync,
      saveAfterRefine: meetSaveEnabledAfterRefine,
      savedDocKind: meetSavedReq && meetSavedReq.body.doc_kind,
      savedRefinedText: meetSavedReq && meetSavedReq.body.text,
    },
    quote: {
      asked: quoteAsked,
      reqAfterEmpty: quoteReqAfterEmpty,
      chatPayload: quoteChatPayload,
      formPayload: quoteFormPayload,
      sameOutput: quoteChatOutput === quoteFormOutput && quoteChatOutput.includes("220,000원"),
      formValues: quoteFormValues,
      streamCalls: quoteStreamCalls,
      previewCalls: quotePreviewCalls,
      refinedBody: quoteRefinedBody,
    },
    pdfmd: {
      asked: pdfAsked,
      hasFileTrigger: pdfHasFileTrigger,
      summaryBefore: pdfSummaryBefore,
      postsBefore: pdfPostsBefore,
      postsAfterNoFile: pdfPostsAfterNoFile,
      postUrls: pdfPostUrls,
      jobMode: pdfJobPost && pdfJobPost.body.mode,
      backToForm: pdfBackToForm,
    },
    deepLinks,
  }));
})();
'''


def _run_stage2_harness() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required"
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "harness_stage2_7461.cjs"
        script.write_text(NODE_HARNESS, encoding="utf-8")
        completed = subprocess.run(
            [
                node,
                str(script),
                str(STATIC / "util-manifest.js"),
                str(STATIC / "util-tools-markdown.js"),
                str(STATIC / "util-tools-contract.js"),
                str(STATIC / "util-chat-mode.js"),
                str(STATIC / "util-tools.js"),
                str(STATIC / "util-quote.js"),
                str(STATIC / "util-pdfmd.js"),
                str(STATIC / "util-app.js"),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(completed.stdout.strip())


def test_stage2_all_four_tools_question_order_gate_sync_and_library_save() -> None:
    out = _run_stage2_harness()

    # Manifest-only question source proof
    assert "매니페스트에서 읽은 동적 질문?" in out["manifestDrivenQuestion"]

    # 1. SNS 홍보 + 라이브러리에 저장 & 대화로 다듬기
    sns = out["sns"]
    assert sns["asked1"] == ["event"]
    assert sns["asked2"] == ["event", "content"]
    assert sns["reqAfterEmpty"] == 0
    assert sns["reqAfterFirst"] == 0
    assert sns["reqAfterSecond"] == 1
    assert sns["instaInPrompt"] is True
    assert sns["formSync"] == {
        "formVisible": True,
        "event": "겨울 김장 나눔 한마당",
        "content": "봉사자 모집 및 현장 배부 안내",
        "whenwhere": "11월 20일 구청 광장",
        "instaPressed": "true",
    }
    assert sns["saveBeforeRefine"] is True
    assert sns["saveAfterRefine"] is True
    assert sns["savedDocKind"] == "sns"
    assert "[다듬은 결과 #" in sns["savedRefinedText"]

    # 2. 회의정리 + 라이브러리에 저장 & 대화로 다듬기
    meet = out["meeting"]
    assert meet["asked1"] == ["title"]
    assert meet["asked2"] == ["title", "content"]
    assert meet["reqAfterEmpty"] == 0
    assert meet["reqAfterFirst"] == 0
    assert meet["reqAfterSecond"] == 1
    assert meet["formSync"] == {
        "title": "11월 예산 점검 회의",
        "content": "내년도 도로 보수 예산 2억 편성 합의",
        "attendees": "정책팀장, 예산담당",
    }
    assert meet["saveAfterRefine"] is True
    assert meet["savedDocKind"] == "meeting"
    assert "[다듬은 결과 #" in meet["savedRefinedText"]

    # 3. 견적서 초안 — 계산 경로 동일(/api/util/quote/preview), 대화 중 AI 재계산(/api/chat/stream) 0건
    quote = out["quote"]
    assert quote["asked"] == ["content"]
    assert quote["reqAfterEmpty"] == 0
    assert quote["chatPayload"] == quote["formPayload"] == {
        "content": "복사지 10박스 박스당 22,000원 발주 요청",
        "channel": "kakao",
        "action": "order",
        "sender_hint": "한빛상사",
    }
    assert quote["sameOutput"] is True
    assert quote["formValues"] == {
        "content": "복사지 10박스 박스당 22,000원 발주 요청",
        "channel": "kakao",
        "action": "order",
        "sender": "한빛상사",
    }
    assert quote["streamCalls"] == 0
    assert quote["previewCalls"] == 3
    assert "토너 2개 추가" in quote["refinedBody"]

    # 4. PDF → Markdown — 첨부 질문 1개, 파일 전 요청 0건, 첨부 시 기존 업로드 경로만 실행
    pdfmd = out["pdfmd"]
    assert pdfmd["asked"] == ["files"]
    assert pdfmd["hasFileTrigger"] is True
    assert "검증 변환" in pdfmd["summaryBefore"]
    assert pdfmd["postsBefore"] == 0
    assert pdfmd["postsAfterNoFile"] == 0
    assert pdfmd["postUrls"] == [
        "/api/document-conversions",
        "/api/document-conversions/job_7461_1/files",
    ]
    assert pdfmd["jobMode"] == "verify"
    assert pdfmd["backToForm"] == {
        "formVisible": True,
        "modeValue": "verify",
        "dropTitle": "구의회_회의자료.pdf",
        "refineEnabled": True,
    }

    # Deep links ?mode=chat work on all 4 tools
    assert out["deepLinks"] == {
        "sns": True,
        "meeting": True,
        "quote": True,
        "pdfmd": True,
    }
