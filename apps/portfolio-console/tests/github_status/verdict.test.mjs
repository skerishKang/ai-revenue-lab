import test from "node:test";
import assert from "node:assert/strict";
import { resolvePhaseVerdictFromPool } from "../../functions/_lib/business-verdict-parser.js";
import { mergeBusinessFacts } from "../../functions/_lib/business-fact-merger.js";
import { aggregatePayload, gqlSearchResult, gqlIssue, mockAggregateClient, serviceResult, GITHUB_REPOSITORY } from "./fixtures.mjs";

const HEAD_A = "a".repeat(40);
const HEAD_B = "c".repeat(40);

function verdictBlock({ business, phase, verdict, head = null }) {
  const lines = [`<!-- portfolio-verdict`, `business: ${business}`, `phase: ${phase}`, `verdict: ${verdict}`];
  if (head) lines.push(`accepted_head: ${head}`);
  lines.push("-->");
  return lines.join("\n");
}

test("issue body verdict block binds business and phase (verified, issue_body)", () => {
  const result = resolvePhaseVerdictFromPool({
    expectedBusinessNumber: 15, expectedPhase: "ui",
    issueBody: verdictBlock({ business: 15, phase: "ui", verdict: "UI_APPROVED", head: HEAD_A }),
    prBody: null, staticFallback: null,
  });
  assert.equal(result.status, "verified");
  assert.equal(result.verdict, "UI_APPROVED");
  assert.equal(result.acceptedHead, HEAD_A);
  assert.equal(result.source, "issue_body");
});

test("PR body verdict block is accepted per phase (verified, pr_body)", () => {
  const result = resolvePhaseVerdictFromPool({
    expectedBusinessNumber: 6, expectedPhase: "ux",
    issueBody: null,
    prBody: `Refs #165\n${verdictBlock({ business: 6, phase: "ux", verdict: "UX_APPROVED", head: HEAD_A })}`,
    staticFallback: null,
  });
  assert.equal(result.status, "verified");
  assert.equal(result.verdict, "UX_APPROVED");
  assert.equal(result.source, "pr_body");
});

test("verdict block for another Business is rejected, static fallback applies", () => {
  const result = resolvePhaseVerdictFromPool({
    expectedBusinessNumber: 15, expectedPhase: "ui",
    issueBody: verdictBlock({ business: 16, phase: "ui", verdict: "UI_APPROVED", head: HEAD_A }),
    prBody: null, staticFallback: "IN_PROGRESS",
  });
  assert.equal(result.status, "unverified");
  assert.equal(result.verdict, "IN_PROGRESS");
  assert.equal(result.source, "static_fallback");
});

test("verdict block for another phase is rejected, static fallback applies", () => {
  const result = resolvePhaseVerdictFromPool({
    expectedBusinessNumber: 15, expectedPhase: "ui",
    issueBody: verdictBlock({ business: 15, phase: "ux", verdict: "UX_APPROVED", head: HEAD_A }),
    prBody: null, staticFallback: "IN_PROGRESS",
  });
  assert.equal(result.status, "unverified");
  assert.equal(result.source, "static_fallback");
});

test("head-required verdict without accepted_head is invalid", () => {
  const result = resolvePhaseVerdictFromPool({
    expectedBusinessNumber: 15, expectedPhase: "ui",
    issueBody: verdictBlock({ business: 15, phase: "ui", verdict: "UI_APPROVED" }),
    prBody: null, staticFallback: null,
  });
  assert.equal(result.status, "invalid");
  assert.equal(result.reason, "MISSING_OR_INVALID_ACCEPTED_HEAD");
});

test("non-hex accepted_head is invalid", () => {
  const result = resolvePhaseVerdictFromPool({
    expectedBusinessNumber: 15, expectedPhase: "ui",
    issueBody: verdictBlock({ business: 15, phase: "ui", verdict: "UI_APPROVED", head: "not-a-sha" }),
    prBody: null, staticFallback: null,
  });
  assert.equal(result.status, "invalid");
  assert.equal(result.reason, "MISSING_OR_INVALID_ACCEPTED_HEAD");
});

