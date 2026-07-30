import test from "node:test";
import assert from "node:assert/strict";
import { GitHubClient, GitHubApiError } from "../../functions/_lib/github-client.js";
import { InstallationTokenProvider } from "../../functions/_lib/github-app-auth.js";
import { MemorySnapshotCache } from "../../functions/_lib/cache.js";
import {
  getBatchPlan, getRequestBudget, GRAPHQL_BATCH_SIZE, GRAPHQL_BATCH_CONCURRENCY, buildDiscoveryAliasSelections,
  getAllIssueNumbers, getFallbackPrNumbers,
} from "../../functions/_lib/business-github-query.js";
import { handleGitHubStatusRequest } from "../../functions/api/github-status.js";
import {
  NOW, aggregatePayload, jsonResponse, delay, routeGraphqlResponse, batchedGraphqlFetchImpl,
  serviceResult, mockAggregateClient, envWithCredentials, webcrypto, generatePrivateKeyPem,
  BUSINESS_GITHUB_MAP, GITHUB_REPOSITORY,
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

test("all batches succeeding yields all 55 authority records via the real client", async () => {
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
  assert.equal(result.payload.businesses.length, BUSINESS_GITHUB_MAP.length);
  assert.equal(result.payload.businesses.filter((b) => b.repository).length, BUSINESS_GITHUB_MAP.filter((m) => m.repository === GITHUB_REPOSITORY).length);
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

const LEAK_CANARY = "raw-upstream-message-must-not-leak";

function coreUnexpectedErrorFetch(full) {
  return async (url, init) => {
    if (String(url).includes("access_tokens")) return jsonResponse({ token: "t", expires_at: new Date(NOW + 120_000).toISOString() });
    const query = JSON.parse(init.body).query || "";
    if (query.includes("repository(owner:")) {
      const core = routeGraphqlResponse(full, init);
      // data + a genuine (non null-alias) error ⇒ incomplete refresh.
      core.errors = [{ path: ["repository", "nameWithOwner"], type: "FORBIDDEN", message: LEAK_CANARY }];
      return jsonResponse(core);
    }
    return jsonResponse(routeGraphqlResponse(full, init));
  };
}

function discoveryErrorFetch(full) {
  let discoverySeen = -1;
  return async (url, init) => {
    if (String(url).includes("access_tokens")) return jsonResponse({ token: "t", expires_at: new Date(NOW + 120_000).toISOString() });
    const query = JSON.parse(init.body).query || "";
    if (query.includes("repository(owner:")) return jsonResponse(routeGraphqlResponse(full, init));
    discoverySeen += 1;
    const resp = routeGraphqlResponse(full, init);
    if (discoverySeen === 1) {
      const alias = Object.keys(resp.data)[0];
      resp.errors = [{ path: [alias], type: "FORBIDDEN", message: LEAK_CANARY }];
    }
    return jsonResponse(resp);
  };
}

test("core data+errors (unexpected) is an incomplete refresh: GITHUB_GRAPHQL_PARTIAL_RESPONSE", async () => {
  const full = aggregatePayload();
  const client = new GitHubClient({ authProvider: stubAuth(), fetchImpl: coreUnexpectedErrorFetch(full) });
  await assert.rejects(() => client.getStatusAggregation(), (error) => error instanceof GitHubApiError && error.code === "GITHUB_GRAPHQL_PARTIAL_RESPONSE" && error.status === 502);
});

test("discovery data+errors is an incomplete refresh: GITHUB_GRAPHQL_PARTIAL_RESPONSE", async () => {
  const full = aggregatePayload();
  const client = new GitHubClient({ authProvider: stubAuth(), fetchImpl: discoveryErrorFetch(full) });
  await assert.rejects(() => client.getStatusAggregation(), (error) => error.code === "GITHUB_GRAPHQL_PARTIAL_RESPONSE");
});

test("partial response with stale cache returns stale 200 with diagnostic parity and no raw message", async () => {
  const full = aggregatePayload();
  const snapshot = { ok: true, schemaVersion: 1, syncedAt: "old", stale: false, businesses: [{ number: 15 }] };
  const cache = new MemorySnapshotCache({ now: () => NOW - 181_000 });
  await cache.set(snapshot);
  cache.now = () => NOW;
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"),
    env: envWithCredentials(), now: () => NOW, cache,
    client: new GitHubClient({ authProvider: stubAuth(), fetchImpl: coreUnexpectedErrorFetch(full) }),
  });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("X-Portfolio-Cache"), "stale");
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), "GITHUB_GRAPHQL_PARTIAL_RESPONSE");
  const text = await response.text();
  assert.ok(!text.includes(LEAK_CANARY), "raw GraphQL message is not reflected");
  const body = JSON.parse(text);
  assert.equal(body.stale, true);
  assert.equal(body.errors.at(-1).diagnosticCode, "GITHUB_GRAPHQL_PARTIAL_RESPONSE");
});

