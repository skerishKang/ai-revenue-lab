import test from 'node:test';
import assert from 'node:assert/strict';
import { assessPayoutClaim, buildEligiblePayoutBatch } from '../src/ad-click-first/payout-policy.js';
import type { RewardStateRecord } from '../src/ad-click-first/reward-events.js';

const confirmed: RewardStateRecord = {
  providerId: 'SRC-AYET',
  providerTransactionId: 'tx-1',
  externalUserId: 'user-1',
  amount: 10,
  unit: 'POINT',
  state: 'CONFIRMED',
  firstObservedAt: '2026-08-30T12:00:00.000Z',
  lastObservedAt: '2026-08-30T12:00:01.000Z',
  cashCustodyAction: 'NONE',
};

const readyPolicy = {
  riskHoldUntil: '2026-08-30T13:00:00.000Z',
  riskHoldAuthority: 'APPROVED_PROVIDER_SPECIFIC_RISK_POLICY',
  externalMinimumAmount: 1,
  externalMinimumCurrency: 'USD',
  payoutFaceValueAmount: 1,
  payoutFaceValueCurrency: 'USD',
} as const;

test('provider confirmation alone never makes a payout claim immediately claimable', () => {
  const assessment = assessPayoutClaim({
    transaction: confirmed,
    policy: { ...readyPolicy, riskHoldUntil: null, riskHoldAuthority: null },
    now: '2026-08-30T14:00:00.000Z',
  });
  assert.equal(assessment.state, 'CONFIRMED_RISK_HOLD');
  assert.equal(assessment.mayEnterExternalFulfillment, false);
  assert.equal(assessment.reasons.includes('RISK_HOLD_POLICY_NOT_ESTABLISHED'), true);
  assert.equal(assessment.b64CashCustody, false);
  assert.equal(assessment.userDepositsAccepted, false);
  assert.equal(assessment.peerToPeerTransferAllowed, false);
});

test('a configured provider risk hold must expire before external fulfillment', () => {
  const assessment = assessPayoutClaim({
    transaction: confirmed,
    policy: readyPolicy,
    now: '2026-08-30T12:30:00.000Z',
  });
  assert.equal(assessment.state, 'CONFIRMED_RISK_HOLD');
  assert.equal(assessment.reasons.includes('RISK_HOLD_NOT_EXPIRED'), true);
});

test('live external payout denomination and face value must be established', () => {
  const assessment = assessPayoutClaim({
    transaction: confirmed,
    policy: { ...readyPolicy, externalMinimumAmount: null },
    now: '2026-08-30T14:00:00.000Z',
  });
  assert.equal(assessment.state, 'CONFIRMED_BELOW_EXTERNAL_MINIMUM');
  assert.equal(assessment.reasons.includes('LIVE_PAYOUT_DENOMINATION_OR_FACE_VALUE_NOT_ESTABLISHED'), true);
});

test('face value below the live external product minimum stays unfulfilled', () => {
  const assessment = assessPayoutClaim({
    transaction: confirmed,
    policy: { ...readyPolicy, externalMinimumAmount: 5, payoutFaceValueAmount: 1 },
    now: '2026-08-30T14:00:00.000Z',
  });
  assert.equal(assessment.state, 'CONFIRMED_BELOW_EXTERNAL_MINIMUM');
  assert.equal(assessment.reasons.includes('PAYOUT_FACE_VALUE_BELOW_LIVE_EXTERNAL_MINIMUM'), true);
});

test('only fully risk-cleared claims with a valid live payout denomination become externally fulfillable', () => {
  const assessment = assessPayoutClaim({
    transaction: confirmed,
    policy: readyPolicy,
    now: '2026-08-30T14:00:00.000Z',
  });
  assert.equal(assessment.state, 'ELIGIBLE_FOR_EXTERNAL_FULFILLMENT');
  assert.equal(assessment.mayEnterExternalFulfillment, true);
  assert.deepEqual(assessment.reasons, []);
});

test('reversed or provisional provider state never enters a payout batch', () => {
  const ready = assessPayoutClaim({ transaction: confirmed, policy: readyPolicy, now: '2026-08-30T14:00:00.000Z' });
  const reversed = assessPayoutClaim({ transaction: { ...confirmed, state: 'REVERSED' }, policy: readyPolicy, now: '2026-08-30T14:00:00.000Z' });
  const pending = assessPayoutClaim({ transaction: { ...confirmed, state: 'PENDING_PROVIDER_CONFIRMATION' }, policy: readyPolicy, now: '2026-08-30T14:00:00.000Z' });
  const batch = buildEligiblePayoutBatch([
    { claimId: 'ready', externalUserId: 'user-1', assessment: ready, payoutFaceValueAmount: 1, payoutFaceValueCurrency: 'USD' },
    { claimId: 'reversed', externalUserId: 'user-1', assessment: reversed, payoutFaceValueAmount: 1, payoutFaceValueCurrency: 'USD' },
    { claimId: 'pending', externalUserId: 'user-1', assessment: pending, payoutFaceValueAmount: 1, payoutFaceValueCurrency: 'USD' },
  ]);
  assert.deepEqual(batch.map((item) => item.claimId), ['ready']);
});
