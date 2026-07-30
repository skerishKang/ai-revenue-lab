import test from "node:test";
import assert from "node:assert/strict";
import { GitHubClient, GitHubApiError } from "../../functions/_lib/github-client.js";
import { MemorySnapshotCache } from "../../functions/_lib/cache.js";
import { handleGitHubStatusRequest } from "../../functions/api/github-status.js";
import {
  NOW, aggregatePayload, createProvider, envWithCredentials, generatePrivateKeyPem,
  jsonResponse, mockAggregateClient, serviceResult, webcrypto
} from "./fixtures.mjs";

let privateKeyPem;
test.before(async () => { privateKeyPem = await generatePrivateKeyPem(); });

const CONTRACT = "github-status-diagnostics-v1";

const RAW_LEAK_MARKERS = [
  "ECONNREFUSED", "network unreachable", "fetch failed", "merge exploded", "secret-data",
  "secret-token", "app-secret", "install-secret", "private-secret", "Bad credentials",
  "api.github.com", "Authorization", "Bearer", "stack",
];
function assertNoRawLeakage(text) {
  for (const marker of RAW_LEAK_MARKERS) {
    assert.equal(text.includes(marker), false, `raw runtime detail not leaked: ${marker}`);
  }
  assert.equal(/\beyJ[A-Za-z0-9_-]{10,}/.test(text), false, "no JWT-like token in body");
}

function tokenOk() {
  return jsonResponse({ token: "t", expires_at: new Date(NOW + 120_000).toISOString() });
}

test("installation-token fetch reject → INSTALLATION_TOKEN_REQUEST_FAILED (GET)", async () => {
  const fetchImpl = async (url) => {
    if (url.includes("access_tokens")) throw new TypeError("fetch failed: ECONNREFUSED secret-token");
    return jsonResponse({});
  };
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"),
    env: envWithCredentials({ GITHUB_APP_PRIVATE_KEY_PKCS8: privateKeyPem }), now: () => NOW,
    cache: new MemorySnapshotCache({ now: () => NOW }), fetchImpl, cryptoImpl: webcrypto,
  });
  assert.equal(response.status, 502);
  assert.equal(response.headers.get("X-Portfolio-Function-Contract"), CONTRACT);
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), "INSTALLATION_TOKEN_REQUEST_FAILED");
  const body = await response.json();
  assert.equal(body.error.code, "UPSTREAM_UNAVAILABLE");
  assert.equal(body.error.diagnosticCode, "INSTALLATION_TOKEN_REQUEST_FAILED");
  assertNoRawLeakage(JSON.stringify(body));
});

test("installation-token fetch reject HEAD parity (header present, empty body)", async () => {
  const fetchImpl = async (url) => {
    if (url.includes("access_tokens")) throw new TypeError("ECONNREFUSED");
    return jsonResponse({});
  };
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status", { method: "HEAD" }),
    env: envWithCredentials({ GITHUB_APP_PRIVATE_KEY_PKCS8: privateKeyPem }), now: () => NOW,
    cache: new MemorySnapshotCache({ now: () => NOW }), fetchImpl, cryptoImpl: webcrypto,
  });
  assert.equal(response.status, 502);
  assert.equal(response.headers.get("X-Portfolio-Function-Contract"), CONTRACT);
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), "INSTALLATION_TOKEN_REQUEST_FAILED");
  assert.equal(await response.text(), "");
});

test("GraphQL fetch reject → GITHUB_GRAPHQL_TRANSPORT_FAILED with no retry loop (GET)", async () => {
  let graphqlCalls = 0;
  const fetchImpl = async (url) => {
    if (url.includes("access_tokens")) return tokenOk();
    graphqlCalls += 1;
    throw new TypeError("network unreachable https://api.github.com/graphql");
  };
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"),
    env: envWithCredentials({ GITHUB_APP_PRIVATE_KEY_PKCS8: privateKeyPem }), now: () => NOW,
    cache: new MemorySnapshotCache({ now: () => NOW }), fetchImpl, cryptoImpl: webcrypto,
  });
  assert.equal(response.status, 502);
  assert.equal(response.headers.get("X-Portfolio-Function-Contract"), CONTRACT);
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), "GITHUB_GRAPHQL_TRANSPORT_FAILED");
  const body = await response.json();
  assert.equal(body.error.code, "UPSTREAM_UNAVAILABLE");
  assert.equal(body.error.diagnosticCode, "GITHUB_GRAPHQL_TRANSPORT_FAILED");
  assert.equal(graphqlCalls, 1, "transport failure must not be retried");
  assertNoRawLeakage(JSON.stringify(body));
});

