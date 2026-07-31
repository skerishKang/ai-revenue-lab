import test from "node:test";
import assert from "node:assert/strict";
import { bindFetchImpl } from "../../functions/_lib/runtime-fetch.js";
import { GitHubClient } from "../../functions/_lib/github-client.js";
import { MemorySnapshotCache } from "../../functions/_lib/cache.js";
import { handleGitHubStatusRequest } from "../../functions/api/github-status.js";
import {
  NOW, BUSINESS_GITHUB_MAP, GITHUB_REPOSITORY, aggregatePayload, createProvider, envWithCredentials,
  generatePrivateKeyPem, jsonResponse, webcrypto, routeGraphqlResponse
} from "./fixtures.mjs";

const MAPPED_BUSINESS_COUNT = BUSINESS_GITHUB_MAP.filter((m) => m.repository === GITHUB_REPOSITORY).length;

let privateKeyPem;
test.before(async () => { privateKeyPem = await generatePrivateKeyPem(); });

const RAW_LEAK_MARKERS = [
  "ECONNREFUSED", "network unreachable", "fetch failed", "Illegal invocation", "secret-data",
  "secret-token", "app-secret", "install-secret", "private-secret", "Bad credentials",
  "api.github.com", "Authorization", "Bearer", "stack",
];
function assertNoRawLeakage(text) {
  for (const marker of RAW_LEAK_MARKERS) {
    assert.equal(text.includes(marker), false, `raw runtime detail not leaked: ${marker}`);
  }
  assert.equal(/\beyJ[A-Za-z0-9_-]{10,}/.test(text), false, "no JWT-like token in body");
}

function receiverStrictFetch(behaviour) {
  return function (...args) {
    if (this !== globalThis) throw new TypeError("Illegal invocation");
    return behaviour(...args);
  };
}

function tokenOk() {
  return jsonResponse({ token: "t", expires_at: new Date(NOW + 120_000).toISOString() });
}

test("bindFetchImpl invokes the implementation with the globalThis receiver", () => {
  let seen = "unset";
  const bound = bindFetchImpl(function (...args) { seen = this; return "ok"; });
  assert.equal(bound("u", {}), "ok");
  assert.equal(seen, globalThis);
});

test("bindFetchImpl forwards every argument in order", () => {
  let got;
  const bound = bindFetchImpl(function (...args) { got = args; return 1; });
  bound("url", { method: "POST" }, "extra");
  assert.deepEqual(got, ["url", { method: "POST" }, "extra"]);
});

test("bindFetchImpl keeps injected mock fetch working", async () => {
  const bound = bindFetchImpl(async (url) => jsonResponse({ url }));
  assert.equal((await (await bound("https://x")).json()).url, "https://x");
});

test("bindFetchImpl rejects a non-function implementation with TypeError", () => {
  assert.throws(() => bindFetchImpl(null), TypeError);
  assert.throws(() => bindFetchImpl("fetch"), TypeError);
  assert.throws(() => bindFetchImpl({}), TypeError);
});

test("binding corrects a receiver-strict implementation that rejects instance receivers", () => {
  const strict = receiverStrictFetch(() => "called");
  assert.throws(() => strict(), /Illegal invocation/);
  assert.equal(bindFetchImpl(strict)(), "called");
});

test("receiver-strict runtime fetch succeeds through InstallationTokenProvider", async () => {
  const strict = receiverStrictFetch(async (url) => {
    if (url.includes("access_tokens")) return jsonResponse({ token: "rt", expires_at: new Date(NOW + 120_000).toISOString() });
    return jsonResponse({});
  });
  const provider = createProvider(privateKeyPem, strict);
  assert.equal(await provider.getToken(), "rt");
});

test("receiver-strict runtime fetch succeeds through GitHubClient", async () => {
  const full = aggregatePayload();
  const strict = receiverStrictFetch(async (url, init) => {
    if (url.includes("access_tokens")) return tokenOk();
    return jsonResponse(routeGraphqlResponse(full, init));
  });
  const authProvider = createProvider(privateKeyPem, strict);
  const client = new GitHubClient({ authProvider, fetchImpl: strict });
  const aggregate = await client.getStatusAggregation();
  assert.equal(aggregate.data.repository.nameWithOwner, GITHUB_REPOSITORY);
});

test("receiver-strict runtime fetch end-to-end returns 200 with all mapped businesses", async () => {
  const full = aggregatePayload();
  const strict = receiverStrictFetch(async (url, init) => {
    if (url.includes("access_tokens")) return tokenOk();
    return jsonResponse(routeGraphqlResponse(full, init));
  });
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"),
    env: envWithCredentials({ GITHUB_APP_PRIVATE_KEY_PKCS8: privateKeyPem }), now: () => NOW,
    cache: new MemorySnapshotCache({ now: () => NOW }), fetchImpl: strict, cryptoImpl: webcrypto,
  });
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.ok, true);
  assert.equal(body.schemaVersion, 2);
  assert.equal(body.stale, false);
  assert.equal(body.businesses.length, BUSINESS_GITHUB_MAP.length);
  const connected = body.businesses.filter((b) => b.repository).length;
  const unmapped = body.businesses.filter((b) => b.connectionState === "unmapped").length;
  assert.equal(connected, MAPPED_BUSINESS_COUNT);
  assert.equal(unmapped, BUSINESS_GITHUB_MAP.length - MAPPED_BUSINESS_COUNT);
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), null);
});

test("receiver-strict transport failure still classifies without raw leakage", async () => {
  const strict = receiverStrictFetch(async (url) => {
    if (url.includes("access_tokens")) return tokenOk();
    throw new TypeError("Illegal invocation secret-token");
  });
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"),
    env: envWithCredentials({ GITHUB_APP_PRIVATE_KEY_PKCS8: privateKeyPem }), now: () => NOW,
    cache: new MemorySnapshotCache({ now: () => NOW }), fetchImpl: strict, cryptoImpl: webcrypto,
  });
  assert.equal(response.status, 502);
  const body = await response.json();
  assert.equal(body.error.code, "UPSTREAM_UNAVAILABLE");
  assert.equal(body.error.diagnosticCode, "GITHUB_GRAPHQL_TRANSPORT_FAILED");
  assertNoRawLeakage(JSON.stringify(body));
});
