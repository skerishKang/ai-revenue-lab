const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const STATIC = process.argv[2];
const source = fs.readFileSync(path.join(STATIC, "chat-feedback-module.js"), "utf8");
const html = fs.readFileSync(path.join(STATIC, "index.html"), "utf8");
const ID = "fb_" + "a".repeat(32), NEXT = "fb_" + "b".repeat(32);
const record = (values = {}) => ({ id: ID, body: "fixture feedback", status: "new", created_at: "2026-11-14T01:00:00Z",
  updated_at: "2026-11-14T01:00:00Z", screen: null, fixed_version: 0, unread_fixed: false, ...values });
const response = (status, data) => ({ status, json: async () => data });
const settle = async () => { for (let i = 0; i < 8; i += 1) await new Promise(setImmediate); };
const deferred = () => { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; };

class Element {
  constructor(tag = "div") { this.tagName = tag.toUpperCase(); this.children = []; this.listeners = {}; this.attrs = {}; this.value = ""; this.text = ""; this.hidden = false; this.checked = false; this.disabled = false; this.open = false; this.isConnected = true; }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return this.text + this.children.map((child) => child.textContent).join(" "); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; this.text = ""; }
  setAttribute(key, value) { this.attrs[key] = String(value); if (key === "open") this.open = true; }
  removeAttribute(key) { delete this.attrs[key]; if (key === "open") this.open = false; }
  addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
  emit(name) { for (const callback of this.listeners[name] || []) callback({ target: this, preventDefault() {} }); }
  click() { if (!this.disabled) this.emit("click"); }
  focus() { this.focused = true; }
  showModal() { this.open = true; }
  close() { this.open = false; this.emit("close"); }
  all() { return [this, ...this.children.flatMap((child) => child.all())]; }
}

