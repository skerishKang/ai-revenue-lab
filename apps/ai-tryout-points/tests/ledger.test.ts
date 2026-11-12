import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { applyVerifiedCompletion, completionNonceKey, completionRecordKey } from '../src/ledger.js';
import { verifySignedCompletionEvent } from '../src/signed-completion.js';
import { MAX_OBSERVED_NONCES, MAX_PROVIDER_CLOCK_SKEW_MS, isSafeIdentifier } from '../src/domain.js';
import type { CompletionLedgerRecord, SignedCompletionEvent, TryoutOffer } from '../src/domain.js';
import type { VerifiedCompletionEnvelope } from '../src/signed-completion.js';

const SECRET = 'test-only-b65-ledger-secret';

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

function envelope(value: SignedCompletionEvent, now = observedAt): VerifiedCompletionEnvelope {
  const verified = tryEnvelope(value, now);
  assert.equal(verified.accepted, true, 'test envelope was rejected');
  if (!verified.accepted) throw new Error('test envelope was rejected');
  return verified.envelope;
}

/** Verification result without asserting acceptance, for inputs expected to be rejected. */
function tryEnvelope(value: SignedCompletionEvent, now = observedAt) {
  const rawBody = JSON.stringify(value);
  const signedTimestamp = String(Date.parse(now));
  const signatureHeader = `v1=${createHmac('sha256', SECRET).update(`${signedTimestamp}.${rawBody}`).digest('hex')}`;
  return verifySignedCompletionEvent({ providerId: value.providerId, rawBody, signedTimestamp, signatureHeader, secret: SECRET, now, maxAgeMs: 1000 });
}

function credit(overrides: Partial<SignedCompletionEvent> = {}, records: readonly CompletionLedgerRecord[] = []): CompletionLedgerRecord {
  const result = applyVerifiedCompletion(records, offer, envelope({ ...event, ...overrides }), observedAt);
  assert.equal(result.decision, overrides.eventType === 'REVERSED' ? 'REVERSE_COMPLETED_ACTION' : 'CREDIT_COMPLETED_ACTION');
  assert.notEqual(result.next, null);
  return result.next!;
}

test('credits one verified completed action', () => {
  const result = applyVerifiedCompletion([], offer, envelope(event), observedAt);
  assert.equal(result.decision, 'CREDIT_COMPLETED_ACTION');
  assert.equal(result.balanceDeltaMinor, 500);
  assert.equal(result.next?.state, 'COMPLETED');
  assert.equal(result.appendImmutableAuditEvent, true);
  assert.equal(result.externalPayoutAllowed, false);
});

test('click and visit events never settle points', () => {
  for (const actionType of ['CLICK', 'VISIT'] as const) {
    const result = applyVerifiedCompletion([], offer, envelope({ ...event, actionType }), observedAt);
    assert.equal(result.decision, 'REJECT_CLICK_OR_VISIT');
    assert.equal(result.appendImmutableAuditEvent, false);
  }
});

test('duplicate completion is idempotent and reversal preserves history', () => {
  const created = credit();
  const duplicate = applyVerifiedCompletion([created], offer, envelope(event), observedAt);
  assert.equal(duplicate.decision, 'IGNORE_IDEMPOTENT_DUPLICATE');
  assert.equal(duplicate.balanceDeltaMinor, 0);
  assert.equal(duplicate.appendImmutableAuditEvent, false);
  assert.deepEqual(duplicate.next, created);

  const reversed = applyVerifiedCompletion([created], offer, envelope({ ...event, eventType: 'REVERSED' }), observedAt);
  assert.equal(reversed.decision, 'REVERSE_COMPLETED_ACTION');
  assert.equal(reversed.balanceDeltaMinor, -500);
  assert.equal(reversed.next?.state, 'REVERSED');
  assert.equal(reversed.appendImmutableAuditEvent, true);

  const reopen = applyVerifiedCompletion([reversed.next!], offer, envelope(event), observedAt);
  assert.equal(reopen.decision, 'REJECT_REOPEN_AFTER_REVERSAL');
  assert.equal(reopen.appendImmutableAuditEvent, true);
  assert.equal(reopen.next, null);
});

