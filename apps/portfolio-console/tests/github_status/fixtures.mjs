import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { BUSINESS_GITHUB_MAP, GITHUB_REPOSITORY } from "../../functions/_lib/business-github-map.js";
import { InstallationTokenProvider } from "../../functions/_lib/github-app-auth.js";
import { MemorySnapshotCache } from "../../functions/_lib/cache.js";
import { createGitHubStatusService } from "../../functions/_lib/github-status-service.js";
import { buildIdentitySource } from "../../business-identity-data.js";

export { assert, webcrypto, BUSINESS_GITHUB_MAP, GITHUB_REPOSITORY, MemorySnapshotCache };
export { gqlPr, gqlSearchResult, rollup, gqlIssue };
export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
export const NOW = Date.parse("2026-07-27T01:00:00Z");
export const delay = (ms = 5) => new Promise((resolve) => setTimeout(resolve, ms));

export async function generatePrivateKeyPem() {
  const pair = await webcrypto.subtle.generateKey(
    { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" },
    true,
    ["sign", "verify"]
  );
  const pkcs8 = await webcrypto.subtle.exportKey("pkcs8", pair.privateKey);
  const base64 = Buffer.from(pkcs8).toString("base64").match(/.{1,64}/g).join("\n");
  return `-----BEGIN PRIVATE KEY-----\n${base64}\n-----END PRIVATE KEY-----`;
}
export function decodeJwtPart(part) {
  const normalized = part.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized + "=".repeat((4 - normalized.length % 4) % 4);
  return JSON.parse(Buffer.from(padded, "base64").toString("utf8"));
}
export const jsonResponse = (data, status = 200, headers = {}) => new Response(JSON.stringify(data), {
  status,
  headers: { "Content-Type": "application/json", ...headers }
});
function rollup(state = "SUCCESS", { totalCount = 1, nodes = null } = {}) {
  const defaultNode = state === "PENDING" || state === "EXPECTED"
    ? { __typename: "CheckRun", status: "IN_PROGRESS", conclusion: null }
    : state === "FAILURE" || state === "ERROR"
      ? { __typename: "CheckRun", status: "COMPLETED", conclusion: state }
      : { __typename: "CheckRun", status: "COMPLETED", conclusion: "SUCCESS" };
  return { state, contexts: { totalCount, nodes: nodes || [defaultNode] } };
}
function gqlIssue(number, { body = "", state = "OPEN", stateReason = null } = {}) {
  return { number, title: `Issue ${number}`, state, stateReason, body, updatedAt: "2026-07-27T00:00:00Z", url: `https://github.com/${GITHUB_REPOSITORY}/issues/${number}` };
}
function gqlPr(number, { state = "OPEN", isDraft = true, merged = false, checkState = "SUCCESS", body = "" } = {}) {
  return {
    number,
    title: `PR ${number}`,
    state,
    isDraft,
    merged,
    headRefOid: String(number).padStart(40, "a").slice(-40),
    headRefName: `feat/pr-${number}`,
    baseRefOid: "b".repeat(40),
    baseRefName: "main",
    updatedAt: "2026-07-27T00:00:00Z",
    url: `https://github.com/${GITHUB_REPOSITORY}/pull/${number}`,
    body,
    commits: { nodes: [{ commit: { statusCheckRollup: checkState === null ? null : rollup(checkState) } }] }
  };
}
function gqlSearchResult(number, { state = "OPEN", isDraft = true, merged = false, checkState = "SUCCESS", body = null, headRefName = null } = {}) {
  return {
    __typename: "PullRequest",
    number,
    title: `PR ${number}`,
    state,
    isDraft,
    merged,
    headRefOid: String(number).padStart(40, "a").slice(-40),
    headRefName: headRefName || `feat/pr-${number}`,
    baseRefOid: "b".repeat(40),
    baseRefName: "main",
    updatedAt: "2026-07-27T00:00:00Z",
    url: `https://github.com/${GITHUB_REPOSITORY}/pull/${number}`,
    body: body == null ? `Refs #${number}` : body,
    commits: { nodes: [{ commit: { statusCheckRollup: checkState === null ? null : rollup(checkState) } }] }
  };
}
export function aggregatePayload({ errors = [], overrides = {} } = {}) {
  const repository = {
    nameWithOwner: GITHUB_REPOSITORY,
    url: `https://github.com/${GITHUB_REPOSITORY}`,
    defaultBranchRef: { name: "main", target: { oid: "a".repeat(40), messageHeadline: "feat: current main", committedDate: "2026-07-27T00:00:00Z" } },
    issues: { totalCount: 9 },
    pullRequests: { totalCount: 4 }
  };
  const topLevel = {};
  for (const mapping of BUSINESS_GITHUB_MAP) {
    if (mapping.issueNumber) repository[`issue${mapping.issueNumber}`] = gqlIssue(mapping.issueNumber);
    if (mapping.uiPhaseIssue && mapping.uiPhaseIssue !== mapping.issueNumber) {
      repository[`issue${mapping.uiPhaseIssue}`] = gqlIssue(mapping.uiPhaseIssue);
    }
    if (mapping.uxPhaseIssue) repository[`issue${mapping.uxPhaseIssue}`] = gqlIssue(mapping.uxPhaseIssue);
    if (mapping.bePhaseIssue) repository[`issue${mapping.bePhaseIssue}`] = gqlIssue(mapping.bePhaseIssue);
    const fallbackUi = mapping.fallbackPrNumbers?.ui || null;
    if (fallbackUi) {
      repository[`fallbackPr${fallbackUi}`] = fallbackUi === 88
        ? gqlPr(88, { state: "MERGED", isDraft: false, merged: true })
        : gqlPr(fallbackUi);
    }
    if (mapping.fallbackPrNumbers?.ux) repository[`fallbackPr${mapping.fallbackPrNumbers.ux}`] = gqlPr(mapping.fallbackPrNumbers.ux);
    if (mapping.fallbackPrNumbers?.backend) repository[`fallbackPr${mapping.fallbackPrNumbers.backend}`] = gqlPr(mapping.fallbackPrNumbers.backend);
    // Bounded candidate-pool aliases at top level. The Refs pool carries the
    // default candidate; Related-to, marker and convention pools are empty
    // unless overridden.
    const phasePairs = [
      ["ui", mapping.uiPhaseIssue],
      ["ux", mapping.uxPhaseIssue],
      ["backend", mapping.bePhaseIssue],
    ];
    for (const [phase, pi] of phasePairs) {
      if (!pi) continue;
      if (!topLevel[`prSearchRefs${pi}`]) {
        topLevel[`prSearchRefs${pi}`] = {
          issueCount: 1,
          nodes: [gqlSearchResult(fallbackUi || pi, { body: `Refs #${pi}`, headRefName: `feat/business-${mapping.number}-${pi}` })]
        };
      }
      if (!topLevel[`prSearchRelated${pi}`]) {
        topLevel[`prSearchRelated${pi}`] = { issueCount: 0, nodes: [] };
      }
      if (!topLevel[`prSearchMarker${mapping.number}_${phase}`]) {
        topLevel[`prSearchMarker${mapping.number}_${phase}`] = { issueCount: 0, nodes: [] };
      }
      if (!topLevel[`prSearchConvention${mapping.number}_${phase}`]) {
        topLevel[`prSearchConvention${mapping.number}_${phase}`] = { issueCount: 0, nodes: [] };
      }
    }
  }
  Object.assign(repository, overrides.repository || {});
  Object.assign(topLevel, overrides.topLevel || {});
  return { data: { repository, draftPullRequests: { issueCount: 3 }, ...topLevel }, errors };
}
export function mockAggregateClient(payload = aggregatePayload(), { throwError = null, delayMs = 0, counter = null } = {}) {
  return {
    async getStatusAggregation() {
      if (counter) counter.count += 1;
      if (delayMs) await delay(delayMs);
      if (throwError) throw throwError;
      return payload;
    }
  };
}
/* Route a mocked GraphQL HTTP response by the operation in init.body.query:
 * the core operation receives {repository, draftPullRequests}; each discovery
 * batch receives exactly the search aliases it requested. This mirrors the real
 * batched contract so GitHubClient-level tests exercise the merge faithfully. */
export function routeGraphqlResponse(fullPayload, init) {
  const data = fullPayload.data;
  const query = JSON.parse(init.body).query || "";
  if (query.includes("repository(owner:")) {
    return { data: { repository: data.repository, draftPullRequests: data.draftPullRequests }, errors: fullPayload.errors || [] };
  }
  const slice = {};
  for (const match of query.matchAll(/^\s*([A-Za-z]\w*): search\(/gm)) {
    if (match[1] in data) slice[match[1]] = data[match[1]];
  }
  return { data: slice, errors: [] };
}
export function batchedGraphqlFetchImpl(fullPayload = aggregatePayload(), { counter = null, tokenExchanges = null } = {}) {
  return async (url, init) => {
    if (String(url).includes("access_tokens")) {
      if (tokenExchanges) tokenExchanges.count += 1;
      return jsonResponse({ token: "t", expires_at: new Date(NOW + 120_000).toISOString() });
    }
    if (counter) counter.count += 1;
    return jsonResponse(routeGraphqlResponse(fullPayload, init));
  };
}
export function envWithCredentials(extra = {}) {
  return {
    GITHUB_APP_ID: "app-secret",
    GITHUB_APP_INSTALLATION_ID: "install-secret",
    GITHUB_APP_PRIVATE_KEY_PKCS8: "private-secret",
    ...extra
  };
}
export function memoryKv(initial = null) {
  let value = initial;
  return {
    puts: [],
    async get(key) { assert.equal(key, "github-status:v1:last-good"); return value; },
    async put(key, text, options) {
      assert.equal(key, "github-status:v1:last-good");
      this.puts.push({ text, options });
      value = JSON.parse(text);
    }
  };
}
export function createProvider(privateKeyPem, fetchImpl, now = () => NOW) {
  return new InstallationTokenProvider({
    appId: "123",
    installationId: "456",
    privateKeyPkcs8: privateKeyPem,
    cryptoImpl: webcrypto,
    now,
    fetchImpl
  });
}
export function serviceResult(client, {
  cache = new MemorySnapshotCache({ now: () => NOW }),
  now = () => NOW,
  key = `test-${crypto.randomUUID()}`,
  identitySource = buildIdentitySource()
} = {}) {
  return createGitHubStatusService({ client, cache, now, singleFlightKey: key, identitySource }).getStatus();
}
