import test from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { BUSINESS_GITHUB_MAP, GITHUB_REPOSITORY, assertAllowedRepository } from "../functions/_lib/business-github-map.js";
import { createGitHubAppJwt, InstallationTokenProvider } from "../functions/_lib/github-app-auth.js";
import { GitHubClient, normalizeChecks } from "../functions/_lib/github-client.js";
import { MemorySnapshotCache } from "../functions/_lib/cache.js";
import { createGitHubStatusService } from "../functions/_lib/github-status-service.js";
import { handleGitHubStatusRequest } from "../functions/api/github-status.js";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
let privateKeyPem;

async function generatePrivateKeyPem() {
  const pair = await webcrypto.subtle.generateKey(
    { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" },
    true,
    ["sign", "verify"]
  );
  const pkcs8 = await webcrypto.subtle.exportKey("pkcs8", pair.privateKey);
  const base64 = Buffer.from(pkcs8).toString("base64").match(/.{1,64}/g).join("\n");
  return `-----BEGIN PRIVATE KEY-----\n${base64}\n-----END PRIVATE KEY-----`;
}

function decodeJwtPart(part) {
  const normalized = part.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized + "=".repeat((4 - normalized.length % 4) % 4);
  return JSON.parse(Buffer.from(padded, "base64").toString("utf8"));
}

const jsonResponse = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
const issue = (number, overrides = {}) => ({ number, title: `Issue ${number}`, state: "open", updated_at: "2026-07-27T00:00:00Z", html_url: `https://github.com/${GITHUB_REPOSITORY}/issues/${number}`, ...overrides });
const pull = (number, overrides = {}) => ({ number, title: `PR ${number}`, state: "open", draft: true, merged: false, merged_at: null, head: { sha: `sha-${number}` }, base: { ref: "main" }, updated_at: "2026-07-27T00:00:00Z", html_url: `https://github.com/${GITHUB_REPOSITORY}/pull/${number}`, ...overrides });

function createMockClient(overrides = {}) {
  return Object.assign({
    async getRepository() { return { default_branch: "main" }; },
    async getLatestCommit() { return { sha: "a".repeat(40), commit: { message: "feat: current main\nbody", committer: { date: "2026-07-27T00:00:00Z" } } }; },
    async getSummary() { return { openIssues: 9, openPullRequests: 4, draftPullRequests: 3 }; },
    async getIssue(_repository, number) { return issue(number); },
    async getPullRequest(_repository, number) { return number === 88 ? pull(number, { state: "closed", draft: false, merged: true, merged_at: "2026-07-20T00:00:00Z" }) : pull(number); },
    async getChecks() { return { state: "pass", source: "pr_head", total: 2, completed: 2 }; }
  }, overrides);
}

async function serviceResult(client = createMockClient(), { cache, nowValue = Date.parse("2026-07-27T01:00:00Z") } = {}) {
  const resolvedCache = cache || new MemorySnapshotCache({ now: () => nowValue });
  return createGitHubStatusService({ client, cache: resolvedCache, now: () => nowValue }).getStatus();
}

test.before(async () => { privateKeyPem = await generatePrivateKeyPem(); });

test("missing configuration is a normalized secret-free 503", async () => {
  const response = await handleGitHubStatusRequest({ request: new Request("https://console.example/api/github-status"), env: { GITHUB_APP_ID: "not-returned" } });
  assert.equal(response.status, 503);
  const body = await response.json();
  assert.equal(body.error.code, "CONFIGURATION_MISSING");
  assert.deepEqual(body.businesses, []);
  assert.equal(JSON.stringify(body).includes("not-returned"), false);
});

test("method, HEAD, and arbitrary-query contracts are enforced", async () => {
  const post = await handleGitHubStatusRequest({ request: new Request("https://console.example/api/github-status", { method: "POST" }), env: {} });
  assert.equal(post.status, 405);
  assert.equal(post.headers.get("Allow"), "GET, HEAD");
  assert.equal((await post.json()).error.code, "METHOD_NOT_ALLOWED");
  const query = await handleGitHubStatusRequest({ request: new Request("https://console.example/api/github-status?repo=other/repository"), env: {} });
  assert.equal(query.status, 400);
  assert.equal((await query.json()).error.code, "INVALID_QUERY");
  const head = await handleGitHubStatusRequest({ request: new Request("https://console.example/api/github-status", { method: "HEAD" }), env: {} });
  assert.equal(head.status, 503);
  assert.equal(await head.text(), "");
});

test("JWT uses RS256 with explicit clock drift and bounded expiry", async () => {
  const now = 1_800_000_000;
  const jwt = await createGitHubAppJwt({ appId: "123", privateKeyPkcs8: privateKeyPem, nowSeconds: now, cryptoImpl: webcrypto });
  const [header, claims, signature] = jwt.split(".");
  assert.deepEqual(decodeJwtPart(header), { alg: "RS256", typ: "JWT" });
  assert.deepEqual(decodeJwtPart(claims), { iat: now - 60, exp: now + 540, iss: "123" });
  assert.ok(signature.length > 0);
});

test("installation-token exchange succeeds, fails safely, and refreshes", async () => {
  let nowMs = Date.parse("2026-07-27T00:00:00Z");
  let exchanges = 0;
  const provider = new InstallationTokenProvider({
    appId: "123", installationId: "456", privateKeyPkcs8: privateKeyPem, cryptoImpl: webcrypto, now: () => nowMs,
    fetchImpl: async (url, init) => {
      exchanges += 1;
      assert.equal(url, "https://api.github.com/app/installations/456/access_tokens");
      assert.match(init.headers.Authorization, /^Bearer /);
      assert.equal(init.headers["X-GitHub-Api-Version"], "2026-03-10");
      return jsonResponse({ token: `opaque-${exchanges}`, expires_at: new Date(nowMs + 120_000).toISOString() });
    }
  });
  assert.equal(await provider.getToken(), "opaque-1");
  nowMs += 70_000;
  assert.equal(await provider.getToken(), "opaque-2");
  const failing = new InstallationTokenProvider({ appId: "123", installationId: "456", privateKeyPkcs8: privateKeyPem, cryptoImpl: webcrypto, fetchImpl: async () => jsonResponse({}, 401) });
  await assert.rejects(() => failing.getToken(), (error) => error.code === "INSTALLATION_TOKEN_EXCHANGE_FAILED");
});

test("GitHub client refreshes once after 401", async () => {
  let requests = 0;
  let invalidations = 0;
  const authProvider = { async getToken() { return requests ? "second" : "first"; }, invalidate() { invalidations += 1; } };
  const client = new GitHubClient({ authProvider, fetchImpl: async () => (++requests === 1 ? jsonResponse({}, 401) : jsonResponse({ default_branch: "main" })) });
  assert.equal((await client.getRepository(GITHUB_REPOSITORY)).default_branch, "main");
  assert.equal(requests, 2);
  assert.equal(invalidations, 1);
});

test("repository allowlist and exact Business 1-15 mapping are fixed", () => {
  assert.equal(assertAllowedRepository(GITHUB_REPOSITORY), GITHUB_REPOSITORY);
  assert.throws(() => assertAllowedRepository("other/repository"), (error) => error.code === "REPOSITORY_NOT_ALLOWED");
  assert.deepEqual(BUSINESS_GITHUB_MAP.map((item) => item.number), Array.from({ length: 15 }, (_, index) => index + 1));
  assert.equal(BUSINESS_GITHUB_MAP[14].repository, null);
});

test("server mapping has parity with businesses.js Issue and PR URLs", async () => {
  const source = await readFile(path.join(ROOT, "businesses.js"), "utf8");
  for (const mapping of BUSINESS_GITHUB_MAP) {
    const startMatch = new RegExp(`\\bnumber:\\s*${mapping.number},`).exec(source);
    assert.ok(startMatch, `Business ${mapping.number} exists`);
    const tail = source.slice(startMatch.index + 1);
    const nextMatch = mapping.number < 15 ? new RegExp(`\\bnumber:\\s*${mapping.number + 1},`).exec(tail) : null;
    const block = source.slice(startMatch.index, nextMatch ? startMatch.index + 1 + nextMatch.index : source.length);
    if (mapping.issueNumber) assert.match(block, new RegExp(`/issues/${mapping.issueNumber}(?:"|')`));
    else assert.equal(/\/issues\/\d+/.test(block), false);
    if (mapping.pullRequestNumber) assert.match(block, new RegExp(`/pull/${mapping.pullRequestNumber}(?:"|')`));
    else assert.equal(/\/pull\/\d+/.test(block), false);
  }
});

test("B01, B02, B06, B09, and B15 normalize without product inference", async () => {
  const result = await serviceResult();
  const byNumber = new Map(result.payload.businesses.map((item) => [item.number, item]));
  assert.deepEqual([byNumber.get(1).issue.number, byNumber.get(1).pullRequest.number, byNumber.get(1).pullRequest.draft], [108, 111, true]);
  assert.deepEqual([byNumber.get(2).pullRequest.number, byNumber.get(2).pullRequest.merged], [88, true]);
  assert.deepEqual([byNumber.get(6).issue.number, byNumber.get(6).pullRequest, byNumber.get(6).checks.state], [98, null, "unavailable"]);
  assert.deepEqual([byNumber.get(9).issue.number, byNumber.get(9).pullRequest.number, byNumber.get(9).pullRequest.state, byNumber.get(9).pullRequest.draft, byNumber.get(9).pullRequest.merged], [170, 175, "open", true, false]);
  assert.equal("progress" in byNumber.get(9), false);
  assert.equal("uiApproved" in byNumber.get(9), false);
  assert.equal("nextAction" in byNumber.get(9), false);
  assert.deepEqual(byNumber.get(15), { number: 15, connectionState: "unmapped", repository: null, issue: null, pullRequest: null, checks: { state: "unavailable", source: "none", total: 0, completed: 0 }, activityAt: null, error: null });
});

test("checks normalize pass, fail, pending, and unavailable", () => {
  assert.equal(normalizeChecks([{ status: "completed", conclusion: "success" }], [{ state: "success" }]).state, "pass");
  assert.equal(normalizeChecks([{ status: "completed", conclusion: "failure" }], []).state, "fail");
  assert.equal(normalizeChecks([{ status: "in_progress", conclusion: null }], []).state, "pending");
  assert.equal(normalizeChecks([], []).state, "unavailable");
});

test("one-Business checks failure preserves Issue and PR", async () => {
  const client = createMockClient({ async getChecks(_repository, sha) { if (sha === "sha-111") throw new Error("checks failed"); return { state: "pass", source: "pr_head", total: 1, completed: 1 }; } });
  const result = await serviceResult(client);
  const business = result.payload.businesses.find((item) => item.number === 1);
  assert.equal(result.payload.ok, true);
  assert.deepEqual([business.issue.number, business.pullRequest.number, business.checks.state, business.error.code], [108, 111, "unavailable", "CHECKS_UNAVAILABLE"]);
});

test("fresh cache avoids upstream; stale cache survives refresh failure", async () => {
  let nowMs = 1_000_000;
  const cache = new MemorySnapshotCache({ now: () => nowMs });
  const snapshot = { ok: true, schemaVersion: 1, syncedAt: "2026-07-27T00:00:00Z", stale: false, businesses: [{ number: 15 }] };
  await cache.set(snapshot);
  let calls = 0;
  const failingClient = createMockClient({ async getRepository() { calls += 1; throw new Error("down"); } });
  let result = await createGitHubStatusService({ client: failingClient, cache, now: () => nowMs }).getStatus();
  assert.equal(result.cacheState, "fresh");
  assert.equal(calls, 0);
  nowMs += 181_000;
  result = await createGitHubStatusService({ client: failingClient, cache, now: () => nowMs }).getStatus();
  assert.equal(result.cacheState, "stale");
  assert.equal(result.payload.stale, true);
  assert.deepEqual(result.payload.businesses, [{ number: 15 }]);
});

test("total upstream failure without snapshot is normalized and non-reflective", async () => {
  const result = await serviceResult(createMockClient({ async getRepository() { throw new Error("<html>private upstream body</html>"); } }));
  assert.equal(result.status, 502);
  assert.equal(result.payload.error.code, "UPSTREAM_UNAVAILABLE");
  assert.equal(JSON.stringify(result.payload).includes("<html>"), false);
});

test("success response never discloses credential values or Authorization", async () => {
  const secrets = ["app-secret-value", "installation-secret-value", "private-key-secret-value", "Authorization"];
  const now = () => Date.parse("2026-07-27T01:00:00Z");
  const response = await handleGitHubStatusRequest({
    request: new Request("https://console.example/api/github-status"),
    env: { GITHUB_APP_ID: secrets[0], GITHUB_APP_INSTALLATION_ID: secrets[1], GITHUB_APP_PRIVATE_KEY_PKCS8: secrets[2] },
    client: createMockClient(), cache: new MemorySnapshotCache({ now }), now
  });
  assert.equal(response.status, 200);
  const text = await response.text();
  for (const secret of secrets) assert.equal(text.includes(secret), false);
  assert.equal(text.includes("stack"), false);
});
