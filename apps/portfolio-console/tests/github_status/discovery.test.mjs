import test from "node:test";
import assert from "node:assert/strict";
import { buildStatusQuery, getPrSearchAliases, getPhaseIssueNumbers } from "../../functions/_lib/business-github-query.js";
import { discoverPr, discoverBusinessPrs, reconcileWithFallback, normalizeRawPr } from "../../functions/_lib/business-pr-discovery.js";
import { aggregatePayload, gqlSearchResult, gqlPr, mockAggregateClient, serviceResult } from "./fixtures.mjs";

test("query builder emits bounded dual Refs/Related-to aliases in one request", () => {
  const query = buildStatusQuery({ prSearchLimit: 7 });
  for (const n of getPhaseIssueNumbers()) {
    assert.ok(query.includes(`prSearchRefs${n}: search(`), `Refs alias for ${n}`);
    assert.ok(query.includes(`prSearchRelated${n}: search(`), `Related alias for ${n}`);
    assert.ok(query.includes(`\\"Refs #${n}\\"`), `Refs expression for ${n}`);
    assert.ok(query.includes(`\\"Related to #${n}\\"`), `Related-to expression for ${n}`);
  }
  const firstLimits = query.match(/first: 7/g) || [];
  assert.ok(firstLimits.length >= getPhaseIssueNumbers().length * 2, "both aliases are bounded by prSearchLimit");
  assert.equal(query.split("query PortfolioAutoSync").length, 2, "exactly one GraphQL operation");
  assert.ok(query.includes("draftPullRequests: search(query:"), "draft count search preserved");
});

test("getPrSearchAliases keeps Refs before Related-to", () => {
  assert.deepEqual(getPrSearchAliases(108), ["prSearchRefs108", "prSearchRelated108"]);
});

test("Refs-only PR is discovered with method refs", () => {
  const result = discoverPr({
    businessNumber: 15, phaseIssueNumber: 188, phase: "ui",
    searchResults: { nodes: [gqlSearchResult(301, { body: "Refs #188" })], truncated: false },
    fallbackPrNode: null,
  });
  assert.equal(result.status, "discovered");
  assert.equal(result.pullRequest.number, 301);
  assert.equal(result.pullRequest.discoveryMethod, "refs");
});

test("Related-to-only PR is discovered with method related_to", () => {
  const result = discoverPr({
    businessNumber: 15, phaseIssueNumber: 188, phase: "ui",
    searchResults: { nodes: [gqlSearchResult(302, { body: "Related to #188" })], truncated: false },
    fallbackPrNode: null,
  });
  assert.equal(result.status, "discovered");
  assert.equal(result.pullRequest.number, 302);
  assert.equal(result.pullRequest.discoveryMethod, "related_to");
});

test("one PR present in both pools is deduped, not a conflict", () => {
  const same = gqlSearchResult(303, { body: "Refs #188\nRelated to #188" });
  const seen = new Set();
  const nodes = [];
  for (const node of [same, same]) {
    if (seen.has(node.number)) continue;
    seen.add(node.number);
    nodes.push(node);
  }
  const result = discoverPr({ businessNumber: 15, phaseIssueNumber: 188, phase: "ui", searchResults: { nodes, truncated: false }, fallbackPrNode: null });
  assert.equal(result.status, "discovered");
  assert.equal(result.pullRequest.number, 303);
});

test("multiple Refs matches are a conflict, never a guess", () => {
  const result = discoverPr({
    businessNumber: 15, phaseIssueNumber: 188, phase: "ui",
    searchResults: { nodes: [gqlSearchResult(304, { body: "Refs #188" }), gqlSearchResult(305, { body: "Refs #188" })], truncated: false },
    fallbackPrNode: null,
  });
  assert.equal(result.status, "conflict");
  assert.deepEqual(result.candidates, [304, 305]);
  assert.equal(result.reason, "MULTIPLE_REFS_MATCHES");
});

test("structured marker wins over Refs matches", () => {
  const result = discoverPr({
    businessNumber: 15, phaseIssueNumber: 188, phase: "ui",
    searchResults: { nodes: [
      gqlSearchResult(306, { body: "business: 15\nphase: ui" }),
      gqlSearchResult(307, { body: "Refs #188" }),
    ], truncated: false },
    fallbackPrNode: null,
  });
  assert.equal(result.status, "discovered");
  assert.equal(result.pullRequest.number, 306);
  assert.equal(result.pullRequest.discoveryMethod, "marker");
});