test("partial response without cache returns a normalized 502 with body/header diagnostic parity", async () => {
  const full = aggregatePayload();
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"),
    env: envWithCredentials(), now: () => NOW, cache: new MemorySnapshotCache({ now: () => NOW }),
    client: new GitHubClient({ authProvider: stubAuth(), fetchImpl: coreUnexpectedErrorFetch(full) }),
  });
  assert.equal(response.status, 502);
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), "GITHUB_GRAPHQL_PARTIAL_RESPONSE");
  const text = await response.text();
  assert.ok(!text.includes(LEAK_CANARY), "raw GraphQL message is not reflected");
  const body = JSON.parse(text);
  assert.equal(body.error.diagnosticCode, "GITHUB_GRAPHQL_PARTIAL_RESPONSE");
  assert.equal(body.schemaVersion, 2);
});

test("an expected null issue alias (data+error) is a handled data state, not a partial response", async () => {
  const full = aggregatePayload();
  const nullIssue = getAllIssueNumbers()[0];
  const fetchImpl = async (url, init) => {
    if (String(url).includes("access_tokens")) return jsonResponse({ token: "t", expires_at: new Date(NOW + 120_000).toISOString() });
    const query = JSON.parse(init.body).query || "";
    if (query.includes("repository(owner:")) {
      const core = routeGraphqlResponse(full, init);
      core.data.repository[`issue${nullIssue}`] = null;
      core.errors = [{ path: ["repository", `issue${nullIssue}`], type: "NOT_FOUND", message: "redacted" }];
      return jsonResponse(core);
    }
    return jsonResponse(routeGraphqlResponse(full, init));
  };
  const client = new GitHubClient({ authProvider: stubAuth(), fetchImpl });
  const aggregate = await client.getStatusAggregation();
  assert.equal(aggregate.data.repository[`issue${nullIssue}`], null, "null alias preserved, not treated as partial");
  const result = await serviceResult({ getStatusAggregation: async () => aggregate }, { key: "expected-null-alias" });
  assert.equal(result.status, 200);
  assert.equal(result.payload.ok, true);
  assert.equal(result.payload.stale, false);
  assert.equal(result.payload.businesses.length, BUSINESS_GITHUB_MAP.length);
  assert.ok(!(result.payload.errors || []).some((e) => e.diagnosticCode === "GITHUB_GRAPHQL_PARTIAL_RESPONSE"), "no partial-response diagnostic for an expected null alias");
});

test("a null alias value without any GraphQL error is handled gracefully", async () => {
  const full = aggregatePayload();
  const fb = getFallbackPrNumbers()[0];
  const fetchImpl = async (url, init) => {
    if (String(url).includes("access_tokens")) return jsonResponse({ token: "t", expires_at: new Date(NOW + 120_000).toISOString() });
    const query = JSON.parse(init.body).query || "";
    if (query.includes("repository(owner:")) {
      const core = routeGraphqlResponse(full, init);
      core.data.repository[`fallbackPr${fb}`] = null;
      return jsonResponse(core);
    }
    return jsonResponse(routeGraphqlResponse(full, init));
  };
  const client = new GitHubClient({ authProvider: stubAuth(), fetchImpl });
  const aggregate = await client.getStatusAggregation();
  assert.equal(aggregate.data.repository[`fallbackPr${fb}`], null);
  assert.equal(aggregate.errors.length, 0, "a clean null value surfaces no error");
  const result = await serviceResult({ getStatusAggregation: async () => aggregate }, { key: "null-value-no-error" });
  assert.equal(result.status, 200);
  assert.equal(result.payload.ok, true);
});