test('duplicate REVERSED returns the existing reversed record with zero delta and no audit event', () => {
  const created = credit();
  const firstReversal = applyVerifiedCompletion([created], offer, envelope({ ...event, eventType: 'REVERSED' }), observedAt);
  assert.equal(firstReversal.decision, 'REVERSE_COMPLETED_ACTION');
  const reversedRecord = firstReversal.next!;

  const secondReversal = applyVerifiedCompletion([reversedRecord], offer, envelope({ ...event, eventType: 'REVERSED' }), observedAt);
  assert.equal(secondReversal.decision, 'IGNORE_IDEMPOTENT_DUPLICATE');
  assert.equal(secondReversal.balanceDeltaMinor, 0);
  assert.equal(secondReversal.appendImmutableAuditEvent, false);
  assert.equal(secondReversal.externalPayoutAllowed, false);
  assert.notEqual(secondReversal.next, null);
  assert.deepEqual(secondReversal.next, reversedRecord);
  assert.equal(secondReversal.next?.state, 'REVERSED');
  // History is preserved verbatim: no second reversal, no reopened record.
  assert.equal(secondReversal.next?.firstObservedAt, reversedRecord.firstObservedAt);
  assert.equal(secondReversal.next?.providerOccurredAt, reversedRecord.providerOccurredAt);
  assert.equal(secondReversal.next?.nonce, reversedRecord.nonce);

  // A third duplicate REVERSED is still stable and still non-mutating.
  const third = applyVerifiedCompletion([secondReversal.next!], offer, envelope({ ...event, eventType: 'REVERSED' }), observedAt);
  assert.equal(third.decision, 'IGNORE_IDEMPOTENT_DUPLICATE');
  assert.equal(third.balanceDeltaMinor, 0);
  assert.equal(third.appendImmutableAuditEvent, false);
  assert.deepEqual(third.next, reversedRecord);
});

test('reversal preserves completion history fields', () => {
  const created = credit();
  const reversed = applyVerifiedCompletion([created], offer, envelope({ ...event, eventType: 'REVERSED' }), '2026-09-26T00:00:00.000Z');
  assert.equal(reversed.decision, 'REVERSE_COMPLETED_ACTION');
  const record = reversed.next!;
  assert.equal(record.state, 'REVERSED');
  assert.equal(record.providerOccurredAt, created.providerOccurredAt);
  assert.equal(record.firstObservedAt, created.firstObservedAt);
  assert.equal(record.nonce, created.nonce);
  assert.equal(record.rewardAmountMinor, created.rewardAmountMinor);
  // lastObservedAt is server-owned and advances to the reversal observation.
  assert.equal(record.lastObservedAt, '2026-09-26T00:00:00.000Z');
});

test('reject and unauthenticated paths never request an append-only audit write', () => {
  const created = credit();
  const forged = { event, signature: { algorithm: 'HMAC_SHA256', version: 'v1', verified: true, rawBodyBound: true } } as unknown as VerifiedCompletionEnvelope;

  const unauthenticated = [
    applyVerifiedCompletion([], offer, forged, observedAt),
    applyVerifiedCompletion([], offer, null as unknown as VerifiedCompletionEnvelope, observedAt),
    applyVerifiedCompletion([], offer, {} as unknown as VerifiedCompletionEnvelope, observedAt),
  ];
  for (const result of unauthenticated) {
    assert.equal(result.decision, 'REJECT_INVALID_EVENT');
    assert.equal(result.appendImmutableAuditEvent, false);
    assert.equal(result.balanceDeltaMinor, 0);
    assert.equal(result.next, null);
  }

  const rejections = [
    applyVerifiedCompletion([], offer, envelope({ ...event, providerId: 'OTHER' }), observedAt),
    applyVerifiedCompletion([], { ...offer, state: 'PAUSED' }, envelope(event), observedAt),
    applyVerifiedCompletion([], { ...offer, rewardAmountMinor: Number.NaN }, envelope(event), observedAt),
    applyVerifiedCompletion([], offer, envelope(event), 'not-a-date'),
    applyVerifiedCompletion([created], offer, envelope({ ...event, rewardAmountMinor: 999 }), observedAt),
    applyVerifiedCompletion([created], { ...offer, perUserLimit: 1 }, envelope({ ...event, providerTransactionId: 'tx-2', nonce: 'nonce-2' }), observedAt),
  ];
  for (const result of rejections) {
    assert.equal(result.appendImmutableAuditEvent, false, `${result.decision} must not request an audit append`);
    assert.equal(result.balanceDeltaMinor, 0);
  }

  // Only authenticated, meaningful conflicts and transitions are audited.
  const replay = applyVerifiedCompletion([created], offer, envelope({ ...event, providerTransactionId: 'tx-2' }), observedAt);
  assert.equal(replay.decision, 'REJECT_NONCE_REPLAY');
  assert.equal(replay.appendImmutableAuditEvent, true);

  const reopenedSeed = credit({ providerTransactionId: 'tx-r', nonce: 'nonce-r' });
  const reversedSeed = applyVerifiedCompletion([reopenedSeed], offer, envelope({ ...event, providerTransactionId: 'tx-r', nonce: 'nonce-r', eventType: 'REVERSED' }), observedAt).next!;
  const reopen = applyVerifiedCompletion([reversedSeed], offer, envelope({ ...event, providerTransactionId: 'tx-r', nonce: 'nonce-r' }), observedAt);
  assert.equal(reopen.decision, 'REJECT_REOPEN_AFTER_REVERSAL');
  assert.equal(reopen.appendImmutableAuditEvent, true);
});

