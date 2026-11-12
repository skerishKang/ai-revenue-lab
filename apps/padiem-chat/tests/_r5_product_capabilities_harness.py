"""R2 마무리 1단계 — product-capabilities 구역 실행 관찰 하네스 (#7186).

`static/product-capabilities.js`(모델 등급 패널 + PADIEM Custom/BYOK 배선)를
Node vm에서 그대로 실행하고, 소스 문자열 대신 **호출 결과**를 돌려준다:

- 등급 패널: 서버 등급에서 온 4칸(free·plus·pro·max) 순서·상태·비활성·배지,
  Custom 칩(등급 행 규칙), 패널이 composer-tools 안에 붙는 배선,
  모드알(role·tabindex·aria)과 Enter/Escape 키보드 배선,
  등급 선택이 `padiem:tierchange`와 `PadiemTierSelection`으로 공유되는 것.
- BYOK 흐름: 서버가 알려 준 공급자만 선택 칸에 렌더되는 것, 능력 플래그
  (모델 목록·연결 시험·주소 칸)가 화면 통제를 그대로 따르는 것,
  키 등록이 /api/byok/detect → /api/byok/register 한 번으로 검증·등록하는 것,
  연결 시험·모델 목록이 서버 응답으로만 성공을 말하는 것,
  모델 없이 Custom을 고르면 거절하고 모델 칸으로 포커스하는 것,
  삭제가 확인창 뒤 DELETE(본문 없음)로 가는 것.

부재 금지(금지 문자열·레거시 흔적)와 문구 표 자체는 구조 계약이라 각 시험이
소스 문자열로 남긴다(이유는 시험 docstring). 값·토큰은 만들지 않는다:
파일은 합성 객체다.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
MODULE = STATIC / "product-capabilities.js"

_NODE = r"""
const fs = require("fs");
const vm = require("vm");

