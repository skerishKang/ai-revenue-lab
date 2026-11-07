import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { applyVerifiedCompletion, completionRecordKey } from '../src/ledger.js';
import { isValidLedgerRecord, safeAddMinor, safeSumMinor, validateLedgerHistory } from '../src/ledger-history.js';
import { verifySignedCompletionEvent } from '../src/signed-completion.js';
import { MAX_OBSERVED_NONCES, MAX_PROVIDER_CLOCK_SKEW_MS } from '../src/domain.js';
import type { CompletionLedgerRecord, SignedCompletionEvent, TryoutOffer } from '../src/domain.js';
import type { VerifiedCompletionEnvelope } from '../src/signed-completion.js';

const SECRET = 'test-only-b65-ledger-history-secret';

const offer: TryoutOffer = {
  offerId: 'offer-1', providerId: 'SRC-B65-DEMO', actionType: 'TRYOUT_COMPLETED', rewardAmountMinor: 500,
  rewardCurrency: 'KRW', perUserLimit: 5, fundedBudgetMinor: 100_000, startsAt: '2026-09-25T00:00:00.000Z',
  endsAt: '2026-09-30T00:00:00.000Z', state: 'ACTIVE',
};
const event: SignedCompletionEvent = {
  providerId: offer.providerId, offerId: offer.offerId, providerTransactionId: 'tx-1', externalUserId: 'user-1',
  actionType: offer.actionType, eventType: 'COMPLETED', rewardAmountMinor: 500, rewardCurrency: 'KRW',
  occurredAt: '2026-09-25T01:00:00.000Z', nonce: 'nonce-1',
};
const observedAt = '2026-09-25T01:00:01.000Z';

function envelope(value: SignedCompletionEvent, now = observedAt): VerifiedCompletionEnvelope {
  const rawBody = JSON.stringify(value);
  const signedTimestamp = String(Date.parse(now));
  const signatureHeader = `v1=${createHmac('sha256', SECRET).update(`${signedTimestamp}.${rawBody}`).digest('hex')}`;
  const verified = verifySignedCompletionEvent({ providerId: value.providerId, rawBody, signedTimestamp, signatureHeader, secret: SECRET, now, maxAgeMs: 1000 });
  assert.equal(verified.accepted, true, 'test envelope was rejected');
  if (!verified.accepted) throw new Error('test envelope was rejected');
  return verified.envelope;
}

/** A well-formed historical record, used as the valid baseline for every mutation. */
function historyRecord(overrides: Partial<CompletionLedgerRecord> = {}): CompletionLedgerRecord {
  const base: CompletionLedgerRecord = {
    providerId: 'SRC-B65-DEMO', offerId: 'offer-1', providerTransactionId: 'tx-9', externalUserId: 'user-9',
    actionType: 'TRYOUT_COMPLETED', state: 'COMPLETED', rewardAmountMinor: 500, rewardCurrency: 'KRW',
    providerOccurredAt: '2026-09-25T01:00:00.000Z', firstObservedAt: '2026-09-25T01:00:01.000Z',
    lastObservedAt: '2026-09-25T01:00:01.000Z', nonce: 'nonce-9', observedNonces: ['nonce-9'],
    ...overrides,
  };
  // Keep observedNonces consistent with the canonical nonce unless a test overrides it
  // with an explicit value, including an explicit `undefined` or `null`.
  return Object.prototype.hasOwnProperty.call(overrides, 'observedNonces') ? base : { ...base, observedNonces: [base.nonce] };
}

/** A real record produced by the ledger, so the valid-sibling control is authentic. */
function creditedRecord(overrides: Partial<SignedCompletionEvent> = {}): CompletionLedgerRecord {
  const created = applyVerifiedCompletion([], { ...offer, perUserLimit: 5 }, envelope({ ...event, ...overrides }), observedAt);
  assert.equal(created.decision, 'CREDIT_COMPLETED_ACTION');
  assert.notEqual(created.next, null);
  return created.next!;
}

/**
 * Every rejection of malformed authoritative history must be stable, non-mutating, and
 * unaudited. A malformed record can never be "handled" by returning a next state.
 */
