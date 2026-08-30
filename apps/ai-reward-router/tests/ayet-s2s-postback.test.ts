import test from 'node:test';
import assert from 'node:assert/strict';
import {
  canonicalAyetS2SParameterString,
  expectedAyetS2SSecurityHash,
  normalizeVerifiedAyetS2SRewardPostback,
  verifyAyetS2SSecurityHash,
} from '../src/ad-click-first/ayet-s2s-postback.js';
import { applyProviderRewardEvent } from '../src/ad-click-first/reward-events.js';

const publisherApiKey = 'test-publisher-key';

const conversionParams = Object.freeze({
  callback_type: 'conversion',
  currency_amount: '100',
  currency_identifier: 'Coins',
  external_identifier: 'user 123',
  is_chargeback: '0',
  transaction_id: 'tx-abc',
});

test('S2S canonicalization mirrors documented alphabetical PHP query-string behavior', () => {
  assert.equal(
    canonicalAyetS2SParameterString(conversionParams),
    'callback_type=conversion&currency_amount=100&currency_identifier=Coins&external_identifier=user+123&is_chargeback=0&transaction_id=tx-abc',
  );
  assert.equal(
    expectedAyetS2SSecurityHash(conversionParams, publisherApiKey),
    '26cf747b937934ad041d0638a7794f560ecfd98b0eaaf4e91d1c9d4e6b9eb207',
  );
});

test('valid S2S conversion becomes a provider-confirmed reward event', () => {
  const hash = expectedAyetS2SSecurityHash(conversionParams, publisherApiKey);
  assert.equal(verifyAyetS2SSecurityHash(conversionParams, hash, publisherApiKey), true);
  const normalized = normalizeVerifiedAyetS2SRewardPostback({
    parameters: conversionParams,
    securityHash: hash,
    publisherApiKey,
    observedAt: '2026-08-30T11:30:00.000Z',
  });
  assert.equal(normalized.accepted, true);
  assert.equal(normalized.decision, 'ACCEPT_CONFIRMED_REWARD');
  assert.equal(normalized.rewardEvent?.eventType, 'CONFIRMED');
  assert.equal(normalized.rewardEvent?.providerTransactionId, 'tx-abc');
  assert.equal(normalized.rewardEvent?.amount, 100);
  assert.equal(normalized.rewardEvent?.unit, 'Coins');
});

test('S2S confirmation reconciles a provisional client reward without creating a wallet credit', () => {
  const provisional = applyProviderRewardEvent(null, {
    providerId: 'SRC-AYET',
    providerTransactionId: 'tx-abc',
    externalUserId: 'user 123',
    eventType: 'PROVISIONAL',
    amount: 100,
    unit: 'Coins',
    observedAt: '2026-08-30T11:29:00.000Z',
  });
  const hash = expectedAyetS2SSecurityHash(conversionParams, publisherApiKey);
  const normalized = normalizeVerifiedAyetS2SRewardPostback({
    parameters: conversionParams,
    securityHash: hash,
    publisherApiKey,
    observedAt: '2026-08-30T11:30:00.000Z',
  });
  const reconciled = applyProviderRewardEvent(provisional.next, normalized.rewardEvent!);
  assert.equal(reconciled.decision, 'CONFIRM_PENDING');
  assert.equal(reconciled.next?.state, 'CONFIRMED');
  assert.equal(reconciled.userBalanceMutation, 'NONE');
  assert.equal(reconciled.cashCustodyAction, 'NONE');
});

test('chargeback maps r-prefixed provider transaction back to the original transaction and reverses it', () => {
  const chargebackParams = Object.freeze({
    callback_type: 'chargeback',
    currency_amount: '-100',
    currency_identifier: 'Coins',
    external_identifier: 'user 123',
    is_chargeback: '1',
    transaction_id: 'r-tx-abc',
  });
  const hash = expectedAyetS2SSecurityHash(chargebackParams, publisherApiKey);
  const normalized = normalizeVerifiedAyetS2SRewardPostback({
    parameters: chargebackParams,
    securityHash: hash,
    publisherApiKey,
    observedAt: '2026-08-30T12:00:00.000Z',
  });
  assert.equal(normalized.decision, 'ACCEPT_REVERSAL');
  assert.equal(normalized.rewardEvent?.providerTransactionId, 'tx-abc');
  assert.equal(normalized.rewardEvent?.eventType, 'REVERSED');
  assert.equal(normalized.rewardEvent?.amount, 100);

  const confirmed = applyProviderRewardEvent(null, {
    ...normalized.rewardEvent!,
    eventType: 'CONFIRMED',
    observedAt: '2026-08-30T11:30:00.000Z',
  }).next;
  const reversed = applyProviderRewardEvent(confirmed, normalized.rewardEvent!);
  assert.equal(reversed.decision, 'REVERSE_CONFIRMED');
  assert.equal(reversed.next?.state, 'REVERSED');
});

test('tampered and non-reward optional callbacks fail closed', () => {
  const validHash = expectedAyetS2SSecurityHash(conversionParams, publisherApiKey);
  assert.equal(verifyAyetS2SSecurityHash({ ...conversionParams, currency_amount: '999' }, validHash, publisherApiKey), false);

  const optionalParams = Object.freeze({
    ...conversionParams,
    callback_type: 'optional',
    currency_amount: '0',
  });
  const optionalHash = expectedAyetS2SSecurityHash(optionalParams, publisherApiKey);
  const optional = normalizeVerifiedAyetS2SRewardPostback({
    parameters: optionalParams,
    securityHash: optionalHash,
    publisherApiKey,
    observedAt: '2026-08-30T11:30:00.000Z',
  });
  assert.equal(optional.accepted, false);
  assert.equal(optional.decision, 'REJECT_INVALID_CALLBACK_TYPE');
});
