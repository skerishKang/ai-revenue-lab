// Executes the shipped presentation, conversation, auth and transport modules.
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const assert = require("node:assert/strict");
const STATIC = process.argv[2];
const job = "dsp_" + "a".repeat(32);
const cid = "chat_fixture";
const tick = () => new Promise((resolve) => setImmediate(resolve));

class Element {
  constructor(tag) {
    this.tagName = tag.toUpperCase(); this.children = []; this.attrs = {};
    this.dataset = {}; this.listeners = {}; this.value = ""; this.raw = "";
    this.hidden = false; this.disabled = false;
    this.style = { setProperty() {} };
  }
  appendChild(node) { node.parent = this; this.children.push(node); return node; }
  replaceChildren() { this.children = []; this.raw = ""; }
  remove() { this.parent.children = this.parent.children.filter((x) => x !== this); }
  set textContent(value) { this.raw = String(value); this.children = []; }
  get textContent() { return this.raw + this.children.map((x) => x.textContent).join(""); }
  get outerHTML() { return `<${this.tagName}>${JSON.stringify(this.attrs)}${JSON.stringify(this.dataset)}${this.raw}${this.children.map((x) => x.outerHTML).join("")}</${this.tagName}>`; }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
  dispatch(name, event = {}) { for (const fn of this.listeners[name] || []) fn(event); }
  click() { if (!this.disabled) this.dispatch("click"); }
  all() { return [this, ...this.children.flatMap((x) => x.all())]; }
  querySelectorAll() { return this.all().filter((x) => x.dataset.sessionLabel); }
}

function setup(mask = true) {
  const root = new Element("section"); root.hidden = true;
  const listeners = {}, calls = [], events = [], storage = [];
  let reply = async () => ({ status: 200, body: envelope({}) });
  let locale = "ko";
  const labelsSource = fs.readFileSync(path.join(STATIC, "locale.js"), "utf8");
  const labels = (key, vars = {}) => {
    const source = locale === "ko" ? labelsSource.split("    en: {")[0] : labelsSource.split("    en: {")[1];
    const value = new RegExp('"' + key + '": "([^"]*)"').exec(source)?.[1];
    assert.ok(value, "missing locale key: " + key);
    return value.replace(/\{(\w+)\}/g, (_, key) => String(vars[key]));
  };
  const ctx = { console, AbortController, Response, TextEncoder, TextDecoder, setTimeout, clearTimeout,
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options?.detail; } },
    document: { readyState: "complete", createElement: (tag) => new Element(tag),
      getElementById: (id) => id === "chatPcSessionPanel" ? root : null, querySelector: () => null },
    CSS: { supports: () => mask }, getComputedStyle: () => ({ getPropertyValue: () => mask ? "disc" : "none" }),
    navigator: { clipboard: { writeText: async (value) => { ctx.copied = value; } } },
    localStorage: { getItem: () => null, setItem: (...args) => storage.push(args), removeItem() {} },
    addEventListener: (name, fn) => (listeners[name] ||= []).push(fn),
    dispatchEvent: (event) => { events.push(event); for (const fn of listeners[event.type] || []) fn(event); },
    __padiemLocale: { text: labels },
    fetch: async (url, opts) => {
      calls.push({ url, ...opts });
      const value = await reply(url, opts);
      return { ok: value.status < 400, status: value.status, json: async () => value.body };
    },
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  for (const file of ["conversation-state.js", "auth-session.js", "chat-transport.js", "chat-pc-session-module.js"]) {
    vm.runInContext(fs.readFileSync(path.join(STATIC, file), "utf8"), ctx);
  }
  ctx.PadiemAuthSession.update({ ready: true, authenticated: true, user: { email: "fixture-owner" } }, 1);
  ctx.PadiemChatConversationState.setConversationId(cid);
  const api = ctx.PadiemChatPcSessionModule;
  const show = (value = {}) => api.render(envelope(value), api.captureScope());
  const find = (key) => root.all().find((node) => node.dataset.sessionLabel === key);
  const field = (secret) => root.all().find((node) => secret ? node.className === "pc-session-secret" : node.tagName === "TEXTAREA" && node.className !== "pc-session-secret");
  return { ctx, root, calls, events, storage, api, show, find, field,
    reply: (fn) => { reply = fn; }, locale: (value) => { locale = value; ctx.dispatchEvent({ type: "padiem:localechange" }); } };
}