test("a late old-token 401 arriving after the shared refresh still retries once with the new token", async () => {
  const full = aggregatePayload();
  let tokenExchanges = 0;
  const fetchImpl = async (url, init) => {
    if (url.includes("access_tokens")) { tokenExchanges += 1; await delay(10); return jsonResponse({ token: `t${tokenExchanges}`, expires_at: new Date(NOW + 120_000).toISOString() }); }
    const auth = init.headers.Authorization || "";
    const query = JSON.parse(init.body).query || "";
    if (query.includes("repository(owner:")) return jsonResponse(routeGraphqlResponse(full, init));
    // batch A (Discovery0) 401s quickly on the old token and triggers the shared
    // refresh; batch B (Discovery1) 401s LATE on the old token, after the refresh
    // has completed, and must still retry once with the refreshed token.
    if (auth.includes("t1") && query.includes("PortfolioAutoSyncDiscovery0")) { await delay(5); return jsonResponse({}, 401); }
    if (auth.includes("t1") && query.includes("PortfolioAutoSyncDiscovery1")) { await delay(60); return jsonResponse({}, 401); }
    return jsonResponse(routeGraphqlResponse(full, init));
  };
  const pem = await generatePrivateKeyPem();
  const authProvider = new InstallationTokenProvider({ appId: "123", installationId: "456", privateKeyPkcs8: pem, cryptoImpl: webcrypto, now: () => NOW, fetchImpl });
  const client = new GitHubClient({ authProvider, fetchImpl });
  const result = await client.getStatusAggregation();
  assert.ok(result.data.repository, "late 401 recovered with the refreshed token");
  assert.equal(Object.keys(result.data).filter((k) => k.startsWith("prSearch")).length, buildDiscoveryAliasSelections().length, "all discovery aliases merged (batch B recovered)");
  assert.equal(tokenExchanges, 2, "initial exchange + exactly one shared refresh (no second refresh)");
});

test("a 401 on the refreshed token fails as GITHUB_GRAPHQL_AUTH_FAILED with no second refresh", async () => {
  const full = aggregatePayload();
  let tokenExchanges = 0;
  const fetchImpl = async (url, init) => {
    if (url.includes("access_tokens")) { tokenExchanges += 1; await delay(5); return jsonResponse({ token: `t${tokenExchanges}`, expires_at: new Date(NOW + 120_000).toISOString() }); }
    const query = JSON.parse(init.body).query || "";
    if (query.includes("repository(owner:")) return jsonResponse({}, 401);
    return jsonResponse(routeGraphqlResponse(full, init));
  };
  const pem = await generatePrivateKeyPem();
  const authProvider = new InstallationTokenProvider({ appId: "123", installationId: "456", privateKeyPkcs8: pem, cryptoImpl: webcrypto, now: () => NOW, fetchImpl });
  const client = new GitHubClient({ authProvider, fetchImpl });
  await assert.rejects(() => client.getStatusAggregation(), (error) => error.code === "GITHUB_GRAPHQL_AUTH_FAILED");
  assert.equal(tokenExchanges, 2, "initial + one refresh, never a second refresh");
});

const UNMAPPED_NUMBERS = [23, 24, 25, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55];

