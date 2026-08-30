import test from 'node:test';
import assert from 'node:assert/strict';
import { createAdminConsoleFixtureState } from '../src/admin-console/fixture-state.js';
import {
  buildDashboard,
  buildOpportunityReview,
  buildOpportunityRows,
  buildSourceRows,
  renderAdminRoute,
} from '../src/admin-console/read-model.js';
import { applyHealthCommand, applyReviewCommand } from '../src/admin-console/workflow.js';
import type { AdminRoute } from '../src/admin-console/domain.js';

const T1 = '2026-08-30T03:00:00.000Z';

test('W7 dashboard and source read models preserve generalized opportunity and acquisition semantics', () => {
  const state = createAdminConsoleFixtureState();
  const dashboard = buildDashboard(state);
  assert.ok(dashboard.reviewQueueCount >= 5);
  assert.equal(dashboard.materialChangesAwaitingApproval, 1);
  assert.ok((dashboard.categoryCounts.MARKET_RESEARCH ?? 0) >= 1);
  assert.ok((dashboard.ladderCounts.TASK_WORK ?? 0) >= 1);

  const sourceRows = buildSourceRows(state);
  const toss = sourceRows.find((row) => row.sourceId === 'SRC-TOSS');
  assert.ok(toss);
  assert.equal(toss.lane, 'BUILD');
  assert.equal(toss.acquisitionMode, 'MANUAL_CURATED_OFFICIAL_SOURCE');
});

test('opportunity list supports reward and non-reward income-pipeline fixtures without fabricated unknowns', () => {
  const rows = buildOpportunityRows(createAdminConsoleFixtureState());
  assert.equal(rows.some((row) => row.opportunityCategory === 'PROMOTION'), true);
  assert.equal(rows.some((row) => row.opportunityCategory === 'MARKET_RESEARCH'), true);
  assert.equal(rows.some((row) => row.opportunityCategory === 'AI_EVALUATION'), true);
  const unknown = rows.find((row) => row.offerId === 'offer-fixture-unknown');
  assert.ok(unknown);
  assert.equal(unknown.expectedPayoutValue, null);
  assert.equal(unknown.compensationCurrency, null);
});

test('review screen exposes evidence context, explicit NULL unknowns, and distinct trust-state labels', () => {
  const state = createAdminConsoleFixtureState();
  const promoReview = buildOpportunityReview(state, 'offer-fixture-promo-v1');
  assert.equal(promoReview.evidence.length, 1);
  assert.equal(promoReview.evidence[0]?.fieldPath, 'advertisedCompensationValue');
  const changeReview = buildOpportunityReview(state, 'offer-fixture-change-v2');
  assert.equal(changeReview.evidence[0]?.sourceSnapshotId, 'snap-fixture-change-2');

  const html = renderAdminRoute(state, 'OPPORTUNITY_REVIEW', 'offer-fixture-unknown-v1');
  assert.match(html, /NULL \/ UNKNOWN/);
  assert.match(html, /SOURCE POLICY PASS/);
  assert.match(html, /DATA VERIFIED/);
  assert.match(html, /HUMAN REVIEWED/);
  assert.match(html, /PARTNER APPROVED/);
  assert.match(html, /SEND BACK \/ RE-EXTRACT/);
});

test('APPROVE resolves the queue, verifies the version, points current version, and writes decision plus audit', () => {
  const state = createAdminConsoleFixtureState();
  const next = applyReviewCommand(state, {
    action: 'APPROVE', role: 'REVIEWER', actorId: 'reviewer-1', reviewQueueId: 'rq-promo',
    decisionId: 'decision-promo', auditId: 'audit-promo', reason: 'Source evidence checked', at: T1,
  });
  assert.equal(next.reviewQueue.find((item) => item.id === 'rq-promo')?.state, 'RESOLVED');
  assert.equal(next.versions.find((item) => item.id === 'offer-fixture-promo-v1')?.verificationState, 'VERIFIED');
  assert.equal(next.opportunities.find((item) => item.id === 'offer-fixture-promo')?.currentVersionId, 'offer-fixture-promo-v1');
  assert.equal(next.reviewDecisions.at(-1)?.decision, 'APPROVE');
  assert.equal(next.auditLog.at(-1)?.action, 'REVIEW_APPROVE');
});

