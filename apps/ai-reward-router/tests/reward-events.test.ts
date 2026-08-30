import test from 'node:test';
import assert from 'node:assert/strict';
import { applyProviderRewardEvent, type ProviderRewardEvent } from '../src/ad-click-first/reward-events.js';

const baseEvent: ProviderRewardEvent = {
  providerId: 'SRC-AYET',
  providerTransactionId: 'tx-1',
  externalUserId: 'user-123',
  eventType: 'PROVISIONAL',
  amount: 10,
  unit: 'KRW_EQUIVALENT_REWARD_UNIT',
  observedAt: '2026-08-30T11:20:00.000Z',
};

test('provisional then confirmed follows the safe two-step reward path', () => {
  const created = applyProviderRewardEvent(null, baseEvent);
  assert.equal(created.decision, 'CREATE_PENDING');
  assert.equal(created.next?.state, 'PENDING_PROVIDER_CONFIRMATION');
  assert.equal(created.userBalanceMutation, 'NONE');
  assert.equal(created.cashCustodyAction, 'NONE');

  const confirmed = applyProviderRewardEvent(created.next, {
    ...baseEvent,
    eventType: 'CONFIRMED',
    observedAt: '2026-08-30T11:21:00.000Z',
  });
  assert.equal(confirmed.decision, 'CONFIRM_PENDING');
  assert.equal(confirmed.next?.state, 'CONFIRMED');
  assert.equal(confirmed.appendImmutableAuditEvent, true);
});

test('a provider can confirm directly without a client provisional event', () => {
  const confirmed = applyProviderRewardEvent(null, { ...baseEvent, eventType: 'CONFIRMED' });
  assert.equal(confirmed.decision, 'CREATE_CONFIRMED');
  assert.equal(confirmed.next?.state, 'CONFIRMED');
});

test('duplicate callbacks never create duplicate reward state', () => {
  const created = applyProviderRewardEvent(null, baseEvent);
  const duplicate = applyProviderRewardEvent(created.next, baseEvent);
  assert.equal(duplicate.decision, 'IGNORE_IDEMPOTENT_DUPLICATE');
  assert.equal(duplicate.appendImmutableAuditEvent, false);
  assert.deepEqual(duplicate.next, created.next);
});

test('confirmed and pending rewards can be reversed without deleting history', () => {
  const pending = applyProviderRewardEvent(null, baseEvent).next;
  const pendingReversal = applyProviderRewardEvent(pending, { ...baseEvent, eventType: 'REVERSED' });
  assert.equal(pendingReversal.decision, 'REVERSE_PENDING');
  assert.equal(pendingReversal.next?.state, 'REVERSED');

  const confirmed = applyProviderRewardEvent(null, { ...baseEvent, eventType: 'CONFIRMED' }).next;
  const confirmedReversal = applyProviderRewardEvent(confirmed, { ...baseEvent, eventType: 'REVERSED' });
  assert.equal(confirmedReversal.decision, 'REVERSE_CONFIRMED');
  assert.equal(confirmedReversal.next?.state, 'REVERSED');
});

test('orphan reversal and value mismatch fail closed', () => {
  assert.equal(applyProviderRewardEvent(null, { ...baseEvent, eventType: 'REVERSED' }).decision, 'REJECT_ORPHAN_REVERSAL');

  const current = applyProviderRewardEvent(null, baseEvent).next;
  const mismatch = applyProviderRewardEvent(current, { ...baseEvent, eventType: 'CONFIRMED', amount: 999 });
  assert.equal(mismatch.decision, 'REVIEW_IDENTITY_OR_VALUE_MISMATCH');
  assert.equal(mismatch.next?.amount, 10);
});

test('a reversed transaction cannot silently reopen', () => {
  const confirmed = applyProviderRewardEvent(null, { ...baseEvent, eventType: 'CONFIRMED' }).next;
  const reversed = applyProviderRewardEvent(confirmed, { ...baseEvent, eventType: 'REVERSED' }).next;
  const reopen = applyProviderRewardEvent(reversed, { ...baseEvent, eventType: 'CONFIRMED' });
  assert.equal(reopen.decision, 'REVIEW_REOPEN_AFTER_REVERSAL');
  assert.equal(reopen.next?.state, 'REVERSED');
});

test('invalid provider events never create state', () => {
  const invalid = applyProviderRewardEvent(null, { ...baseEvent, amount: 0 });
  assert.equal(invalid.decision, 'REJECT_INVALID_EVENT');
  assert.equal(invalid.next, null);
  assert.equal(invalid.appendImmutableAuditEvent, false);
});
