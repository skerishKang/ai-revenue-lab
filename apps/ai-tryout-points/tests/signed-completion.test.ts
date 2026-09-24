import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { verifySignedCompletionEvent } from '../src/signed-completion.js';

const secret = 'test-only-b65-secret';
const timestamp = '1787000000000';
const now = new Date(Number(timestamp) + 30_000).toISOString();
const event = {
  providerId: 'SRC-B65-DEMO', offerId: 'offer-1', providerTransactionId: 'tx-1', externalUserId: 'user-1',
  actionType: 'TRYOUT_COMPLETED', eventType: 'COMPLETED', rewardAmountMinor: 500, rewardCurrency: 'KRW',
  occurredAt: now, nonce: 'nonce-1',
};
const rawBody = JSON.stringify(event);
const signatureHeader = `v1=${createHmac('sha256', secret).update(`${timestamp}.${rawBody}`).digest('hex')}`;

function input(overrides: Partial<Parameters<typeof verifySignedCompletionEvent>[0]> = {}) {
  return {
    providerId: event.providerId, rawBody, signedTimestamp: timestamp, signatureHeader, secret, now,
    ...overrides,
  };
}

test('accepts a correctly signed exact raw body', () => {
  const result = verifySignedCompletionEvent(input());
  assert.equal(result.accepted, true);
  if (result.accepted) {
    assert.equal(result.envelope.signature.verified, true);
    assert.equal(result.envelope.signature.rawBodyBound, true);
    assert.equal(result.envelope.event.providerTransactionId, 'tx-1');
  }
});

test('rejects tampering and stale callbacks', () => {
  const tampered = verifySignedCompletionEvent(input({ rawBody: `${rawBody} ` }));
  assert.deepEqual(tampered, { accepted: false, reason: 'INVALID_SIGNATURE' });
  const stale = verifySignedCompletionEvent(input({ now: new Date(Number(timestamp) + 300_001).toISOString() }));
  assert.deepEqual(stale, { accepted: false, reason: 'STALE_TIMESTAMP' });
});

test('rejects malformed signatures and provider mismatch', () => {
  assert.equal(verifySignedCompletionEvent(input({ signatureHeader: 'v2=bad' })).accepted, false);
  assert.equal(verifySignedCompletionEvent(input({ providerId: 'OTHER' })).accepted, false);
});

function signedInput(body: string, overrides: Partial<Parameters<typeof verifySignedCompletionEvent>[0]> = {}) {
  const digest = createHmac('sha256', secret).update(`${timestamp}.${body}`).digest('hex');
  return input({ rawBody: body, signatureHeader: `v1=${digest}`, ...overrides });
}

test('binds the parsed event to the exact signed bytes', () => {
  const tamperedParsedEvent = { ...event, rewardAmountMinor: 999 };
  const body = JSON.stringify(tamperedParsedEvent);
  const result = verifySignedCompletionEvent(signedInput(body));
  assert.equal(result.accepted, true);
  if (result.accepted) assert.equal(result.envelope.event.rewardAmountMinor, 999);
  assert.equal(verifySignedCompletionEvent(input({ rawBody: JSON.stringify({ ...event, rewardAmountMinor: 999 }) })).accepted, false);
});

test('rejects non-string and non-allowlisted event fields', () => {
  for (const invalidEvent of [
    { ...event, eventType: ['COMPLETED'] },
    { ...event, actionType: 'UNKNOWN_ACTION' },
    { ...event, rewardAmountMinor: 1.5 },
    { ...event, rewardAmountMinor: Number.MAX_SAFE_INTEGER + 1 },
    { ...event, occurredAt: 'not-a-date' },
  ]) {
    const body = JSON.stringify(invalidEvent);
    assert.equal(verifySignedCompletionEvent(signedInput(body)).accepted, false);
  }
});

test('rejects invalid freshness bounds and accepts uppercase digest interoperably', () => {
  for (const maxAgeMs of [Number.NaN, Number.POSITIVE_INFINITY, 0]) {
    const result = verifySignedCompletionEvent(input({ maxAgeMs }));
    assert.equal(result.accepted, false);
    if (!result.accepted) assert.equal(result.reason, 'INVALID_TIMESTAMP');
  }
  const uppercase = input({ signatureHeader: `v1=${createHmac('sha256', secret).update(`${timestamp}.${rawBody}`).digest('hex').toUpperCase()}` });
  assert.equal(verifySignedCompletionEvent(uppercase).accepted, true);
});
