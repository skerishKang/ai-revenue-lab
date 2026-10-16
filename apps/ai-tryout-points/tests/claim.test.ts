import test from 'node:test';
import assert from 'node:assert/strict';
import { assessPointsClaim, availableClaimableMinor, claimRecordKey, DEFAULT_POINTS_CLAIM_STATE } from '../src/claim.js';
import type { PointsClaimRequest, PointsClaimState } from '../src/claim.js';
import { MAX_IDENTIFIER_LENGTH, type CompletionLedgerRecord } from '../src/domain.js';

function record(overrides: Partial<CompletionLedgerRecord> = {}): CompletionLedgerRecord {
  const base = {
    providerId: 'SRC-B65-DEMO', offerId: 'offer-1', providerTransactionId: 'tx-1', externalUserId: 'user-1',
    actionType: 'TRYOUT_COMPLETED', state: 'COMPLETED', rewardAmountMinor: 500, rewardCurrency: 'KRW',
    providerOccurredAt: '2026-09-25T01:00:00.000Z', firstObservedAt: '2026-09-25T01:00:01.000Z',
    lastObservedAt: '2026-09-25T01:00:01.000Z', nonce: 'nonce-1',
    ...overrides,
  } as CompletionLedgerRecord;
  // observedNonces always contains the canonical nonce and tracks overrides.
  return { ...base, observedNonces: overrides.observedNonces ?? [base.nonce] };
}

const request: PointsClaimRequest = {
  providerId: 'SRC-B65-DEMO', offerId: 'offer-1', externalUserId: 'user-1', rewardCurrency: 'KRW', claimAmountMinor: 500,
};

const liveState: PointsClaimState = {
  livePayoutEnabled: true, claimsFrozen: false, durableStorageProvisioned: true, providerIntegrated: true, paymentRailIntegrated: true,
};

test('an exactly covered claim is accepted but still cannot pay out', () => {
  const result = assessPointsClaim([record()], request);
  assert.equal(result.decision, 'ASSESS_CLAIMABLE');
  assert.equal(result.claimAccepted, true);
  assert.equal(result.availableMinor, 500);
  assert.equal(result.claimableMinor, 500);
  // Default state is non-live; acceptance is not payment.
  assert.equal(result.livePayoutEnabled, false);
  assert.equal(result.payoutBlockReason, 'LIVE_PAYOUT_DISABLED');
  assert.equal(result.payoutAllowed, false);
});

test('payout is blocked even when every state gate claims to be ready', () => {
  for (const state of [
    liveState,
    { ...liveState, durableStorageProvisioned: false },
    { ...liveState, providerIntegrated: false },
    { ...liveState, paymentRailIntegrated: false },
  ]) {
    const result = assessPointsClaim([record()], request, state);
    assert.equal(result.decision, 'ASSESS_CLAIMABLE');
    assert.equal(result.claimAccepted, true);
    // There is no payment rail in this slice, so payout is never authorized.
    assert.equal(result.payoutAllowed, false);
  }
  assert.equal(DEFAULT_POINTS_CLAIM_STATE.livePayoutEnabled, false);
  assert.equal(DEFAULT_POINTS_CLAIM_STATE.providerIntegrated, false);
  assert.equal(DEFAULT_POINTS_CLAIM_STATE.paymentRailIntegrated, false);
  assert.equal(DEFAULT_POINTS_CLAIM_STATE.durableStorageProvisioned, false);
});

test('the block reason stays truthful for an all-true readiness state', () => {
  const allTrue = assessPointsClaim([record()], request, {
    livePayoutEnabled: true, claimsFrozen: false, durableStorageProvisioned: true,
    providerIntegrated: true, paymentRailIntegrated: true,
  });
  assert.equal(allTrue.payoutAllowed, false);
  // The slice is source-only, so the honest reason is the source slice itself, never
  // a claim that an integrated payment rail is merely missing.
  assert.equal(allTrue.payoutBlockReason, 'SOURCE_ONLY_PAYOUT_DISABLED');

  // The specific missing prerequisite is still named when a caller admits it is absent.
  const noStorage = assessPointsClaim([record()], request, { ...liveState, durableStorageProvisioned: false });
  assert.equal(noStorage.payoutBlockReason, 'DURABLE_STORAGE_NOT_PROVISIONED');
  const noProvider = assessPointsClaim([record()], request, { ...liveState, providerIntegrated: false });
  assert.equal(noProvider.payoutBlockReason, 'PROVIDER_NOT_INTEGRATED');
  const notLive = assessPointsClaim([record()], request);
  assert.equal(notLive.payoutBlockReason, 'LIVE_PAYOUT_DISABLED');
});

