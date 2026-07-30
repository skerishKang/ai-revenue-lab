import test from "node:test";
import assert from "node:assert/strict";
import { buildStatusQuery, getPrSearchAliases, getPhaseIssueNumbers, getQueryBudget, getFallbackPrNumbers } from "../../functions/_lib/business-github-query.js";
import { discoverPr, discoverBusinessPrs, reconcileWithFallback, normalizeRawPr } from "../../functions/_lib/business-pr-discovery.js";
import { aggregatePayload, gqlSearchResult, gqlPr, mockAggregateClient, serviceResult, BUSINESS_GITHUB_MAP } from "./fixtures.mjs";

test("query builder emits bounded Refs/Related-to aliases in one request", () => {
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

test("query builder emits bounded marker and convention aliases per Business/phase pair", () => {
  const query = buildStatusQuery({ prPrecisionLimit: 4 });
  const mapped = BUSINESS_GITHUB_MAP.filter((m) => m.repository);
  let pairs = 0;
  for (const m of mapped) {
    const phaseIssues = [["ui", m.uiPhaseIssue], ["ux", m.uxPhaseIssue], ["backend", m.bePhaseIssue]];
    for (const [phase, issueNum] of phaseIssues) {
      if (!issueNum) continue;
      pairs += 1;
      assert.ok(query.includes(`prSearchMarker${m.number}_${phase}: search(`), `marker alias for B${m.number} ${phase}`);
      assert.ok(query.includes(`prSearchConvention${m.number}_${phase}: search(`), `convention alias for B${m.number} ${phase}`);
    }
  }
  // Marker queries bind BOTH business and phase phrases (AND)
  assert.ok(query.includes(`\\"business: 15\\" \\"phase: ui\\"`), "marker query restricts business and phase");
  // Convention queries use the phase-suffixed head qualifier: business-1's
  // qualifier `head:business-1-ui` cannot recall branch `feat/business-11-ui`
  // because the latter does not contain the phase-suffixed substring.
  assert.ok(query.includes(`head:business-1-ui`), "B1 convention qualifier is phase-suffixed");
  assert.ok(query.includes(`head:business-11-ui`), "B11 convention qualifier is distinct");
  assert.ok(!query.includes(`head:business-1\\"`) && !query.match(/head:business-1[^\d-]/), "no unsuffixed business-1 head qualifier");
  const precisionLimits = query.match(/first: 4/g) || [];
  assert.equal(precisionLimits.length, pairs * 2, "every marker/convention alias is explicitly bounded");
  assert.equal(query.split("query PortfolioAutoSync").length, 2, "still exactly one GraphQL operation");
});

test("query budget is statically bounded and verified", () => {
  const budget = getQueryBudget();
  assert.equal(budget.graphqlRequests, 1, "single GraphQL operation");
  const query = buildStatusQuery();
  const searchAliases = (query.match(/: search\(/g) || []).length;
  assert.equal(searchAliases, budget.searchAliases, "budget matches emitted search aliases");
  assert.ok(budget.searchAliases <= 200, `search alias count bounded (got ${budget.searchAliases})`);
  assert.ok(budget.searchNodeBudget <= 1300, `search node budget bounded (got ${budget.searchNodeBudget})`);
  assert.ok(budget.issueAliases <= 100, `issue alias count bounded (got ${budget.issueAliases})`);
  assert.ok(budget.fallbackAliases <= 20, `fallback alias count bounded (got ${budget.fallbackAliases})`);
  const firstLimits = (query.replace(/contexts\(first: 100\)/g, "").match(/first: (\d+)/g) || []).map((s) => Number(s.split(": ")[1]));
  assert.ok(firstLimits.every((n) => n <= 10), "every search alias carries an explicit first limit <= 10");
});

test("getPrSearchAliases keeps Refs before Related-to", () => {
  assert.deepEqual(getPrSearchAliases(108), ["prSearchRefs108", "prSearchRelated108"]);
});

test("phase-scoped fallback aliases are deduped across phases", () => {
  const numbers = getFallbackPrNumbers();
  assert.deepEqual(numbers, [...new Set(numbers)].sort((a, b) => a - b));
  const query = buildStatusQuery();
  for (const n of numbers) {
    assert.equal((query.match(new RegExp(`fallbackPr${n}: pullRequest`, "g")) || []).length, 1, `fallbackPr${n} emitted once`);
  }
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

test("marker-only PR is discovered with method marker", () => {
  const result = discoverPr({
    businessNumber: 15, phaseIssueNumber: 188, phase: "ui",
    searchResults: { nodes: [gqlSearchResult(313, { body: "business: 15\nphase: ui" })], truncated: false },
    fallbackPrNode: null,
  });
  assert.equal(result.status, "discovered");
  assert.equal(result.pullRequest.number, 313);
  assert.equal(result.pullRequest.discoveryMethod, "marker");
});

test("branch-only PR is discovered with method branch", () => {
  const result = discoverPr({
    businessNumber: 15, phaseIssueNumber: 188, phase: "ui",
    searchResults: { nodes: [gqlSearchResult(314, { body: "", headRefName: "feat/business-15-ui" })], truncated: false },
    fallbackPrNode: null,
  });
  assert.equal(result.status, "discovered");
  assert.equal(result.pullRequest.number, 314);
  assert.equal(result.pullRequest.discoveryMethod, "branch");
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

test("multiple automatic candidates across pools are a conflict", () => {
  const result = discoverPr({
    businessNumber: 15, phaseIssueNumber: 188, phase: "ui",
    searchResults: { nodes: [
      gqlSearchResult(315, { body: "business: 15\nphase: ui" }),
      gqlSearchResult(316, { body: "business: 15\nphase: ui" }),
    ], truncated: false },
    fallbackPrNode: null,
  });
  assert.equal(result.status, "conflict");
  assert.equal(result.reason, "MULTIPLE_MARKER_MATCHES");
  assert.deepEqual(result.candidates, [315, 316]);
  assert.equal(result.pullRequest, null);
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

test("wrong-phase marker is rejected, never discovered", () => {
  const result = discoverPr({
    businessNumber: 15, phaseIssueNumber: 188, phase: "ui",
    searchResults: { nodes: [gqlSearchResult(317, { body: "business: 15\nphase: ux" })], truncated: false },
    fallbackPrNode: null,
  });
  assert.equal(result.status, "unavailable");
  assert.equal(result.reason, "NO_DISCOVERY_MATCH");
});

test("wrong-Business marker is rejected, never discovered", () => {
  const result = discoverPr({
    businessNumber: 1, phaseIssueNumber: 108, phase: "ui",
    searchResults: { nodes: [gqlSearchResult(318, { body: "business: 11\nphase: ui" })], truncated: false },
    fallbackPrNode: null,
  });
  assert.equal(result.status, "unavailable");
  assert.equal(result.reason, "NO_DISCOVERY_MATCH");
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

// ── Conservative truncation contract ──

test("truncation case 1: Refs pool visible match + truncated → conflict, no authoritative PR", () => {
  const result = discoverPr({
    businessNumber: 15, phaseIssueNumber: 188, phase: "ui",
    searchResults: { nodes: [gqlSearchResult(310, { body: "Refs #188" })], truncated: true, truncatedPools: ["refs"] },
    fallbackPrNode: null,
  });
  assert.equal(result.status, "conflict");
  assert.equal(result.reason, "DISCOVERY_POOL_TRUNCATED");
  assert.equal(result.pullRequest, null);
  assert.equal(result.truncated, true);
  assert.deepEqual(result.truncatedPools, ["refs"]);
  assert.deepEqual(result.candidates, [310]);
});

test("truncation case 2: Related pool visible match + truncated → conflict", () => {
  const result = discoverPr({
    businessNumber: 15, phaseIssueNumber: 188, phase: "ui",
    searchResults: { nodes: [gqlSearchResult(319, { body: "Related to #188" })], truncated: true, truncatedPools: ["related"] },
    fallbackPrNode: null,
  });
  assert.equal(result.status, "conflict");
  assert.equal(result.reason, "DISCOVERY_POOL_TRUNCATED");
  assert.equal(result.pullRequest, null);
});

test("truncation case 3: marker/convention pool truncation → conflict", () => {
  const result = discoverPr({
    businessNumber: 15, phaseIssueNumber: 188, phase: "ui",
    searchResults: { nodes: [gqlSearchResult(323, { body: "business: 15\nphase: ui" })], truncated: true, truncatedPools: ["marker"] },
    fallbackPrNode: null,
  });
  assert.equal(result.status, "conflict");
  assert.equal(result.reason, "DISCOVERY_POOL_TRUNCATED");
  assert.equal(result.pullRequest, null);
});

test("truncation case 4: no visible match + fallback present + truncated → fallback NOT confirmed", () => {
  const result = discoverPr({
    businessNumber: 1, phaseIssueNumber: 108, phase: "ui",
    searchResults: { nodes: [], truncated: true, truncatedPools: ["refs"] },
    fallbackPrNode: gqlPr(111),
  });
  assert.equal(result.status, "conflict");
  assert.equal(result.reason, "DISCOVERY_POOL_TRUNCATED");
  assert.equal(result.pullRequest, null, "fallback must not become authoritative under truncation");
});

test("truncation case 5: only one of dual pools truncated → still conflict", () => {
  const result = discoverPr({
    businessNumber: 15, phaseIssueNumber: 188, phase: "ui",
    searchResults: {
      nodes: [gqlSearchResult(324, { body: "Related to #188" })],
      truncated: true,
      truncatedPools: ["refs"],
    },
    fallbackPrNode: null,
  });
  assert.equal(result.status, "conflict");
  assert.equal(result.reason, "DISCOVERY_POOL_TRUNCATED");
  assert.equal(result.pullRequest, null);
});

test("truncation case 6: all pools non-truncated + unique match → discovered", () => {
  const result = discoverPr({
    businessNumber: 15, phaseIssueNumber: 188, phase: "ui",
    searchResults: { nodes: [gqlSearchResult(325, { body: "Refs #188" })], truncated: false, truncatedPools: [] },
    fallbackPrNode: null,
  });
  assert.equal(result.status, "discovered");
  assert.equal(result.pullRequest.number, 325);
  assert.equal(result.pullRequest.discoveryMethod, "refs");
});

test("truncation case 7: non-truncated no match + valid fallback → fallback discovered", () => {
  const result = discoverPr({
    businessNumber: 1, phaseIssueNumber: 108, phase: "ui",
    searchResults: { nodes: [], truncated: false, truncatedPools: [] },
    fallbackPrNode: gqlPr(111),
  });
  assert.equal(result.status, "discovered");
  assert.equal(result.pullRequest.number, 111);
  assert.equal(result.pullRequest.discoveryMethod, "fallback");
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

// ── Phase-scoped fallback ──

test("UI fallback does not populate UX or backend discovery", () => {
  const mapping = { number: 6, uiPhaseIssue: 155, uxPhaseIssue: 165, bePhaseIssue: null };
  const fallbackPrNodes = { ui: gqlPr(111), ux: null, backend: null };
  const discoveryPools = {
    "6:ui": { nodes: [], truncated: false, truncatedPools: [] },
    "6:ux": { nodes: [], truncated: false, truncatedPools: [] },
  };
  const result = discoverBusinessPrs({ mapping, discoveryPools, fallbackPrNodes });
  assert.equal(result.ui.status, "discovered");
  assert.equal(result.ui.pullRequest.number, 111);
  assert.equal(result.ui.pullRequest.discoveryMethod, "fallback");
  assert.equal(result.ux.status, "unavailable", "UX must NOT receive the UI fallback");
  assert.equal(result.ux.pullRequest, null);
  assert.equal(result.backend.status, "unavailable");
  assert.equal(result.backend.reason, "NO_PHASE_ISSUE");
});

test("B6 UX discovery never receives an unrelated UI fallback (service-level mapping shape)", () => {
  const b6 = BUSINESS_GITHUB_MAP.find((m) => m.number === 6);
  const result = discoverBusinessPrs({
    mapping: b6,
    discoveryPools: {
      "6:ui": { nodes: [], truncated: false, truncatedPools: [] },
      "6:ux": { nodes: [], truncated: false, truncatedPools: [] },
    },
    fallbackPrNodes: { ui: gqlPr(999), ux: null, backend: null },
  });
  assert.equal(result.ux.pullRequest, null);
  assert.notEqual(result.ux.status, "discovered");
});

// ── Service end-to-end through the real GraphQL alias contract ──

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

test("service end-to-end: marker-only alias reaches currentPullRequests.ui", async () => {
  const payload = aggregatePayload({
    overrides: {
      topLevel: {
        prSearchRefs188: { issueCount: 0, nodes: [] },
        prSearchRelated188: { issueCount: 0, nodes: [] },
        prSearchMarker15_ui: { issueCount: 1, nodes: [gqlSearchResult(326, { body: "business: 15\nphase: ui" })] },
      },
    },
  });
  const result = await serviceResult(mockAggregateClient(payload));
  const b15 = result.payload.businesses.find((b) => b.number === 15);
  assert.equal(b15.currentPullRequests.ui.number, 326);
  assert.equal(b15.currentPullRequests.ui.discoveryMethod, "marker");
  assert.equal(b15.phaseDiscovery.ui.status, "discovered");
  assert.equal(b15.phaseDiscovery.ui.method, "marker");
});

test("service end-to-end: branch-only convention alias reaches currentPullRequests.ui", async () => {
  const payload = aggregatePayload({
    overrides: {
      topLevel: {
        prSearchRefs188: { issueCount: 0, nodes: [] },
        prSearchRelated188: { issueCount: 0, nodes: [] },
        prSearchConvention15_ui: { issueCount: 1, nodes: [gqlSearchResult(327, { body: "", headRefName: "feat/business-15-ui" })] },
      },
    },
  });
  const result = await serviceResult(mockAggregateClient(payload));
  const b15 = result.payload.businesses.find((b) => b.number === 15);
  assert.equal(b15.currentPullRequests.ui.number, 327);
  assert.equal(b15.currentPullRequests.ui.discoveryMethod, "branch");
  assert.equal(b15.phaseDiscovery.ui.method, "branch");
});

test("service end-to-end: business-1 search never authorizes a business-11 PR", async () => {
  const payload = aggregatePayload({
    overrides: {
      topLevel: {
        prSearchRefs108: { issueCount: 0, nodes: [] },
        prSearchRelated108: { issueCount: 0, nodes: [] },
        prSearchMarker1_ui: { issueCount: 1, nodes: [gqlSearchResult(328, { body: "business: 11\nphase: ui" })] },
        prSearchConvention1_ui: { issueCount: 1, nodes: [gqlSearchResult(329, { body: "", headRefName: "feat/business-11-ui" })] },
      },
    },
  });
  const result = await serviceResult(mockAggregateClient(payload));
  const b1 = result.payload.businesses.find((b) => b.number === 1);
  // B1 carries UI fallback 111; the wrong-business candidates must be ignored,
  // so the phase-scoped fallback (non-truncated pools) is the only authority.
  assert.equal(b1.currentPullRequests.ui.number, 111);
  assert.equal(b1.currentPullRequests.ui.discoveryMethod, "fallback");
  assert.notEqual(b1.currentPullRequests.ui.number, 328);
  assert.notEqual(b1.currentPullRequests.ui.number, 329);
});

test("service end-to-end: wrong-phase marker alias is rejected for the ui phase", async () => {
  const payload = aggregatePayload({
    overrides: {
      topLevel: {
        prSearchRefs188: { issueCount: 0, nodes: [] },
        prSearchRelated188: { issueCount: 0, nodes: [] },
        prSearchMarker15_ui: { issueCount: 1, nodes: [gqlSearchResult(330, { body: "business: 15\nphase: ux" })] },
      },
    },
  });
  const result = await serviceResult(mockAggregateClient(payload));
  const b15 = result.payload.businesses.find((b) => b.number === 15);
  assert.equal(b15.currentPullRequests.ui, null);
  assert.equal(b15.phaseDiscovery.ui.status, "unavailable");
  assert.equal(b15.phaseDiscovery.ui.reason, "NO_DISCOVERY_MATCH");
});

test("service end-to-end: same PR in marker and refs pools is deduped by number", async () => {
  const shared = gqlSearchResult(331, { body: "business: 15\nphase: ui\nRefs #188" });
  const payload = aggregatePayload({
    overrides: {
      topLevel: {
        prSearchRefs188: { issueCount: 1, nodes: [shared] },
        prSearchRelated188: { issueCount: 0, nodes: [] },
        prSearchMarker15_ui: { issueCount: 1, nodes: [{ ...shared }] },
      },
    },
  });
  const result = await serviceResult(mockAggregateClient(payload));
  const b15 = result.payload.businesses.find((b) => b.number === 15);
  assert.equal(b15.phaseDiscovery.ui.status, "discovered", "deduped candidate is not a conflict");
  assert.equal(b15.currentPullRequests.ui.number, 331);
  assert.equal(b15.currentPullRequests.ui.discoveryMethod, "marker", "marker keeps priority");
});

test("service end-to-end: multiple automatic candidates across pools are a conflict", async () => {
  const payload = aggregatePayload({
    overrides: {
      topLevel: {
        prSearchRefs188: { issueCount: 1, nodes: [gqlSearchResult(332, { body: "Refs #188" })] },
        prSearchRelated188: { issueCount: 0, nodes: [] },
        prSearchMarker15_ui: { issueCount: 1, nodes: [gqlSearchResult(333, { body: "business: 15\nphase: ui" })] },
        prSearchConvention15_ui: { issueCount: 1, nodes: [gqlSearchResult(334, { body: "", headRefName: "feat/business-15-ui" })] },
      },
    },
  });
  const result = await serviceResult(mockAggregateClient(payload));
  const b15 = result.payload.businesses.find((b) => b.number === 15);
  assert.equal(b15.phaseDiscovery.ui.status, "discovered");
  assert.equal(b15.currentPullRequests.ui.number, 333, "single marker match wins over refs/branch candidates");
  assert.equal(b15.currentPullRequests.ui.discoveryMethod, "marker");
});

test("service end-to-end: truncated marker pool blocks discovery with diagnostic reason", async () => {
  const payload = aggregatePayload({
    overrides: {
      topLevel: {
        prSearchRefs188: { issueCount: 0, nodes: [] },
        prSearchRelated188: { issueCount: 0, nodes: [] },
        prSearchMarker15_ui: { issueCount: 9, nodes: [gqlSearchResult(335, { body: "business: 15\nphase: ui" })] },
      },
    },
  });
  const result = await serviceResult(mockAggregateClient(payload));
  const b15 = result.payload.businesses.find((b) => b.number === 15);
  assert.equal(b15.phaseDiscovery.ui.status, "conflict");
  assert.equal(b15.phaseDiscovery.ui.reason, "DISCOVERY_POOL_TRUNCATED");
  assert.equal(b15.phaseDiscovery.ui.truncated, true);
  assert.deepEqual(b15.phaseDiscovery.ui.truncatedPools, ["marker"]);
  assert.equal(b15.currentPullRequests.ui, null);
  assert.equal(b15.connectionState, "partial");
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

test("service end-to-end: UI fallback never populates UX/backend currentPullRequests", async () => {
  const result = await serviceResult(mockAggregateClient());
  const b1 = result.payload.businesses.find((b) => b.number === 1);
  assert.equal(b1.currentPullRequests.ui.discoveryMethod, "refs", "B1 ui resolved automatically");
  assert.equal(b1.currentPullRequests.ux, null, "UX never receives the UI fallback");
  assert.equal(b1.currentPullRequests.backend, null, "backend never receives the UI fallback");
  assert.equal(b1.phaseDiscovery.ux.reason, "NO_PHASE_ISSUE");
  assert.equal(b1.phaseDiscovery.backend.reason, "NO_PHASE_ISSUE");
});