function makeElement(tag) {
  const attrs = {};
  const classes = new Set();
  const node = {
    tagName: String(tag || "div").toUpperCase(),
    get id() { return attrs.id === undefined ? "" : attrs.id; },
    set id(v) { attrs.id = String(v); },
    type: "", value: "", hidden: false, disabled: false,
    open: false, isConnected: true, dataset: null, attrs, children: [],
    parentElement: null, style: {}, scrollHeight: 0, focused: 0,
    htmlFor: "", placeholder: "", rel: "", href: "",
    get className() { return Array.from(classes).join(" "); },
    set className(v) {
      classes.clear();
      String(v || "").split(/\s+/).filter(Boolean).forEach((c) => classes.add(c));
    },
    classList: {
      add(...xs) { xs.forEach((x) => classes.add(x)); },
      remove(...xs) { xs.forEach((x) => classes.delete(x)); },
      contains(x) { return classes.has(x); },
      toggle(x, on) { on ? classes.add(x) : classes.delete(x); },
    },
    setAttribute(k, v) { attrs[k] = String(v); },
    getAttribute(k) { return attrs[k] === undefined ? null : attrs[k]; },
    removeAttribute(k) { delete attrs[k]; },
    dataset: null,
    append(...xs) { xs.forEach((x) => this.appendChild(x)); },
    appendChild(x) { x.parentElement = this; this.children.push(x); return x; },
    insertBefore(x, ref) {
      const i = this.children.indexOf(ref);
      if (i < 0) this.children.push(x); else this.children.splice(i, 0, x);
      x.parentElement = this; return x;
    },
    replaceChildren(...xs) { this.children = []; xs.forEach((x) => this.appendChild(x)); },
    remove() { if (this.parentElement) {
      const i = this.parentElement.children.indexOf(this);
      if (i >= 0) this.parentElement.children.splice(i, 1);
    } },
    focus() { this.focused += 1; },
    addEventListener(t, fn) { (node.listeners[t] = node.listeners[t] || []).push(fn); },
    dispatchEvent(ev) {
      const base = Object.assign({ preventDefault() {}, stopPropagation() {} }, ev || {});
      base.type = ev && ev.type; base.target = node;
      (node.listeners[base.type] || []).forEach((fn) => fn(base));
      return true;
    },
    listeners: {},
    closest(sel) {
      const want = String(sel).replace(/^[.#]/, "");
      let at = this;
      while (at) {
        if (at.tagName === want.toUpperCase()
            || (typeof at.className === "string" && at.className.split(/\s+/).includes(want))) return at;
        at = at.parentElement;
      }
      return null;
    },
    querySelector(sel) { return queryIn(this, sel, true); },
    querySelectorAll(sel) { return queryIn(this, sel, false); },
  };
  // dataset is a live view over data-* attributes, like a real element.
  node.dataset = new Proxy({}, {
    get(_t, k) { const v = attrs[toAttrName(k)]; return v === undefined ? "" : v; },
    set(_t, k, v) { attrs[toAttrName(k)] = String(v); return true; },
    has(_t, k) { return toAttrName(k) in attrs; },
  });
  // textContent follows real DOM semantics: reading concatenates the subtree,
  // writing replaces every child.
  let ownText = "";
  Object.defineProperty(node, "textContent", {
    get() {
      if (node.children.length) return node.children.map((c) => c.textContent).join("");
      return ownText;
    },
    set(v) { ownText = String(v === undefined ? "" : v); node.children = []; },
  });
  return node;
}
function toAttrName(k) {
  return "data-" + String(k).replace(/[A-Z]/g, (c) => "-" + c.toLowerCase());
}
function walk(root) {
  const out = [];
  const step = (n) => {
    for (const child of n.children || []) { out.push(child); step(child); }
  };
  step(root);
  return out;
}
function queryIn(root, sel, first) {
  const parts = String(sel).trim().split(/\s+/).filter(Boolean);
  const last = parts[parts.length - 1];
  const found = [];
  for (const n of walk(root)) {
    if (!matches(n, last)) continue;
    if (parts.length > 1 && !ancestorMatches(n, parts.slice(0, -1))) continue;
    if (first) return n;
    found.push(n);
  }
  return first ? null : found;
}
function ancestorMatches(node, chain) {
  let at = node.parentElement;
  let i = chain.length - 1;
  while (at && i >= 0) {
    if (matches(at, chain[i])) i -= 1;
    at = at.parentElement;
  }
  return i < 0;
}
function matches(node, selRaw) {
  let sel = String(selRaw).trim();
  let lastChild = false;
  if (sel.endsWith(":last-child")) { lastChild = true; sel = sel.slice(0, -":last-child".length); }
  let rest = sel.replace(/\[([^\]=]+)(?:="([^"]*)")?\]/g, (all, name, val) => {
    const key = name.trim();
    if (!(key in node.attrs)) return "\u0000";
    if (val !== undefined && node.attrs[key] !== val) return "\u0000";
    return "";
  });
  if (rest.includes("\u0000")) return false;
  const idm = rest.match(/#([\w-]+)/);
  if (idm && node.attrs.id !== idm[1]) return false;
  for (const c of rest.match(/\.[\w-]+/g) || []) {
    if (!node.classList.contains(c.slice(1))) return false;
  }
  const tag = rest.replace(/[.#][\w-]+/g, "").trim();
  if (tag && node.tagName !== tag.toUpperCase()) return false;
  if (lastChild) {
    const p = node.parentElement;
    if (!p || p.children[p.children.length - 1] !== node) return false;
  }
  return true;
}

// ── boot: product-capabilities.js 를 그대로 실행 ────────────────────────────
const byId = {};
function node(id, tag) { const e = makeElement(tag); e.id = id; byId[id] = e; return e; }
for (const id of ["loginButton", "accountName", "projectsNavButton", "loginPending"]) node(id, "div");

const modePill = makeElement("button");
modePill.className = "model-pill composer-tier-trigger";
const pillIcon = makeElement("span");
const pillLabel = makeElement("span");
modePill.append(pillIcon, pillLabel);
const modeHost = makeElement("div");
modeHost.className = "composer-tools";
const accountContainer = makeElement("div");
accountContainer.className = "sidebar-account";

const head = makeElement("head");
const body = makeElement("body");
const documentElement = makeElement("html");
documentElement.lang = "ko";
const documentRoot = makeElement("#document");
documentRoot.append(head, body);
const windowListeners = {};
const timers = [];
const fetchCalls = [];
const routes = [];
function route(prefix, status, body) {
  routes.push({ prefix: String(prefix), status, body });
}
function jsonResponse(status, body) {
  return {
    ok: status >= 200 && status < 400, status,
    json: () => Promise.resolve(typeof body === "string" ? JSON.parse(body) : body),
  };
}
function fakeFetch(url, opts) {
  const call = {
    url: String(url),
    method: String((opts && opts.method) || "GET").toUpperCase(),
    body: opts && opts.body !== undefined ? String(opts.body) : null,
    credentials: opts && opts.credentials || null,
  };
  fetchCalls.push(call);
  const hitIdx = routes.reduce((acc, r, i) => (call.url.startsWith(r.prefix) ? i : acc), -1);
  const hit = hitIdx >= 0 ? routes[hitIdx] : null;
  return Promise.resolve(hit ? jsonResponse(hit.status, hit.body) : jsonResponse(404, { ok: false }));
}
function settle(times) {
  const n = times || 6;
  let p = Promise.resolve();
  for (let i = 0; i < n; i += 1) {
    p = p.then(() => new Promise((r) => setImmediate(r)));
  }
  return p;
}
const windowObj = {
  fetch: fakeFetch,
  setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
  clearTimeout: () => {},
  addEventListener(t, fn) { (windowListeners[t] = windowListeners[t] || []).push(fn); },
  dispatchEvent(ev) {
    (windowListeners[ev && ev.type] || []).forEach((fn) => fn(ev));
    return true;
  },
  confirmCalls: [],
  confirm(msg) { this.confirmCalls.push(String(msg)); return true; },
  CustomEvent: function CustomEvent(type, init) {
    this.type = type; this.detail = init && init.detail;
  },
  AbortController: class { constructor() { this.signal = { aborted: false }; } abort() { this.signal.aborted = true; } },
  MutationObserver: class { observe() {} disconnect() {} },
};
const documentObj = {
  readyState: "complete",
  documentElement,
  head, body,
  createElement: (t) => makeElement(t),
  getElementById: (id) => byId[id] || null,
  querySelector: (sel) => walk(documentRoot).find((n) => matches(n, sel)) || null,
  querySelectorAll: (sel) => walk(documentRoot).filter((n) => matches(n, sel)),
  addEventListener(t, fn) { (windowListeners["doc:" + t] = windowListeners["doc:" + t] || []).push(fn); },
};
modeHost.appendChild(modePill);
body.append(modeHost, accountContainer, byId.loginButton, byId.accountName,
            byId.projectsNavButton, byId.loginPending);

function bootModule() {
  const ctx = {
    window: windowObj,
    document: documentObj,
    fetch: fakeFetch,
    console,
    Date, Math, JSON, Promise, Set, Map, Object, Array, String, Number, Boolean,
    encodeURIComponent, decodeURIComponent, setTimeout: windowObj.setTimeout,
    clearTimeout: windowObj.clearTimeout,
    MutationObserver: windowObj.MutationObserver,
    CustomEvent: windowObj.CustomEvent,
    AbortController: windowObj.AbortController,
  };
  ctx.globalThis = ctx;
  ctx.self = ctx;
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx,
                  { filename: "product-capabilities.js" });
  return ctx;
}

function flushTimers() {
  const run = timers.splice(0, timers.length);
  run.forEach((t) => { try { t.fn(); } catch (_) { /* 타이머 실패는 관찰 대상 아님 */ } });
}

function panelButtons() {
  const panel = walk(modeHost).find((n) => n.classList.contains("mode-presentation-panel"));
  if (!panel) return { panel: null, options: [] };
  const list = panel.querySelector(".mode-option-list");
  return { panel, list,
           options: list ? walk(list).filter((n) => n.tagName === "BUTTON") : [] };
}
function customParts() {
  const panel = panelButtons().panel;
  const section = panel ? walk(panel).find((n) => n.classList.contains("mode-custom-section")) : null;
  if (!section) return null;
  const find = (sel) => section.querySelector(sel);
  return {
    section,
    option: find(".mode-option--custom"),
    optionTitle: find(".mode-option--custom strong"),
    optionModel: find(".mode-option--custom small"),
    optionState: find(".mode-option--custom .mode-option-state"),
    heading: find("#modeCustomTitle"),
    providerSelect: find("#modeCustomProvider"),
    modelSelect: find("#modeCustomModelSelect"),
    modelInput: find("#modeCustomModelInput"),
    endpointInput: find("#modeCustomEndpoint"),
    keyInput: find("#modeAutoByokKey"),
    registerButton: find("#modeAutoByokRegister"),
    testButton: find(".mode-custom-test"),
    listButton: find(".mode-custom-model-load"),
    deleteButton: find(".mode-custom-delete"),
    message: find(".mode-custom-message"),
    status: find(".mode-custom-status"),
    advanced: find("#modeCustomAdvanced"),
    reasoningSelect: find("#modeCustomReasoning"),
  };
}

// ── 시나리오 ─────────────────────────────────────────────────────────────────
const AUTH_PLUS = { ready: true, authenticated: true, session_state: "signed_in",
  user: { name: "\ud14c\uc2a4\ud2b8", email: "member@example.com" }, member_grade: "plus",
  history_ready: true, project_files_ready: true };
function bootRoutes(opts) {
  const o = opts || {};
  route("/health", 200, { ok: true, web_search: true, deep_research: false, auth: true,
    projects: true, project_files: true, saved_outputs: true });
  route("/api/auth/status", 200, o.auth === undefined ? AUTH_PLUS : o.auth);
  route("/api/account/model-selection", 200, { ok: true, selection: null, restorable_tier: "" });
  route("/api/b66/admin/me", 200, { ok: true, admin: false });
  route("/api/chat/custom/credential", 200, o.credential || { ok: true, providers: [],
    credentials: [], byok_engine_enabled: false });
}

const scenarios = {
  // 등급 패널: 4칸 순서·상태·배지·Custom 칩·배선·키보드·선택 공유.
  async mode_tiers() {
    bootRoutes({});
    bootModule();
    await settle(); flushTimers();
    const caps = windowObj.PadiemProductCapabilities;
    const tiers = windowObj.PadiemTierSelection;
    const events = [];
    windowObj.addEventListener("padiem:tierchange", (e) => events.push(e.detail && e.detail.tier));
    tiers.open();
    const { panel, options } = panelButtons();
    const custom = customParts();
    const out = {
      panelFound: Boolean(panel),
      panelParentIsModeHost: Boolean(panel) && panel.parentElement === modeHost,
      panelInDocumentBody: Boolean(panel) && panel.parentElement === body,
      optionValues: options.map((b) => b.dataset.modeValue),
      optionStatuses: options.map((b) => b.dataset.modeStatus),
      optionDisabled: options.map((b) => b.disabled),
      optionIcons: options.map((b) => {
        const st = b.querySelector(".mode-option-state-icon"); return st ? st.textContent : null;
      }),
      optionTitles: options.map((b) => { const t = b.querySelector("strong"); return t ? t.textContent : null; }),
      panelTitle: (panel.querySelector("[data-mode-title]") || {}).textContent || null,
      pillAttrs: {
        role: modePill.getAttribute("role"), tabindex: modePill.getAttribute("tabindex"),
        haspopup: modePill.getAttribute("aria-haspopup"),
        expanded: modePill.getAttribute("aria-expanded"),
      },
      pillLabel: pillLabel.textContent,
      customLane: custom && custom.option ? {
        classes: String(custom.option.className),
        modeValue: custom.option.dataset.modeValue,
        title: custom.optionTitle ? custom.optionTitle.textContent : null,
        modelText: custom.optionModel ? custom.optionModel.textContent : null,
      } : null,
      customHeadingChildren: custom && custom.heading
        ? custom.heading.parentElement.children.map((n) => n.tagName) : null,
      styleLinkInHead: walk(head).some((n) => n.tagName === "LINK"
        && n.attrs["data-b62-mode-styles"] === "true"),
      tierSelectionKeys: Object.keys(tiers || {}),
      tierGetBefore: tiers ? tiers.get() : null,
    };
    // 사용 가능한 등급 클릭 → 선택 공유 + 서버 저장(PUT).
    const free = options.find((b) => b.dataset.modeValue === "free");
    if (free) free.dispatchEvent({ type: "click" });
    await settle();
    out.tierGetAfterFreeClick = tiers.get();
    out.tierEvents = events;
    out.selectionPut = fetchCalls.filter((c) => c.url.startsWith("/api/account/model-selection")
      && c.method === "PUT").map((c) => c.body);
    // 상위 등급(upgrade) 클릭 → 선택 변화 없이 안내만.
    tiers.open();
    const pro = panelButtons().options.find((b) => b.dataset.modeValue === "pro");
    if (pro) pro.dispatchEvent({ type: "click" });
    await settle();
    const truth = panelButtons().panel.querySelector("[data-mode-truth]");
    out.upgradeTruthText = truth ? truth.textContent : null;
    out.upgradeTruthHighlighted = truth ? truth.classList.contains("is-highlighted") : null;
    out.tierGetAfterUpgradeClick = tiers.get();
    flushTimers();
    // 키보드: Escape 닫힘, Enter 다시 열림.
    modePill.dispatchEvent({ type: "keydown", key: "Escape" });
    out.panelHiddenAfterEscape = panelButtons().panel.hidden;
    modePill.dispatchEvent({ type: "keydown", key: "Enter" });
    out.panelHiddenAfterEnter = panelButtons().panel.hidden;
    return out;
  },

  // 게스트 부팅: 기본 등급은 free이고 상위 등급은 모두 업그레이드다.
  async mode_tiers_guest() {
    bootRoutes({ auth: { ready: true, authenticated: false, session_state: "guest" } });
    bootModule();
    await settle(); flushTimers();
    const tiers = windowObj.PadiemTierSelection;
    tiers.open();
    const { options } = panelButtons();
    const custom = customParts();
    return {
      tierGet: tiers.get(),
      optionValues: options.map((b) => b.dataset.modeValue),
      optionStatuses: options.map((b) => b.dataset.modeStatus),
      optionDisabled: options.map((b) => b.disabled),
      customDisabled: custom && custom.option ? custom.option.disabled : null,
      customAriaDisabled: custom && custom.option ? custom.option.getAttribute("aria-disabled") : null,
    };
  },

  // 서버가 알려 준 공급자만 · 능력 플래그가 화면 통제를 따름 · 시험/목록/삭제.
  async custom_flow() {
    bootRoutes({ credential: { ok: true, byok_engine_enabled: true,
      providers: [
        { provider: "prov-a", display_name: "\uacf5\uae09\uc790 A", models: ["m1", "m2"],
          manual_model: false, supports_model_listing: true,
          supports_connection_test: true, supports_custom_endpoint: true },
        { provider: "prov-b", display_name: "B", models: [],
          manual_model: true, supports_model_listing: false,
          supports_connection_test: false, supports_custom_endpoint: false },
      ],
      credentials: [{ provider: "prov-a", key_last4: "abcd", endpoint: "",
        endpoint_is_default: true }] } });
    bootModule();
    await settle(); flushTimers();
    windowObj.PadiemTierSelection.open();
    const p = customParts();
    const out = {};
    out.providerOptionValues = walk(p.providerSelect).filter((n) => n.tagName === "OPTION")
      .map((n) => n.value);
    out.providerValueBeforeChoice = p.providerSelect.value;
    out.noProviderChosenByDefault = p.providerSelect.value === "";
    out.provB = {};
    // prov-a 선택 → 모델 목록이 서버 rows에서만 채워짐.
    p.providerSelect.value = "prov-a";
    p.providerSelect.dispatchEvent({ type: "change" });
    await settle();
    const p2 = customParts();
    out.modelOptionValues = walk(p2.modelSelect).filter((n) => n.tagName === "OPTION")
      .map((n) => n.value);
    out.listButtonHidden = p2.listButton.hidden;
    out.endpointHidden = p2.endpointInput.hidden;
    out.endpointPlaceholder = p2.endpointInput.placeholder;
    out.testHiddenWithCredential = p2.testButton.hidden;
    out.deleteHiddenWithCredential = p2.deleteButton.hidden;
    out.statusHidden = p2.status.hidden;
    out.statusText = p2.status.textContent;
    out.statusLeaksKeyFragment = String(p2.section.textContent || "").includes("abcd");
    // 모델 목록 불러오기: 서버 응답이 성공의 유일한 근거.
    route("/api/chat/custom/models", 200, { ok: true, models: ["m1", "m2", "m3"] });
    p2.listButton.dispatchEvent({ type: "click" });
    await settle();
    const p3 = customParts();
    out.modelsCall = fetchCalls.filter((c) => c.url.startsWith("/api/chat/custom/models"))
      .map((c) => c.url);
    out.modelsLoadedMessage = p3.message.textContent;
    out.modelsMessageState = p3.message.dataset.state;
    out.modelsAfterLoad = walk(p3.modelSelect).filter((n) => n.tagName === "OPTION")
      .map((n) => n.value);
    // 연결 시험 성공.
    route("/api/chat/custom/credential/test", 200, { ok: true });
    p3.testButton.dispatchEvent({ type: "click" });
    await settle();
    const p4 = customParts();
    out.testCall = fetchCalls.filter((c) => c.url.includes("/api/chat/custom/credential/test"))
      .map((c) => c.url);
    out.testOkMessage = p4.message.textContent;
    out.testOkState = p4.message.dataset.state;
    // 연결 시험 실패 → 서버 응답이 실패를 말하고, 클라이언트가 성공을 만들지 않는다.
    route("/api/chat/custom/credential/test", 500, { ok: false,
      error: { message: "\uc11c\ubc84\uac00 \uac70\uc808\ud588\uc2b5\ub2c8\ub2e4" } });
    p4.testButton.dispatchEvent({ type: "click" });
    await settle();
    const p5 = customParts();
    out.testFailMessage = p5.message.textContent;
    out.testFailState = p5.message.dataset.state;
    // prov-b: 능력 플래그가 모두 없으면 모든 부가 통제가 숨는다.
    p5.providerSelect.value = "prov-b";
    p5.providerSelect.dispatchEvent({ type: "change" });
    await settle();
    const p6 = customParts();
    out.provB = {
      modelSelectHidden: p6.modelSelect.hidden,
      modelInputHidden: p6.modelInput.hidden,
      listButtonHidden: p6.listButton.hidden,
      endpointHidden: p6.endpointInput.hidden,
      testHidden: p6.testButton.hidden,
      deleteHidden: p6.deleteButton.hidden,
    };
    out.ids = {
      providerSelect: p6.providerSelect.id,
      modelSelect: p6.modelSelect.id,
      modelInput: p6.modelInput.id,
      endpointInput: p6.endpointInput.id,
      testButtonClass: String(p6.testButton.className),
      keyInputId: p6.keyInput.id,
      registerButtonId: p6.registerButton.id,
    };
    out.endpointPlaceholder = p6.endpointInput.placeholder;
    // 다시 prov-a로 돌아가 삭제를 관찰한다.
    p6.providerSelect.value = "prov-a";
    p6.providerSelect.dispatchEvent({ type: "change" });
    await settle();
    const p7 = customParts();
    // 삭제: 확인창 뒤 DELETE(본문 없음), 그 뒤 상태 새로 읽음.
    const getCallsBeforeDelete = fetchCalls.filter((c) =>
      c.url.startsWith("/api/chat/custom/credential") && c.method === "GET").length;
    route("/api/chat/custom/credential?provider=", 200, { ok: true });
    p7.deleteButton.dispatchEvent({ type: "click" });
    await settle(); flushTimers();
    out.confirmCalls = windowObj.confirmCalls;
    out.deleteCall = fetchCalls.filter((c) => c.method === "DELETE")
      .map((c) => ({ url: c.url, body: c.body }));
    out.refreshAfterDelete = fetchCalls.filter((c) =>
      c.url.startsWith("/api/chat/custom/credential") && c.method === "GET").length
      - getCallsBeforeDelete;
    return out;
  },

  // 키 등록: 한 번의 등록 클릭이 detect → register로 이어지고 키는 지워진다.
  async register_flow() {
    bootRoutes({ credential: { ok: true, providers: [], credentials: [],
      byok_engine_enabled: false } });
    bootModule();
    await settle(); flushTimers();
    windowObj.PadiemTierSelection.open();
    const p = customParts();
    const out = {};
    out.keyInputType = p.keyInput.type;
    out.advancedOpenByDefault = p.advanced.open;
    // 짧은 키 → 서버 호출 없이 거절.
    p.keyInput.value = "short";
    p.registerButton.dispatchEvent({ type: "click" });
    await settle();
    out.shortKeyMessage = customParts().message.textContent;
    out.fetchCountAfterShortKey = fetchCalls.length;
    // 정상 키 → detect → register → 키 지움 + 상태 새로 읽음.
    route("/api/byok/detect", 200, { verified: true, provider: "prov-x", models: ["mx1"] });
    route("/api/byok/register", 200, { ok: true, selection: { provider: "prov-x", model: "mx1" },
      models: ["mx1"] });
    route("/api/chat/custom/credential", 200, { ok: true, byok_engine_enabled: true,
      providers: [{ provider: "prov-x", display_name: "X", models: ["mx1"], manual_model: false,
        supports_model_listing: false, supports_connection_test: false,
        supports_custom_endpoint: false }],
      credentials: [{ provider: "prov-x", key_last4: "9876", endpoint: "",
        endpoint_is_default: true }] });
    p.keyInput.value = "k".repeat(20);
    p.registerButton.dispatchEvent({ type: "click" });
    await settle(); flushTimers();
    const p2 = customParts();
    out.registerCalls = fetchCalls.filter((c) => c.url.startsWith("/api/byok/"))
      .map((c) => ({ url: c.url, method: c.method, body: c.body ? JSON.parse(c.body) : null }));
    out.keyClearedAfterRegister = p2.keyInput.value === "";
    out.registeredStatus = p2.status.textContent;
    out.messageAfterRegister = p2.message.textContent;
    out.providerValueAfterRegister = p2.providerSelect.value;
    // 자동 인식 실패 → 고급 칸만 펼치고 등록 호출은 없다.
    route("/api/byok/detect", 200, { verified: false, reason: "\ubabb \uc54c\uc544\ubd04" });
    p2.keyInput.value = "k".repeat(20);
    p2.registerButton.dispatchEvent({ type: "click" });
    await settle(); flushTimers();
    const p3 = customParts();
    out.detectFailMessage = p3.message.textContent;
    out.advancedOpenAfterDetectFail = p3.advanced.open;
    out.detectCallCount = fetchCalls.filter((c) => c.url.startsWith("/api/byok/detect")).length
      - 1; // 성공 등록 1회를 제외한 증분
    // 직접 저장: 고른 공급자 + 모델 + 키 → PUT(주소는 적었을 때만 실린다).
    // prov-x는 서버가 모델 목록을 준(registry) 공급자라 모델은 선택 칸에서 온다.
    p3.providerSelect.value = "prov-x";
    p3.providerSelect.dispatchEvent({ type: "change" });
    await settle();
    const p4 = customParts();
    p4.modelSelect.value = "mx1";
    p4.modelSelect.dispatchEvent({ type: "change" });
    p4.keyInput.value = "k".repeat(20);
    p4.registerButton.dispatchEvent({ type: "click" });
    await settle(); flushTimers();
    const puts = fetchCalls.filter((c) => c.method === "PUT")
      .map((c) => ({ url: c.url, body: c.body ? JSON.parse(c.body) : null }));
    out.saveKeyPuts = puts;
    p4.endpointInput.value = "https://relay.example/v1";
    p4.endpointInput.dispatchEvent({ type: "input" });
    p4.keyInput.value = "k".repeat(20);
    p4.registerButton.dispatchEvent({ type: "click" });
    await settle(); flushTimers();
    out.saveKeyPutsWithEndpoint = fetchCalls.filter((c) => c.method === "PUT")
      .slice(puts.length).map((c) => ({ url: c.url, body: c.body ? JSON.parse(c.body) : null }));
    return out;
  },

  // 모델 없이 Custom 선택 → 거절 + 모델 칸 포커스; 모델과 함께면 선택 공유.
  async manual_gate() {
    bootRoutes({ credential: { ok: true, byok_engine_enabled: true,
      providers: [{ provider: "prov-m", display_name: "M", models: [],
        manual_model: true, supports_model_listing: false,
        supports_connection_test: false, supports_custom_endpoint: false }],
      credentials: [{ provider: "prov-m", key_last4: "wxyz", endpoint: "",
        endpoint_is_default: true }] } });
    bootModule();
    await settle(); flushTimers();
    const caps = windowObj.PadiemProductCapabilities;
    const sel = windowObj.PadiemCustomSelection;
    const out = { selectionKeys: Object.keys(sel || {}), capsKeys: Object.keys(caps || {}) };
    out.guestSelectionNull = sel.get();
    windowObj.PadiemTierSelection.open();
    const p = customParts();
    p.providerSelect.value = "prov-m";
    p.providerSelect.dispatchEvent({ type: "change" });
    await settle();
    // 모델 없이 선택 → 거절, 모델 칸으로 포커스, 선택 없음.
    const before = fetchCalls.length;
    sel.select();
    await settle(); flushTimers();
    const p2 = customParts();
    out.modelGateMessage = p2.message.textContent;
    out.modelGateMessageState = p2.message.dataset.state;
    out.modelInputFocused = p2.modelInput.focused;
    out.advancedOpenAfterGate = p2.advanced.open;
    out.selectionStillNull = sel.get();
    out.streamNotCalled = fetchCalls.slice(before)
      .every((c) => !c.url.startsWith("/api/chat/stream"));
    // 모델을 입력하면 선택이 만들어진다; 기본 추론은 필드를 보내지 않는다.
    p2.modelInput.value = "my-model";
    p2.modelInput.dispatchEvent({ type: "input" });
    sel.select();
    await settle(); flushTimers();
    out.selectionWithModel = sel.get();
    const p3 = customParts();
    p3.reasoningSelect.value = "high";
    p3.reasoningSelect.dispatchEvent({ type: "change" });
    sel.select();
    await settle(); flushTimers();
    out.selectionWithReasoning = sel.get();
    return out;
  },
};

(async () => {
  const name = process.argv[3];
  const fn = scenarios[name];
  if (!fn) { console.error("unknown scenario " + name); process.exit(2); }
  try {
    const result = await fn();
    process.stdout.write(JSON.stringify(result));
  } catch (err) {
    console.error(String(err && err.stack || err));
    process.exit(1);
  }
})();
"""


def _node() -> str:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("node 실행 파일이 필요합니다")
    return node


@lru_cache(maxsize=1)
def _harness_file() -> Path:
    tmp = tempfile.mkdtemp(prefix="padiem-cap-harness-")
    path = Path(tmp) / "harness.js"
    path.write_text(_NODE, encoding="utf-8")
    return path


def run_capabilities_scenario(name: str) -> dict:
    """시나리오 하나를 실제 모듈 실행으로 관찰해 돌려준다."""
    proc = subprocess.run(
        [_node(), str(_harness_file()), str(MODULE), name],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"product-capabilities 시나리오 {name!r} 실행 실패:\n{proc.stderr}\n{proc.stdout}"
        )
    return json.loads(proc.stdout)