test('MODIFY + APPROVE stores patch lineage and creates a new approved immutable canonical version', () => {
  const state = createAdminConsoleFixtureState();
  const source = state.versions.find((item) => item.id === 'offer-fixture-research-v1');
  assert.ok(source);
  const next = applyReviewCommand(state, {
    action: 'MODIFY_APPROVE', role: 'REVIEWER', actorId: 'reviewer-1', reviewQueueId: 'rq-research',
    decisionId: 'decision-research', auditId: 'audit-research', reason: 'Corrected evidence-backed title', at: T1,
    patchId: 'patch-research', resultingVersionId: 'offer-fixture-research-v2',
    patch: { title: 'Corrected synthetic paid research fixture' },
  });
  const result = next.versions.find((item) => item.id === 'offer-fixture-research-v2');
  assert.ok(result);
  assert.equal(result.versionNumber, source.versionNumber + 1);
  assert.equal(result.verificationState, 'VERIFIED');
  assert.equal(next.versions.find((item) => item.id === source.id)?.title, source.title);
  assert.equal(next.reviewPatches.at(-1)?.fromVersionId, source.id);
  assert.equal(next.reviewPatches.at(-1)?.resultingVersionId, result.id);
  assert.equal(next.opportunities.find((item) => item.id === source.offerId)?.currentVersionId, result.id);
});

test('reviewer patch cannot modify identity or verification fields', () => {
  const state = createAdminConsoleFixtureState();
  assert.throws(() => applyReviewCommand(state, {
    action: 'MODIFY_APPROVE', role: 'REVIEWER', actorId: 'reviewer-1', reviewQueueId: 'rq-research',
    decisionId: 'decision-forbidden', auditId: 'audit-forbidden', reason: 'Attempt forbidden mutation', at: T1,
    patchId: 'patch-forbidden', resultingVersionId: 'offer-fixture-research-v2', patch: { offerId: 'other-offer' },
  }), /non-term or identity fields/);
});

test('REJECT keeps an already-current historical version intact for a material-change review', () => {
  const state = createAdminConsoleFixtureState();
  const next = applyReviewCommand(state, {
    action: 'REJECT', role: 'REVIEWER', actorId: 'reviewer-1', reviewQueueId: 'rq-change-v2',
    decisionId: 'decision-change-reject', auditId: 'audit-change-reject', reason: 'New terms not accepted', at: T1,
  });
  const opportunity = next.opportunities.find((item) => item.id === 'offer-fixture-change');
  assert.equal(opportunity?.currentVersionId, 'offer-fixture-change-v1');
  assert.equal(next.versions.find((item) => item.id === 'offer-fixture-change-v1')?.verificationState, 'VERIFIED');
  assert.equal(next.versions.find((item) => item.id === 'offer-fixture-change-v2')?.verificationState, 'REJECTED');
});

test('material-change APPROVE moves current pointer only after human review while preserving prior version', () => {
  const state = createAdminConsoleFixtureState();
  const next = applyReviewCommand(state, {
    action: 'APPROVE', role: 'ADMIN', actorId: 'admin-1', reviewQueueId: 'rq-change-v2',
    decisionId: 'decision-change-approve', auditId: 'audit-change-approve', reason: 'Material diff verified', at: T1,
  });
  assert.equal(next.opportunities.find((item) => item.id === 'offer-fixture-change')?.currentVersionId, 'offer-fixture-change-v2');
  assert.equal(next.versions.find((item) => item.id === 'offer-fixture-change-v1')?.verificationState, 'VERIFIED');
  assert.equal(next.versions.find((item) => item.id === 'offer-fixture-change-v2')?.verificationState, 'VERIFIED');
});

