import test from "node:test";
import assert from "node:assert/strict";
import { GitHubApiError } from "../../functions/_lib/github-client.js";
import { MemorySnapshotCache } from "../../functions/_lib/cache.js";
import { createGitHubStatusService } from "../../functions/_lib/github-status-service.js";
import { handleGitHubStatusRequest } from "../../functions/api/github-status.js";
import { OUTBOUND_DEADLINES, TIMEOUT_CONTRACT, OutboundTimeoutError } from "../../functions/_lib/outbound-deadline.js";
import {
  NOW, aggregatePayload, delay, envWithCredentials, mockAggregateClient, serviceResult,
} from "./fixtures.mjs";

const STALE_SNAPSHOT = () => ({ ok: true, schemaVersion: 2, syncedAt: "old", stale: false, businesses: [{ number: 15 }] });

function staleCache() {
  const cache = new MemorySnapshotCache({ now: () => NOW - 181_000 });
  return cache.set(STALE_SNAPSHOT()).then(() => { cache.now = () => NOW; return cache; });
}

function fastBudget(extra = {}) {
  return { ...OUTBOUND_DEADLINES, staleRefreshBudgetMs: 20, ...extra };
}

test("timeout contract keeps the client deadline above the server foreground budget", () => {
  assert.ok(
    TIMEOUT_CONTRACT.serverStaleRefreshBudgetMs + TIMEOUT_CONTRACT.networkMarginMs <= TIMEOUT_CONTRACT.clientRequestDeadlineMs,
    "stale snapshot must be served before the client aborts",
  );
  assert.ok(TIMEOUT_CONTRACT.handlerBackstopMs >= TIMEOUT_CONTRACT.serverTotalSyncMs, "handler backstop must outlast the cold-start sync budget");
  assert.equal(OUTBOUND_DEADLINES.staleRefreshBudgetMs, TIMEOUT_CONTRACT.serverStaleRefreshBudgetMs);
});

test("fresh cache returns immediately without touching upstream", async () => {
  const cache = new MemorySnapshotCache({ now: () => NOW });
  await cache.set({ ok: true, schemaVersion: 2, syncedAt: "x", stale: false, businesses: [] });
  const counter = { count: 0 };
  const result = await serviceResult(mockAggregateClient(aggregatePayload(), { counter }), { cache, key: "fresh-fast" });
  assert.equal(result.cacheState, "fresh");
  assert.equal(result.payload.stale, false);
  assert.equal(counter.count, 0);
});

test("slow upstream returns the stale snapshot inside the stale-refresh budget", async () => {
  const cache = await staleCache();
  let resolved = false;
  const client = { async getStatusAggregation() { await delay(80); resolved = true; return aggregatePayload(); } };
  const started = Date.now();
  const result = await createGitHubStatusService({ client, cache, now: () => NOW, singleFlightKey: "slow-stale", timeouts: fastBudget() }).getStatus();
  const elapsed = Date.now() - started;
  assert.equal(result.cacheState, "stale");
  assert.equal(result.payload.stale, true);
  assert.equal(result.payload.businesses[0].number, 15);
  assert.equal(resolved, false, "stale snapshot served before the slow upstream finished");
  assert.ok(elapsed < 70, `served stale fast (${elapsed}ms) rather than waiting 80ms for upstream`);
});

test("a fast upstream still refreshes to fresh within the stale-refresh budget", async () => {
  const cache = await staleCache();
  const counter = { count: 0 };
  const client = mockAggregateClient(aggregatePayload(), { delayMs: 5, counter });
  const result = await createGitHubStatusService({ client, cache, now: () => NOW, singleFlightKey: "fast-stale", timeouts: fastBudget() }).getStatus();
  assert.equal(result.cacheState, "miss");
  assert.equal(result.payload.stale, false);
  assert.equal(counter.count, 1);
});

test("GraphQL timeout during stale refresh preserves the last-good snapshot", async () => {
  const cache = await staleCache();
  const error = new OutboundTimeoutError("graphql-request");
  const result = await serviceResult(mockAggregateClient(null, { throwError: error }), { cache, key: "timeout-stale" });
  assert.equal(result.status, 200);
  assert.equal(result.cacheState, "stale");
  assert.equal(result.payload.ok, true);
  assert.equal(result.payload.stale, true);
  assert.equal(result.payload.businesses[0].number, 15);
  assert.equal(result.payload.errors.at(-1).diagnosticCode, "GITHUB_GRAPHQL_TIMEOUT");
});

test("timeout without any snapshot is a normalized safe failure", async () => {
  const error = new OutboundTimeoutError("sync");
  const result = await serviceResult(mockAggregateClient(null, { throwError: error }), { key: "timeout-nosnapshot" });
  assert.equal(result.status, 502);
  assert.equal(result.cacheState, "unavailable");
  assert.equal(result.payload.ok, false);
  assert.deepEqual(result.payload.businesses, []);
  assert.equal(result.payload.error.diagnosticCode, "GITHUB_GRAPHQL_TIMEOUT");
});

