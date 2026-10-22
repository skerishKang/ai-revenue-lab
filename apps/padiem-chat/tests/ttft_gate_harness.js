// #5554 TTFT gate harness.
//
// Loads the SHIPPED apps/padiem-chat/static/product-capabilities.js in Node with a
// minimal browser stub and records the observable behaviour of the outgoing
// request gate:
//
//   S1  the account-selection read is issued BEFORE the administrator probe is
//       awaited, so the two independent reads overlap instead of running one
//       after the other.
//   S2  the gate does NOT wait for an auth refresh that was queued AFTER the
//       current generation (the window-focus case that held the user's message).
//   S3  the gate still waits for the CURRENT generation's restore, so a request
//       never leaves with a tier that was not verified yet (#5222).
//
// Prints one JSON object on stdout.
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SRC = path.join(__dirname, "..", "static", "product-capabilities.js");

function makeElement() {
  return {
    tagName: "DIV", className: "", id: "", textContent: "", innerHTML: "", value: "",
    type: "", href: "", src: "", alt: "", title: "", role: "", placeholder: "",
    style: {}, dataset: {}, hidden: false, disabled: false, checked: false,
    selected: false, required: false, readOnly: false, open: false,
    classList: {add() {}, remove() {}, toggle() {}, contains() { return false; }},
    children: [], childNodes: [], parentNode: null, parentElement: null,
    firstChild: null, lastChild: null, attributes: {}, scrollTop: 0,
    scrollHeight: 0, clientHeight: 0, clientWidth: 0, offsetHeight: 0, offsetWidth: 0,
    appendChild(c) { return c; }, removeChild(c) { return c; }, insertBefore(c) { return c; },
    replaceChild(c) { return c; }, cloneNode() { return makeElement(); },
    remove() {}, setAttribute() {}, getAttribute() { return null; },
    removeAttribute() {}, hasAttribute() { return false; },
    append(...nodes) { return undefined; }, prepend(...nodes) { return undefined; },
    replaceChildren(...nodes) { return undefined; }, insertAdjacentHTML() {},
    matches() { return false; }, contains() { return false; },
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return true; },
    querySelector() { return null; }, querySelectorAll() { return []; },
    closest() { return null; }, focus() {}, blur() {}, click() {},
    setSelectionRange() {}, scrollIntoView() {}, showModal() {}, close() {},
    getBoundingClientRect() { return {top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0}; },
  };
}

const issued = [];
const pending = new Map();   // path -> [resolve, reject]
const deferred = new Set();  // paths that must never resolve on their own

function routeOf(url) {
  const text = String(url || "");
  if (text.indexOf("/api/account/model-selection") >= 0) return "model-selection";
  if (text.indexOf("/api/b66/admin/me") >= 0) return "admin";
  if (text.indexOf("/api/auth/status") >= 0) return "auth";
  return "other";
}

function jsonResponse(payload, ok) {
  return {
    ok: ok !== false,
    status: ok === false ? 403 : 200,
    json: async () => payload,
    text: async () => JSON.stringify(payload),
    headers: {get() { return null; }},
  };
}

const AUTH_OK = {
  ok: true, ready: true, authenticated: true, history_ready: true,
  user: {email: "harness@example.invalid", name: "Harness"},
  member_grade: "max", account_method: "google", session_state: "signed_in",
};

function makeFetch() {
  return function fakeFetch(url) {
    const route = routeOf(url);
    issued.push(route);
    if (route === "auth") {
      return Promise.resolve(jsonResponse(AUTH_OK));
    }
    if (route === "model-selection") {
      const payload = {ok: true, selection: "max"};
      if (deferred.has("model-selection")) {
        return new Promise((resolve) => { pending.set("model-selection", resolve); });
      }
      return Promise.resolve(jsonResponse(payload));
    }
    if (route === "admin") {
      const payload = {ok: true, admin: false, verified: false};
      if (deferred.has("admin")) {
        return new Promise((resolve) => { pending.set("admin", resolve); });
      }
      return Promise.resolve(jsonResponse(payload));
    }
    return Promise.resolve(jsonResponse({ok: true}));
  };
}

