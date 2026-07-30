import test from "node:test";
import assert from "node:assert/strict";
import { InstallationTokenProvider, GitHubAuthError } from "../../functions/_lib/github-app-auth.js";
import { GitHubClient, GitHubApiError } from "../../functions/_lib/github-client.js";
import { MemorySnapshotCache } from "../../functions/_lib/cache.js";
import { createGitHubStatusService } from "../../functions/_lib/github-status-service.js";
import { buildIdentitySource } from "../../business-identity-data.js";
import { validDiagnosticCode } from "../../functions/_lib/response.js";
import { handleGitHubStatusRequest } from "../../functions/api/github-status.js";
import {
  OUTBOUND_DEADLINES, OutboundTimeoutError, createDeadlineRunner, createStageLogger,
} from "../../functions/_lib/outbound-deadline.js";
import {
  NOW, webcrypto, generatePrivateKeyPem, jsonResponse, aggregatePayload,
  envWithCredentials, mockAggregateClient, serviceResult,
} from "./fixtures.mjs";

const FAST = Object.freeze({
  installationTokenRequestMs: 20,
  installationTokenBodyMs: 20,
  graphqlRequestMs: 20,
  graphqlBodyMs: 20,
  totalSyncMs: 300,
  handlerBackstopMs: 600,
});

const never = () => new Promise(() => {});
const stallJsonResponse = (status = 200) => ({ ok: status >= 200 && status < 300, status, headers: new Headers(), json: never });

function trackingTimers() {
  const set = [];
  const cleared = [];
  return {
    set,
    cleared,
    setTimeout(fn, ms) { const id = setTimeout(fn, ms); set.push(id); return id; },
    clearTimeout(id) { cleared.push(id); clearTimeout(id); },
  };
}

let privateKeyPem;
test.before(async () => { privateKeyPem = await generatePrivateKeyPem(); });

function tokenProvider(fetchImpl, opts = {}) {
  return new InstallationTokenProvider({
    appId: "123", installationId: "456", privateKeyPkcs8: privateKeyPem,
    cryptoImpl: webcrypto, now: () => NOW, fetchImpl, timeouts: FAST, ...opts,
  });
}

function graphqlClient(fetchImpl, opts = {}) {
  const authProvider = { async getToken() { return "t"; }, invalidate() {} };
  return new GitHubClient({ authProvider, fetchImpl, timeouts: FAST, ...opts });
}

// ── deadline runner unit ──
test("runWithDeadline resolves a fast value and clears its timer", async () => {
  const timers = trackingTimers();
  const runner = createDeadlineRunner(timers);
  const value = await runner.runWithDeadline(Promise.resolve("ok"), 50, "x");
  assert.equal(value, "ok");
  assert.deepEqual(new Set(timers.set), new Set(timers.cleared));
});
test("runWithDeadline rejects with OutboundTimeoutError carrying the stage", async () => {
  const runner = createDeadlineRunner();
  await assert.rejects(() => runner.runWithDeadline(never(), 15, "sync"),
    (error) => error instanceof OutboundTimeoutError && error.stage === "sync");
});
test("fetchWithDeadline injects an AbortSignal into the request init", async () => {
  const runner = createDeadlineRunner();
  let seenSignal;
  await runner.fetchWithDeadline((url, init) => { seenSignal = init.signal; return Promise.resolve(new Response("{}")); },
    "https://example.test", { method: "POST" }, 100, "x");
  assert.ok(seenSignal, "signal passed to fetch");
  assert.equal(typeof seenSignal.aborted, "boolean");
});

// ── installation-token deadlines ──
test("never-resolving token fetch produces INSTALLATION_TOKEN_TIMEOUT", async () => {
  await assert.rejects(() => tokenProvider(never).getToken(),
    (error) => error instanceof GitHubAuthError && error.code === "INSTALLATION_TOKEN_TIMEOUT");
});
test("stalled token response body read produces INSTALLATION_TOKEN_TIMEOUT", async () => {
  await assert.rejects(() => tokenProvider(async () => stallJsonResponse(200)).getToken(),
    (error) => error.code === "INSTALLATION_TOKEN_TIMEOUT");
});
test("ordinary token fetch reject preserves INSTALLATION_TOKEN_REQUEST_FAILED", async () => {
  await assert.rejects(() => tokenProvider(async () => { throw new TypeError("network down"); }).getToken(),
    (error) => error.code === "INSTALLATION_TOKEN_REQUEST_FAILED");
});
test("token exchange 500 preserves INSTALLATION_TOKEN_EXCHANGE_FAILED", async () => {
  await assert.rejects(() => tokenProvider(async () => jsonResponse({}, 500)).getToken(),
    (error) => error.code === "INSTALLATION_TOKEN_EXCHANGE_FAILED");
});
test("token invalid JSON preserves INSTALLATION_TOKEN_RESPONSE_INVALID", async () => {
  await assert.rejects(() => tokenProvider(async () => new Response("not-json", { status: 200 })).getToken(),
    (error) => error.code === "INSTALLATION_TOKEN_RESPONSE_INVALID");
});