test('rejects mismatch, inactive offer, per-user limit, and exhausted budget', () => {
  assert.equal(applyVerifiedCompletion([], offer, envelope({ ...event, rewardAmountMinor: 999 }), observedAt).decision, 'REJECT_IDENTITY_OR_VALUE_MISMATCH');
  assert.equal(applyVerifiedCompletion([], { ...offer, state: 'PAUSED' }, envelope(event), observedAt).decision, 'REJECT_OFFER_NOT_ACTIVE');

  const first = credit();
  const second = { ...event, providerTransactionId: 'tx-2', nonce: 'nonce-2' };
  assert.equal(applyVerifiedCompletion([first], offer, envelope(second), observedAt).decision, 'REJECT_PER_USER_LIMIT');

  // A distinct transaction under a new user carries its own nonce history: it must not
  // inherit the first record's observed nonces, which belong to a different transaction.
  const otherUser: CompletionLedgerRecord = { ...first, externalUserId: 'user-2', providerTransactionId: 'tx-other-user', nonce: 'nonce-other-user', observedNonces: ['nonce-other-user'] };
  assert.equal(applyVerifiedCompletion([otherUser], { ...offer, fundedBudgetMinor: 500 }, envelope(event), observedAt).decision, 'REJECT_FUNDED_BUDGET_EXHAUSTED');
});

test('orphan reversal fails closed without an audit append', () => {
  const result = applyVerifiedCompletion([], offer, envelope({ ...event, eventType: 'REVERSED' }), observedAt);
  assert.equal(result.decision, 'REJECT_ORPHAN_REVERSAL');
  assert.equal(result.appendImmutableAuditEvent, false);
});

test('reversal remains available after offer expiry or pause', () => {
  const created = credit();
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
  const created = credit();
  const mismatch = applyVerifiedCompletion([created], offer, envelope({ ...event, rewardAmountMinor: 999 }), observedAt);
  assert.equal(mismatch.decision, 'REJECT_IDENTITY_OR_VALUE_MISMATCH');
  assert.equal(mismatch.next, null);
  assert.equal(applyVerifiedCompletion([], offer, envelope(event), 'not-a-date').decision, 'REJECT_INVALID_EVENT');
});

test('reverses an existing completion after offer pause or expiry', () => {
  const created = credit();
  // The reversal callback arrives after the offer window closes, with a provider
  // occurredAt close to its own server observation (within the skew bound).
  const lateOccurredAt = '2026-10-01T00:00:00.000Z';
  const lateReversal = { ...event, eventType: 'REVERSED' as const, occurredAt: lateOccurredAt };
  for (const state of ['PAUSED', 'EXPIRED'] as const) {
    const reversed = applyVerifiedCompletion([created], { ...offer, state }, envelope(lateReversal, lateOccurredAt), lateOccurredAt);
    assert.equal(reversed.decision, 'REVERSE_COMPLETED_ACTION');
    assert.equal(reversed.next?.state, 'REVERSED');
    assert.equal(reversed.appendImmutableAuditEvent, true);
    // The reversal preserves the original completion's provider evidence.
    assert.equal(reversed.next?.providerOccurredAt, created.providerOccurredAt);
  }
});