test('rejects malformed, zero, negative, and non-finite claim amounts', () => {
  for (const claimAmountMinor of [0, -1, -500, Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY, 1.5, Number.MAX_SAFE_INTEGER + 1, '500', null, undefined]) {
    const result = assessPointsClaim([record()], { ...request, claimAmountMinor: claimAmountMinor as number });
    assert.equal(result.decision, 'REJECT_INVALID_CLAIM', `${String(claimAmountMinor)} must be rejected`);
    assert.equal(result.claimAccepted, false);
    assert.equal(result.availableMinor, 0);
    assert.equal(result.claimableMinor, 0);
    assert.equal(result.payoutAllowed, false);
  }
});

test('rejects malformed claim scope identifiers instead of normalizing them', () => {
  for (const overrides of [
    { providerId: '' },
    { providerId: ' SRC-B65-DEMO' },
    { providerId: 'SRC-B65-DEMO ' },
    { offerId: ' offer-1' },
    { externalUserId: '\tuser-1' },
    { externalUserId: '' },
    { rewardCurrency: 'krw' },
    { rewardCurrency: '' },
    { rewardCurrency: 'KRWX' },
  ]) {
    const result = assessPointsClaim([record()], { ...request, ...overrides });
    assert.equal(result.decision, 'REJECT_INVALID_CLAIM', `${JSON.stringify(overrides)} must be rejected`);
    assert.equal(result.claimAccepted, false);
  }
  for (const recordKeys of [[], [' '], [null], [''], ['a', 'a'], new Array(501).fill('x')]) {
    const result = assessPointsClaim([record()], { ...request, recordKeys: recordKeys as string[] });
    assert.equal(result.decision, 'REJECT_INVALID_CLAIM');
    assert.equal(result.claimAccepted, false);
  }
});

test('rejects overspend beyond the independently available amount', () => {
  const records = [record(), record({ providerTransactionId: 'tx-2', nonce: 'nonce-2' })];
  const available = availableClaimableMinor(records, request);
  assert.equal(available.availableMinor, 1000);

  const over = assessPointsClaim(records, { ...request, claimAmountMinor: 1001 });
  assert.equal(over.decision, 'REJECT_OVERS_SPEND');
  assert.equal(over.availableMinor, 1000);
  assert.equal(over.claimableMinor, 0);
  assert.equal(over.claimAccepted, false);
  assert.equal(over.payoutAllowed, false);

  // Exactly available is allowed.
  assert.equal(assessPointsClaim(records, { ...request, claimAmountMinor: 1000 }).decision, 'ASSESS_CLAIMABLE');
  // A claim against an empty ledger is an overspend, not a free grant.
  assert.equal(assessPointsClaim([], request).decision, 'REJECT_OVERS_SPEND');
});

test('reversed records are excluded from available and reject the claim', () => {
  const reversed = record({ state: 'REVERSED' });
  const available = availableClaimableMinor([reversed], request);
  assert.equal(available.availableMinor, 0);
  assert.deepEqual(available.reversed, [claimRecordKey(reversed)]);

  const result = assessPointsClaim([reversed], request);
  assert.equal(result.decision, 'REJECT_REVERSED_RECORD');
  assert.equal(result.claimAccepted, false);
  assert.equal(result.availableMinor, 0);
  assert.equal(result.payoutAllowed, false);
  assert.deepEqual(result.reversedRecordKeys, [claimRecordKey(reversed)]);

  // Explicitly scoping to a reversed record is rejected the same way.
  assert.equal(assessPointsClaim([reversed], { ...request, recordKeys: [claimRecordKey(reversed)] }).decision, 'REJECT_REVERSED_RECORD');

  // A reversal does not reduce a valid sibling claim's available amount below its own value.
  const mixed = [record({ providerTransactionId: 'tx-1', nonce: 'nonce-1' }), record({ providerTransactionId: 'tx-2', nonce: 'nonce-2', state: 'REVERSED' })];
  const scoped = assessPointsClaim(mixed, { ...request, recordKeys: [claimRecordKey(mixed[0]!)] });
  assert.equal(scoped.decision, 'ASSESS_CLAIMABLE');
  assert.equal(scoped.availableMinor, 500);
});