test("GraphQL fetch reject HEAD parity", async () => {
  const fetchImpl = async (url) => {
    if (url.includes("access_tokens")) return tokenOk();
    throw new TypeError("network unreachable");
  };
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status", { method: "HEAD" }),
    env: envWithCredentials({ GITHUB_APP_PRIVATE_KEY_PKCS8: privateKeyPem }), now: () => NOW,
    cache: new MemorySnapshotCache({ now: () => NOW }), fetchImpl, cryptoImpl: webcrypto,
  });
  assert.equal(response.status, 502);
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), "GITHUB_GRAPHQL_TRANSPORT_FAILED");
  assert.equal(await response.text(), "");
});

test("merge/payload throw after successful GraphQL → GITHUB_DATA_PROCESSING_FAILED", async () => {
  const payload = aggregatePayload();
  Object.defineProperty(payload.data.repository, "nameWithOwner", {
    get() { throw new Error("merge exploded secret-data"); },
  });
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"), env: envWithCredentials(), now: () => NOW,
    cache: new MemorySnapshotCache({ now: () => NOW }), client: mockAggregateClient(payload),
  });
  assert.equal(response.status, 502);
  assert.equal(response.headers.get("X-Portfolio-Function-Contract"), CONTRACT);
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), "GITHUB_DATA_PROCESSING_FAILED");
  const body = await response.json();
  assert.equal(body.error.code, "UPSTREAM_UNAVAILABLE");
  assert.equal(body.error.diagnosticCode, "GITHUB_DATA_PROCESSING_FAILED");
  assertNoRawLeakage(JSON.stringify(body));
});

test("classified GitHubApiError raised during processing is rethrown, not overwritten", async () => {
  const result = await serviceResult(mockAggregateClient({ data: { repository: null }, errors: [] }));
  assert.equal(result.status, 502);
  assert.equal(result.payload.error.code, "UPSTREAM_UNAVAILABLE");
  assert.equal(result.payload.error.diagnosticCode, "GITHUB_GRAPHQL_DATA_UNAVAILABLE");
});

test("HTTP 401 token exchange still → INSTALLATION_TOKEN_EXCHANGE_FAILED (preserved)", async () => {
  const fetchImpl = async (url) => {
    if (url.includes("access_tokens")) return new Response('{"message":"Bad credentials"}', { status: 401, headers: { "Content-Type": "application/json" } });
    return jsonResponse({});
  };
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"),
    env: envWithCredentials({ GITHUB_APP_PRIVATE_KEY_PKCS8: privateKeyPem }), now: () => NOW,
    cache: new MemorySnapshotCache({ now: () => NOW }), fetchImpl, cryptoImpl: webcrypto,
  });
  assert.equal(response.status, 502);
  const body = await response.json();
  assert.equal(body.error.diagnosticCode, "INSTALLATION_TOKEN_EXCHANGE_FAILED");
  assert.equal(JSON.stringify(body).includes("Bad credentials"), false);
});

test("persistent GraphQL 401 still → GITHUB_GRAPHQL_AUTH_FAILED (preserved)", async () => {
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

test("invalid GraphQL JSON still → GITHUB_GRAPHQL_RESPONSE_INVALID (preserved)", async () => {
  const fetchImpl = async (url) => {
    if (url.includes("access_tokens")) return tokenOk();
    return new Response("not-json", { status: 200, headers: { "Content-Type": "application/json" } });
  };
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"),
    env: envWithCredentials({ GITHUB_APP_PRIVATE_KEY_PKCS8: privateKeyPem }), now: () => NOW,
    cache: new MemorySnapshotCache({ now: () => NOW }), fetchImpl, cryptoImpl: webcrypto,
  });
  assert.equal(response.status, 502);
  const body = await response.json();
  assert.equal(body.error.diagnosticCode, "GITHUB_GRAPHQL_RESPONSE_INVALID");
});

