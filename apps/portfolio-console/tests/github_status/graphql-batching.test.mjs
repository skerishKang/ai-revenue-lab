import test from "node:test";
import assert from "node:assert/strict";
import { GitHubClient, GitHubApiError } from "../../functions/_lib/github-client.js";
import { InstallationTokenProvider } from "../../functions/_lib/github-app-auth.js";
import { MemorySnapshotCache } from "../../functions/_lib/cache.js";
import {
  getBatchPlan, getRequestBudget, GRAPHQL_BATCH_SIZE, GRAPHQL_BATCH_CONCURRENCY, buildDiscoveryAliasSelections,
} from "../../functions/_lib/business-github-query.js";
import { handleGitHubStatusRequest } from "../../functions/api/github-status.js";
import {
  NOW, aggregatePayload, jsonResponse, delay, routeGraphqlResponse, batchedGraphqlFetchImpl,
  serviceResult, mockAggregateClient, envWithCredentials, webcrypto, generatePrivateKeyPem,
} from "./fixtures.mjs";

const stubAuth = () => ({ async getToken() { return "t"; }, invalidate() {} });

function batchedFetchWithFault(full, { failBatchIndex = null, failStatus = 504, dropAlias = null, duplicateAlias = null } = {}) {
  let discoverySeen = -1;
  return async (url, init) => {
    if (String(url).includes("access_tokens")) return jsonResponse({ token: "t", expires_at: new Date(NOW + 120_000).toISOString() });
    const query = JSON.parse(init.body).query || "";
    if (query.includes("repository(owner:")) return jsonResponse(routeGraphqlResponse(full, init));
    discoverySeen += 1;
    if (failBatchIndex !== null && discoverySeen === failBatchIndex) return jsonResponse({}, failStatus);
    const resp = routeGraphqlResponse(full, init);
    if (dropAlias) delete resp.data[dropAlias];
    if (duplicateAlias && duplicateAlias in full.data) resp.data[duplicateAlias] = full.data[duplicateAlias];
    return jsonResponse(resp);
  };
}

test("batch plan and request budget are fixed and mutually consistent", () => {
  const plan = getBatchPlan();
  const budget = getRequestBudget();
  assert.equal(plan.batchSize, GRAPHQL_BATCH_SIZE);
  assert.equal(plan.concurrency, GRAPHQL_BATCH_CONCURRENCY);
  assert.equal(plan.coreRequests, 1);
  assert.equal(plan.maxGraphqlRequests, 1 + plan.discoveryBatchCount);
  assert.equal(budget.maxGraphqlRequests, plan.maxGraphqlRequests);
  assert.equal(budget.cold, 1 + plan.maxGraphqlRequests);
  assert.equal(budget.cachedToken, plan.maxGraphqlRequests);
  assert.equal(budget.worstCase, 2 + 2 * plan.maxGraphqlRequests);
  assert.equal(budget.maxTokenExchanges, 2);
  assert.ok(plan.discoveryBatchCount > 1, "discovery is split, not one oversized operation");
});

test("bounded concurrency: in-flight GraphQL operations never exceed the limit", async () => {
  const full = aggregatePayload();
  let inFlight = 0; let maxInFlight = 0;
  const fetchImpl = async (url, init) => {
    if (String(url).includes("access_tokens")) return jsonResponse({ token: "t", expires_at: new Date(NOW + 120_000).toISOString() });
    inFlight += 1; maxInFlight = Math.max(maxInFlight, inFlight);
    await delay(15);
    inFlight -= 1;
    return jsonResponse(routeGraphqlResponse(full, init));
  };
  const client = new GitHubClient({ authProvider: stubAuth(), fetchImpl, batchSize: 10, concurrency: 3 });
  const result = await client.getStatusAggregation();
  assert.ok(result.data.repository, "merged data present");
  assert.ok(maxInFlight <= 3, `in-flight capped at concurrency (observed ${maxInFlight})`);
  assert.ok(maxInFlight >= 2, `batches ran concurrently (observed ${maxInFlight})`);
});

