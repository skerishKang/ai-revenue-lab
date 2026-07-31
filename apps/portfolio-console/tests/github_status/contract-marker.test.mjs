import test from "node:test";
import assert from "node:assert/strict";
import { GitHubApiError } from "../../functions/_lib/github-client.js";
import { MemorySnapshotCache } from "../../functions/_lib/cache.js";
import { handleGitHubStatusRequest } from "../../functions/api/github-status.js";
import {
  NOW, aggregatePayload, envWithCredentials, mockAggregateClient, serviceResult, webcrypto, generatePrivateKeyPem
} from "./fixtures.mjs";

const CONTRACT = "github-status-diagnostics-v1";
const HEADER = "X-Portfolio-Function-Contract";

function assertContract(response) {
  assert.equal(response.headers.get(HEADER), CONTRACT, `${HEADER} must be ${CONTRACT}`);
}

test("contract: success 200 has contract header, no diagnostic header, body preserved", async () => {
  const cache = new MemorySnapshotCache({ now: () => NOW });
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"),
    env: envWithCredentials(), client: mockAggregateClient(), cache, now: () => NOW,
  });
  assert.equal(response.status, 200);
  assertContract(response);
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), null);
  const body = await response.json();
  assert.equal(body.ok, true);
  assert.equal(body.schemaVersion, 2);
  assert.ok(Array.isArray(body.businesses));
});

test("contract: missing credentials 503 has contract header and CONFIGURATION_MISSING", async () => {
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"), env: { GITHUB_APP_ID: "partial" },
  });
  assert.equal(response.status, 503);
  assertContract(response);
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), "CONFIGURATION_MISSING");
  const body = await response.json();
  assert.equal(body.error.code, "CONFIGURATION_MISSING");
  assert.equal(body.error.diagnosticCode, "CONFIGURATION_MISSING");
});

test("contract: missing KV binding 503 has contract header and CACHE_CONFIGURATION_MISSING", async () => {
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"), env: envWithCredentials(),
  });
  assert.equal(response.status, 503);
  assertContract(response);
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), "CACHE_CONFIGURATION_MISSING");
  const body = await response.json();
  assert.equal(body.error.code, "CACHE_CONFIGURATION_MISSING");
  assert.equal(body.error.diagnosticCode, "CACHE_CONFIGURATION_MISSING");
});

test("contract: upstream 502 has contract header, diagnosticCode, and header-body parity", async () => {
  const error = new GitHubApiError("GITHUB_RESPONSE_INVALID", 502);
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"),
    env: envWithCredentials(), now: () => NOW,
    cache: new MemorySnapshotCache({ now: () => NOW }),
    client: mockAggregateClient(null, { throwError: error }),
  });
  assert.equal(response.status, 502);
  assertContract(response);
  const body = await response.json();
  assert.equal(body.error.code, "UPSTREAM_UNAVAILABLE");
  assert.ok(body.error.diagnosticCode, "diagnosticCode present");
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), body.error.diagnosticCode);
});

test("contract: cache read failure 502 has contract header and CACHE_READ_FAILED", async () => {
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"), env: envWithCredentials(), now: () => NOW,
    cache: { async get() { throw new Error("KV down"); }, async set() { return { persisted: true, errorCode: null }; }, setMemory() {} },
  });
  assert.equal(response.status, 502);
  assertContract(response);
  const body = await response.json();
  assert.equal(body.error.diagnosticCode, "CACHE_READ_FAILED");
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), "CACHE_READ_FAILED");
  assert.equal(JSON.stringify(body).includes("KV down"), false);
});

test("contract: stale 200 has contract header, X-Portfolio-Cache stale, and diagnostic header", async () => {
  const snapshot = { ok: true, schemaVersion: 1, syncedAt: "old", stale: false, businesses: [{ number: 15 }] };
  const cache = new MemorySnapshotCache({ now: () => NOW - 181_000 });
  await cache.set(snapshot);
  cache.now = () => NOW;
  const error = new GitHubApiError("GITHUB_GRAPHQL_AUTH_FAILED", 401);
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"),
    env: envWithCredentials(), now: () => NOW,
    cache, client: mockAggregateClient(null, { throwError: error }),
  });
  assert.equal(response.status, 200);
  assertContract(response);
  assert.equal(response.headers.get("X-Portfolio-Cache"), "stale");
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), "GITHUB_GRAPHQL_AUTH_FAILED");
  const body = await response.json();
  assert.equal(body.stale, true);
});

