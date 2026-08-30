import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  CURRENT_SOURCE_COLLECTION_GATES,
  CURRENT_SOURCE_POLICY_REVIEWS,
  CURRENT_SOURCE_REGISTRY,
} from '../src/source-policy/registry.js';
import {
  canMarkVerified,
  guaranteedCompensationTotal,
  persistCollectionGate,
  persistPolicyReview,
  persistSource,
  sourceSnapshotDedupKey,
  validateOpportunityVersion,
  validateOpportunityWindow,
} from '../src/persistence/domain.js';
import {
  AI_DATA_WORK_FIXTURE,
  MATERIAL_CHANGE_FIXTURE,
  MICRO_REWARD_FIXTURE,
  PAID_RESEARCH_FIXTURE,
  SOURCE_HINT_INDEPENDENCE_FIXTURE,
  UNKNOWN_COMPENSATION_FIXTURE,
} from '../src/persistence/fixtures.js';

test('persists W1 source, policy, and gate semantics without granting permission', () => {
  const persistedSources = CURRENT_SOURCE_REGISTRY.map(persistSource);
  const persistedPolicies = CURRENT_SOURCE_POLICY_REVIEWS.map(persistPolicyReview);
  const persistedGates = CURRENT_SOURCE_COLLECTION_GATES.map(persistCollectionGate);

  assert.equal(persistedSources.length, 22);
  assert.equal(new Set(persistedSources.map((item) => item.sourceId)).size, 22);
  assert.equal(persistedPolicies.length, 22);
  assert.equal(new Set(persistedPolicies.map((item) => item.sourceId)).size, 22);
  assert.equal(persistedPolicies.filter((item) => item.decision === 'PASS').length, 0);
  assert.equal(persistedPolicies.filter((item) => item.decision === 'PENDING').length, 22);
  assert.equal(persistedGates.length, 176);

  for (const original of CURRENT_SOURCE_REGISTRY) {
    const persisted = persistedSources.find((item) => item.sourceId === original.sourceId);
    assert.ok(persisted);
    assert.equal(persisted.acquisitionMode, original.acquisitionMode);
    assert.deepEqual(persisted.opportunityClassHint, original.opportunityClassHint);
  }
});

test('reward and non-reward fixtures share the generalized Source to Version trust chain', () => {
  for (const fixture of [MICRO_REWARD_FIXTURE, PAID_RESEARCH_FIXTURE, AI_DATA_WORK_FIXTURE]) {
    assert.equal(fixture.snapshot.sourceId, fixture.opportunity.sourceId);
    assert.equal(fixture.opportunity.merchantId, null);
    assert.equal(fixture.versions[0]?.offerId, fixture.opportunity.id);
    assert.equal(fixture.versions[0]?.sourceSnapshotId, fixture.snapshot.id);
    assert.equal(fixture.reviewQueue[0]?.offerVersionId, fixture.versions[0]?.id);
    assert.equal(fixture.opportunity.currentVersionId, null);
  }

  assert.equal(MICRO_REWARD_FIXTURE.versions[0]?.opportunityCategory, 'PROMOTION');
  assert.equal(PAID_RESEARCH_FIXTURE.versions[0]?.opportunityCategory, 'MARKET_RESEARCH');
  assert.equal(AI_DATA_WORK_FIXTURE.versions[0]?.opportunityCategory, 'AI_EVALUATION');
});

test('snapshot deduplication uses source, canonical reference, and content hash rather than timestamp', () => {
  const first = MICRO_REWARD_FIXTURE.snapshot;
  const sameContentLater = { ...first, id: 'snap-later', acquiredAt: '2026-08-31T00:00:00.000Z' };
  const changedContent = { ...first, id: 'snap-changed', contentHash: 'sha256:changed' };

  assert.equal(sourceSnapshotDedupKey(first), sourceSnapshotDedupKey(sameContentLater));
  assert.notEqual(sourceSnapshotDedupKey(first), sourceSnapshotDedupKey(changedContent));
});

test('unknown compensation, probability, and supply stay null rather than becoming defaults', () => {
  const version = UNKNOWN_COMPENSATION_FIXTURE.versions[0];
  assert.ok(version);
  assert.equal(version.advertisedCompensationValue, null);
  assert.equal(version.expectedPayoutValue, null);
  assert.equal(version.compensationCurrency, null);
  assert.equal(version.qualificationProbability, null);
  assert.equal(version.supplyAvailabilityState, null);
  assert.equal(validateOpportunityVersion(version).length, 0);
});