function buildSandbox() {
  const element = makeElement();
  const storage = new Map();
  const listeners = new Map();
  const sandbox = {
    console,
    setTimeout, clearTimeout, setInterval, clearInterval,
    Promise, JSON, Math, Date, Object, Array, String, Number, Boolean, Error,
    URL, URLSearchParams, Intl, Map, Set, WeakMap, WeakSet, Symbol, RegExp,
    fetch: makeFetch(),
    localStorage: {
      getItem: (k) => (storage.has(k) ? storage.get(k) : null),
      setItem: (k, v) => storage.set(k, String(v)),
      removeItem: (k) => storage.delete(k),
      clear: () => storage.clear(),
      key: () => null,
      length: 0,
    },
    navigator: {userAgent: "node-harness", onLine: true, sendBeacon: () => true, language: "ko-KR"},
    location: {href: "https://chat.padiem.net/", origin: "https://chat.padiem.net", pathname: "/", search: "", hash: ""},
    matchMedia: () => ({matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}}),
    requestAnimationFrame: (cb) => setTimeout(() => cb(Date.now()), 0),
    cancelAnimationFrame: (id) => clearTimeout(id),
    performance: {now: () => Date.now(), mark() {}, measure() {}, getEntriesByType: () => []},
    MutationObserver: class { observe() {} disconnect() {} takeRecords() { return []; } },
    ResizeObserver: class { observe() {} disconnect() {} unobserve() {} },
    IntersectionObserver: class { observe() {} disconnect() {} unobserve() {} },
    Event: class { constructor(type, init) { this.type = type; Object.assign(this, init || {}); } preventDefault() {} stopPropagation() {} },
    CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } },
  };
  sandbox.window = sandbox;
  sandbox.self = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.addEventListener = (name, fn) => {
    listeners.set(name, (listeners.get(name) || []).concat([fn]));
  };
  sandbox.removeEventListener = () => {};
  sandbox.dispatchEvent = () => true;
  sandbox.document = {
    documentElement: makeElement(),
    body: makeElement(),
    head: makeElement(),
    readyState: "complete",
    hidden: false,
    visibilityState: "visible",
    getElementById: () => element,
    querySelector: () => element,
    querySelectorAll: () => [],
    createElement: () => makeElement(),
    createTextNode: (t) => ({textContent: t}),
    addEventListener: (name, fn) => {
      listeners.set("document:" + name, (listeners.get("document:" + name) || []).concat([fn]));
    },
    removeEventListener: () => {},
  };
  vm.createContext(sandbox);
  sandbox.__listeners = listeners;
  return sandbox;
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function withTimeout(promise, ms) {
  return Promise.race([
    promise,
    delay(ms).then(() => undefined),
  ]);
}

async function main() {
  const out = {};

  // --- S1: the two independent reads overlap -------------------------------
  {
    issued.length = 0;
    const sandbox = buildSandbox();
    vm.runInContext(fs.readFileSync(SRC, "utf8"), sandbox, {filename: SRC});
    await delay(0);
    await delay(0);
    await delay(0);
    await delay(0);
    out.s1_issued = issued.slice();
    out.s1_selection_before_admin = issued.indexOf("model-selection") >= 0
      && issued.indexOf("model-selection") < issued.indexOf("admin");
  }

  // --- S3: the gate waits for the CURRENT generation's restore --------------
  {
    issued.length = 0;
    deferred.add("model-selection");
    deferred.add("admin");
    const sandbox = buildSandbox();
    vm.runInContext(fs.readFileSync(SRC, "utf8"), sandbox, {filename: SRC});
    await delay(20);
    let settled = false;
    const gate = sandbox.PadiemTierSelection.ready().then(() => { settled = true; });
    await delay(120);
    out.s3_resolved_before_restore = settled;
    // release the pending reads
    const release = pending.get("model-selection");
    if (release) release(jsonResponse({ok: true, selection: "max"}));
    const releaseAdmin = pending.get("admin");
    if (releaseAdmin) releaseAdmin(jsonResponse({ok: true, admin: false, verified: false}));
    await withTimeout(gate, 2000);
    out.s3_resolved_after_restore = true;
    deferred.clear();
    pending.clear();
  }

  // --- S2: a refresh queued AFTER the current generation must not block -----
  {
    issued.length = 0;
    const sandbox = buildSandbox();
    vm.runInContext(fs.readFileSync(SRC, "utf8"), sandbox, {filename: SRC});
    await delay(30);
    await delay(30);
    // Queue a LATER generation whose reads never settle, exactly as a window
    // focus does in the shipped page.
    deferred.add("model-selection");
    deferred.add("admin");
    for (const fn of sandbox.__listeners.get("focus") || []) fn({type: "focus"});
    await delay(30);
    let settled = false;
    const gate = sandbox.PadiemTierSelection.ready().then(() => { settled = true; });
    await delay(150);
    out.s2_resolved_while_later_generation_pending = settled;
    const release = pending.get("model-selection");
    if (release) release(jsonResponse({ok: true, selection: "max"}));
    const releaseAdmin = pending.get("admin");
    if (releaseAdmin) releaseAdmin(jsonResponse({ok: true, admin: false, verified: false}));
    await withTimeout(gate, 2000);
    deferred.clear();
    pending.clear();
  }

  process.stdout.write(JSON.stringify(out));
}

main().catch((err) => {
  process.stdout.write(JSON.stringify({error: String(err && err.stack ? err.stack : err)}));
  process.exitCode = 1;
});