test('rejects unknown and currency-mismatched scoped records', () => {
  const existing = record();
  const unknown = assessPointsClaim([existing], { ...request, recordKeys: [claimRecordKey({ providerId: existing.providerId, offerId: existing.offerId, providerTransactionId: 'tx-missing' })] });
  assert.equal(unknown.decision, 'REJECT_UNKNOWN_RECORD');
  assert.equal(unknown.claimAccepted, false);

  const wrongCurrency = assessPointsClaim([existing], { ...request, rewardCurrency: 'USD' });
  assert.equal(wrongCurrency.decision, 'REJECT_OVERS_SPEND');
  assert.equal(wrongCurrency.availableMinor, 0);
  assert.equal(assessPointsClaim([existing], { ...request, rewardCurrency: 'USD', recordKeys: [claimRecordKey(existing)] }).decision, 'REJECT_CURRENCY_MISMATCH');

  // Another user's records are never available to this claim.
  assert.equal(assessPointsClaim([record({ externalUserId: 'user-2', providerTransactionId: 'tx-2', nonce: 'nonce-2' })], request).decision, 'REJECT_OVERS_SPEND');
  // Nor are another provider's or another offer's.
  assert.equal(assessPointsClaim([record({ providerId: 'SRC-OTHER', providerTransactionId: 'tx-3', nonce: 'nonce-3' })], request).decision, 'REJECT_OVERS_SPEND');
  assert.equal(assessPointsClaim([record({ offerId: 'offer-2', providerTransactionId: 'tx-4', nonce: 'nonce-4' })], request).decision, 'REJECT_OVERS_SPEND');
});

test('frozen claims and a malformed request fail closed', () => {
  const frozen = assessPointsClaim([record()], request, { ...DEFAULT_POINTS_CLAIM_STATE, claimsFrozen: true });
  assert.equal(frozen.decision, 'REJECT_CLAIMS_FROZEN');
  assert.equal(frozen.claimAccepted, false);
  assert.equal(frozen.payoutAllowed, false);

  for (const malformed of [null, undefined, {}, { ...request, providerId: 1 }] as unknown[]) {
    const result = assessPointsClaim([record()], malformed as PointsClaimRequest);
    assert.equal(result.decision, 'REJECT_INVALID_CLAIM');
    assert.equal(result.claimAccepted, false);
    assert.equal(result.payoutAllowed, false);
  }
});

test('a malformed reward amount on any scoped record rejects the claim', () => {
  const badAmounts = [Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY, -1, -500, 0, 1.5, Number.MAX_SAFE_INTEGER + 1, '500', null, undefined];
  for (const rewardAmountMinor of badAmounts) {
    const result = assessPointsClaim([record({ rewardAmountMinor: rewardAmountMinor as number })], request);
    assert.equal(result.decision, 'REJECT_INVALID_CLAIM', `reward ${String(rewardAmountMinor)} must be rejected`);
    assert.equal(result.claimAccepted, false);
    assert.equal(result.claimableMinor, 0);
    assert.equal(result.payoutAllowed, false);
    // availableClaimableMinor is a fail-closed read too: never a partial/rounded total.
    assert.equal(availableClaimableMinor([record({ rewardAmountMinor: rewardAmountMinor as number })], request).availableMinor, 0);
  }
});

test('an unsafe arithmetic sum of otherwise-valid amounts rejects the claim', () => {
  const hugeA = record({ providerTransactionId: 'tx-a', rewardAmountMinor: Number.MAX_SAFE_INTEGER - 1, nonce: 'nonce-a' });
  const hugeB = record({ providerTransactionId: 'tx-b', rewardAmountMinor: Number.MAX_SAFE_INTEGER - 1, nonce: 'nonce-b' });
  // Each amount is individually a safe integer, but their sum is not.
  const result = assessPointsClaim([hugeA, hugeB], request);
  assert.equal(result.decision, 'REJECT_INVALID_CLAIM');
  assert.equal(result.claimAccepted, false);
  assert.equal(result.claimableMinor, 0);
  assert.equal(result.payoutAllowed, false);
  assert.equal(availableClaimableMinor([hugeA, hugeB], request).availableMinor, 0);
});

test('control characters in a scoped record identifier reject the claim', () => {
  // providerTransactionId is part of the record but not of the scope match, so a
  // record carrying a control character stays in scope and must be rejected invalid
  // rather than silently counted or normalized.
  for (const providerTransactionId of ['tx-1\u0000tx-2', 'tx\u0001', 'tx-1\u007F', 'tx-1\u009F', 'tx-1\u2028', '']) {
    const result = assessPointsClaim([record({ providerTransactionId })], request);
    assert.equal(result.decision, 'REJECT_INVALID_CLAIM', `${JSON.stringify(providerTransactionId)} must be rejected`);
    assert.equal(result.claimAccepted, false);
    assert.equal(result.claimableMinor, 0);
    assert.equal(result.payoutAllowed, false);
  }
});

test('malformed currency, state, action, and timestamps on scoped records reject the claim', () => {
  const malformed: Partial<CompletionLedgerRecord>[] = [
    { rewardCurrency: 'krw' },
    { rewardCurrency: '' },
    { rewardCurrency: 'KRWX' },
    { state: 'COMPLETED\u0002' as never },
    { actionType: 'CLICK' as never },
    { actionType: 'VISIT' as never },
    { providerOccurredAt: 'not-a-date' },
    { firstObservedAt: '2026-13-45T99:99:99.999Z' },
    { lastObservedAt: '' },
    { lastObservedAt: 'not-a-date' },
  ];
  for (const overrides of malformed) {
    const result = assessPointsClaim([record(overrides)], request);
    assert.equal(result.decision, 'REJECT_INVALID_CLAIM', `${JSON.stringify(overrides)} must be rejected`);
    assert.equal(result.claimAccepted, false);
    assert.equal(result.payoutAllowed, false);
  }
});

