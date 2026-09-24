import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { applyVerifiedCompletion } from '../src/ledger.js';
import { verifySignedCompletionEvent } from '../src/signed-completion.js';
import type { CompletionLedgerRecord, SignedCompletionEvent, TryoutOffer } from '../src/domain.js';
import type { VerifiedCompletionEnvelope } from '../src/signed-completion.js';

const offer: TryoutOffer = {
  offerId: 'offer-1', providerId: 'SRC-B65-DEMO', actionType: 'TRYOUT_COMPLETED', rewardAmountMinor: 500,
  rewardCurrency: 'KRW', perUserLimit: 1, fundedBudgetMinor: 1000, startsAt: '2026-09-25T00:00:00.000Z',
  endsAt: '2026-09-30T00:00:00.000Z', state: 'ACTIVE',
};
const event: SignedCompletionEvent = {
  providerId: offer.providerId, offerId: offer.offerId, providerTransactionId: 'tx-1', externalUserId: 'user-1',
  actionType: offer.actionType, eventType: 'COMPLETED', rewardAmountMinor: 500, rewardCurrency: 'KRW',
  occurredAt: '2026-09-25T01:00:00.000Z', nonce: 'nonce-1',
};
const observedAt = '2026-09-25T01:00:01.000Z';

function envelope(value: SignedCompletionEvent): VerifiedCompletionEnvelope {
  const rawBody = JSON.stringify(value);
  const signedTimestamp = String(Date.parse(observedAt));
  const secret = 'test-only-b65-ledger-secret';
  const signatureHeader = `v1=${createHmac('sha256', secret).update(`${signedTimestamp}.${rawBody}`).digest('hex')}`;
  const result = verifySignedCompletionEvent({ providerId: value.providerId, rawBody, signedTimestamp, signatureHeader, secret, now: observedAt, maxAgeMs: 1000 });
  assert.equal(result.accepted, true);
  if (!result.accepted) throw new Error('test envelope was rejected');
  return result.envelope;
}

test('credits one verified completed action', () => {
  const result = applyVerifiedCompletion([], offer, envelope(event), observedAt);
  assert.equal(result.decision, 'CREDIT_COMPLETED_ACTION');
  assert.equal(result.balanceDeltaMinor, 500);
  assert.equal(result.next?.state, 'COMPLETED');
  assert.equal(result.externalPayoutAllowed, false);
});

test('click and visit events never settle points', () => {
  assert.equal(applyVerifiedCompletion([], offer, envelope({ ...event, actionType: 'CLICK' }), observedAt).decision, 'REJECT_CLICK_OR_VISIT');
  assert.equal(applyVerifiedCompletion([], offer, envelope({ ...event, actionType: 'VISIT' }), observedAt).decision, 'REJECT_CLICK_OR_VISIT');
});

test('duplicate completion is idempotent and reversal preserves history', () => {
  const created = applyVerifiedCompletion([], offer, envelope(event), observedAt).next!;
  const duplicate = applyVerifiedCompletion([created], offer, envelope(event), observedAt);
  assert.equal(duplicate.decision, 'IGNORE_IDEMPOTENT_DUPLICATE');
  assert.equal(duplicate.balanceDeltaMinor, 0);

  const reversed = applyVerifiedCompletion([created], offer, envelope({ ...event, eventType: 'REVERSED' }), observedAt);
  assert.equal(reversed.decision, 'REVERSE_COMPLETED_ACTION');
  assert.equal(reversed.balanceDeltaMinor, -500);
  assert.equal(reversed.next?.state, 'REVERSED');
  const reopen = applyVerifiedCompletion([reversed.next!], offer, envelope(event), observedAt);
  assert.equal(reopen.decision, 'REJECT_REOPEN_AFTER_REVERSAL');
});

test('rejects mismatch, inactive offer, per-user limit, and exhausted budget', () => {
  assert.equal(applyVerifiedCompletion([], offer, envelope({ ...event, rewardAmountMinor: 999 }), observedAt).decision, 'REJECT_IDENTITY_OR_VALUE_MISMATCH');
  assert.equal(applyVerifiedCompletion([], { ...offer, state: 'PAUSED' }, envelope(event), observedAt).decision, 'REJECT_OFFER_NOT_ACTIVE');

  const first = applyVerifiedCompletion([], { ...offer, perUserLimit: 1 }, envelope(event), observedAt).next!;
  const second = { ...event, providerTransactionId: 'tx-2', nonce: 'nonce-2' };
  assert.equal(applyVerifiedCompletion([first], offer, envelope(second), observedAt).decision, 'REJECT_PER_USER_LIMIT');

  const otherUser: CompletionLedgerRecord = { ...first, externalUserId: 'user-2', providerTransactionId: 'tx-other-user' };
  assert.equal(applyVerifiedCompletion([otherUser], { ...offer, fundedBudgetMinor: 500 }, envelope(event), observedAt).decision, 'REJECT_FUNDED_BUDGET_EXHAUSTED');
});