function assertFailsClosed(records: readonly unknown[], label: string): void {
  const result = applyVerifiedCompletion(records as readonly CompletionLedgerRecord[], offer, envelope(event), observedAt);
  assert.equal(result.decision, 'REJECT_INVALID_LEDGER_HISTORY', `${label} must fail closed`);
  assert.equal(result.balanceDeltaMinor, 0, `${label} must not move balance`);
  assert.equal(result.next, null, `${label} must not return a writable next`);
  assert.equal(result.appendImmutableAuditEvent, false, `${label} must not request an audit append`);
  assert.equal(result.externalPayoutAllowed, false, `${label} must never allow payout`);
}

test('a well-formed historical record is valid and does not block a later credit', () => {
  const record = historyRecord();
  assert.equal(isValidLedgerRecord(record), true);
  assert.equal(applyVerifiedCompletion([record], offer, envelope(event), observedAt).decision, 'CREDIT_COMPLETED_ACTION');

  // The same record produced by the ledger itself is equally valid.
  assert.equal(isValidLedgerRecord(creditedRecord()), true);
});

test('non-object, null, and array history entries fail closed', () => {
  for (const bad of [null, undefined, 'record', 42, true, ['record'], [{ ...historyRecord() }]]) {
    assert.equal(isValidLedgerRecord(bad), false, `${String(bad)} is not a valid record`);
    assertFailsClosed([bad], `history entry ${String(bad)}`);
  }
  // A history that is not even a list is rejected rather than iterated.
  for (const notAList of [null, undefined, {}, 'records', 7]) {
    const validation = validateLedgerHistory(notAList, offer, event.externalUserId);
    assert.equal(validation.ok, false);
    if (!validation.ok) assert.equal(validation.reason, 'HISTORY_NOT_A_LIST');
  }
});

test('NaN, Infinity, negative, zero, fractional, and unsafe reward amounts fail closed', () => {
  for (const rewardAmountMinor of [
    Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY, 0, -1, -500, 1.5, 500.0000001,
    Number.MAX_SAFE_INTEGER + 1, Number.MIN_SAFE_INTEGER - 1, '500', null, undefined, { valueOf: () => 500 },
  ]) {
    const record = historyRecord({ rewardAmountMinor: rewardAmountMinor as number });
    assert.equal(isValidLedgerRecord(record), false, `reward ${String(rewardAmountMinor)} must be invalid`);
    assertFailsClosed([record], `reward ${String(rewardAmountMinor)}`);
  }
  // A safe, positive, integer amount is still accepted.
  assert.equal(isValidLedgerRecord(historyRecord({ rewardAmountMinor: Number.MAX_SAFE_INTEGER })), true);
});

test('malformed, padded, and control-character identifiers fail closed', () => {
  const cases: [keyof CompletionLedgerRecord, unknown][] = [
    ['providerId', ''],
    ['providerId', ' SRC-B65-DEMO'],
    ['providerId', 'SRC-B65-DEMO '],
    ['providerId', 'SRC-B65-DEMO\u0000OTHER'],
    ['providerId', 'SRC\u0001'],
    ['providerId', 'SRC\u007F'],
    ['providerId', 'SRC\u009F'],
    ['providerId', 'SRC\u2028'],
    ['providerId', null],
    ['providerId', 7],
    ['offerId', ' offer-1'],
    ['providerTransactionId', 'tx-9\u0000tx-10'],
    ['externalUserId', '\tuser-9'],
    ['externalUserId', ''],
    ['nonce', ' nonce-9'],
    ['nonce', 'nonce-9\u0000nonce-8'],
    ['nonce', ''],
    ['nonce', 42],
  ];
  for (const [field, value] of cases) {
    const record = historyRecord({ [field]: value } as Partial<CompletionLedgerRecord>);
    assert.equal(isValidLedgerRecord(record), false, `${String(field)}=${JSON.stringify(value)} must be invalid`);
    assertFailsClosed([record], `${String(field)}=${JSON.stringify(value)}`);
  }
});