test('rejects invalid structural values and keeps rejected state empty', () => {
  const invalidOffer = { ...offer, fundedBudgetMinor: Number.NaN };
  assert.deepEqual(applyVerifiedCompletion([], invalidOffer, envelope(event), observedAt).next, null);
  assert.deepEqual(applyVerifiedCompletion([], { ...offer, endsAt: offer.startsAt }, envelope(event), observedAt).next, null);
  assert.equal(applyVerifiedCompletion([], offer, envelope({ ...event, actionType: 'CLICK' }), observedAt).decision, 'REJECT_CLICK_OR_VISIT');
  assert.equal(applyVerifiedCompletion([], offer, envelope({ ...event, actionType: 'QUALITY_CHECK_COMPLETED' }), observedAt).decision, 'REJECT_IDENTITY_OR_VALUE_MISMATCH');
});

test('isolates budget usage by provider and currency', () => {
  const first = credit();
  const foreignRecord: CompletionLedgerRecord = { ...first, providerId: 'OTHER', rewardCurrency: 'USD' };
  assert.equal(applyVerifiedCompletion([foreignRecord], { ...offer, fundedBudgetMinor: 500 }, envelope(event), observedAt).decision, 'CREDIT_COMPLETED_ACTION');
});

test('whitespace-padded identifiers are rejected rather than normalized', () => {
  const padded: Partial<Record<keyof SignedCompletionEvent, string>> = {
    providerId: ' SRC-B65-DEMO',
    offerId: 'offer-1 ',
    providerTransactionId: '\ttx-1',
    externalUserId: 'user-1\n',
    nonce: ' nonce-1',
  };
  // A padded identifier never produces a verified envelope in the first place.
  for (const [field, value] of Object.entries(padded)) {
    const verification = tryEnvelope({ ...event, [field]: value } as SignedCompletionEvent);
    assert.equal(verification.accepted, false, `${field} padding must fail verification`);
    // A padded providerId fails the header check; a padded body field fails the event check.
    if (!verification.accepted) {
      const expected = field === 'providerId' ? 'INVALID_SIGNATURE_HEADER' : 'INVALID_EVENT';
      assert.equal(verification.reason, expected, `${field} padding must fail as ${expected}`);
    }

    // And it can never reach an audited or crediting ledger path.
    const result = applyVerifiedCompletion([], offer, { event: { ...event, [field]: value } } as unknown as VerifiedCompletionEnvelope, observedAt);
    assert.equal(result.decision, 'REJECT_INVALID_EVENT');
    assert.equal(result.appendImmutableAuditEvent, false);
    assert.equal(result.next, null);
  }

  // A padded offer identifier never matches a verified event, so it can never credit.
  // The offer-identity check is evaluated before offer validity, so it rejects first.
  const paddedOffer = applyVerifiedCompletion([], { ...offer, offerId: ' offer-1' }, envelope(event), observedAt);
  assert.equal(paddedOffer.decision, 'REJECT_OFFER_IDENTITY_MISMATCH');
  assert.equal(paddedOffer.appendImmutableAuditEvent, false);
  assert.equal(paddedOffer.next, null);

  // A padded providerId on the offer likewise cannot match the verified provider.
  const paddedProvider = applyVerifiedCompletion([], { ...offer, providerId: 'SRC-B65-DEMO ' }, envelope(event), observedAt);
  assert.equal(paddedProvider.decision, 'REJECT_OFFER_IDENTITY_MISMATCH');
  assert.equal(paddedProvider.appendImmutableAuditEvent, false);

  // Two identifiers differing only by padding can never collide on one record key.
  assert.notEqual(completionRecordKey('SRC', 'offer-1', 'tx-1'), completionRecordKey('SRC', 'offer-1 ', 'tx-1'));
});

