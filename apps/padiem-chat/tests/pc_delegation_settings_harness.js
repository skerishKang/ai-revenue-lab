const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[2], "utf8");

class Element {
  constructor(tag = "div") { this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.listeners = {}; this.attrs = {}; this.text = ""; this.disabled = false; this.checked = false; }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return this.text + this.children.map((child) => child.textContent).join(" "); }
  set value(value) { this._value = String(value); }
  get value() { return this._value === undefined ? (this.tagName === "SELECT" ? this.children[0]?.value || "" : "") : this._value; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; this.text = ""; if (this.tagName === "SELECT") delete this._value; }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
  click() { if (!this.disabled) for (const callback of this.listeners.click || []) callback({ target: this }); }
  all() { return [this, ...this.children.flatMap((child) => child.all())]; }
}

const LINK = { mesh_node_id: "node/test/pc-one", label: "회사 PC", state: "active" };
const RULE = { id: "rule-one", device_id: LINK.mesh_node_id, folder: "C:/문서", actions: ["move"], mode: "allow", enabled: true };
const clone = (value) => JSON.parse(JSON.stringify(value));
const settle = async () => { for (let i = 0; i < 8; ++i) await new Promise((resolve) => setImmediate(resolve)); };

function setup({ rules = [], links = [LINK], status = 200 } = {}) {
  const ids = {};
  for (const name of ["Settings", "Status", "Folder", "Actions", "Add", "Refresh", "List", "Editor", "Write", "Move", "Delete"]) ids["pcDelegation" + name] = new Element(name === "Folder" ? "input" : "div");
  ids.pcDelegationDevice = new Element("select");
  ids.pcDelegationMode = new Element("select");
  ids.pcDelegationMode.value = "allow";
  ids.settingsDialog = new Element("dialog");
  ids.settingsDialog.open = false;
  const events = {}, observers = [], calls = [];
  const server = { rules: clone(rules), links, status, writeStatus: 200, pending: null };
  let locale = "ko", sequence = 0;
  const window = {
    document: { readyState: "complete", getElementById: (id) => ids[id], createElement: (tag) => new Element(tag) },
    crypto: { randomUUID: () => "new-rule-" + ++sequence },
    __padiemLocale: { text: (key) => locale + ":" + key },
    addEventListener: (name, callback) => { (events[name] ||= []).push(callback); },
    MutationObserver: class { constructor(callback) { observers.push(callback); } observe() {} },
    fetch: async (url, options) => {
      calls.push({ url, ...options });
      if (url === "/api/pc/pairings") return { status: 200, json: async () => ({ ok: true, links: server.links }) };
      if (options.method === "PUT") {
        const body = JSON.parse(options.body);
        if (server.writeStatus === 200) server.rules = clone(body.rules);
        return { status: server.writeStatus, json: async () => server.writeStatus === 200 ? { ok: true, version: 1, rules: clone(server.rules) } : { ok: false } };
      }
      if (server.pending) return server.pending;
      return { status: server.status, json: async () => ({ ok: server.status === 200, version: 1, rules: clone(server.rules) }) };
    },
  };
  vm.runInNewContext(source, { window, console });
  return {
    ids, calls, server,
    async open() { ids.settingsDialog.open = true; observers.forEach((callback) => callback()); await settle(); },
    async event(name) { for (const callback of events[name] || []) callback(); await settle(); },
    language(value) { locale = value; },
    listText() { return ids.pcDelegationList.textContent; },
    toggle() { return ids.pcDelegationList.all().find((node) => node.tagName === "BUTTON"); },
  };
}