test('malformed action, state, and currency fail closed', () => {
  for (const [field, value] of [
    ['actionType', 'CLICK'], ['actionType', 'VISIT'], ['actionType', 'TRYOUT_COMPLETED '], ['actionType', ''], ['actionType', 3],
    ['state', 'PENDING'], ['state', 'completed'], ['state', 'REVERSED\u0002'], ['state', ''], ['state', null],
    ['rewardCurrency', 'krw'], ['rewardCurrency', ''], ['rewardCurrency', 'KRWX'], ['rewardCurrency', 'US$'], ['rewardCurrency', 840],
  ] as [keyof CompletionLedgerRecord, unknown][]) {
    const record = historyRecord({ [field]: value } as Partial<CompletionLedgerRecord>);
    assert.equal(isValidLedgerRecord(record), false, `${String(field)}=${JSON.stringify(value)} must be invalid`);
    assertFailsClosed([record], `${String(field)}=${JSON.stringify(value)}`);
  }
  // REVERSED is a legitimate terminal state and remains valid history.
  assert.equal(isValidLedgerRecord(historyRecord({ state: 'REVERSED' })), true);
});

test('malformed provider, first, and last observed timestamps fail closed', () => {
  for (const [field, value] of [
    ['providerOccurredAt', 'not-a-date'],
    ['providerOccurredAt', '2026-13-45T99:99:99.999Z'],
    ['providerOccurredAt', ''],
    ['providerOccurredAt', 1_789_000_000_000],
    ['firstObservedAt', 'not-a-date'],
    ['firstObservedAt', ''],
    ['lastObservedAt', 'not-a-date'],
    ['lastObservedAt', ''],
  ] as [keyof CompletionLedgerRecord, unknown][]) {
    const record = historyRecord({ [field]: value } as Partial<CompletionLedgerRecord>);
    assert.equal(isValidLedgerRecord(record), false, `${String(field)}=${JSON.stringify(value)} must be invalid`);
    assertFailsClosed([record], `${String(field)}=${JSON.stringify(value)}`);
  }
});

test('per-record timestamp inconsistency fails closed even when each field parses', () => {
  // The contract defines both invariants, so a record that violates either one is
  // malformed history even though every individual timestamp is a valid date.
  const lastBeforeFirst = historyRecord({ lastObservedAt: '2026-09-25T00:00:00.000Z' });
  assert.equal(Date.parse(lastBeforeFirst.lastObservedAt) < Date.parse(lastBeforeFirst.firstObservedAt), true);
  assert.equal(isValidLedgerRecord(lastBeforeFirst), false);
  assertFailsClosed([lastBeforeFirst], 'lastObservedAt before firstObservedAt');

  const outsideSkew = historyRecord({ providerOccurredAt: new Date(Date.parse('2026-09-25T01:00:01.000Z') - MAX_PROVIDER_CLOCK_SKEW_MS - 1000).toISOString() });
  assert.equal(isValidLedgerRecord(outsideSkew), false);
  assertFailsClosed([outsideSkew], 'providerOccurredAt outside the documented skew');

  // Exactly at the documented bound is still consistent history.
  const atSkew = historyRecord({ providerOccurredAt: new Date(Date.parse('2026-09-25T01:00:01.000Z') - MAX_PROVIDER_CLOCK_SKEW_MS).toISOString() });
  assert.equal(isValidLedgerRecord(atSkew), true);
});

test('a malformed observed-nonce history fails closed', () => {
  const cases: [string, unknown][] = [
    ['missing (undefined)', undefined],
    ['missing (null)', null],
    ['empty list', []],
    ['wrong type (string)', 'nonce-9' as unknown as readonly string[]],
    ['wrong type (object)', { 0: 'nonce-9' } as unknown as readonly string[]],
    ['omits the canonical nonce', ['nonce-other']],
    ['canonical nonce not first', ['nonce-other', 'nonce-9']],
    ['duplicate entry', ['nonce-9', 'nonce-9']],
    ['control character', ['nonce-9', 'nonce-other\u0000nonce-x']],
    ['padded entry', ['nonce-9', ' nonce-other']],
    ['empty string entry', ['nonce-9', '']],
    ['non-string entry', ['nonce-9', 7 as unknown as string]],
    ['over the bound', Array.from({ length: MAX_OBSERVED_NONCES + 1 }, (_, index) => index === 0 ? 'nonce-9' : `nonce-${index}`)],
  ];
  for (const [label, observedNonces] of cases) {
    const record = historyRecord({ observedNonces: observedNonces as CompletionLedgerRecord['observedNonces'] });
    assert.equal(isValidLedgerRecord(record), false, `observedNonces ${label} must be invalid`);
    assertFailsClosed([record], `observedNonces ${label}`);
  }
  // A full list exactly at the bound is still valid history.
  const atBound = historyRecord({ observedNonces: Array.from({ length: MAX_OBSERVED_NONCES }, (_, index) => index === 0 ? 'nonce-9' : `nonce-${index}`) });
  assert.equal(isValidLedgerRecord(atBound), true);
});

