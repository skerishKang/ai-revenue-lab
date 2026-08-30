import test from 'node:test';
import assert from 'node:assert/strict';
import {
  AYET_REWARDED_VIDEO_GO_LIVE_REQUIREMENTS,
  expectedAyetRewardedVideoSignature,
  processAyetRewardedVideoClientCallback,
  verifyAyetRewardedVideoClientCallback,
  type AyetRewardedVideoClientCallback,
} from '../src/ad-click-first/ayet-rewarded-video.js';

const publisherApiKey = 'server-only-test-key';

function signedCallback(overrides: Partial<AyetRewardedVideoClientCallback> = {}): AyetRewardedVideoClientCallback {
  const unsigned = {
    status: overrides.status ?? 'success',
    rewarded: overrides.rewarded ?? true,
    externalIdentifier: overrides.externalIdentifier ?? 'user-123',
    currency: overrides.currency ?? 10,
    conversionId: overrides.conversionId ?? 'conversion-abc',
    custom_1: overrides.custom_1,
    custom_2: overrides.custom_2,
    custom_3: overrides.custom_3,
    custom_4: overrides.custom_4,
    custom_5: overrides.custom_5,
  };
  const signature = expectedAyetRewardedVideoSignature(unsigned, publisherApiKey);
  return { ...unsigned, signature: overrides.signature ?? signature };
}

test('valid rewarded callback becomes a provisional reward event only', () => {
  const callback = signedCallback();
  assert.equal(verifyAyetRewardedVideoClientCallback(callback, publisherApiKey), true);
  const result = processAyetRewardedVideoClientCallback(callback, publisherApiKey, new Set());
  assert.equal(result.decision, 'ACCEPT_PROVISIONAL_REWARD_EVENT');
  assert.equal(result.settlementState, 'PENDING_S2S_RECONCILIATION');
  assert.equal(result.currency, 10);
  assert.equal(result.cashCustodyAction, 'NONE');
});

test('completion without rewarded=true can never grant a reward event', () => {
  const callback = signedCallback({ rewarded: false });
  const result = processAyetRewardedVideoClientCallback(callback, publisherApiKey, new Set());
  assert.equal(result.decision, 'REJECT_INVALID_CALLBACK');
  assert.equal(result.settlementState, 'NONE');
});

test('tampered reward amount fails the provider signature', () => {
  const callback = signedCallback();
  const tampered = { ...callback, currency: 999 };
  assert.equal(verifyAyetRewardedVideoClientCallback(tampered, publisherApiKey), false);
  assert.equal(processAyetRewardedVideoClientCallback(tampered, publisherApiKey, new Set()).decision, 'REJECT_INVALID_SIGNATURE');
});

test('a conversion id can never be credited twice', () => {
  const callback = signedCallback();
  const seen = new Set([callback.conversionId]);
  assert.equal(processAyetRewardedVideoClientCallback(callback, publisherApiKey, seen).decision, 'REJECT_DUPLICATE_CONVERSION');
});

test('publisher key is required and remains a server-side go-live dependency', () => {
  const callback = signedCallback();
  assert.equal(verifyAyetRewardedVideoClientCallback(callback, ''), false);
  assert.equal(AYET_REWARDED_VIDEO_GO_LIVE_REQUIREMENTS.includes('PUBLISHER_API_KEY_SERVER_SIDE_ONLY'), true);
  assert.equal(AYET_REWARDED_VIDEO_GO_LIVE_REQUIREMENTS.includes('ADS_TXT_PUBLISHED'), true);
  assert.equal(AYET_REWARDED_VIDEO_GO_LIVE_REQUIREMENTS.includes('CMP_CONSENT_FLOW_READY'), true);
  assert.equal(AYET_REWARDED_VIDEO_GO_LIVE_REQUIREMENTS.includes('DEMAND_SETUP_FINALIZED_WITH_ACCOUNT_MANAGER'), true);
});