test("all batches succeeding yields the 40 mapped Business facts via the real client", async () => {
  const full = aggregatePayload();
  const counter = { count: 0 };
  const client = new GitHubClient({ authProvider: stubAuth(), fetchImpl: batchedGraphqlFetchImpl(full, { counter }) });
  const aggregate = await client.getStatusAggregation();
  assert.equal(counter.count, getBatchPlan().maxGraphqlRequests, "exactly the bounded GraphQL plan");
  const result = await serviceResult({ getStatusAggregation: async () => aggregate }, { key: "batching-40-facts" });
  assert.equal(result.status, 200);
  assert.equal(result.payload.ok, true);
  assert.equal(result.payload.stale, false);
  assert.equal(result.payload.schemaVersion, 2);
  assert.equal(result.payload.businesses.length, 40);
  assert.equal(result.payload.businesses.filter((b) => b.repository).length, 40);
});

test("merge is deterministic: two runs produce identical data and Business order", async () => {
  const full = aggregatePayload();
  const make = () => new GitHubClient({ authProvider: stubAuth(), fetchImpl: batchedGraphqlFetchImpl(full) });
  const a = await make().getStatusAggregation();
  const b = await make().getStatusAggregation();
  assert.deepEqual(Object.keys(a.data), Object.keys(b.data), "merged key order deterministic");
  assert.deepEqual(a.data, b.data, "merged data identical");
  const ra = await serviceResult({ getStatusAggregation: async () => a }, { key: "det-a" });
  const rb = await serviceResult({ getStatusAggregation: async () => b }, { key: "det-b" });
  assert.deepEqual(ra.payload.businesses.map((x) => x.number), rb.payload.businesses.map((x) => x.number));
});

test("one discovery batch HTTP 504 is classified GITHUB_GRAPHQL_TIMEOUT and aborts the refresh", async () => {
  const full = aggregatePayload();
  const client = new GitHubClient({ authProvider: stubAuth(), fetchImpl: batchedFetchWithFault(full, { failBatchIndex: 2, failStatus: 504 }) });
  await assert.rejects(() => client.getStatusAggregation(), (error) => error instanceof GitHubApiError && error.code === "GITHUB_GRAPHQL_TIMEOUT" && error.status === 504);
});

test("a non-504 batch failure keeps the safe request-failure classification", async () => {
  const full = aggregatePayload();
  const client = new GitHubClient({ authProvider: stubAuth(), fetchImpl: batchedFetchWithFault(full, { failBatchIndex: 1, failStatus: 500 }) });
  await assert.rejects(() => client.getStatusAggregation(), (error) => error.code === "GITHUB_REQUEST_FAILED" && error.status === 500);
});

test("a batch missing an alias is never reported as fresh (fail safe)", async () => {
  const full = aggregatePayload();
  const missingAlias = Object.keys(full.data).find((k) => k.startsWith("prSearch"));
  const client = new GitHubClient({ authProvider: stubAuth(), fetchImpl: batchedFetchWithFault(full, { dropAlias: missingAlias }) });
  await assert.rejects(() => client.getStatusAggregation(), (error) => error.code === "GRAPHQL_DATA_UNAVAILABLE");
});

test("a duplicated alias across batches fails safe instead of merging partial data", async () => {
  const full = aggregatePayload();
  const dupAlias = Object.keys(full.data).find((k) => k.startsWith("prSearch"));
  const client = new GitHubClient({ authProvider: stubAuth(), fetchImpl: batchedFetchWithFault(full, { duplicateAlias: dupAlias }) });
  await assert.rejects(() => client.getStatusAggregation(), (error) => error.code === "GRAPHQL_DATA_UNAVAILABLE");
});