test("stale handler response preserves diagnostic header and body contract", async () => {
  const cache = await staleCache();
  const client = { async getStatusAggregation() { await delay(80); return aggregatePayload(); } };
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"), env: envWithCredentials(), client, cache, now: () => NOW,
    timeouts: fastBudget(),
  });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("X-Portfolio-Cache"), "stale");
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), "GITHUB_GRAPHQL_TIMEOUT");
  assert.equal(response.headers.get("X-Portfolio-Function-Contract"), "github-status-diagnostics-v1");
  const body = await response.json();
  assert.equal(body.schemaVersion, 2);
  assert.equal(body.ok, true);
  assert.equal(body.stale, true);
  assert.equal(body.businesses[0].number, 15);
});

test("stale path preserves the full 55 / 40 / 15 authority set and order", async () => {
  const fresh = await serviceResult(mockAggregateClient(aggregatePayload()), { key: "seed-55" });
  const numbers = fresh.payload.businesses.map((b) => b.number);
  assert.equal(numbers.length, 55);
  const connected = fresh.payload.businesses.filter((b) => b.connectionState !== "unmapped").length;
  const unmapped = fresh.payload.businesses.filter((b) => b.connectionState === "unmapped").length;
  assert.equal(connected, 40);
  assert.equal(unmapped, 15);
  const cache = new MemorySnapshotCache({ now: () => NOW - 181_000 });
  await cache.set(fresh.payload); cache.now = () => NOW;
  const client = { async getStatusAggregation() { await delay(80); return aggregatePayload(); } };
  const stale = await createGitHubStatusService({ client, cache, now: () => NOW, singleFlightKey: "stale-55", timeouts: fastBudget() }).getStatus();
  assert.equal(stale.cacheState, "stale");
  assert.deepEqual(stale.payload.businesses.map((b) => b.number), numbers);
});

test("stale-fast response leaks no secret, stack, or raw upstream content", async () => {
  const cache = await staleCache();
  const client = { async getStatusAggregation() { await delay(80); throw new Error("raw <html>PRIVATE_KEY stack Authorization</html>"); } };
  const result = await createGitHubStatusService({ client, cache, now: () => NOW, singleFlightKey: "stale-leak", timeouts: fastBudget() }).getStatus();
  const text = JSON.stringify(result.payload);
  for (const forbidden of ["<html>", "PRIVATE_KEY", "stack", "Authorization", "app-secret", "install-secret", "private-secret"]) {
    assert.equal(text.includes(forbidden), false, `no leakage of ${forbidden}`);
  }
});

test("concurrent stale callers share a single slow refresh (no request storm)", async () => {
  const cache = await staleCache();
  const counter = { count: 0 };
  const client = { async getStatusAggregation() { counter.count += 1; await delay(60); return aggregatePayload(); } };
  const timeouts = fastBudget();
  const services = Array.from({ length: 20 }, () => createGitHubStatusService({ client, cache, now: () => NOW, singleFlightKey: "concurrent-slow-stale", timeouts }));
  const results = await Promise.all(services.map((s) => s.getStatus()));
  assert.equal(counter.count, 1, "single-flight deduplication prevents a refresh storm");
  assert.equal(results.every((r) => r.cacheState === "stale" && r.payload.stale === true), true);
});

test("deadline timer is cleared after a stale-fast return (no timer leak)", async () => {
  const cache = await staleCache();
  const calls = { set: 0, clear: 0 };
  const timers = {
    setTimeout: (fn, ms) => { calls.set += 1; return setTimeout(fn, ms); },
    clearTimeout: (id) => { calls.clear += 1; return clearTimeout(id); },
  };
  const client = { async getStatusAggregation() { return new Promise(() => {}); } }; // never settles
  const result = await createGitHubStatusService({ client, cache, now: () => NOW, singleFlightKey: "timer-cleanup", timeouts: fastBudget(), timers }).getStatus();
  assert.equal(result.cacheState, "stale");
  assert.ok(calls.set >= 1, "a deadline timer was started");
  assert.ok(calls.clear >= 1, "the deadline timer was cleared");
});

test("non-timeout upstream error on stale cache still serves the snapshot", async () => {
  const cache = await staleCache();
  const error = new GitHubApiError("UPSTREAM_RATE_LIMITED", 429);
  const result = await serviceResult(mockAggregateClient(null, { throwError: error }), { cache, key: "ratelimit-stale" });
  assert.equal(result.cacheState, "stale");
  assert.equal(result.payload.stale, true);
  assert.equal(result.payload.errors.at(-1).code, "UPSTREAM_RATE_LIMITED");
});