test("verdict not valid for the phase is invalid", () => {
  const result = resolvePhaseVerdictFromPool({
    expectedBusinessNumber: 15, expectedPhase: "ui",
    issueBody: verdictBlock({ business: 15, phase: "ui", verdict: "BACKEND_IMPLEMENTED", head: HEAD_A }),
    prBody: null, staticFallback: null,
  });
  assert.equal(result.status, "invalid");
  assert.match(result.reason, /INVALID_VERDICT_PHASE/);
});

test("head-free verdict (UI_NOT_READY) verifies without accepted_head", () => {
  const result = resolvePhaseVerdictFromPool({
    expectedBusinessNumber: 15, expectedPhase: "ui",
    issueBody: verdictBlock({ business: 15, phase: "ui", verdict: "UI_NOT_READY" }),
    prBody: null, staticFallback: null,
  });
  assert.equal(result.status, "verified");
  assert.equal(result.acceptedHead, null);
});

test("conflicting verdicts across issue and PR bodies are a conflict", () => {
  const result = resolvePhaseVerdictFromPool({
    expectedBusinessNumber: 15, expectedPhase: "ui",
    issueBody: verdictBlock({ business: 15, phase: "ui", verdict: "UI_APPROVED", head: HEAD_A }),
    prBody: verdictBlock({ business: 15, phase: "ui", verdict: "UI_CONDITIONALLY_READY" }),
    staticFallback: null,
  });
  assert.equal(result.status, "conflict");
  assert.equal(result.reason, "MULTIPLE_CONFLICTING_VERDICTS");
});

test("same verdict with different accepted_heads is a conflict", () => {
  const result = resolvePhaseVerdictFromPool({
    expectedBusinessNumber: 15, expectedPhase: "ui",
    issueBody: verdictBlock({ business: 15, phase: "ui", verdict: "UI_APPROVED", head: HEAD_A }),
    prBody: verdictBlock({ business: 15, phase: "ui", verdict: "UI_APPROVED", head: HEAD_B }),
    staticFallback: null,
  });
  assert.equal(result.status, "conflict");
  assert.equal(result.reason, "CONFLICTING_ACCEPTED_HEADS");
});

test("backend verdict BACKEND_IMPLEMENTED verifies with head", () => {
  const result = resolvePhaseVerdictFromPool({
    expectedBusinessNumber: 90, expectedPhase: "backend",
    issueBody: verdictBlock({ business: 90, phase: "backend", verdict: "BACKEND_IMPLEMENTED", head: HEAD_A }),
    prBody: null, staticFallback: null,
  });
  assert.equal(result.status, "verified");
  assert.equal(result.verdict, "BACKEND_IMPLEMENTED");
});

test("service end-to-end: B15 issue body verdict reaches phaseVerdicts.ui", async () => {
  const payload = aggregatePayload({
    overrides: {
      repository: { issue188: gqlIssue(188, { body: verdictBlock({ business: 15, phase: "ui", verdict: "UI_APPROVED", head: HEAD_A }) }) },
    },
  });
  const result = await serviceResult(mockAggregateClient(payload));
  const verdict = result.payload.businesses.find((b) => b.number === 15).phaseVerdicts.ui;
  assert.equal(verdict.status, "verified");
  assert.equal(verdict.verdict, "UI_APPROVED");
  assert.equal(verdict.source, "issue_body");
  assert.equal(verdict.acceptedHead, HEAD_A);
});

test("service end-to-end: wrong-Business block falls back to static (B15 ui IN_PROGRESS)", async () => {
  const payload = aggregatePayload({
    overrides: {
      repository: { issue188: gqlIssue(188, { body: verdictBlock({ business: 16, phase: "ui", verdict: "UI_APPROVED", head: HEAD_A }) }) },
    },
  });
  const result = await serviceResult(mockAggregateClient(payload));
  const verdict = result.payload.businesses.find((b) => b.number === 15).phaseVerdicts.ui;
  assert.equal(verdict.status, "unverified");
  assert.equal(verdict.verdict, "IN_PROGRESS");
  assert.equal(verdict.source, "static_fallback");
});

