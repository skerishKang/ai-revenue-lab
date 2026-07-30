import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mergeBusinessFacts } from "../../functions/_lib/business-fact-merger.js";
import { mockAggregateClient, serviceResult } from "./fixtures.mjs";

const require = createRequire(import.meta.url);
const live = require("../../github-live-status.js");

const PHASES = ["ui", "ux", "backend"];

test("server payload is schemaVersion 2 with canonical top-level keys", async () => {
  const result = await serviceResult(mockAggregateClient());
  const payload = result.payload;
  assert.equal(payload.ok, true);
  assert.equal(payload.schemaVersion, 2);
  assert.ok(Array.isArray(payload.businesses));
  assert.ok(payload.repository.fullName.length > 0);
});

test("mapped Business exposes canonical keys and never legacy issue/pullRequest/checks", async () => {
  const result = await serviceResult(mockAggregateClient());
  const b15 = result.payload.businesses.find((b) => b.number === 15);
  for (const key of ["productDecisionIssue", "phaseIssues", "currentPullRequests", "phaseDiscovery", "phaseVerdicts"]) {
    assert.ok(key in b15, `canonical key ${key} present`);
  }
  for (const legacy of ["issue", "pullRequest", "checks"]) {
    assert.equal(legacy in b15, false, `legacy key ${legacy} must not be emitted by the server`);
  }
});

test("phase objects always carry all three phase keys", async () => {
  const result = await serviceResult(mockAggregateClient());
  const b15 = result.payload.businesses.find((b) => b.number === 15);
  for (const group of ["phaseIssues", "currentPullRequests", "phaseDiscovery", "phaseVerdicts"]) {
    assert.deepEqual(Object.keys(b15[group]).sort(), [...PHASES].sort(), `${group} has ui/ux/backend keys`);
  }
  assert.equal(b15.phaseIssues.ux, null, "B15 has no ux phase Issue");
  assert.equal(b15.phaseIssues.backend, null, "B15 has no backend phase Issue");
  assert.equal(b15.phaseDiscovery.ux.status, "unavailable");
  assert.equal(b15.phaseDiscovery.ux.reason, "NO_PHASE_ISSUE");
});

test("unmapped Business (no repository) is deterministic", () => {
  const fact = mergeBusinessFacts({
    mapping: { number: 91, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
    repositoryData: null,
    discoveryPools: {},
    fallbackPrNodes: { ui: null, ux: null, backend: null },
    identitySource: {},
  });
  assert.equal(fact.connectionState, "unmapped");
  assert.equal(fact.productDecisionIssue, null);
  assert.equal(fact.phaseIssues, null);
  assert.equal(fact.currentPullRequests, null);
  assert.equal(fact.phaseDiscovery, null);
  assert.equal(fact.phaseVerdicts, null);
});

test("adaptLiveBusiness derives legacy primaries from the canonical schema", async () => {
  const result = await serviceResult(mockAggregateClient());
  const b15 = result.payload.businesses.find((b) => b.number === 15);
  const adapted = live.adaptLiveBusiness(b15);
  assert.equal(adapted.issue.number, b15.productDecisionIssue.number);
  assert.equal(adapted.pullRequest.number, b15.currentPullRequests.ui.number);
  assert.equal(adapted.checks.state, b15.currentPullRequests.ui.checks.state);
  assert.equal(adapted.productDecisionIssue, b15.productDecisionIssue, "canonical fields preserved");
});

test("adaptLiveBusiness prefers ux/backend PRs when ui has none", () => {
  const uxPr = { number: 501, checks: { state: "fail", source: "pr_head_rollup", total: 1, completed: 1 } };
  const adapted = live.adaptLiveBusiness({
    number: 99, productDecisionIssue: null,
    phaseIssues: { ui: null, ux: { number: 300 }, backend: null },
    currentPullRequests: { ui: null, ux: uxPr, backend: null },
  });
  assert.equal(adapted.pullRequest.number, 501);
  assert.equal(adapted.issue.number, 300, "falls through to phase Issues when no product Issue");
  assert.equal(adapted.checks.state, "fail");
});

test("adaptLiveBusiness passes legacy schemaVersion-1 payloads through unchanged", () => {
  const legacy = { number: 7, issue: { number: 1 }, pullRequest: { number: 2 }, checks: { state: "pass" } };
  assert.deepEqual(live.adaptLiveBusiness(legacy), legacy);
});

test("adaptLiveBusiness provides unavailable checks when no PR exists", () => {
  const adapted = live.adaptLiveBusiness({ number: 8, productDecisionIssue: { number: 9 }, currentPullRequests: { ui: null, ux: null, backend: null } });
  assert.equal(adapted.pullRequest, null);
  assert.equal(adapted.checks.state, "unavailable");
});

test("liveMapFromPayload adapts every Business entry", async () => {
  const result = await serviceResult(mockAggregateClient());
  const map = live.liveMapFromPayload(result.payload);
  assert.ok(map.get(15).pullRequest, "B15 adapted with primary PR");
  assert.equal(map.size, result.payload.businesses.length);
  for (const adapted of map.values()) {
    assert.ok("issue" in adapted && "pullRequest" in adapted && "checks" in adapted);
  }
});
