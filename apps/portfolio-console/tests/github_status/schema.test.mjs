import test from "node:test";
import assert from "node:assert/strict";
import { aggregatePayload, gqlSearchResult, gqlPr, mockAggregateClient, serviceResult } from "./fixtures.mjs";

test("discovered draft PR keeps draft/headSha/body through the service (single normalization)", async () => {
  const payload = aggregatePayload({
    overrides: {
      topLevel: {
        prSearchRefs188: { issueCount: 1, nodes: [gqlSearchResult(320, { body: "Refs #188", isDraft: true, checkState: "PENDING" })] },
        prSearchRelated188: { issueCount: 0, nodes: [] },
      },
    },
  });
  const result = await serviceResult(mockAggregateClient(payload));
  const pr = result.payload.businesses.find((b) => b.number === 15).currentPullRequests.ui;
  assert.equal(pr.number, 320);
  assert.equal(pr.draft, true, "draft survives normalization");
  assert.equal(pr.merged, false);
  assert.match(pr.headSha, /^[0-9a-f]{40}$/);
  assert.equal(pr.baseRef, "main");
  assert.equal(pr.body, "Refs #188", "body preserved for verdict parsing");
  assert.equal(pr.checks.state, "pending");
  assert.equal(pr.checks.source, "pr_head_rollup");
});

test("fallback PR path normalizes identically (B02 merged fallback)", async () => {
  const payload = aggregatePayload({
    overrides: {
      topLevel: {
        prSearchRefs107: { issueCount: 0, nodes: [] },
        prSearchRelated107: { issueCount: 0, nodes: [] },
      },
    },
  });
  const result = await serviceResult(mockAggregateClient(payload));
  const pr = result.payload.businesses.find((b) => b.number === 2).currentPullRequests.ui;
  assert.equal(pr.number, 88);
  assert.equal(pr.merged, true);
  assert.equal(pr.draft, false);
  assert.equal(pr.discoveryMethod, "fallback");
  assert.equal(pr.checks.state, "pass");
});

test("merged PR never becomes a verified approval without a verdict block", async () => {
  const payload = aggregatePayload({
    overrides: {
      topLevel: {
        prSearchRefs107: { issueCount: 0, nodes: [] },
        prSearchRelated107: { issueCount: 0, nodes: [] },
      },
    },
  });
  const result = await serviceResult(mockAggregateClient(payload));
  const verdict = result.payload.businesses.find((b) => b.number === 2).phaseVerdicts.ui;
  assert.notEqual(verdict.status, "verified", "merge alone cannot verify");
  assert.equal(verdict.source, "static_fallback");
  assert.equal(verdict.verdict, "UI_APPROVED");
  assert.equal(verdict.status, "unverified");
});

test("ready (non-draft) open PR is neither draft nor merged", async () => {
  const payload = aggregatePayload({
    overrides: {
      topLevel: {
        prSearchRefs188: { issueCount: 1, nodes: [gqlSearchResult(321, { body: "Refs #188", isDraft: false })] },
        prSearchRelated188: { issueCount: 0, nodes: [] },
      },
    },
  });
  const result = await serviceResult(mockAggregateClient(payload));
  const pr = result.payload.businesses.find((b) => b.number === 15).currentPullRequests.ui;
  assert.equal(pr.draft, false);
  assert.equal(pr.merged, false);
  assert.equal(pr.state, "open");
});

test("normalized PR objects expose no raw GraphQL field names anywhere", async () => {
  const result = await serviceResult(mockAggregateClient());
  const text = JSON.stringify(result.payload.businesses);
  for (const rawKey of ["isDraft", "headRefOid", "headRefName", "baseRefOid", "baseRefName", "statusCheckRollup"]) {
    assert.equal(text.includes(`"${rawKey}"`), false, `${rawKey} must not appear in the API payload`);
  }
});

test("truncated search pool is flagged through the service", async () => {
  const payload = aggregatePayload({
    overrides: {
      topLevel: {
        prSearchRefs188: { issueCount: 42, nodes: [gqlSearchResult(322, { body: "Refs #188" })] },
        prSearchRelated188: { issueCount: 0, nodes: [] },
      },
    },
  });
  const result = await serviceResult(mockAggregateClient(payload));
  const b15 = result.payload.businesses.find((b) => b.number === 15);
  assert.equal(b15.phaseDiscovery.ui.truncated, true);
  assert.equal(b15.phaseDiscovery.ui.status, "discovered");
});
