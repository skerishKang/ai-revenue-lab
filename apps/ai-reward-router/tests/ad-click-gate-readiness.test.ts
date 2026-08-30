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

test('current P0 gate records CENTRAL technical completion while owner live activation stays deferred', () => {
  assert.equal(CURRENT_AD_CLICK_FIRST_READINESS.issueNumber, 1112);
  assert.equal(CURRENT_AD_CLICK_FIRST_READINESS.readiness, 'TECHNICAL_COMPLETE_OWNER_ACTIVATION_PENDING');
  assert.equal(CURRENT_AD_CLICK_FIRST_READINESS.centralTechnicalComplete, true);
  assert.equal(CURRENT_AD_CLICK_FIRST_READINESS.centralTechnicalReadiness, 'READY_FOR_CENTRAL_TECHNICAL_ACCEPTANCE');
  assert.equal(CURRENT_AD_CLICK_FIRST_READINESS.liveActivationComplete, false);
  assert.equal(CURRENT_AD_CLICK_FIRST_READINESS.liveActivationReadiness, 'OWNER_ACTION_PENDING');
  assert.deepEqual(CURRENT_AD_CLICK_FIRST_READINESS.centralTechnicalMissing, []);
  assert.deepEqual(CURRENT_AD_CLICK_FIRST_READINESS.ownerActions, OWNER_LIVE_ACTIVATION_CRITERIA);
});

test('every current CENTRAL technical criterion is runtime-PASS evidence', () => {
  for (const criterion of CENTRAL_AD_CLICK_TECHNICAL_CRITERIA) {
    assert.equal(CURRENT_AD_CLICK_FIRST_EVIDENCE[criterion], 'PASS', criterion);
  }
});

test('all live-account and real-supply criteria remain OWNER_ACTION, never synthetic PASS', () => {
  for (const criterion of OWNER_LIVE_ACTIVATION_CRITERIA) {
    assert.equal(CURRENT_AD_CLICK_FIRST_EVIDENCE[criterion], 'OWNER_ACTION', criterion);
  }
  assert.equal(CURRENT_AD_CLICK_FIRST_EVIDENCE.POLICY_CLEARED_REAL_SUPPLY, 'OWNER_ACTION');
  assert.equal(CURRENT_AD_CLICK_FIRST_EVIDENCE.LIVE_PROVIDER_FILL_OBSERVED, 'OWNER_ACTION');
  assert.equal(CURRENT_AD_CLICK_FIRST_EVIDENCE.SIGNED_REWARD_CALLBACK_OBSERVED, 'OWNER_ACTION');
  assert.equal(CURRENT_AD_CLICK_FIRST_EVIDENCE.LIVE_EXTERNAL_REWARD_FULFILLMENT_OBSERVED, 'OWNER_ACTION');
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