test("rate limit still → GITHUB_GRAPHQL_RATE_LIMITED 503 (preserved)", async () => {
  const fetchImpl = async (url) => {
    if (url.includes("access_tokens")) return tokenOk();
    return jsonResponse({}, 429, { "X-RateLimit-Remaining": "0" });
  };
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"),
    env: envWithCredentials({ GITHUB_APP_PRIVATE_KEY_PKCS8: privateKeyPem }), now: () => NOW,
    cache: new MemorySnapshotCache({ now: () => NOW }), fetchImpl, cryptoImpl: webcrypto,
  });
  assert.equal(response.status, 503);
  const body = await response.json();
  assert.equal(body.error.code, "UPSTREAM_RATE_LIMITED");
  assert.equal(body.error.diagnosticCode, "GITHUB_GRAPHQL_RATE_LIMITED");
});

test("cache read failure still → CACHE_READ_FAILED (preserved)", async () => {
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"), env: envWithCredentials(), now: () => NOW,
    cache: { async get() { throw new Error("KV down"); }, async set() { return { persisted: true }; }, setMemory() {} },
  });
  assert.equal(response.status, 502);
  const body = await response.json();
  assert.equal(body.error.diagnosticCode, "CACHE_READ_FAILED");
});

test("contract header present on every new runtime-stage failure response", async () => {
  const cases = [
    { diag: "INSTALLATION_TOKEN_REQUEST_FAILED", fetchImpl: async (u) => { if (u.includes("access_tokens")) throw new TypeError("x"); return jsonResponse({}); } },
    { diag: "GITHUB_GRAPHQL_TRANSPORT_FAILED", fetchImpl: async (u) => (u.includes("access_tokens") ? tokenOk() : Promise.reject(new TypeError("x"))) },
  ];
  for (const c of cases) {
    const response = await handleGitHubStatusRequest({
      request: new Request("https://x/api/github-status"),
      env: envWithCredentials({ GITHUB_APP_PRIVATE_KEY_PKCS8: privateKeyPem }), now: () => NOW,
      cache: new MemorySnapshotCache({ now: () => NOW }), fetchImpl: c.fetchImpl, cryptoImpl: webcrypto,
    });
    assert.equal(response.headers.get("X-Portfolio-Function-Contract"), CONTRACT, c.diag);
    assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), c.diag);
  }
});

test("no JWT/token/key/IDs/stack/raw-message across all new failure paths", async () => {
  const responses = [];
  responses.push(await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"),
    env: envWithCredentials({ GITHUB_APP_PRIVATE_KEY_PKCS8: privateKeyPem }), now: () => NOW,
    cache: new MemorySnapshotCache({ now: () => NOW }), cryptoImpl: webcrypto,
    fetchImpl: async (u) => { if (u.includes("access_tokens")) throw new TypeError("ECONNREFUSED secret-token"); return jsonResponse({}); },
  }));
  responses.push(await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"),
    env: envWithCredentials({ GITHUB_APP_PRIVATE_KEY_PKCS8: privateKeyPem }), now: () => NOW,
    cache: new MemorySnapshotCache({ now: () => NOW }), cryptoImpl: webcrypto,
    fetchImpl: async (u) => (u.includes("access_tokens") ? tokenOk() : Promise.reject(new TypeError("network unreachable"))),
  }));
  const payload = aggregatePayload();
  Object.defineProperty(payload.data.repository, "nameWithOwner", { get() { throw new Error("merge exploded secret-data"); } });
  responses.push(await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"), env: envWithCredentials(), now: () => NOW,
    cache: new MemorySnapshotCache({ now: () => NOW }), client: mockAggregateClient(payload),
  }));
  for (const response of responses) {
    assertNoRawLeakage(JSON.stringify(await response.json()));
  }
});