test('provider occurredAt is stored separately from server-owned observed timestamps', () => {
  const providerOccurredAt = '2026-09-25T00:59:00.000Z';
  const record = applyVerifiedCompletion([], offer, envelope({ ...event, occurredAt: providerOccurredAt }), observedAt).next!;
  assert.equal(record.providerOccurredAt, providerOccurredAt);
  assert.equal(record.firstObservedAt, observedAt);
  assert.equal(record.lastObservedAt, observedAt);
  // The provider clock never populates the observed timestamps.
  assert.notEqual(record.firstObservedAt, providerOccurredAt);
});

test('enforces the documented maximum provider-clock skew', () => {
  assert.equal(MAX_PROVIDER_CLOCK_SKEW_MS, 24 * 60 * 60 * 1000);

  const withinSkew = '2026-09-24T01:00:01.000Z';
  assert.equal(applyVerifiedCompletion([], offer, envelope({ ...event, occurredAt: withinSkew }), observedAt).decision, 'CREDIT_COMPLETED_ACTION');

  const tooOld = new Date(Date.parse(observedAt) - MAX_PROVIDER_CLOCK_SKEW_MS - 1000).toISOString();
  const stale = applyVerifiedCompletion([], offer, envelope({ ...event, occurredAt: tooOld }), observedAt);
  assert.equal(stale.decision, 'REJECT_PROVIDER_CLOCK_SKEW');
  assert.equal(stale.next, null);
  assert.equal(stale.appendImmutableAuditEvent, false);

  const tooNew = new Date(Date.parse(observedAt) + MAX_PROVIDER_CLOCK_SKEW_MS + 1000).toISOString();
  assert.equal(applyVerifiedCompletion([], offer, envelope({ ...event, occurredAt: tooNew }), observedAt).decision, 'REJECT_PROVIDER_CLOCK_SKEW');

  // A narrow explicit bound is enforced too, and a malformed bound fails closed.
  assert.equal(applyVerifiedCompletion([], offer, envelope({ ...event, occurredAt: '2026-09-25T00:59:00.000Z' }), observedAt, { maxProviderClockSkewMs: 1000 }).decision, 'REJECT_PROVIDER_CLOCK_SKEW');
  assert.equal(applyVerifiedCompletion([], offer, envelope(event), observedAt, { maxProviderClockSkewMs: 0 }).decision, 'REJECT_INVALID_EVENT');
  assert.equal(applyVerifiedCompletion([], offer, envelope(event), observedAt, { maxProviderClockSkewMs: Number.NaN }).decision, 'REJECT_INVALID_EVENT');
});

test('provider transaction uniqueness is keyed by provider, offer, and transaction', () => {
  const created = credit();
  assert.equal(completionRecordKey(created.providerId, created.offerId, created.providerTransactionId), completionRecordKey(offer.providerId, offer.offerId, 'tx-1'));

  // Same provider transaction id under a different offer is a distinct record.
  const otherOffer: TryoutOffer = { ...offer, offerId: 'offer-2', perUserLimit: 2 };
  const otherEvent: SignedCompletionEvent = { ...event, offerId: 'offer-2', nonce: 'nonce-offer-2' };
  const other = applyVerifiedCompletion([created], otherOffer, envelope(otherEvent), observedAt);
  assert.equal(other.decision, 'CREDIT_COMPLETED_ACTION');
  assert.notEqual(completionRecordKey(other.next!.providerId, other.next!.offerId, other.next!.providerTransactionId), completionRecordKey(created.providerId, created.offerId, created.providerTransactionId));
});