test("focused regression: all 55 authority records — connected 40, unmapped 15, safe shape, cache round-trip", async () => {
  const full = aggregatePayload();

  // 1. Fresh load through real client + service
  const client = new GitHubClient({ authProvider: stubAuth(), fetchImpl: batchedGraphqlFetchImpl(full) });
  const aggregate = await client.getStatusAggregation();
  const result = await serviceResult({ getStatusAggregation: async () => aggregate }, { key: "55-regression" });
  assert.equal(result.status, 200);
  assert.equal(result.payload.ok, true);

  // 1. businesses.length === 55
  assert.equal(result.payload.businesses.length, BUSINESS_GITHUB_MAP.length, "total 55");

  // 2. businesses.map(b => b.number) === [1, 2, ..., 55]
  const numbers = result.payload.businesses.map((b) => b.number);
  assert.deepEqual(numbers, [...Array(55).keys()].map((i) => i + 1), "deterministic order 1–55, no gaps, no duplicates");

  // 3. connected count === 40
  const connected = result.payload.businesses.filter((b) => b.repository);
  assert.equal(connected.length, BUSINESS_GITHUB_MAP.filter((m) => m.repository === GITHUB_REPOSITORY).length, "connected 40");

  // 4. unmapped count === 15
  const unmapped = result.payload.businesses.filter((b) => b.connectionState === "unmapped");
  assert.equal(unmapped.length, UNMAPPED_NUMBERS.length, "unmapped 15");

  // 5. unmapped numbers === exact list
  assert.deepEqual(unmapped.map((b) => b.number), UNMAPPED_NUMBERS, "unmapped numbers match");

  // 6. All unmapped records have the safe null shape
  for (const b of unmapped) {
    assert.equal(b.connectionState, "unmapped", `B${b.number} connectionState`);
    assert.equal(b.repository, null, `B${b.number} repository`);
    assert.equal(b.productDecisionIssue, null, `B${b.number} productDecisionIssue`);
    assert.equal(b.phaseIssues, null, `B${b.number} phaseIssues`);
    assert.equal(b.currentPullRequests, null, `B${b.number} currentPullRequests`);
    assert.equal(b.phaseDiscovery, null, `B${b.number} phaseDiscovery`);
    assert.equal(b.phaseVerdicts, null, `B${b.number} phaseVerdicts`);
    assert.equal(b.activityAt, null, `B${b.number} activityAt`);
    assert.equal(b.error, null, `B${b.number} error`);
  }

  // 7. No fabricated GitHub facts in unmapped records
  for (const b of unmapped) {
    assert.equal(b.phaseDiscovery, null, `B${b.number} no discovery`);
    assert.equal(b.phaseVerdicts, null, `B${b.number} no verdicts`);
    assert.equal(b.repository, null, `B${b.number} no repo`);
  }

  // 8. Cache round-trip preserves all 55 records and exact number order
  const cache = new MemorySnapshotCache({ now: () => NOW });
  await cache.set(result.payload);
  // Read from cache (within fresh TTL)
  const cached = await cache.get();
  assert.ok(cached, "snapshot cached");
  assert.equal(cached.snapshot.businesses.length, 55, "cached 55");
  const cachedNums = cached.snapshot.businesses.map((b) => b.number);
  assert.deepEqual(cachedNums, [...Array(55).keys()].map((i) => i + 1), "cached order 1–55");

  // Stale fallback: force stale cache by jumping past freshTtl + staleTtl check
  const staleCache = new MemorySnapshotCache({ now: () => NOW - 200_000 });
  await staleCache.set(result.payload);
  staleCache.now = () => NOW;  // now TTL is expired but within stale window
  const staleResponse = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"),
    env: envWithCredentials(), now: () => NOW, cache: staleCache,
    client: mockAggregateClient(null, { throwError: new GitHubApiError("GITHUB_GRAPHQL_TIMEOUT", 504) }),
  });
  assert.equal(staleResponse.status, 200);
  const staleBody = await staleResponse.json();
  assert.equal(staleBody.businesses.length, 55, "stale fallback 55");
  assert.deepEqual(staleBody.businesses.map((b) => b.number), [...Array(55).keys()].map((i) => i + 1), "stale order 1–55");

  // 9. Request budget verification (pinned values)
  const budget = getRequestBudget();
  assert.equal(budget.cold, 9, "cold 9");
  assert.equal(budget.cachedToken, 8, "cachedToken 8");
  assert.equal(budget.worstCase, 18, "worstCase 18");
  assert.equal(budget.maxGraphqlRequests, 8, "maxGraphqlRequests 8");
  assert.equal(budget.maxTokenExchanges, 2, "maxTokenExchanges 2");
});
