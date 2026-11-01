// Execute the production selector and projection with a minimal deterministic
// DOM, fetch and timer boundary. No browser installation or user PC is needed.
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const path = require("node:path");

class Events {
  constructor() { this.listeners = new Map(); }
  addEventListener(name, listener) {
    if (!this.listeners.has(name)) this.listeners.set(name, []);
    this.listeners.get(name).push(listener);
  }
  dispatchEvent(event) {
    for (const listener of this.listeners.get(event.type) || []) listener(event);
  }
}
class Element extends Events {
  constructor(tag) {
    super(); this.tagName = tag.toUpperCase(); this.children = []; this.attrs = {};
    this.dataset = {}; this.className = ""; this.hidden = false; this._text = "";
  }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(""); }
  set textContent(value) { this._text = value; this.children = []; }
  append(...nodes) { for (const node of nodes) { node.parentElement = this; this.children.push(node); } }
  appendChild(node) { this.append(node); return node; }
  replaceChildren(...nodes) { this._text = ""; this.children = []; this.append(...nodes); }
  insertBefore(node, before) {
    node.parentElement = this; this.children.splice(this.children.indexOf(before), 0, node);
  }
  setAttribute(key, value) { this.attrs[key] = value; }
  removeAttribute(key) { delete this.attrs[key]; }
  getAttribute(key) { return this.attrs[key] ?? null; }
  hasAttribute(key) { return key in this.attrs; }
  contains(node) { return this === node || this.children.some(child => child.contains(node)); }
  focus() { document.activeElement = this; }
  click() { this.dispatchEvent({ type: "click", target: this }); }
}
const walk = root => [root, ...root.children.flatMap(walk)];
const document = Object.assign(new Events(), {
  readyState: "complete", visibilityState: "visible",
  documentElement: Object.assign(new Element("html"), { lang: "ko" }),
  createElement: tag => new Element(tag),
  getElementById(id) { return walk(this.documentElement).find(node => node.id === id); },
  querySelector(selector) { return walk(this.documentElement).find(node => "." + node.className === selector); },
});
const shell = new Element("div"); shell.className = "app-shell";
const composer = new Element("form"); composer.id = "composerForm";
shell.append(composer); document.documentElement.append(shell);
const timers = new Map(); let nextTimer = 0;
let authenticated = true;
const window = Object.assign(new Events(), {
  setTimeout(callback, delay) { timers.set(++nextTimer, { callback, delay }); return nextTimer; },
  clearTimeout(id) { timers.delete(id); },
  PadiemAuthGate: { authenticated: () => authenticated },
});
const observers = [];
class MutationObserver {
  constructor(callback) { this.callback = callback; }
  observe(target) { observers.push({ target, callback: this.callback }); }
}
const input = JSON.parse(fs.readFileSync(0, "utf8"));
let envelope = input.responses[0];
let nextRead = null;
const calls = [];
const context = vm.createContext({
  document, window, MutationObserver, AbortController, Intl, Date,
  CustomEvent: class { constructor(type, options = {}) { this.type = type; this.detail = options.detail; } },
  fetch: async (url, options) => {
    calls.push({ url, method: options.method });
    if (options.method === "GET" && nextRead) {
      const read = nextRead; nextRead = null; return read();
    }
    const body = options.method === "POST"
      ? { ok: true, selectedDeviceId: JSON.parse(options.body).device_id } : envelope;
    return { ok: true, status: 200, text: async () => JSON.stringify(body), json: async () => body };
  },
});
const staticDir = path.resolve(__dirname, "../static");
for (const module of ["claw-local-handoff.js", "claw-device-manager.js"])
  vm.runInContext(fs.readFileSync(path.join(staticDir, module), "utf8"), context);
const flush = async () => { for (let i = 0; i < 8; i++) await new Promise(setImmediate); };
const nodes = name => walk(document.getElementById("clawDeviceManagerList"))
  .filter(node => node.className === name);
const refreshTimers = () => [...timers.values()].filter(timer => timer.delay === 30000);
async function tick() {
  const timer = [...timers].find(([, value]) => value.delay === 30000);
  assert.ok(timer, "the open selector schedules a 30-second read");
  timers.delete(timer[0]); timer[1].callback(); await flush();
}