test('rejects provider+nonce replay against a different transaction id', () => {
  const created = credit();
  assert.equal(created.nonce, 'nonce-1');

  // Exact duplicate with the same nonce and transaction stays idempotent.
  const exact = applyVerifiedCompletion([created], offer, envelope(event), observedAt);
  assert.equal(exact.decision, 'IGNORE_IDEMPOTENT_DUPLICATE');
  assert.equal(exact.balanceDeltaMinor, 0);
  assert.equal(exact.appendImmutableAuditEvent, false);

  // Same provider+nonce, different provider transaction id is a replay.
  const replay = applyVerifiedCompletion([created], offer, envelope({ ...event, providerTransactionId: 'tx-2' }), observedAt);
  assert.equal(replay.decision, 'REJECT_NONCE_REPLAY');
  assert.equal(replay.balanceDeltaMinor, 0);
  assert.equal(replay.next, null);
  // An authenticated replay conflict is a meaningful conflict and is audited.
  assert.equal(replay.appendImmutableAuditEvent, true);

  // The same nonce under a different offer for the same provider is also a replay,
  // but the offer-identity check is evaluated first and rejects it even earlier.
  const crossOffer = applyVerifiedCompletion([created], offer, envelope({ ...event, offerId: 'offer-2', providerTransactionId: 'tx-2' }), observedAt);
  assert.equal(crossOffer.decision, 'REJECT_OFFER_IDENTITY_MISMATCH');
  assert.equal(crossOffer.appendImmutableAuditEvent, false);

  // A replay cannot be used to bypass the per-user limit either.
  const limited = applyVerifiedCompletion([created], { ...offer, perUserLimit: 1 }, envelope({ ...event, providerTransactionId: 'tx-2' }), observedAt);
  assert.equal(limited.decision, 'REJECT_NONCE_REPLAY');
  assert.equal(limited.next, null);

  // The same nonce string from a different provider is not a replay.
  const otherProvider = applyVerifiedCompletion([created], { ...offer, providerId: 'SRC-OTHER', offerId: 'offer-2' }, envelope({ ...event, providerId: 'SRC-OTHER', offerId: 'offer-2', providerTransactionId: 'tx-9' }), observedAt);
  assert.equal(otherProvider.decision, 'CREDIT_COMPLETED_ACTION');
  assert.notEqual(completionNonceKey('SRC-OTHER', 'nonce-1'), completionNonceKey(offer.providerId, 'nonce-1'));
});

test('a nonce first seen on a duplicate completion is bound to that transaction', () => {
  const created = credit();
  assert.deepEqual(created.observedNonces, ['nonce-1']);

  // The provider re-issues the same completion under a NEW nonce. It is still an
  // idempotent duplicate with zero delta, but the new nonce is now remembered.
  const reissued = applyVerifiedCompletion([created], offer, envelope({ ...event, nonce: 'nonce-dup' }), observedAt);
  assert.equal(reissued.decision, 'IGNORE_IDEMPOTENT_DUPLICATE');
  assert.equal(reissued.balanceDeltaMinor, 0);
  assert.equal(reissued.appendImmutableAuditEvent, false);
  assert.deepEqual(reissued.next?.observedNonces, ['nonce-1', 'nonce-dup']);
  // Completion evidence and the canonical nonce are preserved verbatim.
  assert.equal(reissued.next?.nonce, 'nonce-1');
  assert.equal(reissued.next?.providerOccurredAt, created.providerOccurredAt);
  assert.equal(reissued.next?.firstObservedAt, created.firstObservedAt);
  assert.equal(reissued.next?.rewardAmountMinor, created.rewardAmountMinor);

  // Reusing that duplicate-introduced nonce for a DIFFERENT transaction is a replay.
  const replay = applyVerifiedCompletion([reissued.next!], { ...offer, perUserLimit: 5 }, envelope({ ...event, providerTransactionId: 'tx-2', nonce: 'nonce-dup' }), observedAt);
  assert.equal(replay.decision, 'REJECT_NONCE_REPLAY');
  assert.equal(replay.balanceDeltaMinor, 0);
  assert.equal(replay.next, null);
  assert.equal(replay.appendImmutableAuditEvent, true);

  // Re-sending the exact same completion remains a zero-delta no-op.
  const exact = applyVerifiedCompletion([reissued.next!], offer, envelope({ ...event, nonce: 'nonce-dup' }), observedAt);
  assert.equal(exact.decision, 'IGNORE_IDEMPOTENT_DUPLICATE');
  assert.equal(exact.balanceDeltaMinor, 0);
  assert.deepEqual(exact.next?.observedNonces, ['nonce-1', 'nonce-dup']);
});