// ── GraphQL deadlines ──
test("never-resolving GraphQL fetch produces GITHUB_GRAPHQL_TIMEOUT", async () => {
  await assert.rejects(() => graphqlClient(never).getStatusAggregation(),
    (error) => error instanceof GitHubApiError && error.code === "GITHUB_GRAPHQL_TIMEOUT");
});
test("stalled GraphQL response body read produces GITHUB_GRAPHQL_TIMEOUT", async () => {
  await assert.rejects(() => graphqlClient(async () => stallJsonResponse(200)).getStatusAggregation(),
    (error) => error.code === "GITHUB_GRAPHQL_TIMEOUT");
});
test("ordinary GraphQL fetch reject preserves GITHUB_GRAPHQL_TRANSPORT_FAILED", async () => {
  await assert.rejects(() => graphqlClient(async () => { throw new TypeError("reset"); }).getStatusAggregation(),
    (error) => error.code === "GITHUB_GRAPHQL_TRANSPORT_FAILED");
});
test("GraphQL timeout does not retry (fetch called exactly once)", async () => {
  let calls = 0;
  const client = graphqlClient(() => { calls += 1; return never(); });
  await assert.rejects(() => client.getStatusAggregation(), (error) => error.code === "GITHUB_GRAPHQL_TIMEOUT");
  assert.equal(calls, 1);
});
test("GraphQL 403 rate-limit preserved with deadlines active", async () => {
  let calls = 0;
  const client = graphqlClient(async () => { calls += 1; return jsonResponse({}, 403, { "Retry-After": "60" }); });
  await assert.rejects(() => client.getStatusAggregation(), (error) => error.code === "UPSTREAM_RATE_LIMITED");
  assert.equal(calls, 1);
});
test("GraphQL invalid JSON preserved as GITHUB_RESPONSE_INVALID with deadlines active", async () => {
  await assert.rejects(() => graphqlClient(async () => new Response("<<not json>>", { status: 200 })).getStatusAggregation(),
    (error) => error.code === "GITHUB_RESPONSE_INVALID");
});

// ── timer cleanup ──
test("token timeout clears every timer it creates", async () => {
  const timers = trackingTimers();
  await assert.rejects(() => tokenProvider(never, { timers }).getToken(), (error) => error.code === "INSTALLATION_TOKEN_TIMEOUT");
  assert.deepEqual(new Set(timers.set), new Set(timers.cleared));
});
test("graphql success clears every timer it creates", async () => {
  const timers = trackingTimers();
  const client = graphqlClient(async () => jsonResponse(aggregatePayload()), { timers });
  await client.getStatusAggregation();
  assert.deepEqual(new Set(timers.set), new Set(timers.cleared));
});

