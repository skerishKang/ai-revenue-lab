import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { DEFAULT_MAX_SIGNATURE_FUTURE_SKEW_MS, verifySignedCompletionEvent } from '../src/signed-completion.js';
import { isSafeIdentifier } from '../src/domain.js';

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

test('rejects future timestamps beyond the explicit skew and accepts ones inside it', () => {
  assert.equal(DEFAULT_MAX_SIGNATURE_FUTURE_SKEW_MS, 30_000);

  // Exactly at the boundary is accepted.
  const atBoundary = verifySignedCompletionEvent(input({ now: new Date(Number(timestamp) - DEFAULT_MAX_SIGNATURE_FUTURE_SKEW_MS).toISOString() }));
  assert.equal(atBoundary.accepted, true);

  // One millisecond beyond the boundary fails as a future timestamp, not as staleness.
  const beyond = verifySignedCompletionEvent(input({ now: new Date(Number(timestamp) - DEFAULT_MAX_SIGNATURE_FUTURE_SKEW_MS - 1).toISOString() }));
  assert.deepEqual(beyond, { accepted: false, reason: 'FUTURE_TIMESTAMP' });

  // A far-future timestamp also fails as FUTURE_TIMESTAMP, never as accepted.
  const far = verifySignedCompletionEvent(input({ now: new Date(Number(timestamp) - 365 * 24 * 60 * 60 * 1000).toISOString() }));
  assert.deepEqual(far, { accepted: false, reason: 'FUTURE_TIMESTAMP' });

  // An explicit narrower skew is enforced.
  const narrow = verifySignedCompletionEvent(input({ now: new Date(Number(timestamp) - 2000).toISOString(), maxFutureSkewMs: 1000 }));
  assert.deepEqual(narrow, { accepted: false, reason: 'FUTURE_TIMESTAMP' });
  const narrowOk = verifySignedCompletionEvent(input({ now: new Date(Number(timestamp) - 500).toISOString(), maxFutureSkewMs: 1000 }));
  assert.equal(narrowOk.accepted, true);
});

test('rejects malformed future-skew bounds', () => {
  for (const maxFutureSkewMs of [Number.NaN, Number.POSITIVE_INFINITY, 0, -1, 1.5, 25 * 60 * 60 * 1000]) {
    const result = verifySignedCompletionEvent(input({ maxFutureSkewMs }));
    assert.equal(result.accepted, false, `${String(maxFutureSkewMs)} must be rejected`);
    if (!result.accepted) assert.equal(result.reason, 'INVALID_TIMESTAMP');
  }
});

test('rejects whitespace-padded identifiers rather than normalizing them', () => {
  for (const overrides of [
    { providerId: ' SRC-B65-DEMO' },
    { providerId: 'SRC-B65-DEMO ' },
    { providerId: '' },
  ]) {
    const result = verifySignedCompletionEvent(input(overrides));
    assert.equal(result.accepted, false, `${JSON.stringify(overrides)} must be rejected`);
    if (!result.accepted) assert.ok(result.reason === 'INVALID_SIGNATURE_HEADER' || result.reason === 'INVALID_EVENT');
  }

  for (const field of ['offerId', 'providerTransactionId', 'externalUserId', 'nonce'] as const) {
    const padded = { ...event, [field]: ` ${event[field]} ` };
    const body = JSON.stringify(padded);
    const digest = createHmac('sha256', secret).update(`${timestamp}.${body}`).digest('hex');
    const result = verifySignedCompletionEvent(input({ rawBody: body, signatureHeader: `v1=${digest}` }));
    assert.equal(result.accepted, false, `${field} padding must be rejected`);
    if (!result.accepted) assert.equal(result.reason, 'INVALID_EVENT');
  }
});

test('rejects control characters in identifiers rather than allowing key collisions', () => {
  // NUL is the composite-key join character, so a NUL inside any identifier part could
  // merge two distinct records. All control characters are rejected outright.
  const controls = ['\u0000', '\u0001', '\u0009', '\u000A', '\u000D', '\u001F', '\u007F', '\u0085', '\u009F', '\u2028', '\u2029'];
  for (const control of controls) {
    for (const field of ['providerId', 'offerId', 'providerTransactionId', 'externalUserId', 'nonce'] as const) {
      const body = JSON.stringify({ ...event, [field]: `${event[field]}${control}` });
      const digest = createHmac('sha256', secret).update(`${timestamp}.${body}`).digest('hex');
      const result = verifySignedCompletionEvent(input({ rawBody: body, signatureHeader: `v1=${digest}` }));
      assert.equal(result.accepted, false, `${field} with ${JSON.stringify(control)} must be rejected`);
      // The header carries the clean provider id, so a control character anywhere in
      // the signed body fails the event check. Either way it is never accepted.
      if (!result.accepted) assert.equal(result.reason, 'INVALID_EVENT');
    }
  }

  // An embedded NUL can never split one identifier into two record-key parts.
  assert.equal(isSafeIdentifier(`tx-1\u0000tx-2`), false);
  assert.equal(isSafeIdentifier('SRC\u0000DEMO'), false);
  assert.equal(isSafeIdentifier('SRC-B65-DEMO'), true);
});

test('the accepted envelope never carries the test-only secret or raw payload', () => {
  const result = verifySignedCompletionEvent(input());
  assert.equal(result.accepted, true);
  if (!result.accepted) return;
  const serialized = JSON.stringify(result.envelope);
  for (const forbidden of [secret, 'secret', '"signatureHeader"', '"rawBody"', '"signedTimestamp"']) {
    assert.equal(serialized.includes(forbidden), false, `envelope must not expose ${forbidden}`);
  }
  assert.deepEqual(Object.keys(result.envelope).sort(), ['event', 'signature']);
  assert.equal(Object.isFrozen(result.envelope), true);
  assert.equal(Object.isFrozen(result.envelope.event), true);
  assert.equal(Object.isFrozen(result.envelope.signature), true);
});
