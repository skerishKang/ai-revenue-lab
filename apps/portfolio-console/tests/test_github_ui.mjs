import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const ui = require(path.resolve(HERE, "../github-live-status.js"));

const staticBusinesses = [
  { number: 1, progress: 82, priority: 100, githubLabel: "Draft PR #111", nextAction: "Static CTO decision" },
  { number: 9, progress: 25, priority: 58, githubLabel: "UI_APPROVED · Draft PR #175", nextAction: "Keep PR #175 Draft pending separate authorization" }
];

function payload() {
  return {
    ok: true,
    schemaVersion: 1,
    syncedAt: "2026-07-27T00:00:00Z",
    stale: false,
    businesses: [
      { number: 1, connectionState: "connected", issue: { number: 108, state: "open" }, pullRequest: { number: 111, state: "open", draft: true, merged: false }, checks: { state: "pending" } },
      { number: 9, connectionState: "connected", issue: { number: 170, state: "open" }, pullRequest: { number: 175, state: "open", draft: true, merged: false }, checks: { state: "pass" } }
    ]
  };
}

test("CONFIGURATION_MISSING keeps the static fallback payload", () => {
  const current = { ok: true, businesses: [{ number: 1 }] };
  const missing = { ok: false, error: { code: "CONFIGURATION_MISSING" }, businesses: [] };
  assert.equal(ui.acceptPayload(current, missing), current);
  assert.equal(ui.acceptPayload(null, missing), null);
});

test("live response merges strictly by Business number", () => {
  const merged = ui.mergeLiveByBusinessNumber(staticBusinesses, payload());
  assert.equal(merged[0].liveGithub.pullRequest.number, 111);
  assert.equal(merged[1].liveGithub.pullRequest.number, 175);
});

test("Korean and English live labels are deterministic", () => {
  assert.equal(ui.labelsFor("ko").checksPass, "검사 통과");
  assert.equal(ui.labelsFor("ko").draftPr, "PR 초안");
  assert.equal(ui.labelsFor("en").checksPass, "CHECKS PASS");
  assert.equal(ui.labelsFor("en").draftPr, "DRAFT PR");
});

test("B01 live Draft PR summary is compact", () => {
  const summary = ui.liveSummary(payload().businesses[0], payload(), "en");
  assert.equal(summary.connection, "SYNCED");
  assert.equal(summary.primary, "DRAFT PR #111");
  assert.equal(summary.checks, "CHECKS PENDING");
});

test("B09 preserves UI_APPROVED static judgment beside live Draft facts", () => {
  const business = ui.mergeLiveByBusinessNumber(staticBusinesses, payload()).find((item) => item.number === 9);
  assert.equal(business.githubLabel, "UI_APPROVED · Draft PR #175");
  assert.match(business.nextAction, /separate authorization/);
  assert.equal(business.liveGithub.pullRequest.state, "open");
  assert.equal(business.liveGithub.pullRequest.draft, true);
  assert.equal(business.liveGithub.pullRequest.merged, false);
});

test("live merge never overwrites progress, priority, or nextAction", () => {
  const merged = ui.mergeLiveByBusinessNumber(staticBusinesses, payload());
  for (let index = 0; index < staticBusinesses.length; index += 1) {
    assert.equal(merged[index].progress, staticBusinesses[index].progress);
    assert.equal(merged[index].priority, staticBusinesses[index].priority);
    assert.equal(merged[index].nextAction, staticBusinesses[index].nextAction);
  }
});

test("stale state has a distinct user-facing label", () => {
  const stale = { ...payload(), stale: true };
  assert.equal(ui.liveSummary(stale.businesses[0], stale, "ko").connection, "오래된 정보");
});

test("unmapped state remains unavailable rather than pass", () => {
  const live = { number: 15, connectionState: "unmapped", issue: null, pullRequest: null, checks: { state: "unavailable" } };
  const summary = ui.liveSummary(live, payload(), "en");
  assert.equal(summary.connection, "UNMAPPED");
  assert.equal(summary.checks, "CHECKS UNAVAILABLE");
});