// ── service total deadline + stale fallback ──
test("service total deadline bounds a hanging refresh and falls back to stale 200", async () => {
  const snapshot = { ok: true, schemaVersion: 1, syncedAt: "old", stale: false, businesses: [{ number: 15 }] };
  const cache = new MemorySnapshotCache({ now: () => NOW - 181_000 });
  await cache.set(snapshot);
  cache.now = () => NOW;
  const hangingClient = { getStatusAggregation: never };
  const service = createGitHubStatusService({
    client: hangingClient, cache, now: () => NOW, singleFlightKey: "total-deadline-stale",
    identitySource: buildIdentitySource(), timeouts: FAST,
  });
  const result = await service.getStatus();
  assert.equal(result.status, 200);
  assert.equal(result.cacheState, "stale");
  assert.equal(result.payload.stale, true);
  assert.equal(result.payload.errors.at(-1).diagnosticCode, "GITHUB_GRAPHQL_TIMEOUT");
});
test("timeout with stale cache preserves GraphQL timeout diagnostic (stale 200)", async () => {
  const snapshot = { ok: true, schemaVersion: 1, syncedAt: "old", stale: false, businesses: [{ number: 15 }] };
  const cache = new MemorySnapshotCache({ now: () => NOW - 181_000 });
  await cache.set(snapshot);
  cache.now = () => NOW;
  const error = new GitHubApiError("GITHUB_GRAPHQL_TIMEOUT", 504);
  const result = await serviceResult(mockAggregateClient(null, { throwError: error }), { cache, key: "stale-gql-timeout" });
  assert.equal(result.status, 200);
  assert.equal(result.cacheState, "stale");
  assert.equal(result.payload.errors.at(-1).diagnosticCode, "GITHUB_GRAPHQL_TIMEOUT");
});
test("timeout with stale cache preserves installation-token timeout diagnostic (stale 200)", async () => {
  const snapshot = { ok: true, schemaVersion: 1, syncedAt: "old", stale: false, businesses: [{ number: 15 }] };
  const cache = new MemorySnapshotCache({ now: () => NOW - 181_000 });
  await cache.set(snapshot);
  cache.now = () => NOW;
  const error = new GitHubAuthError("INSTALLATION_TOKEN_TIMEOUT", "GitHub App authentication failed.");
  const result = await serviceResult(mockAggregateClient(null, { throwError: error }), { cache, key: "stale-token-timeout" });
  assert.equal(result.status, 200);
  assert.equal(result.cacheState, "stale");
  assert.equal(result.payload.errors.at(-1).diagnosticCode, "INSTALLATION_TOKEN_TIMEOUT");
});
test("timeout without cache returns normalized 502 with timeout diagnostic", async () => {
  const error = new GitHubApiError("GITHUB_GRAPHQL_TIMEOUT", 504);
  const result = await serviceResult(mockAggregateClient(null, { throwError: error }), { key: "no-cache-timeout" });
  assert.equal(result.status, 502);
  assert.equal(result.cacheState, "unavailable");
  assert.equal(result.payload.error.diagnosticCode, "GITHUB_GRAPHQL_TIMEOUT");
  assert.equal(result.payload.schemaVersion, 2);
});

