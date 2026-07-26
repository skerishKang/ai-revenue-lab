import test from "node:test";
import assert from "node:assert/strict";
import { createGitHubAppJwt } from "../../functions/_lib/github-app-auth.js";
import { GitHubClient, STATUS_QUERY, normalizeStatusCheckRollup } from "../../functions/_lib/github-client.js";
import { assertAllowedRepository } from "../../functions/_lib/business-github-map.js";
import { handleGitHubStatusRequest } from "../../functions/api/github-status.js";
import {
  BUSINESS_GITHUB_MAP, GITHUB_REPOSITORY, NOW, aggregatePayload, createProvider, decodeJwtPart,
  delay, envWithCredentials, generatePrivateKeyPem, jsonResponse, rollup, serviceResult, webcrypto
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
test("fixed GraphQL query contains all mapped aliases", () => {
  assert.match(STATUS_QUERY, /query PortfolioGithubStatus/);
  for (const mapping of BUSINESS_GITHUB_MAP) {
    if (mapping.issueNumber) assert.match(STATUS_QUERY, new RegExp(`issue${mapping.issueNumber}: issue\\(number: ${mapping.issueNumber}\\)`));
    if (mapping.pullRequestNumber) assert.match(STATUS_QUERY, new RegExp(`pr${mapping.pullRequestNumber}: pullRequest\\(number: ${mapping.pullRequestNumber}\\)`));
  }
  assert.doesNotMatch(STATUS_QUERY, /\$repository|\$issue|\$pullRequest/);
});
test("repository allowlist remains fixed", () => {
  assert.equal(assertAllowedRepository(GITHUB_REPOSITORY), GITHUB_REPOSITORY);
  assert.throws(() => assertAllowedRepository("other/repo"), (error) => error.code === "REPOSITORY_NOT_ALLOWED");
});
test("checks pass", () => assert.equal(normalizeStatusCheckRollup(rollup("SUCCESS")).state, "pass"));
test("checks fail", () => assert.equal(normalizeStatusCheckRollup(rollup("FAILURE")).state, "fail"));
test("checks pending", () => assert.equal(normalizeStatusCheckRollup(rollup("PENDING")).state, "pending"));
test("checks unavailable", () => assert.equal(normalizeStatusCheckRollup(null).state, "unavailable"));
test("normal cold refresh uses exactly token exchange plus GraphQL", async () => {
  let requests = 0;
  const fetchImpl = async (url) => {
    requests += 1;
    if (url.includes("access_tokens")) return jsonResponse({ token: "t1", expires_at: new Date(NOW + 120_000).toISOString() });
    assert.equal(url, "https://api.github.com/graphql");
    return jsonResponse(aggregatePayload());
  };
  const authProvider = createProvider(privateKeyPem, fetchImpl);
  const result = await serviceResult(new GitHubClient({ authProvider, fetchImpl }));
  assert.equal(result.status, 200);
  assert.equal(requests, 2);
});
test("cached installation token makes cold status refresh one external request", async () => {
  let requests = 0;
  const fetchImpl = async (url) => {
    requests += 1;
    if (url.includes("access_tokens")) return jsonResponse({ token: "cached", expires_at: new Date(NOW + 120_000).toISOString() });
    return jsonResponse(aggregatePayload());
  };
  const authProvider = createProvider(privateKeyPem, fetchImpl);
  await authProvider.getToken();
  requests = 0;
  const result = await serviceResult(new GitHubClient({ authProvider, fetchImpl }));
  assert.equal(result.status, 200);
  assert.equal(requests, 1);
});
test("401 recovery has fixed request ceiling four", async () => {
  let requests = 0; let graphql = 0;
  const fetchImpl = async (url) => {
    requests += 1;
    if (url.includes("access_tokens")) return jsonResponse({ token: `t${requests}`, expires_at: new Date(NOW + 120_000).toISOString() });
    graphql += 1;
    return graphql === 1 ? jsonResponse({}, 401) : jsonResponse(aggregatePayload());
  };
  const authProvider = createProvider(privateKeyPem, fetchImpl);
  const result = await serviceResult(new GitHubClient({ authProvider, fetchImpl }));
  assert.equal(result.status, 200);
  assert.equal(requests, 4);
  assert.ok(requests <= 4);
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