test('a malformed canonical nonce fails closed', () => {
  for (const nonce of ['', ' nonce-9', 'nonce-9 ', 'nonce-9\u0000nonce-8', 'nonce-9\u0001', 42, null, undefined]) {
    const record = historyRecord({ nonce: nonce as string, observedNonces: [nonce as string] });
    assert.equal(isValidLedgerRecord(record), false, `nonce ${String(nonce)} must be invalid`);
    assertFailsClosed([record], `nonce ${String(nonce)}`);
  }
});

test('an unsafe aggregate sum of otherwise-valid amounts fails closed', () => {
  // Each amount is individually a safe integer, but their relevant sum is not, so the
  // history cannot be used for a budget decision.
  const hugeA = historyRecord({ providerTransactionId: 'tx-a', nonce: 'nonce-a', rewardAmountMinor: Number.MAX_SAFE_INTEGER - 1 });
  const hugeB = historyRecord({ providerTransactionId: 'tx-b', nonce: 'nonce-b', rewardAmountMinor: Number.MAX_SAFE_INTEGER - 1 });
  assert.equal(isValidLedgerRecord(hugeA), true);
  assert.equal(isValidLedgerRecord(hugeB), true);
  assert.equal(safeSumMinor([hugeA.rewardAmountMinor, hugeB.rewardAmountMinor]), null);
  assertFailsClosed([hugeA, hugeB], 'unsafe aggregate sum');

  const validation = validateLedgerHistory([hugeA, hugeB], offer, 'user-9');
  assert.equal(validation.ok, false);
  if (!validation.ok) assert.equal(validation.reason, 'UNSAFE_AGGREGATE_SUM');

  // A sum that stays inside the safe range is a real aggregate and is accepted.
  const safeA = historyRecord({ providerTransactionId: 'tx-c', nonce: 'nonce-c', rewardAmountMinor: 1_000 });
  const safeB = historyRecord({ providerTransactionId: 'tx-d', nonce: 'nonce-d', rewardAmountMinor: 2_000 });
  const safeValidation = validateLedgerHistory([safeA, safeB], offer, 'user-9');
  assert.equal(safeValidation.ok, true);
  if (safeValidation.ok) assert.equal(safeValidation.history.usage.creditedMinor, 3_000);
});

test('safeAddMinor rejects an unsafe prospective total instead of comparing it', () => {
  assert.equal(safeAddMinor(500, 500), 1_000);
  assert.equal(safeAddMinor(Number.MAX_SAFE_INTEGER - 1, 500), null);
  assert.equal(safeAddMinor(-1, 500), null);
  assert.equal(safeAddMinor(Number.NaN, 500), null);
  assert.equal(safeAddMinor(1.5, 500), null);
  assert.equal(safeAddMinor(Number.MAX_SAFE_INTEGER, 1), null);
});

