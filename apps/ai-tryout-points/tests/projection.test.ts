import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { applyVerifiedCompletion } from '../src/ledger.js';
import { verifySignedCompletionEvent } from '../src/signed-completion.js';
import { assessPointsClaim } from '../src/claim.js';
import { SAFE_PROJECTION_OMITTED_FIELDS, toSafeClaimView, toSafeLedgerRecordView, toSafeTransitionView } from '../src/projection.js';
import type { CompletionLedgerRecord, SignedCompletionEvent, TryoutOffer } from '../src/domain.js';

const SECRET = 'test-only-b65-projection-secret';
const offer: TryoutOffer = {
  offerId: 'offer-1', providerId: 'SRC-B65-DEMO', actionType: 'TRYOUT_COMPLETED', rewardAmountMinor: 500,
  rewardCurrency: 'KRW', perUserLimit: 2, fundedBudgetMinor: 1000, startsAt: '2026-09-25T00:00:00.000Z',
  endsAt: '2026-09-30T00:00:00.000Z', state: 'ACTIVE',
};
const event: SignedCompletionEvent = {
  providerId: offer.providerId, offerId: offer.offerId, providerTransactionId: 'tx-1', externalUserId: 'user-1',
  actionType: offer.actionType, eventType: 'COMPLETED', rewardAmountMinor: 500, rewardCurrency: 'KRW',
  occurredAt: '2026-09-25T01:00:00.000Z', nonce: 'nonce-1',
};
const observedAt = '2026-09-25T01:00:01.000Z';

function envelope() {
  const rawBody = JSON.stringify(event);
  const signedTimestamp = String(Date.parse(observedAt));
  const signatureHeader = `v1=${createHmac('sha256', SECRET).update(`${signedTimestamp}.${rawBody}`).digest('hex')}`;
  const result = verifySignedCompletionEvent({ providerId: event.providerId, rawBody, signedTimestamp, signatureHeader, secret: SECRET, now: observedAt, maxAgeMs: 1000 });
  assert.equal(result.accepted, true);
  if (!result.accepted) throw new Error('test envelope was rejected');
  return result.envelope;
}

test('safe ledger projections are allowlisted and frozen', () => {
  const record = applyVerifiedCompletion([], offer, envelope(), observedAt).next!;
  const view = toSafeLedgerRecordView(record);
  assert.deepEqual(Object.keys(view).sort(), [
    'actionType', 'externalUserId', 'firstObservedAt', 'lastObservedAt', 'offerId',
    'providerId', 'providerOccurredAt', 'providerTransactionId', 'rewardAmountMinor',
    'rewardCurrency', 'state',
  ]);
  assert.equal(Object.isFrozen(view), true);
  assert.equal(view.state, 'COMPLETED');
  assert.equal(view.providerOccurredAt, event.occurredAt);
  assert.equal(view.firstObservedAt, observedAt);
});

test('safe projections never expose the secret, token, signature, or raw provider payload', () => {
  const transition = applyVerifiedCompletion([], offer, envelope(), observedAt);
  const record = transition.next!;
  const claim = assessPointsClaim([record], {
    providerId: offer.providerId, offerId: offer.offerId, externalUserId: event.externalUserId,
    rewardCurrency: offer.rewardCurrency, claimAmountMinor: 500,
  });

  const projections = {
    record: toSafeLedgerRecordView(record),
    transition: toSafeTransitionView(transition),
    claim: toSafeClaimView(claim),
  };
  const serialized = JSON.stringify(projections);
  for (const forbidden of [SECRET, 'test-only', 'nonce-1', 'nonce', 'signature', 'rawBody', 'secret', 'token', 'apiKey', 'bearer']) {
    assert.equal(serialized.includes(forbidden), false, `projections must not expose ${forbidden}`);
  }
  for (const omitted of SAFE_PROJECTION_OMITTED_FIELDS) {
    assert.equal(serialized.includes(omitted), false, `projections must omit ${omitted}`);
  }
  for (const view of Object.values(projections)) assert.equal(Object.isFrozen(view), true);
});

test('the safe transition projection preserves audit and payout decisions only', () => {
  const forged = { event, signature: { algorithm: 'HMAC_SHA256', version: 'v1', verified: true, rawBodyBound: true } } as never;
  const rejected = toSafeTransitionView(applyVerifiedCompletion([], offer, forged, observedAt));
  assert.equal(rejected.decision, 'REJECT_INVALID_EVENT');
  assert.equal(rejected.appendImmutableAuditEvent, false);
  assert.equal(rejected.externalPayoutAllowed, false);
  assert.equal(rejected.next, null);
  assert.deepEqual(Object.keys(rejected).sort(), ['appendImmutableAuditEvent', 'balanceDeltaMinor', 'decision', 'externalPayoutAllowed', 'next']);
});

test('a record carrying an extra unexpected field cannot leak it into a projection', () => {
  const base: CompletionLedgerRecord = {
    providerId: offer.providerId, offerId: offer.offerId, providerTransactionId: 'tx-1', externalUserId: 'user-1',
    actionType: offer.actionType, state: 'COMPLETED', rewardAmountMinor: 500, rewardCurrency: 'KRW',
    providerOccurredAt: event.occurredAt, firstObservedAt: observedAt, lastObservedAt: observedAt, nonce: 'nonce-1',
    observedNonces: ['nonce-1'],
  };
  const contaminated = { ...base, secret: SECRET, signatureHeader: 'v1=deadbeef', rawProviderPayload: 'blob' } as unknown as CompletionLedgerRecord;
  const serialized = JSON.stringify(toSafeLedgerRecordView(contaminated));
  for (const forbidden of [SECRET, 'secret', 'signatureHeader', 'rawProviderPayload', 'nonce']) {
    assert.equal(serialized.includes(forbidden), false);
  }
});
