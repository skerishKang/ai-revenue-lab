import test from "node:test";
import assert from "node:assert/strict";
import { createGitHubAppJwt } from "../../functions/_lib/github-app-auth.js";
import { GitHubClient, GitHubApiError, normalizeStatusCheckRollup } from "../../functions/_lib/github-client.js";
import { MemorySnapshotCache, RuntimeSnapshotCache } from "../../functions/_lib/cache.js";
import { validDiagnosticCode } from "../../functions/_lib/response.js";
import { assertAllowedRepository } from "../../functions/_lib/business-github-map.js";
import {
  buildCoreQuery, buildDiscoveryAliasSelections, buildDiscoveryBatchQuery,
  partitionDiscoverySelections, getBatchPlan, getRequestBudget, GRAPHQL_BATCH_SIZE,
} from "../../functions/_lib/business-github-query.js";
import { handleGitHubStatusRequest } from "../../functions/api/github-status.js";
import {
  BUSINESS_GITHUB_MAP, GITHUB_REPOSITORY, NOW, aggregatePayload, createProvider, decodeJwtPart,
  delay, envWithCredentials, generatePrivateKeyPem, jsonResponse, mockAggregateClient, rollup, serviceResult, webcrypto,
  batchedGraphqlFetchImpl, routeGraphqlResponse,
} from "./fixtures.mjs";

let privateKeyPem;
test.before(async () => { privateKeyPem = await generatePrivateKeyPem(); });