test('a nonce first seen on a reversal is bound to that transaction', () => {
  const created = credit();
  // The reversal arrives under a nonce the ledger has never seen before.
  const reversed = applyVerifiedCompletion([created], offer, envelope({ ...event, eventType: 'REVERSED', nonce: 'nonce-rev' }), observedAt);
  assert.equal(reversed.decision, 'REVERSE_COMPLETED_ACTION');
  assert.equal(reversed.balanceDeltaMinor, -500);
  assert.equal(reversed.appendImmutableAuditEvent, true);
  // History is append-only: the completion nonce is preserved and the reversal nonce added.
  assert.equal(reversed.next?.nonce, 'nonce-1');
  assert.deepEqual(reversed.next?.observedNonces, ['nonce-1', 'nonce-rev']);
  assert.equal(reversed.next?.providerOccurredAt, created.providerOccurredAt);
  assert.equal(reversed.next?.firstObservedAt, created.firstObservedAt);

  // Reusing the reversal nonce for a different transaction is rejected.
  const replay = applyVerifiedCompletion([reversed.next!], { ...offer, perUserLimit: 5 }, envelope({ ...event, providerTransactionId: 'tx-2', nonce: 'nonce-rev' }), observedAt);
  assert.equal(replay.decision, 'REJECT_NONCE_REPLAY');
  assert.equal(replay.next, null);

  // Reusing the ORIGINAL completion nonce for a different transaction is also rejected.
  const originalReplay = applyVerifiedCompletion([reversed.next!], { ...offer, perUserLimit: 5 }, envelope({ ...event, providerTransactionId: 'tx-3' }), observedAt);
  assert.equal(originalReplay.decision, 'REJECT_NONCE_REPLAY');
});

test('a duplicate reversal under a new nonce is idempotent and still records the nonce', () => {
  const created = credit();
  const reversed = applyVerifiedCompletion([created], offer, envelope({ ...event, eventType: 'REVERSED', nonce: 'nonce-rev' }), observedAt).next!;

  // The provider re-sends the same reversal under yet another nonce.
  const again = applyVerifiedCompletion([reversed], offer, envelope({ ...event, eventType: 'REVERSED', nonce: 'nonce-rev-2' }), observedAt);
  assert.equal(again.decision, 'IGNORE_IDEMPOTENT_DUPLICATE');
  assert.equal(again.balanceDeltaMinor, 0);
  assert.equal(again.appendImmutableAuditEvent, false);
  assert.equal(again.next?.state, 'REVERSED');
  assert.equal(again.next?.nonce, 'nonce-1');
  assert.deepEqual(again.next?.observedNonces, ['nonce-1', 'nonce-rev', 'nonce-rev-2']);

  // And that new reversal nonce is bound to the reversed transaction.
  const replay = applyVerifiedCompletion([again.next!], { ...offer, perUserLimit: 5 }, envelope({ ...event, providerTransactionId: 'tx-2', nonce: 'nonce-rev-2' }), observedAt);
  assert.equal(replay.decision, 'REJECT_NONCE_REPLAY');
});

test('the observed-nonce list is bounded and fails closed rather than dropping a nonce', () => {
  const created = credit();
  // Fill the list to the bound with distinct nonces for this same transaction.
  let current = created;
  for (let index = 1; index < MAX_OBSERVED_NONCES; index += 1) {
    const next = applyVerifiedCompletion([current], offer, envelope({ ...event, nonce: `nonce-fill-${index}` }), observedAt);
    assert.equal(next.decision, 'IGNORE_IDEMPOTENT_DUPLICATE');
    current = next.next!;
  }
  assert.equal(current.observedNonces.length, MAX_OBSERVED_NONCES);

  // One more distinct nonce would exceed the bound: fail closed, do not drop it.
  const overflow = applyVerifiedCompletion([current], offer, envelope({ ...event, nonce: 'nonce-overflow' }), observedAt);
  assert.equal(overflow.decision, 'REJECT_NONCE_HISTORY_EXHAUSTED');
  assert.equal(overflow.balanceDeltaMinor, 0);
  assert.equal(overflow.next, null);
  assert.equal(overflow.appendImmutableAuditEvent, false);
  // The record is returned unchanged; the caller keeps its authoritative history.
  assert.equal(current.observedNonces.includes('nonce-overflow'), false);
});