function envelope(value, conversation = cid, decision = "pc_session") {
  return { decision_status: decision, conversation_id: conversation,
    pc_session: { job_id: job, session: job.slice(4), alive: true, status: "completed", ok: true,
      offset: 0, next_offset: 0, end_offset: 0, output: "", ...value } };
}

const tests = {
  async typed_only() {
    const s = setup();
    assert.equal(s.calls.length, 0); assert.equal(s.root.hidden, true);
    assert.equal(s.api.render({ answer: JSON.stringify(envelope({})) }, s.api.captureScope()), false);
    assert.equal(s.api.render(envelope({ session: "b".repeat(32) }), s.api.captureScope()), false);
    assert.equal(s.api.render(envelope({}, "other"), s.api.captureScope()), false);
    assert.equal(s.root.hidden, true);
    assert.equal(s.show({ output: "<script>fixture</script>", next_offset: 24 }), true);
    assert.equal(s.root.hidden, false); assert.equal(s.calls.length, 0);
    s.find("copy").click(); await tick(); assert.equal(s.ctx.copied, job);
  },
  async flow_and_offsets() {
    const s = setup(); s.show({ output: "한", next_offset: 3, end_offset: 3 });
    s.reply(async (_url, opts) => {
      const value = JSON.parse(opts.body);
      assert.equal(value.conversation_id, cid); assert.equal(value.job_id, job);
      if (value.op === "input") return { status: 200, body: envelope({ output: "글", offset: 3, next_offset: 6 }) };
      if (value.op === "stop") { assert.equal("wait_ms" in value, false); return { status: 200, body: envelope({ alive: false, ended: "stopped", offset: 6, next_offset: 6 }) }; }
      assert.equal(value.offset, 6); assert.equal(value.wait_ms, 1000);
      return { status: 200, body: envelope({ output: "", offset: 6, next_offset: 6 }) };
    });
    s.field(false).value = "hello"; s.find("send").click(); await tick();
    assert.equal(JSON.parse(s.calls[0].body).text, "hello");
    assert.equal(s.calls[0].credentials, "same-origin"); assert.equal(s.calls[0].cache, "no-store");
    assert.equal(s.calls[0].url, "/api/chat/pc/session"); assert.equal(s.calls[0].method, "POST");
    assert.equal(s.calls[0].headers["Content-Type"], "application/json");
    assert.match(s.root.textContent, /한글/);
    s.find("read").click(); await tick();
    s.show({ output: "한", offset: 0, next_offset: 3 });
    assert.equal(s.root.textContent.includes("한글한"), false);
    s.find("stop").click(); await tick();
    assert.equal(s.find("send").disabled, true); assert.ok(s.find("ended"));
  },
  async secret_confirmation() {
    const s = setup(); s.show(); let resolve;
    const secret = "fixture-secret\n" + "x".repeat(201);
    s.reply((_url, opts) => {
      assert.equal(s.field(true).value, "");
      assert.equal(JSON.parse(opts.body).text, secret);
      assert.equal(JSON.parse(opts.body).secret, true);
      return new Promise((r) => { resolve = r; });
    });
    s.field(true).value = secret; s.find("send-secret").click(); s.find("send-secret").click();
    assert.equal(s.calls.length, 1); assert.equal(s.field(true).value, "");
    assert.equal(s.root.outerHTML.includes(secret), false);
    assert.equal(JSON.stringify(s.events).includes(secret), false);
    assert.equal(JSON.stringify(s.storage).includes(secret), false);
    assert.equal(JSON.stringify(s.ctx.PadiemChatConversationState.outboundWithUser("probe")).includes(secret), false);
    resolve({ status: 200, body: { conversation_id: cid, decision_status: "pc_session_confirm",
      pc_session: { job_id: job, status: "waiting_approval", confirmation_required: true } } });
    await tick(); assert.equal(s.field(true).value, "");
    assert.match(s.root.textContent, /216자/); assert.match(s.root.textContent, /5분/);
    assert.equal(s.root.textContent.includes(secret), false);
    assert.equal(s.calls.length, 1);
  },
  async expired_no_restore() {
    const s = setup(); s.show();
    s.reply(async () => ({ status: 409, body: { error: { code: "pc_session_input_expired", message: "fixture-secret" } } }));
    s.field(true).value = "fixture-secret"; s.find("send-secret").click(); await tick();
    assert.equal(s.field(true).value, ""); assert.ok(s.find("expired"));
    assert.equal(s.root.textContent.includes("fixture-secret"), false); assert.equal(s.calls.length, 1);
  },
  async conversation_and_account() {
    for (const kind of ["conversation", "account", "reset", "logout"]) {
      const s = setup(); s.show(); let resolve;
      s.reply(() => new Promise((r) => { resolve = r; }));
      s.field(true).value = "transient"; s.find("read").click();
      if (kind === "conversation") s.ctx.PadiemChatConversationState.setConversationId("other");
      if (kind === "account") s.ctx.PadiemAuthSession.update({ ready: true, authenticated: true, user: { email: "other-fixture" } }, 2);
      if (kind === "reset") s.ctx.PadiemChatConversationState.reset();
      if (kind === "logout") s.ctx.PadiemAuthSession.update({ ready: true, authenticated: false }, 2);
      assert.equal(s.root.hidden, true); assert.equal(s.calls[0].signal.aborted, true);
      resolve({ status: 200, body: envelope({ output: "late", next_offset: 4 }) }); await tick();
      assert.equal(s.root.hidden, true); assert.equal(s.root.textContent, "");
    }
  },
  async scope_before_completion() {
    const s = setup(); s.ctx.PadiemChatConversationState.reset();
    const scope = s.api.captureScope();
    s.ctx.PadiemChatConversationState.setConversationId(cid);
    assert.equal(s.api.render(envelope({}), scope), true);
    const stale = s.api.captureScope();
    s.ctx.PadiemChatConversationState.reset(); s.ctx.PadiemChatConversationState.setConversationId(cid);
    assert.equal(s.api.render(envelope({}), stale), false);
  },
  async disabled_and_fallback() {
    const s = setup(false); s.show(); const field = s.field(true);
    assert.equal(field.tagName, "INPUT"); assert.equal(field.type, "password");
    let prevented = false; field.value = "old";
    field.dispatch("paste", { clipboardData: { getData: () => "first\nsecond" }, preventDefault: () => { prevented = true; } });
    assert.equal(prevented, true); assert.equal(field.value, ""); assert.equal(s.calls.length, 0);
    assert.ok(s.find("multiline-unavailable"));
    s.reply(async () => ({ status: 404, body: { error: { code: "pc_session_disabled" } } }));
    s.find("status").click(); await tick(); assert.equal(s.root.hidden, true); assert.equal(s.calls.length, 1);
  },
  async bounds_enter_locale() {
    const s = setup(); s.show();
    s.field(true).value = "x".repeat(4001); s.find("send-secret").click();
    assert.equal(s.calls.length, 0); assert.equal(s.field(true).value, ""); assert.ok(s.find("too-long"));
    s.find("send").click(); await tick(); assert.equal(JSON.parse(s.calls[0].body).key, "enter");
    s.field(false).value = "x".repeat(200); s.find("send").click(); await tick();
    assert.equal(JSON.parse(s.calls[1].body).text.length, 200);
    s.locale("en"); assert.equal(s.find("title").textContent, "PC session");
    assert.equal(s.field(true).attrs["aria-label"], "Masked secret input");
  },
  async ended_hint_auth_errors() {
    const s = setup(); s.show({ prompt_kind: "secret" });
    assert.ok(s.find("secret-hint")); assert.equal(s.calls.length, 0);
    const secret = s.field(true); secret.value = "not-sent";
    s.show({ alive: false, ended: "exited" });
    assert.equal(secret.value, ""); assert.equal(secret.disabled, true);
    for (const [status, code] of [[401, "canonical_session_required"], [403, "connector_enrollment_csrf_denied"], [403, "request_origin_rejected"]]) {
      const live = setup(); live.show(); live.field(true).value = "not-sent";
      live.reply(async () => ({ status, body: { error: { code } } }));
      live.find("status").click(); await tick();
      assert.equal(live.root.hidden, true); assert.equal(live.root.textContent, "");
    }
  },
};

module.exports = { setup, envelope };
if (require.main === module) (async () => {
  const names = process.argv[3] ? [process.argv[3]] : Object.keys(tests);
  for (const name of names) await tests[name]();
  process.stdout.write(JSON.stringify({ passed: names }));
})().catch((error) => { console.error(error.stack); process.exit(1); });
