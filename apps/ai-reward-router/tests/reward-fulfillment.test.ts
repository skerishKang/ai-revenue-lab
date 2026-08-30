import test from 'node:test';
import assert from 'node:assert/strict';
import {
  REWARD_FULFILLMENT_PROVIDER_STRATEGY,
  TREMENDOUS_B64_GO_LIVE_REQUIREMENTS,
  assessRewardFulfillment,
  buildTremendousRewardOrderDraft,
} from '../src/ad-click-first/reward-fulfillment.js';
import type { RewardStateRecord } from '../src/ad-click-first/reward-events.js';

const confirmed: RewardStateRecord = {
  providerId: 'ADSCEND_MEDIA',
  providerTransactionId: 'tx-123',
  externalUserId: 'user-123',
  amount: 100,
  unit: 'POINT',
  state: 'CONFIRMED',
  firstObservedAt: '2026-08-30T12:00:00.000Z',
  lastObservedAt: '2026-08-30T12:00:01.000Z',
  cashCustodyAction: 'NONE',
};

test('Tremendous is the first Korea external fulfillment candidate and remains non-live', () => {
  const tremendous = REWARD_FULFILLMENT_PROVIDER_STRATEGY[0];
  assert.equal(tremendous?.providerId, 'TREMENDOUS');
  assert.equal(tremendous?.rank, 1);
  assert.deepEqual(tremendous?.koreaRewardOptions, ['NAVER_PAY', 'TEENCASH', 'PAYPAL_INTERNATIONAL', 'VIRTUAL_VISA']);
  assert.equal(tremendous?.activateForB64, false);
});

test('provisional or reversed ad rewards can never create an external payout order', () => {
  for (const state of ['PENDING_PROVIDER_CONFIRMATION', 'REVERSED'] as const) {
    const result = assessRewardFulfillment({
      transaction: { ...confirmed, state },
      rewardFaceValue: 1,
      rewardCurrency: 'USD',
      externalFulfillmentProviderApproved: true,
      payoutPolicyApproved: true,
      chargebackReservePolicyReady: true,
    });
    assert.equal(result.state, 'BLOCKED_NOT_PROVIDER_CONFIRMED');
    assert.equal(result.mayCreateExternalRewardOrder, false);
    assert.equal(result.b64UserCashCustody, false);
  }
});

test('confirmed reward still waits for provider approval, payout policy and chargeback controls', () => {
  const providerBlocked = assessRewardFulfillment({
    transaction: confirmed,
    rewardFaceValue: 1,
    rewardCurrency: 'USD',
    externalFulfillmentProviderApproved: false,
    payoutPolicyApproved: true,
    chargebackReservePolicyReady: true,
  });
  assert.equal(providerBlocked.state, 'BLOCKED_PROVIDER_NOT_APPROVED');

  const payoutBlocked = assessRewardFulfillment({
    transaction: confirmed,
    rewardFaceValue: 1,
    rewardCurrency: 'USD',
    externalFulfillmentProviderApproved: true,
    payoutPolicyApproved: false,
    chargebackReservePolicyReady: true,
  });
  assert.equal(payoutBlocked.state, 'BLOCKED_PAYOUT_POLICY_NOT_READY');

  const chargebackBlocked = assessRewardFulfillment({
    transaction: confirmed,
    rewardFaceValue: 1,
    rewardCurrency: 'USD',
    externalFulfillmentProviderApproved: true,
    payoutPolicyApproved: true,
    chargebackReservePolicyReady: false,
  });
  assert.equal(chargebackBlocked.state, 'BLOCKED_CHARGEBACK_RISK_NOT_READY');
});

test('external fulfillment becomes order-eligible only after all payout controls pass', () => {
  const result = assessRewardFulfillment({
    transaction: confirmed,
    rewardFaceValue: 1,
    rewardCurrency: 'USD',
    externalFulfillmentProviderApproved: true,
    payoutPolicyApproved: true,
    chargebackReservePolicyReady: true,
  });
  assert.equal(result.state, 'READY_FOR_EXTERNAL_FULFILLMENT');
  assert.equal(result.mayCreateExternalRewardOrder, true);
  assert.equal(result.b64UserCashCustody, false);
});

test('Tremendous order draft uses provider transaction identity for idempotency and keeps token server-side', () => {
  const order = buildTremendousRewardOrderDraft({
    transaction: confirmed,
    recipientEmail: 'user@example.com',
    amount: 1,
    currency: 'usd',
    campaignId: 'campaign-kr-rewards',
  });
  assert.equal(order.externalId, 'b64-ADSCEND_MEDIA-tx-123');
  assert.equal(order.currency, 'USD');
  assert.equal(order.accessTokenExposure, 'SERVER_SIDE_ONLY');
  assert.equal(order.idempotencyKeySource, 'AD_PROVIDER_TRANSACTION_ID');
  assert.equal(TREMENDOUS_B64_GO_LIVE_REQUIREMENTS.length, 10);
});
