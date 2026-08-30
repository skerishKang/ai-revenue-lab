import test from 'node:test';
import assert from 'node:assert/strict';
import {
  AD_CLICK_FIRST_REQUIRED_CRITERIA,
  CENTRAL_AD_CLICK_TECHNICAL_CRITERIA,
  OWNER_LIVE_ACTIVATION_CRITERIA,
  CURRENT_AD_CLICK_FIRST_EVIDENCE,
  CURRENT_AD_CLICK_FIRST_READINESS,
  evaluateAdClickFirstReadiness,
  type AdClickFirstEvidenceState,
} from '../src/ad-click-first/gate-readiness.js';

test('current P0 gate separates CENTRAL technical work from deferred owner activation', () => {
  assert.equal(CURRENT_AD_CLICK_FIRST_READINESS.issueNumber, 1112);
  assert.equal(CURRENT_AD_CLICK_FIRST_READINESS.readiness, 'IN_PROGRESS');
  assert.equal(CURRENT_AD_CLICK_FIRST_READINESS.centralTechnicalReadiness, 'IN_PROGRESS');
  assert.equal(CURRENT_AD_CLICK_FIRST_READINESS.liveActivationReadiness, 'OWNER_ACTION_PENDING');
  assert.equal(CURRENT_AD_CLICK_FIRST_EVIDENCE.POLICY_CLEARED_REAL_SUPPLY, 'OWNER_ACTION');
  assert.equal(CURRENT_AD_CLICK_FIRST_EVIDENCE.LIVE_PROVIDER_FILL_OBSERVED, 'OWNER_ACTION');
  assert.equal(CURRENT_AD_CLICK_FIRST_EVIDENCE.SIGNED_REWARD_CALLBACK_OBSERVED, 'OWNER_ACTION');
});

test('implemented code is not silently promoted to runtime PASS evidence', () => {
  assert.equal(CURRENT_AD_CLICK_FIRST_EVIDENCE.DEFAULT_UI_IS_AD_CLICK_ONLY, 'IMPLEMENTED_NOT_RUNTIME_VERIFIED');
  assert.equal(CURRENT_AD_CLICK_FIRST_EVIDENCE.DUPLICATE_SUPPRESSION_WORKS, 'IMPLEMENTED_NOT_RUNTIME_VERIFIED');
  assert.equal(CURRENT_AD_CLICK_FIRST_EVIDENCE.ACCOUNT_OPTIONAL_RUNTIME_CONFIG_WORKS, 'IMPLEMENTED_NOT_RUNTIME_VERIFIED');
});

test('owner live-account actions do not block a separately complete CENTRAL technical milestone', () => {
  const evidence = Object.fromEntries(
    AD_CLICK_FIRST_REQUIRED_CRITERIA.map((criterion) => [
      criterion,
      CENTRAL_AD_CLICK_TECHNICAL_CRITERIA.includes(criterion as never) ? 'PASS' : 'OWNER_ACTION',
    ]),
  ) as AdClickFirstEvidenceState;
  const readiness = evaluateAdClickFirstReadiness(evidence);
  assert.equal(readiness.centralTechnicalComplete, true);
  assert.equal(readiness.liveActivationComplete, false);
  assert.equal(readiness.centralTechnicalReadiness, 'READY_FOR_CENTRAL_TECHNICAL_ACCEPTANCE');
  assert.equal(readiness.liveActivationReadiness, 'OWNER_ACTION_PENDING');
  assert.equal(readiness.readiness, 'TECHNICAL_COMPLETE_OWNER_ACTIVATION_PENDING');
  assert.deepEqual(readiness.centralTechnicalMissing, []);
  assert.deepEqual(readiness.ownerActions, OWNER_LIVE_ACTIVATION_CRITERIA);
});

test('all evidence PASS remains ready for separate CENTRAL acceptance', () => {
  const allPass = Object.fromEntries(AD_CLICK_FIRST_REQUIRED_CRITERIA.map((criterion) => [criterion, 'PASS'])) as AdClickFirstEvidenceState;
  const readiness = evaluateAdClickFirstReadiness(allPass);
  assert.equal(readiness.criteriaComplete, true);
  assert.equal(readiness.centralTechnicalComplete, true);
  assert.equal(readiness.liveActivationComplete, true);
  assert.equal(readiness.readiness, 'READY_FOR_CENTRAL_ACCEPTANCE');
  assert.equal(readiness.centralAcceptance, 'REQUIRED_SEPARATELY');
  assert.deepEqual(readiness.missing, []);
});