test("contract: HEAD success and failure have contract header, empty body, matching status", async () => {
  const headOk = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status", { method: "HEAD" }),
    env: envWithCredentials(), client: mockAggregateClient(),
    cache: new MemorySnapshotCache({ now: () => NOW }), now: () => NOW,
  });
  assert.equal(headOk.status, 200);
  assertContract(headOk);
  assert.equal(await headOk.text(), "");

  const headFail = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status", { method: "HEAD" }), env: {},
  });
  assert.equal(headFail.status, 503);
  assertContract(headFail);
  assert.equal(headFail.headers.get("X-Portfolio-Diagnostic-Code"), "CONFIGURATION_MISSING");
  assert.equal(await headFail.text(), "");
});

test("contract: POST 405 has contract header and Allow", async () => {
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status", { method: "POST" }), env: {},
  });
  assert.equal(response.status, 405);
  assertContract(response);
  assert.equal(response.headers.get("Allow"), "GET, HEAD");
  const body = await response.json();
  assert.equal(body.error.code, "METHOD_NOT_ALLOWED");
});

test("contract: invalid query 400 has contract header and INVALID_QUERY", async () => {
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status?x=1"), env: {},
  });
  assert.equal(response.status, 400);
  assertContract(response);
  const body = await response.json();
  assert.equal(body.error.code, "INVALID_QUERY");
});

test("contract: header value is fixed literal with no newline or runtime reflection", async () => {
  const cache = new MemorySnapshotCache({ now: () => NOW });
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"),
    env: envWithCredentials(), client: mockAggregateClient(), cache, now: () => NOW,
  });
  const value = response.headers.get(HEADER);
  assert.equal(value, CONTRACT);
  assert.equal(value.includes("\n"), false);
  assert.equal(value.includes("\r"), false);
  assert.equal(value.length, CONTRACT.length);
  assert.match(value, /^github-status-diagnostics-v1$/);
});

test("contract: no secret or runtime leakage in body or headers", async () => {
  const privateKeyPem = await generatePrivateKeyPem();
  const scenarios = [
    {
      name: "success",
      opts: { request: new Request("https://x/api/github-status"), env: envWithCredentials(), client: mockAggregateClient(), cache: new MemorySnapshotCache({ now: () => NOW }), now: () => NOW },
    },
    {
      name: "config-missing",
      opts: { request: new Request("https://x/api/github-status"), env: { GITHUB_APP_ID: "app-secret" } },
    },
    {
      name: "upstream-502",
      opts: { request: new Request("https://x/api/github-status"), env: envWithCredentials(), now: () => NOW, cache: new MemorySnapshotCache({ now: () => NOW }), client: mockAggregateClient(null, { throwError: new Error("raw <html>secret</html>") }) },
    },
    {
      name: "invalid-key",
      opts: { request: new Request("https://x/api/github-status"), env: envWithCredentials({ GITHUB_APP_PRIVATE_KEY_PKCS8: "bad-key" }), now: () => NOW, cache: new MemorySnapshotCache({ now: () => NOW }) },
    },
  ];
  const forbidden = [
    "app-secret", "install-secret", "private-secret", "bad-key",
    "BEGIN PRIVATE KEY", "BEGIN RSA PRIVATE KEY",
    "Authorization", "Bearer ", "stack", "at Object",
    "<html>", "deployment", "account_id",
  ];
  for (const { name, opts } of scenarios) {
    const response = await handleGitHubStatusRequest(opts);
    const bodyText = await response.text();
    const headerBlob = [...response.headers.entries()].map(([k, v]) => `${k}: ${v}`).join("\n");
    const combined = bodyText + "\n" + headerBlob;
    for (const f of forbidden) {
      assert.equal(combined.includes(f), false, `${name}: must not contain "${f}"`);
    }
  }
});
