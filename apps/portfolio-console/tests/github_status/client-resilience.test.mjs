import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const mod = require(path.resolve(HERE, "../../github-live-status.js"));

function makeClock() {
  let now = 0; let seq = 0; const pending = [];
  const flush = async () => { for (let i = 0; i < 25; i++) await Promise.resolve(); };
  return {
    now: () => now,
    setTimeout(fn, ms) { const id = ++seq; pending.push({ id, fn, at: now + Math.max(0, ms) }); return id; },
    clearTimeout(id) { const i = pending.findIndex((t) => t.id === id); if (i >= 0) pending.splice(i, 1); },
    activeTimers: () => pending.length,
    async tick(ms) {
      const target = now + ms;
      for (;;) {
        await flush();
        pending.sort((a, b) => a.at - b.at);
        const idx = pending.findIndex((t) => t.at <= target);
        if (idx < 0) break;
        const [t] = pending.splice(idx, 1);
        now = t.at;
        t.fn();
      }
      now = target;
      await flush();
    },
  };
}

class FakeEl {
  constructor(tag) {
    this.tagName = tag; this.id = ""; this.className = ""; this.type = "";
    this.children = []; this.dataset = {}; this.attrs = {}; this._listeners = {}; this._text = "";
  }
  set textContent(v) { this._text = v; this.children = []; }
  get textContent() { return this._text; }
  setAttribute(k, v) { this.attrs[k] = v; }
  getAttribute(k) { return this.attrs[k]; }
  appendChild(c) { this.children.push(c); return c; }
  insertBefore(c, ref) { const i = ref ? this.children.indexOf(ref) : -1; if (i < 0) this.children.push(c); else this.children.splice(i, 0, c); return c; }
  addEventListener(t, fn) { (this._listeners[t] = this._listeners[t] || []).push(fn); }
  get firstChild() { return this.children[0] || null; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
}

function stubDoc(extra = {}) {
  return {
    documentElement: { lang: "ko" }, visibilityState: "visible", readyState: "complete", body: {},
    querySelector: () => null, querySelectorAll: () => [], createElement: (tag) => new FakeEl(tag),
    addEventListener: () => {}, removeEventListener: () => {}, ...extra,
  };
}

function makeGlobal({ fetchImpl, clock, doc = stubDoc() }) {
  return {
    fetch: fetchImpl, AbortController,
    setTimeout: (fn, ms) => clock.setTimeout(fn, ms),
    clearTimeout: (id) => clock.clearTimeout(id),
    queueMicrotask: (fn) => queueMicrotask(fn),
    Math: { random: () => 0 }, Date: { now: () => clock.now() },
    MutationObserver: class { observe() {} disconnect() {} },
    document: doc, window: null,
  };
}

function mockFetch(sequence) {
  const calls = { count: 0 };
  const impl = async (url, init) => {
    const i = calls.count++;
    const entry = typeof sequence === "function" ? sequence(i, init) : sequence[Math.min(i, sequence.length - 1)];
    if (entry.throw) throw new Error(entry.throw);
    return { status: entry.status ?? 200, json: async () => { if (entry.jsonThrow) throw new Error("bad json"); return entry.body ?? null; } };
  };
  impl.calls = calls;
  return impl;
}

function resetState() {
  const s = mod._state;
  s.payload = null; s.loading = false; s.started = false; s.observer = null; s.scheduled = false;
  s.status = "idle"; s.controller = null; s.inFlight = null; s.lastSuccessAt = null; s.lastRecoveryAt = null; s.listeners = null;
}

const OK = (n, extra = {}) => ({ ok: true, schemaVersion: 2, syncedAt: "2026-07-27T00:00:00Z", stale: false, businesses: [{ number: n }], ...extra });

test("1. initial success reaches the fresh state and stores the payload", async () => {
  resetState();
  const clock = makeClock();
  const fetchImpl = mockFetch([{ status: 200, body: OK(1) }]);
  const g = makeGlobal({ fetchImpl, clock });
  await mod.load(g, { reason: "startup" });
  assert.equal(mod._state.status, "fresh");
  assert.equal(mod._state.payload.businesses[0].number, 1);
  assert.equal(fetchImpl.calls.count, 1);
});

test("2. a transient timeout then retry success recovers the live layer", async () => {
  resetState();
  const clock = makeClock();
  const fetchImpl = mockFetch([{ throw: "network" }, { status: 200, body: OK(7) }]);
  const g = makeGlobal({ fetchImpl, clock });
  const p = mod.load(g, { reason: "startup" });
  await clock.tick(800);
  await p;
  assert.equal(mod._state.status, "fresh");
  assert.equal(mod._state.payload.businesses[0].number, 7);
  assert.equal(fetchImpl.calls.count, 2);
});

test("3. exhausting all bounded retries reaches unavailable", async () => {
  resetState();
  const clock = makeClock();
  const fetchImpl = mockFetch([{ throw: "network" }]);
  const g = makeGlobal({ fetchImpl, clock });
  const p = mod.load(g, { reason: "startup" });
  await clock.tick(800);
  await clock.tick(2400);
  await p;
  assert.equal(mod._state.status, "unavailable");
  assert.equal(mod._state.payload, null);
  assert.equal(fetchImpl.calls.count, mod.MAX_ATTEMPTS);
  assert.equal(clock.activeTimers(), 0, "no timer leak after retries");
});

test("4. a stale payload is shown with the stale state and keeps its data", async () => {
  resetState();
  const clock = makeClock();
  const fetchImpl = mockFetch([{ status: 200, body: OK(3, { stale: true }) }]);
  const g = makeGlobal({ fetchImpl, clock });
  await mod.load(g, { reason: "startup" });
  assert.equal(mod._state.status, "stale");
  assert.equal(mod._state.payload.stale, true);
  assert.equal(mod._state.payload.businesses[0].number, 3);
});

test("5. focus recovery reloads after a startup failure", async () => {
  resetState();
  const clock = makeClock();
  let fail = true;
  const fetchImpl = mockFetch(() => (fail ? { throw: "network" } : { status: 200, body: OK(9) }));
  const g = makeGlobal({ fetchImpl, clock });
  const p = mod.load(g, { reason: "startup" });
  await clock.tick(800); await clock.tick(2400); await p;
  assert.equal(mod._state.status, "unavailable");
  fail = false;
  await clock.tick(mod.RECOVERY_DEDUP_MS + 1);
  mod.recover(g);
  await clock.tick(0);
  assert.equal(mod._state.status, "fresh");
  assert.equal(mod._state.payload.businesses[0].number, 9);
});

test("6. simultaneous visibility and focus trigger a single recovery fetch", async () => {
  resetState();
  const clock = makeClock();
  const fetchImpl = mockFetch([{ status: 200, body: OK(1) }]);
  const g = makeGlobal({ fetchImpl, clock });
  mod._state.status = "unavailable";
  mod.recover(g);
  mod.recover(g);
  await clock.tick(0);
  assert.equal(fetchImpl.calls.count, 1);
});

test("7. repeated focus within the cooldown window adds no fetch", async () => {
  resetState();
  const clock = makeClock();
  const fetchImpl = mockFetch([{ status: 200, body: OK(1) }]);
  const g = makeGlobal({ fetchImpl, clock });
  await mod.load(g, { reason: "startup" });
  assert.equal(fetchImpl.calls.count, 1);
  await clock.tick(1000);
  mod._state.lastRecoveryAt = null;
  mod.recover(g);
  await clock.tick(0);
  assert.equal(fetchImpl.calls.count, 1, "cooldown suppressed the extra fetch");
});

test("8. an in-flight load is joined rather than duplicated", async () => {
  resetState();
  const clock = makeClock();
  const body = OK(1);
  let fetchCount = 0; let resolveFetch;
  const fetchImpl = () => { fetchCount += 1; return new Promise((res) => { resolveFetch = () => res({ status: 200, json: async () => body }); }); };
  const g = makeGlobal({ fetchImpl, clock });
  const p1 = mod.load(g, { reason: "startup" });
  const p2 = mod.load(g, { reason: "startup" });
  assert.equal(p1, p2, "second call returns the same in-flight promise");
  resolveFetch();
  await clock.tick(0);
  await p1;
  assert.equal(fetchCount, 1);
  assert.equal(mod._state.status, "fresh");
});

test("9. no timers leak after retries and teardown removes listeners", async () => {
  resetState();
  const clock = makeClock();
  const fetchImpl = mockFetch([{ throw: "network" }]);
  const removed = { vis: 0, focus: 0 };
  const doc = stubDoc({ removeEventListener: (type) => { if (type === "visibilitychange") removed.vis += 1; } });
  const g = makeGlobal({ fetchImpl, clock, doc });
  g.window = { addEventListener: () => {}, removeEventListener: (type) => { if (type === "focus") removed.focus += 1; } };
  mod.autoStart(g);
  await clock.tick(800); await clock.tick(2400); await clock.tick(0);
  assert.equal(mod._state.status, "unavailable");
  assert.equal(clock.activeTimers(), 0, "all retry timers cleared");
  mod.teardown(g);
  assert.equal(removed.vis, 1);
  assert.equal(removed.focus, 1);
  assert.equal(mod._state.observer, null);
  assert.equal(mod._state.started, false);
});

test("10. status text localizes for stale, retrying and unavailable states", () => {
  assert.equal(mod.statusText("stale", "ko"), "최신 정보가 아닐 수 있음");
  assert.equal(mod.statusText("stale", "en"), "May be out of date");
  assert.equal(mod.statusText("unavailable", "ko"), "GitHub live 정보를 잠시 불러올 수 없음");
  assert.equal(mod.statusText("unavailable", "en"), "GitHub live data temporarily unavailable");
  assert.equal(mod.statusText("retrying", "en"), "Retrying GitHub…");
  assert.equal(mod.statusText("loading", "ko"), "GitHub 동기화 중…");
});

test("11. a prior good payload is retained as stale when a later sync fails", async () => {
  resetState();
  const clock = makeClock();
  const fetchImpl = mockFetch([{ status: 200, body: OK(1) }, { throw: "network" }]);
  const g = makeGlobal({ fetchImpl, clock });
  await mod.load(g, { reason: "startup" });
  assert.equal(mod._state.status, "fresh");
  const p = mod.load(g, { reason: "manual" });
  await clock.tick(800); await clock.tick(2400); await p;
  assert.equal(mod._state.status, "stale", "keeps showing the last-good data as stale");
  assert.equal(mod._state.payload.businesses[0].number, 1);
});

test("13a. 400 INVALID_QUERY is fatal and never auto-retried", async () => {
  resetState();
  const clock = makeClock();
  const fetchImpl = mockFetch([{ status: 400, body: { ok: false, error: { code: "INVALID_QUERY" }, businesses: [] } }]);
  const g = makeGlobal({ fetchImpl, clock });
  await mod.load(g, { reason: "startup" });
  assert.equal(mod._state.status, "unavailable");
  assert.equal(fetchImpl.calls.count, 1, "no retry for a contract violation");
});

test("13b. 405 METHOD_NOT_ALLOWED is fatal and never auto-retried", async () => {
  resetState();
  const clock = makeClock();
  const fetchImpl = mockFetch([{ status: 405, body: { ok: false, error: { code: "METHOD_NOT_ALLOWED" }, businesses: [] } }]);
  const g = makeGlobal({ fetchImpl, clock });
  await mod.load(g, { reason: "startup" });
  assert.equal(mod._state.status, "unavailable");
  assert.equal(fetchImpl.calls.count, 1);
});

test("14a. a malformed ok payload fails closed and is never rendered", async () => {
  resetState();
  const clock = makeClock();
  const fetchImpl = mockFetch([{ status: 200, body: { ok: true, schemaVersion: 2 } }]);
  const g = makeGlobal({ fetchImpl, clock });
  await mod.load(g, { reason: "startup" });
  assert.equal(mod._state.status, "unavailable");
  assert.equal(mod._state.payload, null, "malformed payload not accepted");
  assert.equal(fetchImpl.calls.count, 1, "schema violation is fatal, not retried");
});

test("14b. an unparseable body is fail-closed, retried, then unavailable", async () => {
  resetState();
  const clock = makeClock();
  const fetchImpl = mockFetch([{ status: 200, jsonThrow: true }]);
  const g = makeGlobal({ fetchImpl, clock });
  const p = mod.load(g, { reason: "startup" });
  await clock.tick(800); await clock.tick(2400); await p;
  assert.equal(mod._state.status, "unavailable");
  assert.equal(mod._state.payload, null);
});

test("DOM: renders a localized unavailable state with an accessible retry button", async () => {
  resetState();
  const clock = makeClock();
  const statusEl = new FakeEl("div");
  const doc = stubDoc({ documentElement: { lang: "en" }, querySelector: (sel) => (sel === "#github-live-status" ? statusEl : null) });
  const fetchImpl = mockFetch([{ status: 502, body: { ok: false, error: { code: "UPSTREAM_UNAVAILABLE" }, businesses: [] } }]);
  const g = makeGlobal({ fetchImpl, clock, doc });
  const p = mod.load(g, { reason: "startup" });
  await clock.tick(800); await clock.tick(2400); await p;
  assert.equal(mod._state.status, "unavailable");
  assert.equal(statusEl.dataset.status, "unavailable");
  const btn = statusEl.children.find((c) => c.className === "github-live-status-retry");
  assert.ok(btn, "retry button rendered");
  assert.equal(btn.attrs["aria-label"], "Retry");
  assert.equal(btn.textContent, "Retry");
});

test("DOM: renders a Korean stale banner that flags possibly-outdated data", async () => {
  resetState();
  const clock = makeClock();
  const statusEl = new FakeEl("div");
  const doc = stubDoc({ documentElement: { lang: "ko" }, querySelector: (sel) => (sel === "#github-live-status" ? statusEl : null) });
  const fetchImpl = mockFetch([{ status: 200, body: OK(5, { stale: true }) }]);
  const g = makeGlobal({ fetchImpl, clock, doc });
  await mod.load(g, { reason: "startup" });
  assert.equal(statusEl.dataset.status, "stale");
  const span = statusEl.children.find((c) => c.className === "github-live-status-text");
  assert.ok(span.textContent.includes("최신 정보가 아닐 수 있음"));
});