test("branch convention uses whole-word business numbers (no business-1 vs business-11 false positive)", () => {
  const result = discoverPr({
    businessNumber: 1, phaseIssueNumber: 108, phase: "ui",
    searchResults: { nodes: [gqlSearchResult(308, { body: "", headRefName: "feat/business-111-ui" })], truncated: false },
    fallbackPrNode: null,
  });
  assert.equal(result.status, "unavailable");
  assert.equal(result.reason, "NO_DISCOVERY_MATCH");
  const exact = discoverPr({
    businessNumber: 111, phaseIssueNumber: 908, phase: "ui",
    searchResults: { nodes: [gqlSearchResult(308, { body: "", headRefName: "feat/business-111-ui" })], truncated: false },
    fallbackPrNode: null,
  });
  assert.equal(exact.status, "discovered");
  assert.equal(exact.pullRequest.discoveryMethod, "branch");
});

test("fallback pointer agreeing with discovery keeps the automatic method", () => {
  const discovery = { status: "discovered", pullRequest: { number: 111, discoveryMethod: "refs" }, candidates: null, reason: null };
  const reconciled = reconcileWithFallback(discovery, gqlPr(111));
  assert.equal(reconciled.status, "discovered");
  assert.equal(reconciled.pullRequest.discoveryMethod, "refs");
});

test("fallback pointer disagreeing with discovery is a mapping conflict", () => {
  const discovery = { status: "discovered", pullRequest: { number: 309, discoveryMethod: "refs" }, candidates: null, reason: null };
  const reconciled = reconcileWithFallback(discovery, gqlPr(111));
  assert.equal(reconciled.status, "conflict");
  assert.equal(reconciled.reason, "FALLBACK_DISCOVERY_MISMATCH");
  assert.deepEqual(reconciled.candidates, [309, 111]);
  assert.equal(reconciled.pullRequest, null);
});

test("truncated pool with a single match is discovered and flagged", () => {
  const result = discoverPr({
    businessNumber: 15, phaseIssueNumber: 188, phase: "ui",
    searchResults: { nodes: [gqlSearchResult(310, { body: "Refs #188" })], truncated: true },
    fallbackPrNode: null,
  });
  assert.equal(result.status, "discovered");
  assert.equal(result.truncated, true);
});

test("no phase issue yields deterministic unavailable", () => {
  const result = discoverPr({ businessNumber: 2, phaseIssueNumber: null, phase: "backend", searchResults: { nodes: [], truncated: false }, fallbackPrNode: null });
  assert.equal(result.status, "unavailable");
  assert.equal(result.reason, "NO_PHASE_ISSUE");
});

test("normalizeRawPr is the single raw-to-normalized boundary", () => {
  const normalized = normalizeRawPr(gqlPr(88, { state: "MERGED", isDraft: false, merged: true, body: "hello" }));
  assert.equal(normalized.draft, false);
  assert.equal(normalized.merged, true);
  assert.equal(normalized.headSha.length, 40);
  assert.equal(normalized.baseSha, "b".repeat(40));
  assert.equal(normalized.baseRef, "main");
  assert.equal(normalized.body, "hello");
  assert.equal(normalized.checks.state, "pass");
  for (const rawKey of ["isDraft", "headRefOid", "headRefName", "baseRefOid", "baseRefName", "commits"]) {
    assert.equal(rawKey in normalized, false, `raw field ${rawKey} must not leak downstream`);
  }
});

test("service end-to-end: Related-to-only PR reaches canonical currentPullRequests", async () => {
  const payload = aggregatePayload({
    overrides: {
      topLevel: {
        prSearchRefs188: { issueCount: 0, nodes: [] },
        prSearchRelated188: { issueCount: 1, nodes: [gqlSearchResult(311, { body: "Related to #188", isDraft: true })] },
      },
    },
  });
  const result = await serviceResult(mockAggregateClient(payload));
  const b15 = result.payload.businesses.find((b) => b.number === 15);
  assert.equal(b15.currentPullRequests.ui.number, 311);
  assert.equal(b15.currentPullRequests.ui.discoveryMethod, "related_to");
  assert.equal(b15.currentPullRequests.ui.draft, true);
  assert.equal(b15.currentPullRequests.ui.headSha.length, 40);
  assert.equal(b15.phaseDiscovery.ui.status, "discovered");
  assert.equal(b15.phaseDiscovery.ui.method, "related_to");
});

test("service end-to-end: fallback mismatch surfaces as conflict", async () => {
  const payload = aggregatePayload({
    overrides: {
      topLevel: {
        prSearchRefs108: { issueCount: 1, nodes: [gqlSearchResult(312, { body: "Refs #108" })] },
        prSearchRelated108: { issueCount: 0, nodes: [] },
      },
    },
  });
  const result = await serviceResult(mockAggregateClient(payload));
  const b1 = result.payload.businesses.find((b) => b.number === 1);
  assert.equal(b1.phaseDiscovery.ui.status, "conflict");
  assert.equal(b1.phaseDiscovery.ui.reason, "FALLBACK_DISCOVERY_MISMATCH");
  assert.deepEqual(b1.phaseDiscovery.ui.candidates, [312, 111]);
  assert.equal(b1.currentPullRequests.ui, null);
  assert.equal(b1.connectionState, "partial");
});