(async () => {
  document.getElementById("clawDeviceManagerToggle").click(); await flush();
  assert.equal(nodes("claw-device-manager-drive").length, 1);
  assert.equal(nodes("claw-device-manager-drive-name")[0].textContent, "Windows (C:/)");
  assert.equal(nodes("claw-device-manager-drive-kind")[0].textContent, "내장 디스크");
  assert.equal(nodes("claw-device-manager-drive-free")[0].textContent, "여유 128 GiB");
  assert.ok(nodes("claw-device-manager-drive-updated")[0].textContent.startsWith("마지막 확인:"));

  // A selection reprojects the saved envelope; it must preserve inventory.
  nodes("claw-device-manager-select")[0].click(); await flush();
  assert.equal(nodes("claw-device-manager-drive").length, 1);
  assert.equal(calls.filter(call => call.method === "POST").length, 1);

  const target = input.responses[0].devices[0].deviceId;
  assert.equal(window.padiemSelectedDeviceId(), target);
  envelope = { ...input.responses[1], selectedDeviceId: target };
  let finishHeaders;
  let finishBody;
  nextRead = () => new Promise(resolve => { finishHeaders = resolve; });
  await tick();
  assert.equal(window.padiemSelectedDeviceId(), target, "pending refresh must not deselect Chat's target");
  assert.equal(window.padiemClawSelectedDeviceId(), target);
  assert.equal(nodes("claw-device-manager-drive").length, 1);
  finishHeaders({ ok: true, status: 200, text: () => new Promise(resolve => { finishBody = resolve; }) });
  await flush();
  assert.equal(window.padiemSelectedDeviceId(), target, "keep selection through response body reading");
  finishBody(JSON.stringify(envelope)); await flush();
  assert.equal(window.padiemSelectedDeviceId(), target);
  assert.equal(nodes("claw-device-manager-drive").length, 2);
  assert.equal(nodes("claw-device-manager-drive-kind")[1].textContent, "이동식 디스크");
  assert.equal(nodes("claw-device-manager-drive-free")[1].textContent, "여유 공간 확인 안 됨");
  assert.equal(window.PadiemClawDeviceDirectory.devices[0].drives.length, 2);

  envelope = input.responses[2]; await tick();
  assert.equal(nodes("claw-device-manager-drive").length, 1);
  assert.ok(!document.getElementById("clawDeviceManagerList").textContent.includes("USB"));
  envelope = input.responses[3]; await tick();
  assert.equal(nodes("claw-device-manager-drive").length, 0);
  assert.equal(nodes("claw-device-manager-drive-empty")[0].textContent, "현재 보고된 드라이브가 없습니다.");
  assert.equal(window.PadiemClawDeviceDirectory.devices[0].drives.length, 0);

  envelope = input.responses[4]; await tick();
  assert.equal(nodes("claw-device-manager-drive-status")[0].textContent, "드라이브 목록을 기다리고 있어요.");
  envelope = input.responses[5]; await tick();
  assert.equal(nodes("claw-device-manager-drive-status")[0].textContent, "드라이브 목록을 확인하지 못했습니다.");

  // Rendering never treats a drive label as markup or an instruction.
  envelope = JSON.parse(JSON.stringify(input.responses[0]));
  envelope.devices[0].drives[0].name = '<img src=x onerror="execute()">';
  await tick();
  assert.equal(nodes("claw-device-manager-drive-name")[0].textContent, '<img src=x onerror="execute()"> (C:/)');
  assert.equal(walk(document.documentElement).filter(node => node.tagName === "IMG").length, 0);

  document.documentElement.lang = "en";
  for (const observer of observers.filter(item => item.target === document.documentElement)) observer.callback();
  assert.equal(nodes("claw-device-manager-drive-kind")[0].textContent, "Fixed disk");
  assert.equal(nodes("claw-device-manager-drive-free")[0].textContent, "128 GiB free");
  assert.equal(calls.filter(call => call.method === "POST").length, 1, "all refreshes are read-only");

  document.visibilityState = "hidden";
  document.dispatchEvent({ type: "visibilitychange" });
  assert.equal(refreshTimers().length, 0);
  document.visibilityState = "visible";
  envelope = { ...input.responses[0], selectedDeviceId: target };
  document.dispatchEvent({ type: "visibilitychange" }); await flush();
  assert.equal(refreshTimers().length, 1);
  assert.equal(window.padiemSelectedDeviceId(), target);

  // Previous evidence lasts only until the scheduled response settles.
  // A denied read and a removed PC must both clear the target and inventory.
  let finishDenied;
  nextRead = () => new Promise(resolve => { finishDenied = resolve; });
  await tick();
  assert.equal(window.padiemSelectedDeviceId(), target);
  finishDenied({ ok: false, status: 403 }); await flush();
  assert.equal(window.padiemSelectedDeviceId(), null);
  assert.equal(nodes("claw-device-manager-drive").length, 0);
  assert.equal(window.PadiemClawDeviceDirectory.devices.length, 0);
  await tick();
  assert.equal(window.padiemSelectedDeviceId(), target);
  let finishRemoved;
  nextRead = () => new Promise(resolve => { finishRemoved = resolve; });
  await tick();
  assert.equal(window.padiemSelectedDeviceId(), target);
  finishRemoved({ ok: true, status: 200, text: async () => JSON.stringify({
    ok: true, available: true, ownerScoped: true, devices: [],
  }) }); await flush();
  assert.equal(window.padiemSelectedDeviceId(), null);
  assert.equal(window.PadiemClawDeviceDirectory.devices.length, 0);

  // Account changes erase the prior owner's DOM and shared snapshot before
  // the next authenticated read resolves; no inventory persists locally.
  await tick();
  assert.equal(nodes("claw-device-manager-drive").length, 1);
  assert.equal(window.padiemSelectedDeviceId(), target);
  envelope = { ok: true, available: true, ownerScoped: true, devices: [] };
  window.dispatchEvent({ type: "padiem:account-changed" });
  assert.equal(nodes("claw-device-manager-drive").length, 0);
  assert.equal(window.PadiemClawDeviceDirectory.devices.length, 0);
  await flush();
  assert.equal(window.PadiemClawDeviceDirectory.devices.length, 0);
  walk(document.documentElement).find(node => node.className === "claw-device-manager-close").click();
  assert.equal(refreshTimers().length, 0);
  authenticated = false;
  window.dispatchEvent({ type: "padiem:auth-changed" }); await flush();
  assert.equal(refreshTimers().length, 0);
  console.log(JSON.stringify({ ok: true, reads: calls.filter(call => call.method === "GET").length }));
})().catch(error => { console.error(error); process.exitCode = 1; });