test('a malformed sibling cannot be masked by any number of valid siblings', () => {
  const validSiblings = [
    creditedRecord({ providerTransactionId: 'tx-10', nonce: 'nonce-10', externalUserId: 'user-10' }),
    creditedRecord({ providerTransactionId: 'tx-11', nonce: 'nonce-11', externalUserId: 'user-11' }),
    creditedRecord({ providerTransactionId: 'tx-12', nonce: 'nonce-12', externalUserId: 'user-12' }),
  ];
  for (const sibling of validSiblings) assert.equal(isValidLedgerRecord(sibling), true);
  // Without the malformed sibling the history credits normally.
  assert.equal(applyVerifiedCompletion(validSiblings, offer, envelope(event), observedAt).decision, 'CREDIT_COMPLETED_ACTION');

  const malformed = historyRecord({ providerTransactionId: 'tx-bad', nonce: 'nonce-bad', rewardAmountMinor: Number.NaN });
  for (const position of [0, 1, 2, 3]) {
    const records = [...validSiblings];
    records.splice(position, 0, malformed);
    assertFailsClosed(records, `malformed sibling at position ${position}`);
  }
});

test('a malformed sibling is not skipped because of its scope, currency, or state', () => {
  const valid = creditedRecord({ providerTransactionId: 'tx-20', nonce: 'nonce-20' });

  // A malformed record from another provider, another offer, another currency, and a
  // reversed state are all still part of the supplied authoritative history, so each
  // one fails the whole transition closed rather than being filtered out of scope.
  const outOfScope: [string, CompletionLedgerRecord][] = [
    ['other provider', historyRecord({ providerId: 'SRC-OTHER', providerTransactionId: 'tx-p', nonce: 'nonce-p', rewardAmountMinor: -1 })],
    ['other offer', historyRecord({ offerId: 'offer-2', providerTransactionId: 'tx-o', nonce: 'nonce-o', rewardAmountMinor: Number.NaN })],
    ['other currency', historyRecord({ rewardCurrency: 'USD', providerTransactionId: 'tx-c', nonce: 'nonce-c', rewardAmountMinor: 0 })],
    ['reversed state', historyRecord({ state: 'REVERSED', providerTransactionId: 'tx-r', nonce: 'nonce-r', rewardAmountMinor: 1.5 })],
    ['other user', historyRecord({ externalUserId: 'user-77', providerTransactionId: 'tx-u', nonce: 'nonce-u', rewardAmountMinor: Number.POSITIVE_INFINITY })],
  ];
  for (const [label, record] of outOfScope) {
    assertFailsClosed([valid, record], `malformed out-of-scope sibling: ${label}`);
  }
});

test('malformed history is rejected before replay, duplicate, and reversal decisions', () => {
  const valid = creditedRecord();
  const malformed = historyRecord({ providerTransactionId: 'tx-bad', nonce: 'nonce-bad', rewardAmountMinor: Number.NaN });

  // Without the malformed sibling, each of these is a different audited outcome. With
  // it present, none of them can be reached: history validation runs first.
  const replay = applyVerifiedCompletion([valid], offer, envelope({ ...event, providerTransactionId: 'tx-2' }), observedAt);
  assert.equal(replay.decision, 'REJECT_NONCE_REPLAY');
  assert.equal(replay.appendImmutableAuditEvent, true);

  const duplicate = applyVerifiedCompletion([valid], offer, envelope(event), observedAt);
  assert.equal(duplicate.decision, 'IGNORE_IDEMPOTENT_DUPLICATE');

  const reversal = applyVerifiedCompletion([valid], offer, envelope({ ...event, eventType: 'REVERSED', nonce: 'nonce-rev' }), observedAt);
  assert.equal(reversal.decision, 'REVERSE_COMPLETED_ACTION');
  assert.equal(reversal.appendImmutableAuditEvent, true);

  for (const [label, evt] of [
    ['replay', { ...event, providerTransactionId: 'tx-2' }],
    ['duplicate', event],
    ['reversal', { ...event, eventType: 'REVERSED' as const, nonce: 'nonce-rev' }],
  ] as [string, SignedCompletionEvent][]) {
    const result = applyVerifiedCompletion([valid, malformed], offer, envelope(evt), observedAt);
    assert.equal(result.decision, 'REJECT_INVALID_LEDGER_HISTORY', `${label} must not be reachable on malformed history`);
    assert.equal(result.balanceDeltaMinor, 0);
    assert.equal(result.next, null);
    assert.equal(result.appendImmutableAuditEvent, false, `${label} on malformed history must not be audited`);
  }
});