// ── end-to-end handler: bounded, normalized, contract header, no leakage ──
test("GET terminates within a deterministic deadline on a never-resolving upstream", async () => {
  const started = Date.now();
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"),
    env: envWithCredentials({ GITHUB_APP_PRIVATE_KEY_PKCS8: privateKeyPem }),
    now: () => NOW, cache: new MemorySnapshotCache({ now: () => NOW }),
    fetchImpl: never, cryptoImpl: webcrypto, timeouts: FAST,
  });
  const elapsed = Date.now() - started;
  assert.equal(response.status, 502);
  assert.ok(elapsed < FAST.handlerBackstopMs + 1500, `bounded (${elapsed}ms)`);
  assert.equal(response.headers.get("X-Portfolio-Function-Contract"), "github-status-diagnostics-v1");
  const body = await response.json();
  assert.equal(body.schemaVersion, 2);
  assert.equal(body.error.diagnosticCode, "INSTALLATION_TOKEN_TIMEOUT");
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), "INSTALLATION_TOKEN_TIMEOUT");
});
test("HEAD terminates within a deterministic deadline and keeps the contract header", async () => {
  const started = Date.now();
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status", { method: "HEAD" }),
    env: envWithCredentials({ GITHUB_APP_PRIVATE_KEY_PKCS8: privateKeyPem }),
    now: () => NOW, cache: new MemorySnapshotCache({ now: () => NOW }),
    fetchImpl: never, cryptoImpl: webcrypto, timeouts: FAST,
  });
  assert.ok(Date.now() - started < FAST.handlerBackstopMs + 1500);
  assert.equal(response.status, 502);
  assert.equal(response.headers.get("X-Portfolio-Function-Contract"), "github-status-diagnostics-v1");
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), "INSTALLATION_TOKEN_TIMEOUT");
  assert.equal(await response.text(), "");
});
test("GraphQL stall end-to-end falls back to stale 200 with timeout diagnostic header", async () => {
  const snapshot = { ok: true, schemaVersion: 1, syncedAt: "old", stale: false, businesses: [{ number: 15 }] };
  const cache = new MemorySnapshotCache({ now: () => NOW - 181_000 });
  await cache.set(snapshot);
  cache.now = () => NOW;
  const fetchImpl = async (url) => (url.includes("access_tokens")
    ? jsonResponse({ token: "t", expires_at: new Date(NOW + 120_000).toISOString() })
    : stallJsonResponse(200));
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"),
    env: envWithCredentials({ GITHUB_APP_PRIVATE_KEY_PKCS8: privateKeyPem }),
    now: () => NOW, cache, fetchImpl, cryptoImpl: webcrypto, timeouts: FAST,
  });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("X-Portfolio-Cache"), "stale");
  assert.equal(response.headers.get("X-Portfolio-Diagnostic-Code"), "GITHUB_GRAPHQL_TIMEOUT");
  const body = await response.json();
  assert.equal(body.stale, true);
  assert.equal(body.errors.at(-1).diagnosticCode, "GITHUB_GRAPHQL_TIMEOUT");
});
test("timeout response leaks no credential, key, token, JWT, raw error, or URL identifier", async () => {
  const logs = [];
  const stageLogger = (stage, result) => logs.push(JSON.stringify({ stage, result }));
  const response = await handleGitHubStatusRequest({
    request: new Request("https://x/api/github-status"),
    env: envWithCredentials({ GITHUB_APP_PRIVATE_KEY_PKCS8: privateKeyPem }),
    now: () => NOW, cache: new MemorySnapshotCache({ now: () => NOW }),
    fetchImpl: never, cryptoImpl: webcrypto, timeouts: FAST, stageLogger,
  });
  const text = JSON.stringify(await response.json()) + JSON.stringify(Object.fromEntries(response.headers));
  for (const secret of ["app-secret", "install-secret", privateKeyPem, "Bearer ", "eyJ", "api.github.com", "TypeError", "stack"]) {
    assert.equal(text.includes(secret), false, `no ${secret.slice(0, 12)}... in response`);
  }
  for (const line of logs) {
    for (const secret of ["app-secret", "install-secret", privateKeyPem, "Bearer", "api.github.com"]) {
      assert.equal(line.includes(secret), false, "stage log carries no secret");
    }
  }
});

// ── safe stage log format ──
test("safe stage log carries only event/stage/result/elapsed", () => {
  const lines = [];
  const logger = createStageLogger((line) => lines.push(line), () => 1000);
  logger("graphql", "timeout", 400);
  logger("installation-token", "success", 900);
  assert.equal(lines.length, 2);
  for (const line of lines) {
    const parsed = JSON.parse(line);
    assert.deepEqual(Object.keys(parsed).sort(), ["elapsed", "event", "result", "stage"]);
    assert.equal(parsed.event, "portfolio_github_sync_stage");
    assert.equal(typeof parsed.elapsed, "number");
  }
  assert.deepEqual(JSON.parse(lines[0]), { event: "portfolio_github_sync_stage", stage: "graphql", result: "timeout", elapsed: 600 });
});

// ── diagnostic allowlist parity ──
test("timeout diagnostics are valid allowlisted codes", () => {
  assert.equal(validDiagnosticCode("INSTALLATION_TOKEN_TIMEOUT"), "INSTALLATION_TOKEN_TIMEOUT");
  assert.equal(validDiagnosticCode("GITHUB_GRAPHQL_TIMEOUT"), "GITHUB_GRAPHQL_TIMEOUT");
  assert.equal(validDiagnosticCode("INSTALLATION_TOKEN_REQUEST_FAILED"), "INSTALLATION_TOKEN_REQUEST_FAILED");
  assert.equal(validDiagnosticCode("GITHUB_GRAPHQL_TRANSPORT_FAILED"), "GITHUB_GRAPHQL_TRANSPORT_FAILED");
});
test("default deadline constants are frozen and ordered below the wall-clock limit", () => {
  assert.equal(Object.isFrozen(OUTBOUND_DEADLINES), true);
  assert.ok(OUTBOUND_DEADLINES.installationTokenRequestMs < OUTBOUND_DEADLINES.totalSyncMs);
  assert.ok(OUTBOUND_DEADLINES.graphqlRequestMs < OUTBOUND_DEADLINES.totalSyncMs);
  assert.ok(OUTBOUND_DEADLINES.totalSyncMs < OUTBOUND_DEADLINES.handlerBackstopMs);
});
