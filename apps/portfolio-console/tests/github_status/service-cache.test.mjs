import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { GitHubApiError } from "../../functions/_lib/github-client.js";
import { MemorySnapshotCache, RuntimeSnapshotCache } from "../../functions/_lib/cache.js";
import { createGitHubStatusService } from "../../functions/_lib/github-status-service.js";
import { handleGitHubStatusRequest } from "../../functions/api/github-status.js";
import {
  BUSINESS_GITHUB_MAP, NOW, ROOT, aggregatePayload, delay, envWithCredentials, gqlPr,
  memoryKv, mockAggregateClient, serviceResult
} from "./fixtures.mjs";

test("full GraphQL aggregation normalizes B01 B02 B06 B09 B15", async () => {
  const result = await serviceResult(mockAggregateClient());
  const map = new Map(result.payload.businesses.map((item) => [item.number, item]));
  assert.deepEqual([map.get(1).issue.number, map.get(1).pullRequest.number, map.get(1).pullRequest.draft], [108, 111, true]);
  assert.deepEqual([map.get(2).pullRequest.state, map.get(2).pullRequest.merged], ["merged", true]);
  assert.deepEqual([map.get(6).issue.number, map.get(6).pullRequest, map.get(6).checks.state], [98, null, "unavailable"]);
  assert.deepEqual([map.get(9).pullRequest.state, map.get(9).pullRequest.draft, map.get(9).pullRequest.merged], ["open", true, false]);
  assert.equal("progress" in map.get(9), false);
  assert.equal(map.get(15).connectionState, "unmapped");
});
test("closed unmerged PR remains closed", async () => {
  const payload = aggregatePayload({ overrides: { repository: { pr94: gqlPr(94, { state: "CLOSED", isDraft: false, merged: false }) } } });
  const result = await serviceResult(mockAggregateClient(payload));
  const business = result.payload.businesses.find((item) => item.number === 4);
  assert.deepEqual([business.pullRequest.state, business.pullRequest.merged], ["closed", false]);
});
test("GraphQL partial checks error preserves Issue and PR", async () => {
  const payload = aggregatePayload({ errors: [{ path: ["repository", "pr174", "commits", 0, "commit", "statusCheckRollup"], message: "hidden upstream" }] });
  const result = await serviceResult(mockAggregateClient(payload));
  const business = result.payload.businesses.find((item) => item.number === 7);
  assert.equal(business.issue.number, 166);
  assert.equal(business.pullRequest.number, 174);
  assert.equal(business.checks.state, "unavailable");
  assert.equal(business.connectionState, "partial");
  assert.equal(business.error.code, "CHECKS_UNAVAILABLE");
  assert.equal(JSON.stringify(result.payload).includes("hidden upstream"), false);
});
test("GraphQL partial Issue error preserves other aliases", async () => {
  const payload = aggregatePayload({ errors: [{ path: ["repository", "issue166"], message: "secret body" }], overrides: { repository: { issue166: null } } });
  const result = await serviceResult(mockAggregateClient(payload));
  const business = result.payload.businesses.find((item) => item.number === 7);
  assert.equal(business.issue, null);
  assert.equal(business.pullRequest.number, 174);
  assert.equal(business.connectionState, "partial");
});
test("20 concurrent getStatus calls aggregate once", async () => {
  const counter = { count: 0 };
  const cache = new MemorySnapshotCache({ now: () => NOW });
  const services = Array.from({ length: 20 }, () => createGitHubStatusService({
    client: mockAggregateClient(aggregatePayload(), { delayMs: 10, counter }), cache, now: () => NOW, singleFlightKey: "concurrent-success"
  }));
  const results = await Promise.all(services.map((service) => service.getStatus()));
  assert.equal(counter.count, 1);
  assert.equal(new Set(results.map((result) => result.payload.syncedAt)).size, 1);
});
test("failed refresh flight clears and later recovers", async () => {
  const counter = { count: 0 }; let fail = true;
  const client = { async getStatusAggregation() { counter.count += 1; await delay(); if (fail) throw new Error("down"); return aggregatePayload(); } };
  const cache = new MemorySnapshotCache({ now: () => NOW });
  const services = Array.from({ length: 20 }, () => createGitHubStatusService({ client, cache, now: () => NOW, singleFlightKey: "concurrent-recovery" }));
  const first = await Promise.all(services.map((service) => service.getStatus()));
  assert.equal(counter.count, 1);
  assert.equal(first.every((result) => result.status === 502), true);
  fail = false;
  const recovered = await services[0].getStatus();
  assert.equal(recovered.status, 200);
  assert.equal(counter.count, 2);
});
test("20 concurrent stale callers share one failed refresh and snapshot", async () => {
  const snapshot = { ok: true, schemaVersion: 1, syncedAt: "old", stale: false, businesses: [{ number: 15 }] };
  const cache = new MemorySnapshotCache({ now: () => NOW - 181_000 });
  await cache.set(snapshot); cache.now = () => NOW;
  const counter = { count: 0 };
  const error = new GitHubApiError("UPSTREAM_RATE_LIMITED", 429);
  const services = Array.from({ length: 20 }, () => createGitHubStatusService({
    client: mockAggregateClient(null, { throwError: error, delayMs: 10, counter }), cache, now: () => NOW, singleFlightKey: "concurrent-stale"
  }));
  const results = await Promise.all(services.map((service) => service.getStatus()));
  assert.equal(counter.count, 1);
  assert.equal(results.every((result) => result.cacheState === "stale" && result.payload.stale && result.payload.businesses[0].number === 15), true);
});
test("fresh memory cache avoids aggregation", async () => {
  const cache = new MemorySnapshotCache({ now: () => NOW });
  await cache.set({ ok: true, schemaVersion: 1, syncedAt: "x", stale: false, businesses: [] });
  const counter = { count: 0 };
  const result = await serviceResult(mockAggregateClient(aggregatePayload(), { counter }), { cache, key: "fresh-memory" });
  assert.equal(result.cacheState, "fresh"); assert.equal(counter.count, 0);
});
test("fresh KV cache avoids aggregation", async () => {
  const snapshot = { ok: true, schemaVersion: 1, syncedAt: "x", stale: false, businesses: [] };
  const kv = memoryKv({ schemaVersion: 1, storedAtMs: NOW, snapshot });
  const cache = new RuntimeSnapshotCache({ kv, now: () => NOW, memoryStore: new Map() });
  const counter = { count: 0 };
  const result = await serviceResult(mockAggregateClient(aggregatePayload(), { counter }), { cache, key: "fresh-kv" });
  assert.equal(result.cacheState, "fresh"); assert.equal(counter.count, 0);
});
test("stale KV snapshot is returned on rate limit", async () => {
  const snapshot = { ok: true, schemaVersion: 1, syncedAt: "old", stale: false, businesses: [{ number: 15 }] };
  const kv = memoryKv({ schemaVersion: 1, storedAtMs: NOW - 181_000, snapshot });
  const cache = new RuntimeSnapshotCache({ kv, now: () => NOW, memoryStore: new Map() });
  const error = new GitHubApiError("UPSTREAM_RATE_LIMITED", 429);
  const result = await serviceResult(mockAggregateClient(null, { throwError: error }), { cache, key: "stale-kv" });
  assert.equal(result.cacheState, "stale");
  assert.equal(result.payload.stale, true);
  assert.equal(result.payload.errors.at(-1).code, "UPSTREAM_RATE_LIMITED");
});
test("failure without snapshot is normalized", async () => {
  const result = await serviceResult(mockAggregateClient(null, { throwError: new Error("<html>secret</html>") }));
  assert.equal(result.status, 502);
  assert.equal(result.payload.error.code, "UPSTREAM_UNAVAILABLE");
  assert.equal(JSON.stringify(result.payload).includes("<html>"), false);
});
test("KV stores only versioned last-good snapshot", async () => {
  const kv = memoryKv();
  const cache = new RuntimeSnapshotCache({ kv, now: () => NOW, memoryStore: new Map() });
  await cache.set({ ok: true, schemaVersion: 1, businesses: [] });
  assert.equal(kv.puts.length, 1);
  const text = kv.puts[0].text;
  for (const forbidden of ["private key", "JWT", "installation token", "Authorization", "app-secret", "install-secret"]) assert.equal(text.includes(forbidden), false);
  assert.equal(kv.puts[0].options.expirationTtl, 86400);
});
test("handler response never discloses secrets", async () => {
  const cache = new MemorySnapshotCache({ now: () => NOW });
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"), env: envWithCredentials(), client: mockAggregateClient(), cache, now: () => NOW
  });
  const text = await response.text();
  for (const secret of ["app-secret", "install-secret", "private-secret", "Authorization", "stack"]) assert.equal(text.includes(secret), false);
});
test("server mapping parity with businesses.js", async () => {
  const source = await readFile(path.join(ROOT, "businesses.js"), "utf8");
  for (const mapping of BUSINESS_GITHUB_MAP) {
    const expression = new RegExp(`\\bnumber:\\s*${mapping.number},([\\s\\S]*?)(?=\\n  \\{|\\n\\];)`);
    const block = expression.exec(source)?.[0] || "";
    assert.ok(block);
    if (mapping.issueNumber) assert.match(block, new RegExp(`/issues/${mapping.issueNumber}`));
    if (mapping.pullRequestNumber) assert.match(block, new RegExp(`/pull/${mapping.pullRequestNumber}`));
    else assert.equal(/\/pull\/\d+/.test(block), false);
  }
});