test("configuration missing is normalized", async () => {
  const response = await handleGitHubStatusRequest({ request: new Request("https://x/api/github-status"), env: { GITHUB_APP_ID: "not-returned" } });
  assert.equal(response.status, 503);
  const body = await response.json();
  assert.equal(body.error.code, "CONFIGURATION_MISSING");
  assert.equal(JSON.stringify(body).includes("not-returned"), false);
});
test("credentials without KV fail safely", async () => {
  const response = await handleGitHubStatusRequest({ request: new Request("https://x/api/github-status"), env: envWithCredentials() });
  assert.equal(response.status, 503);
  assert.equal((await response.json()).error.code, "CACHE_CONFIGURATION_MISSING");
});
test("method HEAD and arbitrary query contracts", async () => {
  const post = await handleGitHubStatusRequest({ request: new Request("https://x/api/github-status", { method: "POST" }), env: {} });
  assert.equal(post.status, 405);
  assert.equal(post.headers.get("Allow"), "GET, HEAD");
  const query = await handleGitHubStatusRequest({ request: new Request("https://x/api/github-status?repo=other/x"), env: {} });
  assert.equal(query.status, 400);
  const head = await handleGitHubStatusRequest({ request: new Request("https://x/api/github-status", { method: "HEAD" }), env: {} });
  assert.equal(head.status, 503);
  assert.equal(await head.text(), "");
});
test("JWT uses RS256 and clock drift", async () => {
  const now = 1_800_000_000;
  const jwt = await createGitHubAppJwt({ appId: "123", privateKeyPkcs8: privateKeyPem, nowSeconds: now, cryptoImpl: webcrypto });
  const [header, claims, signature] = jwt.split(".");
  assert.deepEqual(decodeJwtPart(header), { alg: "RS256", typ: "JWT" });
  assert.deepEqual(decodeJwtPart(claims), { iat: now - 60, exp: now + 540, iss: "123" });
  assert.ok(signature);
});
test("20 concurrent token calls exchange once", async () => {
  let exchanges = 0;
  const provider = createProvider(privateKeyPem, async () => {
    exchanges += 1; await delay();
    return jsonResponse({ token: "same-token", expires_at: new Date(NOW + 120_000).toISOString() });
  });
  const values = await Promise.all(Array.from({ length: 20 }, () => provider.getToken()));
  assert.equal(exchanges, 1);
  assert.deepEqual(new Set(values), new Set(["same-token"]));
});
test("failed token exchange releases lock and recovers", async () => {
  let exchanges = 0;
  const provider = createProvider(privateKeyPem, async () => {
    exchanges += 1; await delay();
    return exchanges === 1 ? jsonResponse({}, 500) : jsonResponse({ token: "recovered", expires_at: new Date(NOW + 120_000).toISOString() });
  });
  const first = await Promise.allSettled(Array.from({ length: 20 }, () => provider.getToken()));
  assert.equal(first.every((item) => item.status === "rejected"), true);
  assert.equal(exchanges, 1);
  assert.equal(await provider.getToken(), "recovered");
  assert.equal(exchanges, 2);
});
test("20 concurrent forceRefresh calls exchange once", async () => {
  let exchanges = 0;
  const provider = createProvider(privateKeyPem, async () => {
    exchanges += 1; await delay();
    return jsonResponse({ token: `token-${exchanges}`, expires_at: new Date(NOW + 120_000).toISOString() });
  });
  await provider.getToken();
  exchanges = 0;
  const values = await Promise.all(Array.from({ length: 20 }, () => provider.getToken({ forceRefresh: true })));
  assert.equal(exchanges, 1);
  assert.deepEqual(new Set(values), new Set(["token-1"]));
});
test("batched GraphQL contract: core carries identity/issues/fallbacks only", () => {
  const core = buildCoreQuery();
  assert.match(core, /query PortfolioAutoSyncCore\(\$owner: String!, \$name: String!\)/);
  assert.match(core, /repository\(owner: \$owner, name: \$name\)/);
  assert.match(core, /issues\(first:\s*1,\s*states:\s*OPEN\)/);
  assert.match(core, /pullRequests\(first:\s*1,\s*states:\s*OPEN\)/);
  assert.match(core, /commits\(last:\s*1\)/);
  assert.match(core, /contexts\(first:\s*100\)/);
  assert.match(core, /draftPullRequests: search\(query:/);
  for (const mapping of BUSINESS_GITHUB_MAP) {
    if (mapping.issueNumber) assert.match(core, new RegExp(`issue${mapping.issueNumber}: issue\\(number: ${mapping.issueNumber}\\)`));
    const fallbacks = mapping.fallbackPrNumbers || {};
    for (const phase of ["ui", "ux", "backend"]) {
      if (fallbacks[phase]) assert.match(core, new RegExp(`fallbackPr${fallbacks[phase]}: pullRequest\\(number: ${fallbacks[phase]}\\)`));
    }
  }
  assert.doesNotMatch(core, /prSearchRefs\d+: search\(/);
  assert.doesNotMatch(core, /prSearchRelated\d+: search\(/);
  assert.doesNotMatch(core, /prSearchMarker\d+_\w+: search\(/);
  assert.doesNotMatch(core, /prSearchConvention\d+_\w+: search\(/);
});
test("batched GraphQL contract: discovery aliases split into bounded deterministic batches", () => {
  const selections = buildDiscoveryAliasSelections();
  const batches = partitionDiscoverySelections(selections, GRAPHQL_BATCH_SIZE);
  assert.ok(batches.length > 1, "discovery is split across multiple operations");
  for (let i = 0; i < batches.length; i += 1) {
    assert.ok(batches[i].length <= GRAPHQL_BATCH_SIZE, `batch ${i} bounded by GRAPHQL_BATCH_SIZE`);
    const query = buildDiscoveryBatchQuery(batches[i], i);
    assert.doesNotMatch(query, /repository\(owner:/, "discovery batch carries no repository block");
    assert.equal((query.match(/: search\(/g) || []).length, batches[i].length, "batch emits exactly its aliases");
  }
  assert.equal(batches.reduce((sum, b) => sum + b.length, 0), selections.length, "every discovery alias batched exactly once");
});
test("repository allowlist remains fixed", () => {
  assert.equal(assertAllowedRepository(GITHUB_REPOSITORY), GITHUB_REPOSITORY);
  assert.throws(() => assertAllowedRepository("other/repo"), (error) => error.code === "REPOSITORY_NOT_ALLOWED");
});
test("checks pass", () => assert.equal(normalizeStatusCheckRollup(rollup("SUCCESS")).state, "pass"));
test("checks fail", () => assert.equal(normalizeStatusCheckRollup(rollup("FAILURE")).state, "fail"));
test("checks pending", () => assert.equal(normalizeStatusCheckRollup(rollup("PENDING")).state, "pending"));
test("checks unavailable", () => assert.equal(normalizeStatusCheckRollup(null).state, "unavailable"));
test("rollup aggregate failure overrides first 100 successful contexts", () => {
  const successNodes = Array.from({ length: 100 }, () => ({ __typename: "CheckRun", status: "COMPLETED", conclusion: "SUCCESS" }));
  const checks = normalizeStatusCheckRollup(rollup("FAILURE", { totalCount: 145, nodes: successNodes }));
  assert.deepEqual(checks, { state: "fail", source: "pr_head_rollup", total: 145, completed: 100, truncated: true });
});
test("rollup aggregate pending is authoritative", () => {
  const checks = normalizeStatusCheckRollup(rollup("PENDING", { totalCount: 145,
    nodes: Array.from({ length: 100 }, () => ({ __typename: "CheckRun", status: "COMPLETED", conclusion: "SUCCESS" })) }));
  assert.equal(checks.state, "pending");
  assert.equal(checks.total, 145);
  assert.equal(checks.truncated, true);
});
test("cold refresh issues one token exchange plus the bounded GraphQL plan and maps 40 Businesses", async () => {
  const budget = getRequestBudget();
  let requests = 0;
  const full = aggregatePayload();
  const fetchImpl = async (url, init) => {
    requests += 1;
    if (url.includes("access_tokens")) return jsonResponse({ token: "t1", expires_at: new Date(NOW + 120_000).toISOString() });
    return jsonResponse(routeGraphqlResponse(full, init));
  };
  const authProvider = createProvider(privateKeyPem, fetchImpl);
  const result = await serviceResult(new GitHubClient({ authProvider, fetchImpl }));
  assert.equal(result.status, 200);
  assert.equal(result.payload.ok, true);
  assert.equal(result.payload.businesses.length, 40);
  assert.equal(requests, budget.cold);
});
test("cached installation token makes cold status refresh skip the token exchange", async () => {
  const budget = getRequestBudget();
  let requests = 0;
  const full = aggregatePayload();
  const fetchImpl = async (url, init) => {
    requests += 1;
    if (url.includes("access_tokens")) return jsonResponse({ token: "cached", expires_at: new Date(NOW + 120_000).toISOString() });
    return jsonResponse(routeGraphqlResponse(full, init));
  };
  const authProvider = createProvider(privateKeyPem, fetchImpl);
  await authProvider.getToken();
  requests = 0;
  const result = await serviceResult(new GitHubClient({ authProvider, fetchImpl }));
  assert.equal(result.status, 200);
  assert.equal(requests, budget.cachedToken);
});
test("401 recovery refreshes the installation token at most once", async () => {
  const budget = getRequestBudget();
  let tokenExchanges = 0; let graphqlCalls = 0;
  const full = aggregatePayload();
  const fetchImpl = async (url, init) => {
    if (url.includes("access_tokens")) { tokenExchanges += 1; return jsonResponse({ token: `t${tokenExchanges}`, expires_at: new Date(NOW + 120_000).toISOString() }); }
    graphqlCalls += 1;
    if (graphqlCalls === 1) return jsonResponse({}, 401);
    return jsonResponse(routeGraphqlResponse(full, init));
  };
  const authProvider = createProvider(privateKeyPem, fetchImpl);
  const result = await serviceResult(new GitHubClient({ authProvider, fetchImpl }));
  assert.equal(result.status, 200);
  assert.equal(tokenExchanges, budget.maxTokenExchanges, "initial exchange + exactly one 401 refresh");
  assert.equal(tokenExchanges, 2);
  assert.equal(graphqlCalls, budget.cachedToken + 1, "one failed attempt then the full bounded plan");
});
test("403 is rate limited and never retried", async () => {
  let calls = 0;
  const authProvider = { async getToken() { return "t"; }, invalidate() { throw new Error("must not retry"); } };
  const client = new GitHubClient({ authProvider, fetchImpl: async () => { calls += 1; return jsonResponse({}, 403, { "Retry-After": "60" }); } });
  await assert.rejects(() => client.getStatusAggregation(), (error) => error.code === "UPSTREAM_RATE_LIMITED" && error.details.retryAfter === "60");
  assert.equal(calls, 1);
});
test("429 is rate limited and never retried", async () => {
  let calls = 0;
  const authProvider = { async getToken() { return "t"; }, invalidate() {} };
  const client = new GitHubClient({ authProvider, fetchImpl: async () => { calls += 1; return jsonResponse({}, 429, { "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "123" }); } });
  await assert.rejects(() => client.getStatusAggregation(), (error) => error.code === "UPSTREAM_RATE_LIMITED");
  assert.equal(calls, 1);
});
test("persistent GraphQL 401 after token refresh becomes GITHUB_GRAPHQL_AUTH_FAILED", async () => {
  let tokenExchanges = 0;
  const fetchImpl = async (url) => {
    if (url.includes("access_tokens")) { tokenExchanges += 1; return jsonResponse({ token: `t${tokenExchanges}`, expires_at: new Date(NOW + 120_000).toISOString() }); }
    return jsonResponse({}, 401);
  };
  const authProvider = createProvider(privateKeyPem, fetchImpl);
  const client = new GitHubClient({ authProvider, fetchImpl });
  await assert.rejects(() => client.getStatusAggregation(), (error) => error.code === "GITHUB_GRAPHQL_AUTH_FAILED");
  assert.equal(tokenExchanges, 2);
});
test("missing credentials has diagnostic header and diagnosticCode", async () => {
  const response = await handleGitHubStatusRequest({ request: new Request("https://x/api/github-status"), env: { GITHUB_APP_ID: "partial" } });
  assert.equal(response.status, 503);
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), "CONFIGURATION_MISSING");
  const body = await response.json();
  assert.equal(body.error.diagnosticCode, "CONFIGURATION_MISSING");
});
test("missing KV cache has diagnostic header and diagnosticCode", async () => {
  const response = await handleGitHubStatusRequest({ request: new Request("https://x/api/github-status"), env: envWithCredentials() });
  assert.equal(response.status, 503);
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), "CACHE_CONFIGURATION_MISSING");
  const body = await response.json();
  assert.equal(body.error.diagnosticCode, "CACHE_CONFIGURATION_MISSING");
});
test("HEAD returns diagnostic header without body", async () => {
  const response = await handleGitHubStatusRequest({ request: new Request("https://x/api/github-status", { method: "HEAD" }), env: { GITHUB_APP_ID: "x" } });
  assert.equal(response.status, 503);
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), "CONFIGURATION_MISSING");
  assert.equal(await response.text(), "");
});
test("successful response omits diagnostic header and has no diagnosticCode in body", async () => {
  const cache = new MemorySnapshotCache({ now: () => NOW });
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"), env: envWithCredentials(), client: mockAggregateClient(), cache, now: () => NOW
  });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), null);
  const body = await response.json();
  assert.equal(body.error, undefined);
  assert.equal(body.ok, true);
});
test("cache read failure returns CACHE_READ_FAILED diagnostic with header", async () => {
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"), env: envWithCredentials(), now: () => NOW,
    cache: { async get() { throw new Error("KV cache error"); }, async set() { return { persisted: true, errorCode: null }; }, setMemory() {} },
  });
  assert.equal(response.status, 502);
  const body = await response.json();
  assert.equal(body.error.code, "UPSTREAM_UNAVAILABLE");
  assert.equal(body.error.diagnosticCode, "CACHE_READ_FAILED");
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), "CACHE_READ_FAILED");
  assert.equal(JSON.stringify(body).includes("KV"), false);
  assert.equal(JSON.stringify(body).includes("Error"), false, "no raw error class in body");
});
test("cache read failure on HEAD returns CACHE_READ_FAILED header without body", async () => {
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status", { method: "HEAD" }), env: envWithCredentials(), now: () => NOW,
    cache: { async get() { throw new Error("fail"); }, async set() { return { persisted: true, errorCode: null }; }, setMemory() {} },
  });
  assert.equal(response.status, 502);
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), "CACHE_READ_FAILED");
  assert.equal(await response.text(), "");
});
test("stale GET response propagates diagnostic header from errors array", async () => {
  const snapshot = { ok: true, schemaVersion: 1, syncedAt: "old", stale: false, businesses: [{ number: 15 }] };
  const cache = new MemorySnapshotCache({ now: () => NOW - 181_000 });
  await cache.set(snapshot);
  cache.now = () => NOW;
  const error = new GitHubApiError("GITHUB_GRAPHQL_AUTH_FAILED", 401);
  const result = await serviceResult(mockAggregateClient(null, { throwError: error }), { cache, key: "stale-header" });
  assert.equal(result.cacheState, "stale");
  assert.equal(result.payload.stale, true);
  const lastErr = result.payload.errors.at(-1);
  assert.equal(lastErr.diagnosticCode, "GITHUB_GRAPHQL_AUTH_FAILED");
  // verify handler adds the header via the handler (via handleGitHubStatusRequest)
  const env = envWithCredentials();
  const handlerResponse = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"),
    env, now: () => NOW,
    cache, client: mockAggregateClient(null, { throwError: error }),
  });
  assert.equal(handlerResponse.status, 200);
  assert.equal(handlerResponse.headers.get("X-Portfolio-Cache"), "stale");
  assert.equal(handlerResponse.headers.get("X-Portfolio-Diagnostic-Code"), "GITHUB_GRAPHQL_AUTH_FAILED");
  const handlerBody = await handlerResponse.json();
  assert.equal(handlerBody.stale, true);
  assert.equal(handlerBody.errors.at(-1).diagnosticCode, "GITHUB_GRAPHQL_AUTH_FAILED");
});
test("stale HEAD returns diagnostic header without body", async () => {
  const snapshot = { ok: true, schemaVersion: 1, syncedAt: "old", stale: false, businesses: [{ number: 15 }] };
  const cache = new MemorySnapshotCache({ now: () => NOW - 181_000 });
  await cache.set(snapshot);
  cache.now = () => NOW;
  const error = new GitHubApiError("GITHUB_GRAPHQL_AUTH_FAILED", 401);
  const env = envWithCredentials();
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status", { method: "HEAD" }),
    env, now: () => NOW,
    cache, client: mockAggregateClient(null, { throwError: error }),
  });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("X-Portfolio-Cache"), "stale");
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), "GITHUB_GRAPHQL_AUTH_FAILED");
  assert.equal(await response.text(), "");
});
test("invalid PKCS8 private key end-to-end produces PRIVATE_KEY_INVALID", async () => {
  const env = envWithCredentials({ GITHUB_APP_PRIVATE_KEY_PKCS8: "not-a-valid-key" });
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"), env, now: () => NOW,
    cache: new MemorySnapshotCache({ now: () => NOW }),
  });
  assert.equal(response.status, 502);
  const body = await response.json();
  assert.equal(body.error.code, "UPSTREAM_UNAVAILABLE");
  assert.equal(body.error.diagnosticCode, "PRIVATE_KEY_INVALID");
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), "PRIVATE_KEY_INVALID");
  assert.equal(JSON.stringify(body).includes("not-a-valid-key"), false, "raw key not leaked");
});
test("installation token exchange 401 end-to-end produces INSTALLATION_TOKEN_EXCHANGE_FAILED", async () => {
  let tokenExchangeAttempts = 0;
  const fetchImpl = async (url) => {
    if (url.includes("access_tokens")) {
      tokenExchangeAttempts += 1;
      return new Response('{"message":"Bad credentials"}', { status: 401, headers: { "Content-Type": "application/json" } });
    }
    return new Response('{}', { status: 200 });
  };
  const env = envWithCredentials({ GITHUB_APP_PRIVATE_KEY_PKCS8: privateKeyPem });
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"), env, now: () => NOW,
    cache: new MemorySnapshotCache({ now: () => NOW }),
    fetchImpl, cryptoImpl: webcrypto,
  });
  assert.equal(response.status, 502);
  const body = await response.json();
  assert.equal(body.error.code, "UPSTREAM_UNAVAILABLE");
  assert.equal(body.error.diagnosticCode, "INSTALLATION_TOKEN_EXCHANGE_FAILED");
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), "INSTALLATION_TOKEN_EXCHANGE_FAILED");
  assert.equal(tokenExchangeAttempts, 1);
  assert.equal(JSON.stringify(body).includes("Bad credentials"), false, "raw GitHub response not leaked");
});
test("end-to-end diagnostic leakage: no raw GitHub body, App ID, installation ID, key, JWT, or token in response", async () => {
  // Invalid key path — verify no App ID or installation ID leak
  const env = envWithCredentials({ GITHUB_APP_PRIVATE_KEY_PKCS8: "bad" });
  const r1 = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"), env, now: () => NOW,
    cache: new MemorySnapshotCache({ now: () => NOW }),
  });
  const t1 = JSON.stringify(await r1.json());
  for (const s of ["app-secret", "install-secret", "bad"]) {
    assert.equal(t1.includes(s), false, `secret ${s} not leaked via invalid key path`);
  }
  // 401 exchange path
  let calls = 0;
  const fetchImpl = async (url) => {
    if (url.includes("access_tokens")) { calls += 1; return new Response('{"message":"nope"}', { status: 401, headers: { "Content-Type": "application/json" } }); }
    return new Response('{}', { status: 200 });
  };
  const r2 = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"), env: envWithCredentials({ GITHUB_APP_PRIVATE_KEY_PKCS8: privateKeyPem }),
    now: () => NOW, cache: new MemorySnapshotCache({ now: () => NOW }), fetchImpl, cryptoImpl: webcrypto,
  });
  const t2 = JSON.stringify(await r2.json());
  for (const s of ["app-secret", "install-secret", "nope"]) {
    assert.equal(t2.includes(s), false, `no ${s} in 401 exchange response`);
  }
});
test("RuntimeSnapshotCache KV read failure produces CACHE_READ_FAILED (production path)", async () => {
  const throwingKv = {
    async get() { throw new Error("KV backend unreachable"); },
    async put() {},
  };
  const env = envWithCredentials({ GITHUB_STATUS_SNAPSHOT_KV: throwingKv });
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"), env, now: () => NOW,
  });
  assert.equal(response.status, 502);
  const body = await response.json();
  assert.equal(body.error.code, "UPSTREAM_UNAVAILABLE");
  assert.equal(body.error.diagnosticCode, "CACHE_READ_FAILED");
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), "CACHE_READ_FAILED");
  assert.equal(JSON.stringify(body).includes("KV"), false, "raw KV binding name not leaked");
  assert.equal(JSON.stringify(body).includes("Error"), false, "no raw Error class name");
  assert.equal(JSON.stringify(body).includes("unreachable"), false, "raw KV error message not leaked");
});
test("RuntimeSnapshotCache KV read failure on HEAD has header but no body", async () => {
  const throwingKv = {
    async get() { throw new Error("fail"); },
    async put() {},
  };
  const env = envWithCredentials({ GITHUB_STATUS_SNAPSHOT_KV: throwingKv });
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status", { method: "HEAD" }), env, now: () => NOW,
  });
  assert.equal(response.status, 502);
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), "CACHE_READ_FAILED");
  assert.equal(await response.text(), "");
});
test("validDiagnosticCode rejects arbitrary string, newlines, and raw messages", async () => {
  assert.equal(validDiagnosticCode("GITHUB_GRAPHQL_RATE_LIMITED"), "GITHUB_GRAPHQL_RATE_LIMITED");
  assert.equal(validDiagnosticCode("UNKNOWN_INTERNAL"), "UNKNOWN_INTERNAL");
  assert.equal(validDiagnosticCode("random"), "UNKNOWN_INTERNAL");
  assert.equal(validDiagnosticCode(""), "UNKNOWN_INTERNAL");
  assert.equal(validDiagnosticCode("INSTALLATION_TOKEN_EXCHANGE_FAILED\n"), "UNKNOWN_INTERNAL");
  assert.equal(validDiagnosticCode("INSTALLATION_TOKEN_EXCHANGE_FAILED\r\n"), "UNKNOWN_INTERNAL");
  assert.equal(validDiagnosticCode(null), "UNKNOWN_INTERNAL");
  assert.equal(validDiagnosticCode(undefined), "UNKNOWN_INTERNAL");
  assert.equal(validDiagnosticCode(123), "UNKNOWN_INTERNAL");
  assert.equal(validDiagnosticCode("Bad credentials"), "UNKNOWN_INTERNAL");
  assert.equal(validDiagnosticCode("<html>error</html>"), "UNKNOWN_INTERNAL");
});
test("multiple stale errors select last diagnostic code deterministically (last wins)", async () => {
  const snapshot = {
    ok: true, schemaVersion: 1, syncedAt: "old", stale: false, businesses: [{ number: 15 }],
    errors: [{ code: "UPSTREAM_RATE_LIMITED", diagnosticCode: "GITHUB_GRAPHQL_RATE_LIMITED" }],
  };
  const cache = new MemorySnapshotCache({ now: () => NOW - 181_000 });
  await cache.set(snapshot);
  cache.now = () => NOW;
  const error = new GitHubApiError("GITHUB_GRAPHQL_AUTH_FAILED", 401);
  const result = await serviceResult(mockAggregateClient(null, { throwError: error }), { cache, key: "multi-error-last-wins" });
  assert.equal(result.cacheState, "stale");
  assert.equal(result.payload.errors.length, 2, "snapshot error + new error");
  assert.equal(result.payload.errors[0].diagnosticCode, "GITHUB_GRAPHQL_RATE_LIMITED", "first error preserved");
  assert.equal(result.payload.errors[1].diagnosticCode, "GITHUB_GRAPHQL_AUTH_FAILED", "last is the new error");
  // handler must propagate the last diagnostic
  const env = envWithCredentials();
  const handlerResponse = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"),
    env, now: () => NOW,
    cache, client: mockAggregateClient(null, { throwError: error }),
  });
  assert.equal(handlerResponse.status, 200);
  assert.equal(handlerResponse.headers.get("X-Portfolio-Diagnostic-Code"), "GITHUB_GRAPHQL_AUTH_FAILED", "last diagnostic wins");
});
