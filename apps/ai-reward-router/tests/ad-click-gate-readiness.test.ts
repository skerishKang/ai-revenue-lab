import test from 'node:test';
import assert from 'node:assert/strict';
import {
  AD_CLICK_FIRST_REQUIRED_CRITERIA,
  CURRENT_AD_CLICK_FIRST_EVIDENCE,
  CURRENT_AD_CLICK_FIRST_READINESS,
  evaluateAdClickFirstReadiness,
  type AdClickFirstEvidenceState,
} from '../src/ad-click-first/gate-readiness.js';

test('current P0 gate remains in progress because live provider evidence is not yet available', () => {
  assert.equal(CURRENT_AD_CLICK_FIRST_READINESS.issueNumber, 1112);
  assert.equal(CURRENT_AD_CLICK_FIRST_READINESS.readiness, 'IN_PROGRESS');
  assert.equal(CURRENT_AD_CLICK_FIRST_READINESS.criteriaComplete, false);
  assert.equal(CURRENT_AD_CLICK_FIRST_EVIDENCE.POLICY_CLEARED_REAL_SUPPLY, 'BLOCKED');
  assert.equal(CURRENT_AD_CLICK_FIRST_EVIDENCE.LIVE_PROVIDER_FILL_OBSERVED, 'BLOCKED');
  assert.equal(CURRENT_AD_CLICK_FIRST_EVIDENCE.SIGNED_REWARD_CALLBACK_OBSERVED, 'BLOCKED');
});

test('authored code or tests cannot silently become PASS evidence', () => {
  assert.equal(CURRENT_AD_CLICK_FIRST_EVIDENCE.DEFAULT_UI_IS_AD_CLICK_ONLY, 'NOT_RUN');
  assert.equal(CURRENT_AD_CLICK_FIRST_EVIDENCE.DUPLICATE_SUPPRESSION_WORKS, 'NOT_RUN');
  assert.equal(CURRENT_AD_CLICK_FIRST_EVIDENCE.PROVIDER_TRACKING_IS_CONTRACT_BOUND, 'NOT_RUN');
});

test('even complete technical evidence only becomes ready for separate CENTRAL acceptance', () => {
  const allPass = Object.fromEntries(AD_CLICK_FIRST_REQUIRED_CRITERIA.map((criterion) => [criterion, 'PASS'])) as AdClickFirstEvidenceState;
  const readiness = evaluateAdClickFirstReadiness(allPass);
  assert.equal(readiness.criteriaComplete, true);
  assert.equal(readiness.readiness, 'READY_FOR_CENTRAL_ACCEPTANCE');
  assert.equal(readiness.centralAcceptance, 'REQUIRED_SEPARATELY');
  assert.deepEqual(readiness.missing, []);
});