function setup(options = {}) {
  const ids = {};
  for (const match of html.matchAll(/<([a-z]+)\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
    const node = ids[match[3]] = new Element(match[1]);
    node.hidden = /\bhidden\b/.test(match[2]);
    node.id = match[3];
  }
  ids.feedbackFilter.value = "all";
  let auth = options.guest ? null : { authenticated: true, ownerKey: "fixture-owner" };
  let lang = "ko";
  const calls = [], events = {}, errors = [];
  const server = { own: options.own || [], inbox: options.inbox || [], admin: options.admin === true,
    next: null, unread: options.unread || 0, limits: options.limits || { body_chars: 4000, daily_submissions: 10 }, handler: null };
  const document = { readyState: "complete", documentElement: { lang }, currentScript: { src: "https://fixture.invalid/chat-feedback-module.js?v=1234abcd" },
    activeElement: ids.feedbackButton, getElementById: (id) => ids[id], createElement: (tag) => new Element(tag) };
  const window = { document, innerWidth: 390, innerHeight: 844,
    location: { href: options.href || "https://fixture.invalid/chat/private-conversation?secret=fixture#private" },
    PadiemAuthSession: { get: () => auth },
    __padiemLocale: { text: (key, values) => lang + ":" + key + (values ? JSON.stringify(values) : "") },
    addEventListener: (name, callback) => { (events[name] ||= []).push(callback); },
    fetch: (url, init) => {
      const call = { url, ...init, headers: { ...init.headers } };
      calls.push(call);
      if (server.handler) { const result = server.handler(call); if (result !== undefined) return Promise.resolve(result); }
      if (url === "/api/admin/session") return Promise.resolve(response(200, { authenticated: true, capabilities: { chat_admin: server.admin }, role: "admin" }));
      if (url.startsWith("/api/admin/feedback") && init.method === "GET") return Promise.resolve(response(200, { ok: true, feedback: server.inbox, next_cursor: server.next }));
      if (init.method === "GET") return Promise.resolve(response(200, { ok: true, feedback: server.own, next_cursor: server.next, unread_fixed_count: server.unread, limits: server.limits }));
      if (init.method === "POST" && url === "/api/chat/feedback") return Promise.resolve(response(201, { ok: true, feedback: record(JSON.parse(call.body)) }));
      if (init.method === "PATCH") return Promise.resolve(response(200, { ok: true, feedback: record({ ...server.inbox[0], ...JSON.parse(call.body) }) }));
      if (url.endsWith("/read")) return Promise.resolve(response(200, { ok: true, feedback: record({ status: "fixed", fixed_version: 1 }) }));
      throw new Error("unexpected fixture request");
    } };
  for (const name of ["localStorage", "sessionStorage"]) Object.defineProperty(window, name, { get() { throw new Error("browser storage is forbidden"); } });
  vm.runInNewContext(source, { window, document, URL, URLSearchParams, AbortController,
    console: { log: (...args) => errors.push(args), error: (...args) => errors.push(args) } });
  return { ids, calls, server, errors,
    event(name) { for (const callback of events[name] || []) callback(); },
    auth(value) { auth = value; this.event("padiem:auth-state"); },
    language(value) { lang = value; document.documentElement.lang = value; this.event("padiem:localechange"); },
    submit(text) { ids.feedbackBody.value = text; ids.feedbackForm.emit("submit"); },
    text() { return Object.values(ids).map((node) => node.textContent).join("\n"); },
    rowButton(list, suffix) { return ids[list].all().find((node) => node.tagName === "BUTTON" && node.textContent.endsWith(suffix)); },
  };
}

const scenarios = {
  async guest_and_default_consent() {
    const app = setup({ guest: true }); await settle();
    assert.equal(app.calls.length, 0);
    app.ids.feedbackButton.click();
    assert.equal(app.ids.feedbackDialog.open, true);
    assert.equal(app.ids.feedbackConsent.checked, false);
    assert.equal(app.ids.feedbackSubmit.disabled, true);
    app.submit("must not send"); assert.equal(app.calls.length, 0);
    assert.equal(app.ids.feedbackAdminTab.hidden, true);
    app.auth({ authenticated: true, ownerKey: "fixture-owner" }); await settle();
    assert.equal(app.ids.feedbackSubmit.disabled, false);
    assert.equal(app.ids.feedbackAdminTab.hidden, true); // A role name is not the capability.
  },
  async submit_receipt_and_bounds() {
    const app = setup({ limits: { body_chars: 4, daily_submissions: 3 } }); await settle();
    assert.match(app.ids.feedbackLimit.textContent, /"count":3/);
    app.submit("     "); assert.equal(app.calls.filter((row) => row.method === "POST").length, 0);
    app.submit("12345"); assert.match(app.ids.feedbackStatus.textContent, /too-long/);
    const waiting = deferred(); app.server.handler = (call) => call.method === "POST" ? waiting.promise : undefined;
    app.submit("😀😀😀😀"); app.submit("again");
    const writes = app.calls.filter((row) => row.method === "POST"); assert.equal(writes.length, 1);
    assert.deepEqual(JSON.parse(writes[0].body), { body: "😀😀😀😀" });
    waiting.resolve(response(201, { ok: true, feedback: record() })); await settle();
    assert.match(app.ids.feedbackStatus.textContent, new RegExp(ID));
    assert.equal(app.ids.feedbackBody.value, ""); assert.equal(app.ids.feedbackConsent.checked, false);
    assert.ok(app.calls.every((row) => row.credentials === "same-origin" && row.cache === "no-store"));
    assert.equal(app.errors.length, 0);
  },
  async consent_and_minimal_screen() {
    for (const [href, expected] of [["https://name:password@fixture.invalid/chat/private?key=fixture#private", "https://fixture.invalid/"], ["https://fixture.invalid/claw?key=fixture#private", "https://fixture.invalid/claw"]]) {
      const app = setup({ href }); await settle(); app.ids.feedbackConsent.checked = true; app.submit("fixture"); await settle();
      const body = JSON.parse(app.calls.find((row) => row.method === "POST").body);
      assert.deepEqual(body.screen, { url: expected, width: 390, height: 844, app_version: "1234abcd" });
      assert.deepEqual(Object.keys(body).sort(), ["body", "screen"]);
    }
  },
  async own_pagination_and_safe_text() {
    const app = setup({ own: [record({ body: '<img src=x onerror="fixture()">' })] }); await settle();
    app.server.next = ID; app.ids.feedbackOwnTab.click(); await settle();
    assert.equal(app.ids.feedbackOwnPanel.hidden, false); assert.equal(app.ids.feedbackOwnMore.hidden, false);
    app.server.own = [record({ id: NEXT, status: "reviewing" })]; app.server.next = null;
    app.ids.feedbackOwnMore.click(); await settle();
    assert.ok(app.calls.some((row) => row.url === "/api/chat/feedback?cursor=" + ID));
    assert.match(app.ids.feedbackOwnList.textContent, /<img src=x/);
    assert.match(app.ids.feedbackOwnList.textContent, /feedback-status-reviewing/);
    assert.ok(!app.ids.feedbackOwnList.all().some((row) => row.tagName === "IMG"));
    assert.equal(app.ids.feedbackOwnList.children.length, 2);
  },
  async admin_capability_and_status() {
    const app = setup({ admin: true, inbox: [record({ sender_label: "f***@e***", screen: { url: "https://fixture.invalid/", width: 390, height: 844, app_version: "1234abcd" } })] }); await settle();
    assert.equal(app.ids.feedbackAdminTab.hidden, false);
    assert.ok(!app.calls.some((row) => row.url.startsWith("/api/admin/feedback")));
    app.ids.feedbackAdminTab.click(); await settle();
    assert.match(app.ids.feedbackAdminList.textContent, /f\*\*\*@e\*\*\*/);
    const select = app.ids.feedbackAdminList.all().find((row) => row.tagName === "SELECT"); select.value = "fixed";
    app.rowButton("feedbackAdminList", "feedback-save").click(); await settle();
    const write = app.calls.find((row) => row.method === "PATCH");
    assert.equal(write.url, "/api/admin/feedback/" + ID); assert.deepEqual(JSON.parse(write.body), { status: "fixed" });
    assert.match(app.ids.feedbackAdminList.textContent, /feedback-status-fixed/);
    app.server.handler = (call) => call.url.startsWith("/api/admin/feedback") ? response(403, { error: { code: "global_model_admin_forbidden" } }) : undefined;
    app.ids.feedbackAdminRefresh.click(); await settle();
    assert.equal(app.ids.feedbackAdminTab.hidden, true); assert.ok(!app.ids.feedbackAdminList.textContent.includes("f***"));
  },
  async fixed_notification_and_version_race() {
    const item = record({ status: "fixed", fixed_version: 2, unread_fixed: true });
    const app = setup({ own: [item], unread: 1 }); await settle();
    assert.equal(app.ids.feedbackNotice.hidden, false);
    assert.ok(!app.ids.feedbackNoticeText.textContent.includes(item.body));
    assert.ok(!app.calls.some((row) => row.method === "POST"));
    app.ids.feedbackNoticeOpen.click(); await settle();
    app.server.handler = (call) => call.url.endsWith("/read") ? response(200, { ok: true, feedback: record({ ...item, fixed_version: 3 }) }) : undefined;
    app.rowButton("feedbackOwnList", "feedback-acknowledge").click(); await settle();
    assert.deepEqual(JSON.parse(app.calls.find((row) => row.url.endsWith("/read")).body), { fixed_version: 2 });
    assert.equal(app.ids.feedbackNotice.hidden, false);
    app.server.handler = (call) => call.url.endsWith("/read") ? response(200, { ok: true, feedback: record({ ...item, fixed_version: 3, unread_fixed: false }) }) : undefined;
    app.rowButton("feedbackOwnList", "feedback-acknowledge").click(); await settle();
    assert.equal(app.ids.feedbackNotice.hidden, true);
  },
  async account_switch_and_late_submit() {
    const app = setup({ admin: true, own: [record()], unread: 1 }); await settle();
    const waiting = deferred(); app.server.handler = (call) => call.method === "POST" ? waiting.promise : undefined;
    app.ids.feedbackButton.click(); app.ids.feedbackConsent.checked = true; app.submit("old draft");
    app.server.own = []; app.server.admin = false; app.server.unread = 0;
    app.auth({ authenticated: true, ownerKey: "other-fixture" }); await settle();
    assert.equal(app.ids.feedbackBody.value, ""); assert.equal(app.ids.feedbackConsent.checked, false);
    assert.equal(app.ids.feedbackDialog.open, false); assert.equal(app.ids.feedbackAdminTab.hidden, true);
    waiting.resolve(response(201, { ok: true, feedback: record({ body: "old private draft" }) })); await settle();
    assert.ok(!app.text().includes("old private draft")); assert.ok(!app.text().includes(ID));
    assert.ok(app.calls.find((row) => row.method === "POST").signal.aborted);
    app.auth(null); await settle(); assert.equal(app.ids.feedbackOwnList.textContent.includes("fixture feedback"), false);
  },
  async late_list_and_admin_role() {
    const app = setup(); await settle(); const waiting = deferred();
    app.server.handler = (call) => call.method === "GET" ? waiting.promise : undefined;
    app.ids.feedbackOwnRefresh.click(); app.auth({ authenticated: true, ownerKey: "next-fixture" });
    app.auth(null);
    waiting.resolve(response(200, { ok: true, feedback: [record()], authenticated: true, capabilities: { chat_admin: true }, unread_fixed_count: 1 })); await settle();
    assert.ok(!app.text().includes("fixture feedback")); assert.equal(app.ids.feedbackAdminTab.hidden, true); assert.equal(app.ids.feedbackNotice.hidden, true);
  },
  async sanitized_errors_and_no_retry() {
    for (const status of [400, 413, 429, 503]) {
      const app = setup(); await settle();
      app.server.handler = (call) => call.method === "POST" ? response(status, { error: { code: status === 429 ? "feedback_daily_limit" : status === 413 ? "feedback_too_large" : "fixture-private-message", message: "fixture-private-message" } }) : undefined;
      app.submit("fixture draft"); await settle();
      assert.equal(app.calls.filter((row) => row.method === "POST").length, 1);
      assert.ok(!app.text().includes("fixture-private-message")); assert.ok(!app.ids.feedbackStatus.textContent.includes("received"));
      assert.equal(app.errors.length, 0);
    }
    const app = setup(); await settle();
    app.server.handler = () => { throw new Error("fixture-private-message"); };
    app.ids.feedbackOwnRefresh.click(); await settle();
    assert.match(app.ids.feedbackStatus.textContent, /failed/); assert.ok(!app.text().includes("fixture-private-message"));
    app.server.handler = () => response(401, { error: { code: "authentication_required" } });
    app.submit("cleared on expiry"); await settle();
    assert.equal(app.ids.feedbackBody.value, ""); assert.equal(app.ids.feedbackSubmit.disabled, true);
  },
  async locale_focus_close_and_lifecycle() {
    const app = setup({ own: [record()] }); await settle();
    app.ids.feedbackButton.click(); assert.equal(app.ids.feedbackBody.focused, true);
    app.ids.feedbackBody.value = "transient draft"; app.ids.feedbackConsent.checked = true;
    app.language("en");
    assert.match(app.ids.feedbackOwnList.textContent, /en:feedback-status-new/);
    assert.equal(app.ids.feedbackBody.value, "transient draft");
    app.ids.feedbackClose.click();
    assert.equal(app.ids.feedbackBody.value, ""); assert.equal(app.ids.feedbackConsent.checked, false); assert.equal(app.ids.feedbackButton.focused, true);
    app.event("pagehide"); assert.ok(!app.text().includes("fixture feedback"));
    app.server.own = []; app.event("pageshow"); await settle();
    assert.equal(app.ids.feedbackSubmit.disabled, false);
    assert.ok(!/innerHTML|localStorage|sessionStorage|console\./.test(source));
  },
};

(async () => {
  const scenario = process.argv[3];
  if (!scenarios[scenario]) throw new Error("Unknown scenario");
  await scenarios[scenario]();
  process.stdout.write(JSON.stringify({ passed: scenario }));
})().catch((error) => { process.stderr.write(error.stack); process.exitCode = 1; });
