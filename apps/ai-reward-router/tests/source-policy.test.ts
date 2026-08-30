import test from 'node:test';
import assert from 'node:assert/strict';
import { ROUTING_MODES } from '../src/index.js';
import {
  CURRENT_SOURCE_COLLECTION_GATES,
  CURRENT_SOURCE_IDS,
  CURRENT_SOURCE_POLICY_REVIEWS,
  CURRENT_SOURCE_REGISTRY,
  gatesBySourceId,
  policyBySourceId,
  sourceById,
} from '../src/source-policy/registry.js';
import { effectiveAcquisitionDecision } from '../src/source-policy/decision.js';
import type { SourceCollectionGate, SourcePolicyReview } from '../src/source-policy/domain.js';

const expectedSourceIds = [
  'SRC-TOSS', 'SRC-NPAY', 'SRC-TMEM', 'SRC-CJONE', 'SRC-KB', 'SRC-SHINHAN',
  'SRC-LINKPRICE', 'SRC-AYET', 'SRC-ADISON', 'SRC-TNK', 'SRC-ADPOPCORN', 'SRC-CPX',
  'SRC-PROLIFIC', 'SRC-OUTLIER', 'SRC-CROWDGEN', 'SRC-TELUS', 'SRC-ONEFORMA',
  'SRC-CLICKWORKER', 'SRC-UTEST', 'SRC-USERTESTING', 'SRC-RESPONDENT', 'SRC-TOLOKA',
];

const review = (sourceId: string, overrides: Partial<SourcePolicyReview> = {}): SourcePolicyReview => ({
  ...policyBySourceId(sourceId),
  ...overrides,
});

test('fresh registry represents exactly the 22 current source identities once', () => {
  assert.deepEqual(CURRENT_SOURCE_IDS, expectedSourceIds);
  assert.equal(CURRENT_SOURCE_REGISTRY.length, 22);
  assert.equal(new Set(CURRENT_SOURCE_IDS).size, 22);
  assert.equal(CURRENT_SOURCE_POLICY_REVIEWS.length, 22);
  assert.equal(new Set(CURRENT_SOURCE_POLICY_REVIEWS.map((item) => item.sourceId)).size, 22);
  assert.equal(CURRENT_SOURCE_COLLECTION_GATES.length, 22 * 8);
  assert.equal(new Set(CURRENT_SOURCE_COLLECTION_GATES.map((item) => item.sourceId)).size, 22);
});

test('acquisition modes and opportunity hints are preserved as source metadata', () => {
  assert.equal(sourceById('SRC-TOSS').acquisitionMode, 'MANUAL_CURATED_OFFICIAL_SOURCE');
  assert.equal(sourceById('SRC-CPX').acquisitionMode, 'PARTNER_API');
  assert.equal(sourceById('SRC-PROLIFIC').acquisitionMode, 'DEEP_LINK_OR_DIRECTORY');
  assert.equal(sourceById('SRC-KB').acquisitionMode, 'SHADOW_ONLY');
  assert.deepEqual(sourceById('SRC-TOLOKA').opportunityClassHint, ['MICROTASK', 'DATA_ANNOTATION']);
  for (const source of CURRENT_SOURCE_REGISTRY) {
    assert.notEqual(source.opportunityClassHint.includes(ROUTING_MODES.TODAY_ROUTE), true);
    assert.notEqual(source.opportunityClassHint.includes(ROUTING_MODES.INCOME_PIPELINE), true);
  }
});

test('fresh policy state has zero PASS decisions and unknown permission facts', () => {
  assert.equal(CURRENT_SOURCE_POLICY_REVIEWS.filter((item) => item.decision === 'PASS').length, 0);
  assert.equal(CURRENT_SOURCE_POLICY_REVIEWS.filter((item) => item.decision === 'PENDING').length, 22);
  for (const policy of CURRENT_SOURCE_POLICY_REVIEWS) {
    assert.equal(policy.automationPermission, 'UNKNOWN');
  }
});

