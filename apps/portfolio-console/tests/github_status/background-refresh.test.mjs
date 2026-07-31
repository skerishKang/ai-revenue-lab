import { test } from "node:test";
import {
  assert, NOW, delay, aggregatePayload, MemorySnapshotCache,
} from "./fixtures.mjs";
import { createGitHubStatusService } from "../../functions/_lib/github-status-service.js";
import { OUTBOUND_DEADLINES } from "../../functions/_lib/outbound-deadline.js";
import { buildIdentitySource } from "../../business-identity-data.js";

// Background-task registrar tests (Issue #345, Blocking Defect B).
//
// A timed-out stale refresh must not be dropped: it is handed to an injected
// registrar (context.waitUntil on Cloudflare Pages) so it can finish and update
// the cache after the response is sent. These tests inject a counting registrar
// and assert exactly when registration happens, that the guarded promise always
// settles safely, and that the last-good cache is never corrupted.

const STALE_SNAPSHOT = { ok: true, schemaVersion: 2, syncedAt: "old", stale: false, businesses: [{ number: 15 }] };

// A snapshot stored 181s ago: past the 180s fresh TTL (so it is stale) but well
// inside the 86400s stale TTL (so it is still servable).
function staleCache() {
  const cache = new MemorySnapshotCache({ now: () => NOW - 181_000 });
  return cache.set(STALE_SNAPSHOT).then(() => { cache.now = () => NOW; return cache; });
}
// A fresh snapshot stored now: inside the fresh TTL (immediate fresh hit).
function freshCache() {
  const cache = new MemorySnapshotCache({ now: () => NOW });
  return cache.set(STALE_SNAPSHOT).then(() => cache);
}
const fastBudget = () => ({ ...OUTBOUND_DEADLINES, staleRefreshBudgetMs: 20 });
const slowClient = (ms = 80, payload = aggregatePayload()) => ({
  async getStatusAggregation() { await delay(ms); return payload; },
});
function makeRegistrar() {
  const reg = { count: 0, promises: [] };
  reg.fn = (promise) => { reg.count += 1; reg.promises.push(promise); };
  reg.settled = () => Promise.all(reg.promises);
  return reg;
}
const service = (client, cache, reg, key) =>
  createGitHubStatusService({ client, cache, now: () => NOW, singleFlightKey: key, identitySource: buildIdentitySource(), timeouts: fastBudget(), registerBackgroundTask: reg.fn });

test("1. a stale refresh that exceeds the budget registers exactly one background task", async () => {
  const cache = await staleCache();
  const reg = makeRegistrar();
  const result = await service(slowClient(), cache, reg, "bg-1").getStatus();
  assert.equal(result.cacheState, "stale", "stale snapshot served immediately");
  assert.equal(result.payload.stale, true);
  assert.equal(reg.count, 1, "registrar called exactly once on the timeout path");
  await reg.settled();
});

test("2. the registered promise settles only after the background refresh succeeds", async () => {
  const cache = await staleCache();
  const reg = makeRegistrar();
  let done = false;
  const client = { async getStatusAggregation() { await delay(50); done = true; return aggregatePayload(); } };
  await service(client, cache, reg, "bg-2").getStatus();
  assert.equal(reg.count, 1);
  assert.equal(done, false, "refresh still running when the stale response is sent");
  await reg.promises[0];
  assert.equal(done, true, "guarded promise settles after the refresh completes");
});

test("3. a successful background refresh updates the cache via the existing write path", async () => {
  const cache = await staleCache();
  const reg = makeRegistrar();
  await service(slowClient(50), cache, reg, "bg-3").getStatus();
  assert.equal((await cache.get()).snapshot.businesses.length, 1, "still the stale seed before the refresh lands");
  await reg.promises[0];
  const after = await cache.get();
  assert.equal(after.snapshot.businesses.length, 55, "cache now holds the full refreshed payload");
  assert.equal(after.snapshot.stale, false);
});

test("4. a failed background refresh settles safely and preserves the last-good cache", async () => {
  const cache = await staleCache();
  const reg = makeRegistrar();
  const client = { async getStatusAggregation() { await delay(50); throw new Error("upstream-secret-detail"); } };
  const result = await service(client, cache, reg, "bg-4").getStatus();
  assert.equal(result.cacheState, "stale");
  assert.equal(reg.count, 1);
  await reg.promises[0]; // guarded promise must resolve, never reject outward
  const after = await cache.get();
  assert.equal(after.snapshot.businesses.length, 1, "last-good snapshot untouched by the failed refresh");
  assert.equal(after.snapshot.syncedAt, "old");
});

test("5. concurrent stale requests share one single-flight refresh", async () => {
  const cache = await staleCache();
  const reg = makeRegistrar();
  let calls = 0;
  const client = { async getStatusAggregation() { calls += 1; await delay(80); return aggregatePayload(); } };
  const results = await Promise.all(Array.from({ length: 5 }, () => service(client, cache, reg, "bg-5").getStatus()));
  for (const r of results) assert.equal(r.cacheState, "stale");
  assert.equal(calls, 1, "only one upstream refresh for all concurrent stale callers");
  await reg.settled();
});

test("6. background registration is not duplicated by the number of concurrent requests", async () => {
  const cache = await staleCache();
  const reg = makeRegistrar();
  const client = slowClient(80);
  await Promise.all(Array.from({ length: 5 }, () => service(client, cache, reg, "bg-6").getStatus()));
  assert.equal(reg.count, 1, "one registration for the shared flight, not one per request");
  await reg.settled();
});

test("7. a fresh cache hit performs no background registration", async () => {
  const cache = await freshCache();
  const reg = makeRegistrar();
  const result = await service(slowClient(), cache, reg, "bg-7").getStatus();
  assert.equal(result.cacheState, "fresh");
  assert.equal(reg.count, 0, "no registration on a fresh hit");
});

test("8. a refresh that succeeds within the budget performs no background registration", async () => {
  const cache = await staleCache();
  const reg = makeRegistrar();
  const result = await service(slowClient(1), cache, reg, "bg-8").getStatus(); // 1ms << 20ms budget
  assert.equal(result.cacheState, "miss", "refresh completed in the foreground");
  assert.equal(result.payload.businesses.length, 55);
  assert.equal(reg.count, 0, "no registration when the refresh finishes inside the budget");
});

test("9. a cold start (no usable snapshot) performs no background registration", async () => {
  const cache = new MemorySnapshotCache({ now: () => NOW }); // empty
  const reg = makeRegistrar();
  const result = await service(slowClient(1), cache, reg, "bg-9").getStatus();
  assert.equal(result.cacheState, "miss");
  assert.equal(result.payload.businesses.length, 55);
  assert.equal(reg.count, 0, "no registration on the cold-start path");
});

test("10. a registrar failure never breaks the response or secret safety", async () => {
  const cache = await staleCache();
  const reg = { count: 0, fn() { reg.count += 1; throw new Error("registrar-secret-boom"); } };
  const result = await service(slowClient(80), cache, reg, "bg-10").getStatus();
  assert.equal(result.cacheState, "stale", "user still gets the stale snapshot");
  assert.equal(result.payload.stale, true);
  assert.equal(reg.count, 1, "registrar was invoked");
  assert.equal(result.payload.businesses.length, 1, "response is the safe stale payload");
  assert.ok(!JSON.stringify(result.payload).includes("registrar-secret-boom"), "registrar error not reflected to the client");
});