test('a malformed record rejects even when the claim scope excludes it by currency', () => {
  // A malformed sibling in scope must fail the whole claim closed rather than being
  // silently ignored because its currency does not match the request.
  const good = record({ providerTransactionId: 'tx-1' });
  const malformedSibling = record({ providerTransactionId: 'tx-2', rewardAmountMinor: Number.NaN, nonce: 'nonce-2' });
  const result = assessPointsClaim([good, malformedSibling], request);
  assert.equal(result.decision, 'REJECT_INVALID_CLAIM');
  assert.equal(result.claimAccepted, false);
  assert.equal(result.payoutAllowed, false);
});

test('a malformed selected record rejects even when unselected siblings are healthy', () => {
  const good = record({ providerTransactionId: 'tx-1' });
  const malformed = record({ providerTransactionId: 'tx-2', rewardAmountMinor: -1, nonce: 'nonce-2' });
  const keys = [claimRecordKey(good), claimRecordKey(malformed)];
  const result = assessPointsClaim([good, malformed], { ...request, recordKeys: keys });
  assert.equal(result.decision, 'REJECT_INVALID_CLAIM');
  assert.equal(result.claimAccepted, false);
  assert.equal(result.payoutAllowed, false);
});

test('a non-record entry can never make a claim claimable', () => {
  // A non-object or empty entry is not a valid ledger record, so it can never back a
  // claim. It falls out of scope and therefore yields a fail-closed non-claimable
  // decision; it is never counted toward the available amount.
  for (const bad of [null, undefined, 'record', 42, {}]) {
    const result = assessPointsClaim([bad as unknown as CompletionLedgerRecord], request);
    assert.notEqual(result.decision, 'ASSESS_CLAIMABLE', `${String(bad)} must not be claimable`);
    assert.equal(result.claimAccepted, false);
    assert.equal(result.claimableMinor, 0);
    assert.equal(result.payoutAllowed, false);
  }
});

test('throwing scoped record accessors reject the claim instead of escaping', () => {
  const throwing = { ...record() } as Record<string, unknown>;
  Object.defineProperty(throwing, 'providerId', {
    enumerable: true,
    get() { throw new Error('hostile claim getter'); },
  });

  const assessment = assessPointsClaim([throwing as unknown as CompletionLedgerRecord], request);
  assert.equal(assessment.decision, 'REJECT_INVALID_CLAIM');
  assert.equal(assessment.claimAccepted, false);
  assert.equal(assessment.claimableMinor, 0);
  assert.equal(assessment.payoutAllowed, false);

  const available = availableClaimableMinor([throwing as unknown as CompletionLedgerRecord], request);
  assert.equal(available.availableMinor, 0);
  assert.deepEqual(available.considered, []);
});

test('a divergent reward getter is read once and cannot replace the validated claim value', () => {
  let reads = 0;
  const divergent = { ...record() } as Record<string, unknown>;
  Object.defineProperty(divergent, 'rewardAmountMinor', {
    enumerable: true,
    get() {
      reads += 1;
      return reads === 1 ? 500 : 900_000_000;
    },
  });

  const result = assessPointsClaim([divergent as unknown as CompletionLedgerRecord], request);
  assert.equal(result.decision, 'ASSESS_CLAIMABLE');
  assert.equal(result.availableMinor, 500);
  assert.equal(result.claimableMinor, 500);
  assert.equal(result.payoutAllowed, false);
  assert.equal(reads, 1);
});

test('an over-length identifier is rejected at the shared identifier boundary', () => {
  const overLength = 'x'.repeat(MAX_IDENTIFIER_LENGTH + 1);
  const result = assessPointsClaim([record({ providerTransactionId: overLength })], request);
  assert.equal(result.decision, 'REJECT_INVALID_CLAIM');
  assert.equal(result.claimAccepted, false);
  assert.equal(result.payoutAllowed, false);
});

test('assessments are frozen and contain no secret, token, or raw provider payload', () => {
  const result = assessPointsClaim([record()], request);
  assert.equal(Object.isFrozen(result), true);
  assert.equal(Object.isFrozen(result.consideredRecordKeys), true);
  const serialized = JSON.stringify(result);
  for (const forbidden of ['nonce-1', 'secret', 'signature', 'rawBody', 'token', 'apiKey']) {
    assert.equal(serialized.includes(forbidden), false, `assessment must not expose ${forbidden}`);
  }
});