async function main() {
  const checks = [];
  async function check(name, callback) { await callback(); checks.push(name); }
  await check("empty default has no browser authority or background write", async () => {
    const app = setup();
    assert.equal(app.calls.length, 0);
    await app.open();
    assert.equal(app.calls.length, 2);
    assert.match(app.listText(), /pc-delegation-empty/);
    assert.equal(app.ids.pcDelegationWrite.checked, false);
    assert.ok(app.calls.every((call) => call.credentials === "same-origin" && call.cache === "no-store"));
    assert.ok(!/localStorage|sessionStorage|innerHTML/.test(source));
  });
  await check("add saves exact folder/action/device scope without SEND", async () => {
    const app = setup(); await app.open();
    app.ids.pcDelegationFolder.value = "C:/업무";
    app.ids.pcDelegationMove.checked = true;
    app.ids.pcDelegationAdd.click(); await settle();
    const call = app.calls.find((row) => row.method === "PUT");
    assert.ok(call); const payload = JSON.parse(call.body);
    assert.equal(payload.version, 1);
    assert.deepEqual(payload.rules[0], { id: "new-rule-1", device_id: LINK.mesh_node_id, folder: "C:/업무", actions: ["move"], mode: "allow", enabled: true });
    assert.match(app.listText(), /C:\/업무/);
    assert.match(app.listText(), /pc-delegation-allow/);
    assert.equal(app.ids.pcDelegationFolder.value, "");
    assert.equal(app.ids.pcDelegationMove.checked, false);
  });
  await check("always ask and disabling retain other rules", async () => {
    const app = setup({ rules: [RULE] }); await app.open();
    app.ids.pcDelegationFolder.value = "C:/업무";
    app.ids.pcDelegationDelete.checked = true;
    app.ids.pcDelegationMode.value = "ask";
    app.ids.pcDelegationAdd.click(); await settle();
    assert.equal(app.server.rules[1].mode, "ask");
    assert.deepEqual(app.server.rules[1].actions, ["delete"]);
    app.toggle().click(); await settle();
    assert.equal(app.server.rules[0].enabled, false);
    assert.equal(app.server.rules[1].enabled, true);
    assert.match(app.listText(), /pc-delegation-off/);
  });
  await check("failed save is never shown as disabled or saved", async () => {
    const app = setup({ rules: [RULE] }); await app.open();
    app.server.writeStatus = 503;
    app.toggle().click(); await settle();
    assert.equal(app.server.rules[0].enabled, true);
    assert.equal(app.toggle().textContent, "ko:pc-delegation-disable");
    assert.equal(app.toggle().disabled, true);
    assert.equal(app.ids.pcDelegationRefresh.disabled, false);
    assert.match(app.ids.pcDelegationStatus.textContent, /pc-delegation-save-error/);
  });
  await check("offline PC still permits revoking existing rules", async () => {
    const app = setup({ rules: [RULE], links: [] }); await app.open();
    assert.equal(app.ids.pcDelegationAdd.disabled, true);
    assert.equal(app.toggle().disabled, false);
    app.toggle().click(); await settle();
    assert.equal(app.server.rules[0].enabled, false);
  });
  await check("login failure clears prior owner rules and disables edits", async () => {
    const app = setup({ rules: [RULE] }); await app.open();
    app.server.status = 401;
    await app.event("padiem:auth-state");
    assert.ok(!app.listText().includes(RULE.folder));
    assert.equal(app.ids.pcDelegationAdd.disabled, true);
    assert.match(app.ids.pcDelegationStatus.textContent, /pc-delegation-login/);
  });
  await check("late response from a previous account is never rendered", async () => {
    const app = setup({ rules: [RULE] });
    let resolveOld;
    app.server.pending = new Promise((resolve) => { resolveOld = resolve; });
    await app.open();
    app.server.pending = null;
    app.server.status = 401;
    await app.event("padiem:auth-state");
    resolveOld({ status: 200, json: async () => ({ ok: true, version: 1, rules: [RULE] }) });
    await settle();
    assert.ok(!app.listText().includes(RULE.folder));
    assert.equal(app.ids.pcDelegationAdd.disabled, true);
    assert.match(app.ids.pcDelegationStatus.textContent, /pc-delegation-login/);
  });
  await check("paused PC labels stay visible but cannot create new grants", async () => {
    const app = setup({ rules: [RULE], links: [{ ...LINK, state: "paused" }] }); await app.open();
    assert.ok(app.listText().includes(LINK.label));
    assert.equal(app.ids.pcDelegationAdd.disabled, true);
    assert.ok(!app.ids.pcDelegationDevice.children.some((option) => option.value === LINK.mesh_node_id));
    assert.equal(app.toggle().disabled, false);
  });
  await check("untrusted names are text and runtime locale follows settings", async () => {
    const app = setup({ rules: [{ ...RULE, folder: 'C:/<img src=x onerror=alert(1)>' }] }); await app.open();
    assert.ok(app.listText().includes("<img src=x"));
    assert.ok(!app.ids.pcDelegationList.all().some((node) => node.tagName === "IMG"));
    app.language("en"); await app.event("padiem:localechange");
    assert.equal(app.toggle().textContent, "en:pc-delegation-disable");
  });
  await check("missing folder or action never writes a rule", async () => {
    const app = setup(); await app.open();
    app.ids.pcDelegationAdd.click(); await settle();
    assert.ok(!app.calls.some((call) => call.method === "PUT"));
    assert.match(app.ids.pcDelegationStatus.textContent, /pc-delegation-required/);
  });
  for (const name of checks) console.log("PC_DELEGATION_CHECK " + name + " PASS");
  console.log("PC_DELEGATION_SETTINGS=PASS");
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