test('orphan reversal fails closed', () => {
  assert.equal(applyVerifiedCompletion([], offer, envelope({ ...event, eventType: 'REVERSED' }), observedAt).decision, 'REJECT_ORPHAN_REVERSAL');
});

test('reversal remains available after offer expiry or pause', () => {
  const created = applyVerifiedCompletion([], offer, envelope(event), observedAt).next!;
  for (const state of ['EXPIRED', 'PAUSED'] as const) {
    const result = applyVerifiedCompletion([created], { ...offer, state }, envelope({ ...event, eventType: 'REVERSED' }), observedAt);
    assert.equal(result.decision, 'REVERSE_COMPLETED_ACTION');
    assert.equal(result.next?.state, 'REVERSED');
  }
});

test('invalid configuration and amount types fail closed', () => {
  for (const invalidOffer of [
    { ...offer, perUserLimit: Number.NaN },
    { ...offer, fundedBudgetMinor: Number.POSITIVE_INFINITY },
    { ...offer, rewardAmountMinor: 500.5 },
    { ...offer, startsAt: 'not-a-date' },
    { ...offer, endsAt: 'not-a-date' },
  ]) {
    assert.equal(applyVerifiedCompletion([], invalidOffer, envelope(event), observedAt).decision, 'REJECT_INVALID_EVENT');
  }
  assert.equal(applyVerifiedCompletion([], offer, envelope({ ...event, providerId: 'OTHER' }), observedAt).decision, 'REJECT_OFFER_IDENTITY_MISMATCH');
  assert.equal(applyVerifiedCompletion([], { ...offer, actionType: 'QUALITY_CHECK_COMPLETED' }, envelope(event), observedAt).decision, 'REJECT_IDENTITY_OR_VALUE_MISMATCH');
});

test('rejects return no writable state and invalid observedAt never passes', () => {
  const created = applyVerifiedCompletion([], offer, envelope(event), observedAt).next!;
  const mismatch = applyVerifiedCompletion([created], offer, envelope({ ...event, rewardAmountMinor: 999 }), observedAt);
  assert.equal(mismatch.decision, 'REJECT_IDENTITY_OR_VALUE_MISMATCH');
  assert.equal(mismatch.next, null);
  assert.equal(applyVerifiedCompletion([], offer, envelope(event), 'not-a-date').decision, 'REJECT_INVALID_EVENT');
});

test('reverses an existing completion after offer pause or expiry', () => {
  const created = applyVerifiedCompletion([], offer, envelope(event), observedAt).next!;
  const paused = applyVerifiedCompletion([created], { ...offer, state: 'PAUSED' }, envelope({ ...event, eventType: 'REVERSED' }), '2026-10-01T00:00:00.000Z');
  assert.equal(paused.decision, 'REVERSE_COMPLETED_ACTION');
  const expired = applyVerifiedCompletion([created], { ...offer, state: 'EXPIRED' }, envelope({ ...event, eventType: 'REVERSED' }), '2026-10-01T00:00:00.000Z');
  assert.equal(expired.decision, 'REVERSE_COMPLETED_ACTION');
});

test('rejects invalid structural values and keeps rejected state empty', () => {
  const invalidOffer = { ...offer, fundedBudgetMinor: Number.NaN };
  assert.deepEqual(applyVerifiedCompletion([], invalidOffer, envelope(event), observedAt).next, null);
  assert.deepEqual(applyVerifiedCompletion([], { ...offer, endsAt: offer.startsAt }, envelope(event), observedAt).next, null);
  const invalidEvent = { ...event, actionType: 'CLICK' as const };
  assert.equal(applyVerifiedCompletion([], offer, envelope(invalidEvent), observedAt).decision, 'REJECT_CLICK_OR_VISIT');
  assert.equal(applyVerifiedCompletion([], offer, envelope({ ...event, actionType: 'QUALITY_CHECK_COMPLETED' }), observedAt).decision, 'REJECT_IDENTITY_OR_VALUE_MISMATCH');
});

test('rejects a structurally valid but unsigned envelope', () => {
  const forged = { event, signature: { algorithm: 'HMAC_SHA256', version: 'v1', verified: true, rawBodyBound: true } } as unknown as VerifiedCompletionEnvelope;
  assert.equal(applyVerifiedCompletion([], offer, forged, observedAt).decision, 'REJECT_INVALID_EVENT');
});

test('isolates budget usage by provider and currency', () => {
  const first = applyVerifiedCompletion([], offer, envelope(event), observedAt).next!;
  const foreignRecord = { ...first, providerId: 'OTHER', rewardCurrency: 'USD' };
  assert.equal(applyVerifiedCompletion([foreignRecord], { ...offer, fundedBudgetMinor: 500 }, envelope(event), observedAt).decision, 'CREDIT_COMPLETED_ACTION');
});