test('material change preserves immutable history and requires review before replacing current version', () => {
  const [v1, v2] = MATERIAL_CHANGE_FIXTURE.versions;
  assert.ok(v1);
  assert.ok(v2);
  assert.equal(v1.versionNumber, 1);
  assert.equal(v2.versionNumber, 2);
  assert.equal(v1.verificationState, 'VERIFIED');
  assert.equal(v2.verificationState, 'REVIEW_REQUIRED');
  assert.equal(MATERIAL_CHANGE_FIXTURE.opportunity.currentVersionId, v1.id);
  assert.equal(MATERIAL_CHANGE_FIXTURE.change.previousVersionId, v1.id);
  assert.equal(MATERIAL_CHANGE_FIXTURE.change.newVersionId, v2.id);
  assert.equal(MATERIAL_CHANGE_FIXTURE.change.material, true);
  assert.equal(MATERIAL_CHANGE_FIXTURE.reviewQueue[0]?.offerVersionId, v2.id);
  assert.equal(canMarkVerified(v2, false), false);
  assert.equal(canMarkVerified(v2, true), true);
});

test('provider opportunity hint is not canonical opportunity-category authority', () => {
  assert.deepEqual(SOURCE_HINT_INDEPENDENCE_FIXTURE.providerHints, ['OFFERWALL', 'SURVEY']);
  assert.equal(SOURCE_HINT_INDEPENDENCE_FIXTURE.normalizedOpportunityCategory, 'MARKET_RESEARCH');
  assert.equal(SOURCE_HINT_INDEPENDENCE_FIXTURE.providerHints.includes(SOURCE_HINT_INDEPENDENCE_FIXTURE.normalizedOpportunityCategory), false);
  assert.equal(SOURCE_HINT_INDEPENDENCE_FIXTURE.evidenceBacked, true);
});

test('validation rejects negative values, invalid probability, and reversed windows', () => {
  const base = AI_DATA_WORK_FIXTURE.versions[0];
  assert.ok(base);
  const invalid = {
    ...base,
    advertisedCompensationValue: -1,
    estimatedActiveMinutes: -5,
    qualificationProbability: 1.5,
  };
  const errors = validateOpportunityVersion(invalid);
  assert.equal(errors.some((item) => item.includes('advertisedCompensationValue')), true);
  assert.equal(errors.some((item) => item.includes('estimatedActiveMinutes')), true);
  assert.equal(errors.some((item) => item.includes('qualificationProbability')), true);

  assert.deepEqual(validateOpportunityWindow({
    id: 'window-invalid', offerVersionId: base.id, windowType: 'APPLICATION',
    startAt: '2026-08-31T00:00:00.000Z', endAt: '2026-08-30T00:00:00.000Z',
    relativeRule: null, displayText: 'invalid', evidenceId: null,
  }), ['endAt must be >= startAt']);
});

test('prize components are excluded from guaranteed compensation totals', () => {
  const components = [
    { id: 'fixed', offerVersionId: 'v1', componentType: 'FIXED_PAY' as const, amount: 10, currency: 'USD', rateUnit: null, percent: null, capAmount: null, conditionText: null, evidenceId: null },
    { id: 'prize', offerVersionId: 'v1', componentType: 'PRIZE' as const, amount: 1000, currency: 'USD', rateUnit: null, percent: null, capAmount: null, conditionText: null, evidenceId: null },
  ];
  assert.equal(guaranteedCompensationTotal(components), 10);
  assert.equal(guaranteedCompensationTotal([components[1]!]), null);
});

test('W2 SQL migration is bounded to trust, inventory, evidence, and review persistence', () => {
  const sql = readFileSync(new URL('../../migrations/0001_w2_generalized_opportunity.sql', import.meta.url), 'utf8');
  const requiredTables = [
    'sources', 'source_endpoints', 'source_policy_reviews', 'source_collection_gates',
    'source_snapshots', 'merchants', 'offers', 'offer_versions', 'offer_evidence',
    'offer_requirements', 'offer_compensation_components', 'offer_windows', 'offer_changes',
    'review_queue', 'review_decisions',
  ];
  for (const table of requiredTables) {
    assert.match(sql, new RegExp(`CREATE TABLE ${table}\\b`, 'i'));
  }
  assert.doesNotMatch(sql, /CREATE TABLE\s+(users|user_preferences|recommendation_runs|recommendation_items|affiliate_clicks|conversions|conversion_events)\b/i);
  assert.match(sql, /merchant_id\s+TEXT\s+NULL/i);
  assert.match(sql, /qualification_probability\s+NUMERIC\s+NULL/i);
  assert.match(sql, /CHECK \(qualification_probability IS NULL OR \(qualification_probability >= 0 AND qualification_probability <= 1\)\)/i);
});