test('Toss manual curation is allowed only as MANUAL_ONLY; automation is blocked', () => {
  const source = sourceById('SRC-TOSS');
  const policy = policyBySourceId('SRC-TOSS');
  const gates = gatesBySourceId('SRC-TOSS');
  assert.equal(effectiveAcquisitionDecision({ source, policy, gates, attempt: 'AUTOMATED' }), 'BLOCK');
  assert.equal(effectiveAcquisitionDecision({ source, policy, gates, attempt: 'MANUAL_CURATED' }), 'MANUAL_ONLY');
});

test('CPX pending partner onboarding blocks live API behavior', () => {
  const source = sourceById('SRC-CPX');
  assert.equal(effectiveAcquisitionDecision({ source, policy: policyBySourceId('SRC-CPX'), gates: gatesBySourceId('SRC-CPX'), attempt: 'AUTOMATED', credentialsAvailable: false }), 'BLOCK');
});

test('Prolific deep link is manual-only and never an automated feed', () => {
  const source = sourceById('SRC-PROLIFIC');
  const policy = policyBySourceId('SRC-PROLIFIC');
  const gates = gatesBySourceId('SRC-PROLIFIC');
  assert.equal(effectiveAcquisitionDecision({ source, policy, gates, attempt: 'DIRECTORY' }), 'MANUAL_ONLY');
  assert.equal(effectiveAcquisitionDecision({ source, policy, gates, attempt: 'AUTOMATED' }), 'BLOCK');
});

test('KB shadow source never becomes ordinary user-visible supply', () => {
  const source = sourceById('SRC-KB');
  assert.equal(effectiveAcquisitionDecision({ source, policy: policyBySourceId('SRC-KB'), gates: gatesBySourceId('SRC-KB'), attempt: 'AUTOMATED' }), 'SHADOW_ONLY');
  assert.equal(effectiveAcquisitionDecision({ source, policy: policyBySourceId('SRC-KB'), gates: gatesBySourceId('SRC-KB'), attempt: 'SHADOW' }), 'SHADOW_ONLY');
});

test('Toloka HOLD blocks active directory behavior', () => {
  const source = sourceById('SRC-TOLOKA');
  assert.equal(effectiveAcquisitionDecision({ source, policy: policyBySourceId('SRC-TOLOKA'), gates: gatesBySourceId('SRC-TOLOKA'), attempt: 'DIRECTORY' }), 'BLOCK');
});

test('unknown permission, BUILD lane, missing gates, and shadow failures fail closed', () => {
  const source = sourceById('SRC-CPX');
  const base = { source, attempt: 'AUTOMATED' as const, credentialsAvailable: true };
  const allowed = review('SRC-CPX', { decision: 'PASS', automationPermission: 'ALLOWED' });
  assert.equal(effectiveAcquisitionDecision({ ...base, policy: allowed, gates: gatesBySourceId('SRC-CPX') }), 'BLOCK');
  const passedGates: SourceCollectionGate[] = gatesBySourceId('SRC-CPX').map((gate) => ({ ...gate, status: 'PASS' }));
  assert.equal(effectiveAcquisitionDecision({ ...base, policy: allowed, gates: passedGates }), 'AUTOMATED_ALLOWED');
  assert.equal(effectiveAcquisitionDecision({ ...base, policy: review('SRC-CPX', { decision: 'PASS' }), gates: passedGates }), 'BLOCK');
  const shadowFailure: SourceCollectionGate[] = passedGates.map((gate, index) => index === 4 ? { ...gate, status: 'FAIL' } : gate);
  assert.equal(effectiveAcquisitionDecision({ ...base, policy: allowed, gates: shadowFailure }), 'SHADOW_ONLY');
});

test('a required BLOCK gate prevents collection even with policy and credentials', () => {
  const source = sourceById('SRC-CPX');
  const policy = review('SRC-CPX', { decision: 'PASS', automationPermission: 'ALLOWED' });
  const gates: SourceCollectionGate[] = gatesBySourceId('SRC-CPX').map((gate) => ({ ...gate, status: 'PASS' }));
  const firstGate = gates[0];
  if (!firstGate) throw new Error('Expected CPX collection gate');
  gates[0] = { ...firstGate, status: 'FAIL' };
  assert.equal(effectiveAcquisitionDecision({ source, policy, gates, attempt: 'AUTOMATED', credentialsAvailable: true }), 'BLOCK');
});