test('RE-EXTRACT resolves the current queue without falsely verifying the candidate', () => {
  const state = createAdminConsoleFixtureState();
  const next = applyReviewCommand(state, {
    action: 'RE_EXTRACT', role: 'REVIEWER', actorId: 'reviewer-1', reviewQueueId: 'rq-ai',
    decisionId: 'unused', auditId: 'audit-ai-reextract', reason: 'Conflicting source wording', at: T1,
    reextractRequestId: 'reextract-ai-1',
  });
  assert.equal(next.reviewQueue.find((item) => item.id === 'rq-ai')?.state, 'RESOLVED');
  assert.equal(next.versions.find((item) => item.id === 'offer-fixture-ai-v1')?.verificationState, 'REVIEW_REQUIRED');
  assert.equal(next.reextractRequests.at(-1)?.sourceSnapshotId, 'snap-fixture-ai-1');
  assert.equal(next.reviewDecisions.length, 0);
});

test('role gates fail closed for review and stale/broken actions', () => {
  const state = createAdminConsoleFixtureState();
  assert.throws(() => applyReviewCommand(state, {
    action: 'APPROVE', role: 'VIEWER', actorId: 'viewer-1', reviewQueueId: 'rq-promo',
    decisionId: 'decision-viewer', auditId: 'audit-viewer', reason: 'Not allowed', at: T1,
  }), /cannot perform opportunity review actions/);
  assert.throws(() => applyHealthCommand(state, {
    action: 'SUPPRESS_OFFER', role: 'REVIEWER', actorId: 'reviewer-1', incidentId: 'stale-fixture-usertesting',
    auditId: 'audit-health-reviewer', reason: 'Not an operator action', at: T1,
  }), /cannot perform stale\/broken operations/);
});

test('stale suppression changes lifecycle without deleting historical version and always audits', () => {
  const state = createAdminConsoleFixtureState();
  const next = applyHealthCommand(state, {
    action: 'SUPPRESS_OFFER', role: 'OPERATOR', actorId: 'operator-1', incidentId: 'stale-fixture-usertesting',
    auditId: 'audit-stale-suppress', reason: 'Source is unavailable', at: T1,
  });
  assert.equal(next.opportunities.find((item) => item.id === 'offer-fixture-unknown')?.lifecycleState, 'STALE');
  assert.ok(next.versions.find((item) => item.id === 'offer-fixture-unknown-v1'));
  assert.equal(next.staleBroken.find((item) => item.id === 'stale-fixture-usertesting')?.state, 'RESOLVED');
  assert.equal(next.auditLog.at(-1)?.action, 'STALE_BROKEN_SUPPRESS_OFFER');
});

test('RETURN TO REVIEW reopens both version state and queue after a resolved prior review', () => {
  const initial = createAdminConsoleFixtureState();
  const rejected = applyReviewCommand(initial, {
    action: 'REJECT', role: 'REVIEWER', actorId: 'reviewer-1', reviewQueueId: 'rq-unknown',
    decisionId: 'decision-unknown-reject', auditId: 'audit-unknown-reject', reason: 'Insufficient evidence', at: T1,
  });
  const returned = applyHealthCommand(rejected, {
    action: 'RETURN_TO_REVIEW', role: 'OPERATOR', actorId: 'operator-1', incidentId: 'stale-fixture-usertesting',
    auditId: 'audit-unknown-return', reason: 'New evidence should be reviewed', at: T1,
    reviewQueueId: 'rq-unknown-returned',
  });
  assert.equal(returned.versions.find((item) => item.id === 'offer-fixture-unknown-v1')?.verificationState, 'REVIEW_REQUIRED');
  assert.equal(returned.opportunities.find((item) => item.id === 'offer-fixture-unknown')?.lifecycleState, 'REVIEW_REQUIRED');
  assert.equal(returned.reviewQueue.find((item) => item.id === 'rq-unknown-returned')?.state, 'OPEN');
});

test('all W7 P0 surfaces render deterministic operator pages', () => {
  const state = createAdminConsoleFixtureState();
  const routes: readonly AdminRoute[] = [
    'DASHBOARD', 'SOURCES', 'OPPORTUNITIES', 'REVIEW_QUEUE', 'OPPORTUNITY_REVIEW', 'CHANGES', 'STALE_BROKEN', 'AUDIT_LOG',
  ];
  for (const route of routes) {
    const html = renderAdminRoute(state, route);
    assert.match(html, /<!doctype html>/i);
    assert.match(html, /B64 Admin Console/);
    assert.match(html, /Trust states are separate/);
  }
});