test('malformed history is rejected before usage, per-user, and budget decisions', () => {
  const valid = creditedRecord({ providerTransactionId: 'tx-30', nonce: 'nonce-30', externalUserId: 'user-1' });
  const malformed = historyRecord({ providerTransactionId: 'tx-bad', nonce: 'nonce-bad', rewardAmountMinor: -500 });

  // The valid sibling alone already exhausts the per-user limit, so the outcome would
  // normally be REJECT_PER_USER_LIMIT. Malformed history is rejected first instead.
  assert.equal(applyVerifiedCompletion([valid], { ...offer, perUserLimit: 1 }, envelope(event), observedAt).decision, 'REJECT_PER_USER_LIMIT');
  assertFailsClosed([valid, malformed], 'per-user limit path');

  // Likewise for the funded-budget path.
  assert.equal(applyVerifiedCompletion([valid], { ...offer, fundedBudgetMinor: 500 }, envelope(event), observedAt).decision, 'REJECT_FUNDED_BUDGET_EXHAUSTED');
  const budgetResult = applyVerifiedCompletion([valid, malformed], { ...offer, fundedBudgetMinor: 500 }, envelope(event), observedAt);
  assert.equal(budgetResult.decision, 'REJECT_INVALID_LEDGER_HISTORY');
  assert.equal(budgetResult.balanceDeltaMinor, 0);
  assert.equal(budgetResult.next, null);
  assert.equal(budgetResult.appendImmutableAuditEvent, false);
});

test('an unauthenticated envelope is still rejected as an invalid event, not as history', () => {
  // Authentication is evaluated first: forged input never reaches history validation
  // and can never be reported as a history problem.
  const forged = { event, signature: { algorithm: 'HMAC_SHA256', version: 'v1', verified: true, rawBodyBound: true } } as unknown as VerifiedCompletionEnvelope;
  const malformed = historyRecord({ rewardAmountMinor: Number.NaN });
  const result = applyVerifiedCompletion([malformed], offer, forged, observedAt);
  assert.equal(result.decision, 'REJECT_INVALID_EVENT');
  assert.equal(result.balanceDeltaMinor, 0);
  assert.equal(result.next, null);
  assert.equal(result.appendImmutableAuditEvent, false);
});

test('a prospective total that leaves the safe range fails closed as amount overflow', () => {
  // The supplied history is valid and sums exactly to MAX_SAFE_INTEGER. Only the new
  // transition cannot be represented, so this is not mislabeled as malformed history.
  const huge = historyRecord({ providerTransactionId: 'tx-h', nonce: 'nonce-h', rewardAmountMinor: Number.MAX_SAFE_INTEGER });
  const result = applyVerifiedCompletion([huge], { ...offer, fundedBudgetMinor: Number.MAX_SAFE_INTEGER }, envelope(event), observedAt);
  assert.equal(result.decision, 'REJECT_AMOUNT_OVERFLOW');
  assert.equal(result.balanceDeltaMinor, 0);
  assert.equal(result.next, null);
  assert.equal(result.appendImmutableAuditEvent, false);
});

test('duplicate record keys and duplicate nonce owners fail closed as invalid history', () => {
  const first = creditedRecord({ providerTransactionId: 'tx-40', nonce: 'nonce-40' });
  const recordCollision = historyRecord({ providerTransactionId: 'tx-40', nonce: 'nonce-40b' });
  assert.equal(completionRecordKey(first.providerId, first.offerId, first.providerTransactionId), completionRecordKey(recordCollision.providerId, recordCollision.offerId, recordCollision.providerTransactionId));
  assertFailsClosed([first, recordCollision], 'duplicate record key');

  const nonceCollision = historyRecord({ providerTransactionId: 'tx-41', nonce: 'nonce-40' });
  assertFailsClosed([first, nonceCollision], 'duplicate provider nonce owner');
});

test('throwing record properties and iterators fail closed as invalid history', () => {
  const throwingGetter = { ...historyRecord() } as Record<string, unknown>;
  Object.defineProperty(throwingGetter, 'rewardAmountMinor', {
    enumerable: true,
    get() { throw new Error('hostile getter'); },
  });
  assert.equal(isValidLedgerRecord(throwingGetter), false);
  assertFailsClosed([throwingGetter], 'throwing record property');

  const throwingIterator: unknown[] & { [Symbol.iterator]: () => unknown } = [historyRecord()];
  throwingIterator[Symbol.iterator] = () => { throw new Error('hostile iterator'); };
  assertFailsClosed(throwingIterator, 'throwing history iterator');
});