test('control characters in identifiers cannot forge a composite record key', () => {
  // NUL is the record-key join character, so a NUL inside any part could merge two
  // distinct records. Every such identifier is rejected at the ledger boundary.
  for (const overrides of [
    { providerTransactionId: 'tx-1\u0000tx-2' },
    { providerTransactionId: 'tx\u0001' },
    { providerTransactionId: 'tx-1\u007F' },
    { providerTransactionId: 'tx-1\u009F' },
    { providerTransactionId: 'tx-1\u2028' },
    { offerId: 'offer-1\u0000offer-2' },
    { externalUserId: 'user-1\u0000user-2' },
    { nonce: 'nonce-1\u0000nonce-2' },
  ]) {
    // A padded/unprintable identifier never produces a verified envelope.
    const verification = tryEnvelope({ ...event, ...overrides } as SignedCompletionEvent);
    assert.equal(verification.accepted, false, `${JSON.stringify(overrides)} must fail verification`);

    // And a forged envelope carrying it never reaches a crediting path.
    const result = applyVerifiedCompletion([], offer, { event: { ...event, ...overrides } } as unknown as VerifiedCompletionEnvelope, observedAt);
    assert.equal(result.decision, 'REJECT_INVALID_EVENT');
    assert.equal(result.next, null);
    assert.equal(result.balanceDeltaMinor, 0);
    assert.equal(result.appendImmutableAuditEvent, false);
  }

  // Two identifiers that would collide under a naive NUL join are both rejected, so
  // the surviving keys can never merge onto one record.
  assert.notEqual(completionRecordKey('SRC', 'offer-1', 'tx-1'), completionRecordKey('SRC\u0000x', 'offer-1', 'tx-1'));
  assert.equal(isSafeIdentifier('SRC\u0000x'), false);
  assert.equal(isSafeIdentifier('tx-1\u0000tx-2'), false);
  assert.equal(isSafeIdentifier('plain-id-1'), true);
});

test('maxProviderClockSkewMs is capped at the documented maximum', () => {
  // Exactly at the documented maximum is accepted as an explicit bound.
  const atMax = applyVerifiedCompletion([], offer, envelope(event), observedAt, { maxProviderClockSkewMs: MAX_PROVIDER_CLOCK_SKEW_MS });
  assert.equal(atMax.decision, 'CREDIT_COMPLETED_ACTION');

  // An over-large bound fails closed instead of widening the accepted window.
  for (const maxProviderClockSkewMs of [MAX_PROVIDER_CLOCK_SKEW_MS + 1, MAX_PROVIDER_CLOCK_SKEW_MS * 2, Number.MAX_SAFE_INTEGER, Number.POSITIVE_INFINITY]) {
    const result = applyVerifiedCompletion([], offer, envelope(event), observedAt, { maxProviderClockSkewMs });
    assert.equal(result.decision, 'REJECT_INVALID_EVENT', `${String(maxProviderClockSkewMs)} must fail closed`);
    assert.equal(result.next, null);
    assert.equal(result.balanceDeltaMinor, 0);
    assert.equal(result.appendImmutableAuditEvent, false);
  }

  // An over-large bound cannot be used to admit a callback that the real maximum rejects.
  const farTooOld = new Date(Date.parse(observedAt) - (MAX_PROVIDER_CLOCK_SKEW_MS + 60_000)).toISOString();
  assert.equal(
    applyVerifiedCompletion([], offer, envelope({ ...event, occurredAt: farTooOld }, farTooOld), farTooOld, { maxProviderClockSkewMs: Number.MAX_SAFE_INTEGER }).decision,
    'REJECT_INVALID_EVENT',
  );
});

test('the test-only secret never appears in the envelope', () => {
  const verified = envelope(event);
  const serialized = JSON.stringify(verified);
  assert.equal(serialized.includes(SECRET), false);
  assert.equal(serialized.includes('"secret"'), false);
  assert.equal(serialized.includes('signatureHeader'), false);
  assert.equal(serialized.includes('"rawBody"'), false);
  assert.deepEqual(Object.keys(verified).sort(), ['event', 'signature']);
  assert.deepEqual(Object.keys(verified.signature).sort(), ['algorithm', 'rawBodyBound', 'verified', 'version']);
});