test("service end-to-end: B6 ux verdict from the ux PR body, ui verdict unaffected", async () => {
  const payload = aggregatePayload({
    overrides: {
      topLevel: {
        prSearchRefs165: { issueCount: 1, nodes: [gqlSearchResult(401, { body: `Refs #165\n${verdictBlock({ business: 6, phase: "ux", verdict: "UX_APPROVED", head: HEAD_A })}` })] },
        prSearchRelated165: { issueCount: 0, nodes: [] },
      },
    },
  });
  const result = await serviceResult(mockAggregateClient(payload));
  const b6 = result.payload.businesses.find((b) => b.number === 6);
  assert.equal(b6.currentPullRequests.ux.number, 401);
  assert.equal(b6.phaseVerdicts.ux.status, "verified");
  assert.equal(b6.phaseVerdicts.ux.verdict, "UX_APPROVED");
  assert.equal(b6.phaseVerdicts.ux.source, "pr_body");
  assert.equal(b6.phaseVerdicts.ui.status, "unverified");
  assert.equal(b6.phaseVerdicts.ui.source, "static_fallback");
});

test("service end-to-end: conflicting issue/PR verdicts surface as conflict", async () => {
  const payload = aggregatePayload({
    overrides: {
      repository: { issue188: gqlIssue(188, { body: verdictBlock({ business: 15, phase: "ui", verdict: "UI_APPROVED", head: HEAD_A }) }) },
      topLevel: {
        prSearchRefs188: { issueCount: 1, nodes: [gqlSearchResult(402, { body: `Refs #188\n${verdictBlock({ business: 15, phase: "ui", verdict: "UI_CONDITIONALLY_READY" })}` })] },
        prSearchRelated188: { issueCount: 0, nodes: [] },
      },
    },
  });
  const result = await serviceResult(mockAggregateClient(payload));
  const verdict = result.payload.businesses.find((b) => b.number === 15).phaseVerdicts.ui;
  assert.equal(verdict.status, "conflict");
  assert.equal(verdict.reason, "MULTIPLE_CONFLICTING_VERDICTS");
});

test("P0-6 regression: backend verdict resolves through the bePhaseIssue key map", () => {
  const mapping = { number: 90, repository: GITHUB_REPOSITORY, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: 999, fallbackPrNumber: null };
  const repositoryData = { issue999: gqlIssue(999, { body: verdictBlock({ business: 90, phase: "backend", verdict: "BACKEND_IMPLEMENTED", head: HEAD_A }) }) };
  const phaseIssueResults = { prSearch999: { nodes: [gqlSearchResult(999, { body: "Refs #999" })], truncated: false } };
  const fact = mergeBusinessFacts({ mapping, repositoryData, phaseIssueResults, fallbackPrNode: null, identitySource: {} });
  assert.equal(fact.phaseDiscovery.backend.status, "discovered");
  assert.equal(fact.phaseDiscovery.backend.method, "refs");
  assert.equal(fact.phaseVerdicts.backend.status, "verified");
  assert.equal(fact.phaseVerdicts.backend.verdict, "BACKEND_IMPLEMENTED");
  assert.equal(fact.phaseVerdicts.backend.source, "issue_body");
});

test("merged PR with no verdict block never verifies (static fallback only)", async () => {
  const payload = aggregatePayload({
    overrides: {
      topLevel: {
        prSearchRefs107: { issueCount: 0, nodes: [] },
        prSearchRelated107: { issueCount: 0, nodes: [] },
      },
    },
  });
  const result = await serviceResult(mockAggregateClient(payload));
  const b2 = result.payload.businesses.find((b) => b.number === 2);
  assert.equal(b2.currentPullRequests.ui.merged, true);
  assert.equal(b2.currentPullRequests.ui.discoveryMethod, "fallback");
  assert.notEqual(b2.phaseVerdicts.ui.status, "verified");
  assert.equal(b2.phaseVerdicts.ui.source, "static_fallback");
});