test('a stateful getter that changes after validation cannot escape through a later re-read', () => {
  let providerTransactionIdReads = 0;
  const stateful = { ...historyRecord() } as Record<string, unknown>;
  Object.defineProperty(stateful, 'providerTransactionId', {
    enumerable: true,
    get() {
      providerTransactionIdReads += 1;
      if (providerTransactionIdReads > 1) throw new Error('late hostile getter');
      return 'tx-stateful';
    },
  });

  // The validator must snapshot the untrusted record once. A later ledger read uses the
  // plain snapshot, not the original stateful object.
  const validation = validateLedgerHistory([stateful], offer, event.externalUserId);
  assert.equal(validation.ok, true);
  if (validation.ok) {
    assert.equal(providerTransactionIdReads, 1);
    assert.equal(validation.history.records[0]!.providerTransactionId, 'tx-stateful');
    assert.notEqual(validation.history.records[0], stateful);
  }
  providerTransactionIdReads = 0;
  const applied = applyVerifiedCompletion([stateful as unknown as CompletionLedgerRecord], offer, envelope(event), observedAt);
  assert.equal(applied.decision, 'CREDIT_COMPLETED_ACTION');
  assert.equal(providerTransactionIdReads, 1);
});

test('observed-nonce arrays are copied before validation so iterators cannot smuggle values', () => {
  let iterations = 0;
  const observedNonces = ['nonce-9'];
  Object.defineProperty(observedNonces, Symbol.iterator, {
    value: function* iterator() {
      iterations += 1;
      if (iterations === 1) {
        yield 'nonce-9';
        return;
      }
      yield 'nonce-9';
      yield 'nonce-evil\u0001tx';
    },
  });
  const candidate = { ...historyRecord(), observedNonces };
  const validation = validateLedgerHistory([candidate], offer, event.externalUserId);

  assert.equal(validation.ok, true);
  if (validation.ok) {
    assert.deepEqual(validation.history.records[0]!.observedNonces, ['nonce-9']);
    assert.equal(isValidLedgerRecord(validation.history.records[0]), true);
    assert.equal(Object.isFrozen(validation.history.records[0]!.observedNonces), true);
  }
  assert.equal(iterations, 1, 'the caller-owned array is traversed exactly once');
});

test('malformed history precedes click, identity, value, and inactive-offer decisions', () => {
  const malformed = historyRecord({ rewardAmountMinor: -1 });
  const cases: [string, TryoutOffer, SignedCompletionEvent][] = [
    ['click', offer, { ...event, actionType: 'CLICK' }],
    ['visit', offer, { ...event, actionType: 'VISIT' }],
    ['offer identity mismatch', offer, { ...event, providerId: 'SRC-OTHER-PROVIDER' }],
    ['value mismatch', offer, { ...event, rewardAmountMinor: 600 }],
    ['inactive offer', { ...offer, state: 'PAUSED' }, event],
  ];
  for (const [label, scopedOffer, scopedEvent] of cases) {
    const result = applyVerifiedCompletion([malformed], scopedOffer, envelope(scopedEvent), observedAt);
    assert.equal(result.decision, 'REJECT_INVALID_LEDGER_HISTORY', `${label} must not precede history validation`);
    assert.equal(result.balanceDeltaMinor, 0);
    assert.equal(result.next, null);
    assert.equal(result.appendImmutableAuditEvent, false);
  }
});