test("batch failure with stale cache returns stale 200 with the timeout diagnostic header", async () => {
  const snapshot = { ok: true, schemaVersion: 1, syncedAt: "old", stale: false, businesses: [{ number: 15 }] };
  const cache = new MemorySnapshotCache({ now: () => NOW - 181_000 });
  await cache.set(snapshot);
  cache.now = () => NOW;
  const error = new GitHubApiError("GITHUB_GRAPHQL_TIMEOUT", 504);
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"),
    env: envWithCredentials(), now: () => NOW, cache,
    client: mockAggregateClient(null, { throwError: error }),
  });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("X-Portfolio-Cache"), "stale");
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), "GITHUB_GRAPHQL_TIMEOUT");
  const body = await response.json();
  assert.equal(body.stale, true);
  assert.equal(body.errors.at(-1).diagnosticCode, "GITHUB_GRAPHQL_TIMEOUT");
});

test("batch failure without cache returns a normalized 502 with body/header diagnostic parity", async () => {
  const error = new GitHubApiError("GITHUB_GRAPHQL_TIMEOUT", 504);
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"),
    env: envWithCredentials(), now: () => NOW, cache: new MemorySnapshotCache({ now: () => NOW }),
    client: mockAggregateClient(null, { throwError: error }),
  });
  assert.equal(response.status, 502);
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), "GITHUB_GRAPHQL_TIMEOUT");
  const body = await response.json();
  assert.equal(body.error.diagnosticCode, "GITHUB_GRAPHQL_TIMEOUT");
  assert.equal(body.schemaVersion, 2);
});

test("concurrent 401s across batches trigger exactly one token refresh", async () => {
  const full = aggregatePayload();
  let tokenExchanges = 0;
  const fetchImpl = async (url, init) => {
    if (url.includes("access_tokens")) { tokenExchanges += 1; await delay(10); return jsonResponse({ token: `t${tokenExchanges}`, expires_at: new Date(NOW + 120_000).toISOString() }); }
    const auth = init.headers.Authorization || "";
    const isCore = (JSON.parse(init.body).query || "").includes("repository(owner:");
    // The core succeeds on the initial token; discovery batches that still carry
    // the stale token 401 concurrently and must share a single refresh.
    if (!isCore && auth.includes("t1")) return jsonResponse({}, 401);
    return jsonResponse(routeGraphqlResponse(full, init));
  };
  const pem = await generatePrivateKeyPem();
  const authProvider = new InstallationTokenProvider({ appId: "123", installationId: "456", privateKeyPkcs8: pem, cryptoImpl: webcrypto, now: () => NOW, fetchImpl });
  const client = new GitHubClient({ authProvider, fetchImpl });
  const result = await client.getStatusAggregation();
  assert.ok(result.data.repository, "refresh recovered the refresh");
  assert.equal(Object.keys(result.data).filter((k) => k.startsWith("prSearch")).length, buildDiscoveryAliasSelections().length, "all discovery aliases merged");
  assert.equal(tokenExchanges, 2, "initial exchange + exactly one shared 401 refresh");
});

test("a batch timeout is not retried (fetch for that operation happens once)", async () => {
  const full = aggregatePayload();
  const perQueryCalls = new Map();
  const fetchImpl = async (url, init) => {
    if (String(url).includes("access_tokens")) return jsonResponse({ token: "t", expires_at: new Date(NOW + 120_000).toISOString() });
    const query = JSON.parse(init.body).query || "";
    perQueryCalls.set(query, (perQueryCalls.get(query) || 0) + 1);
    if (!query.includes("repository(owner:") && query.includes("prSearchRefs")) return new Promise(() => {});
    return jsonResponse(routeGraphqlResponse(full, init));
  };
  const client = new GitHubClient({ authProvider: stubAuth(), fetchImpl, timeouts: { graphqlRequestMs: 20, graphqlBodyMs: 20, installationTokenRequestMs: 20, installationTokenBodyMs: 20, totalSyncMs: 300, handlerBackstopMs: 600 } });
  await assert.rejects(() => client.getStatusAggregation(), (error) => error.code === "GITHUB_GRAPHQL_TIMEOUT");
  for (const count of perQueryCalls.values()) assert.equal(count, 1, "no operation retried");
});