test('backdated duplicate and reversal observations fail without bricking the record', () => {
  const original = creditedRecord();
  const backdated = '2026-09-25T00:59:00.000Z';
  assert.equal(Date.parse(backdated) < Date.parse(original.lastObservedAt), true);

  for (const [label, duplicateEvent] of [
    ['same nonce', event],
    ['new nonce', { ...event, nonce: 'nonce-duplicate-backdated' }],
  ] as [string, SignedCompletionEvent][]) {
    const result = applyVerifiedCompletion([original], offer, envelope(duplicateEvent, backdated), backdated);
    assert.equal(result.decision, 'REJECT_OBSERVATION_TIME_REGRESSION', `${label} duplicate must reject backdated observation`);
    assert.equal(result.balanceDeltaMinor, 0);
    assert.equal(result.next, null);
    assert.equal(result.appendImmutableAuditEvent, false);
    assert.equal(isValidLedgerRecord(original), true, 'the original record remains valid');
  }

  const backdatedReversal = applyVerifiedCompletion(
    [original],
    offer,
    envelope({ ...event, eventType: 'REVERSED', nonce: 'nonce-reversal-backdated' }, backdated),
    backdated,
  );
  assert.equal(backdatedReversal.decision, 'REJECT_OBSERVATION_TIME_REGRESSION');
  assert.equal(backdatedReversal.balanceDeltaMinor, 0);
  assert.equal(backdatedReversal.next, null);
  assert.equal(backdatedReversal.appendImmutableAuditEvent, false);

  const forwardReversalAt = '2026-09-25T01:00:02.000Z';
  const reversed = applyVerifiedCompletion(
    [original],
    offer,
    envelope({ ...event, eventType: 'REVERSED', nonce: 'nonce-reversal-before-reopen' }, forwardReversalAt),
    forwardReversalAt,
  );
  assert.equal(reversed.decision, 'REVERSE_COMPLETED_ACTION');
  const reopen = applyVerifiedCompletion(
    [reversed.next!],
    offer,
    envelope({ ...event, nonce: 'nonce-reopen-backdated' }, backdated),
    backdated,
  );
  assert.equal(reopen.decision, 'REJECT_REOPEN_AFTER_REVERSAL');
  assert.equal(reopen.appendImmutableAuditEvent, true, 'a reopen conflict remains an authenticated audit event');
  assert.equal(reopen.balanceDeltaMinor, 0);
  assert.equal(reopen.next, null);

  // A later, valid completion still succeeds from the untouched original history.
  const followUp = applyVerifiedCompletion(
    [original],
    offer,
    envelope({ ...event, providerTransactionId: 'tx-follow-up', nonce: 'nonce-follow-up' }, '2026-09-25T01:00:02.000Z'),
    '2026-09-25T01:00:02.000Z',
  );
  assert.equal(followUp.decision, 'CREDIT_COMPLETED_ACTION');
  assert.equal(isValidLedgerRecord(followUp.next), true);
});

test('forward duplicate and reversal observations produce valid monotonic records', () => {
  const original = creditedRecord();
  const duplicateAt = '2026-09-25T01:00:02.000Z';
  const duplicate = applyVerifiedCompletion(
    [original],
    offer,
    envelope({ ...event, nonce: 'nonce-duplicate-forward' }, duplicateAt),
    duplicateAt,
  );
  assert.equal(duplicate.decision, 'IGNORE_IDEMPOTENT_DUPLICATE');
  assert.equal(duplicate.balanceDeltaMinor, 0);
  assert.equal(duplicate.appendImmutableAuditEvent, false);
  assert.equal(duplicate.next?.lastObservedAt, duplicateAt);
  assert.equal(isValidLedgerRecord(duplicate.next), true);

  const reversalAt = '2026-09-25T01:00:03.000Z';
  const reversed = applyVerifiedCompletion(
    [duplicate.next!],
    offer,
    envelope({ ...event, eventType: 'REVERSED', nonce: 'nonce-reversal-forward' }, reversalAt),
    reversalAt,
  );
  assert.equal(reversed.decision, 'REVERSE_COMPLETED_ACTION');
  assert.equal(reversed.balanceDeltaMinor, -500);
  assert.equal(reversed.appendImmutableAuditEvent, true);
  assert.equal(reversed.next?.lastObservedAt, reversalAt);
  assert.deepEqual(reversed.next?.observedNonces, ['nonce-1', 'nonce-duplicate-forward', 'nonce-reversal-forward']);
  assert.equal(isValidLedgerRecord(reversed.next), true);
});
