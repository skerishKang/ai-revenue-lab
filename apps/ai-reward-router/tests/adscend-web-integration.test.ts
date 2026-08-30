import test from 'node:test';
import assert from 'node:assert/strict';
import {
  ADSCEND_CASH_INCENTIVE_ALLOWED_TRAFFIC,
  ADSCEND_P0_GO_LIVE_REQUIREMENTS,
  ADSCEND_VIDEO_CATEGORY_ID,
  assessAdscendP0Readiness,
  assessAdscendP0VideoOffer,
  buildAdscendWebVideoBrowserConfig,
  type AdscendOfferApiRecord,
} from '../src/ad-click-first/adscend-web-integration.js';

const cashVideoOffer: AdscendOfferApiRecord = {
  offerId: 123,
  allowedTraffic: ADSCEND_CASH_INCENTIVE_ALLOWED_TRAFFIC,
  categoryIds: [ADSCEND_VIDEO_CATEGORY_ID],
  previewUrl: 'https://example.com/preview',
  endDate: '2026-09-30T00:00:00.000Z',
  conversionNotes: 'Complete the advertiser-defined rewarded video action.',
};

test('only offer-level cash-incentive video supply can enter the Adscend P0 inventory test', () => {
  const result = assessAdscendP0VideoOffer({
    offer: cashVideoOffer,
    koreaEligible: true,
    webEligible: true,
    accountManagerClearedForB64CashModel: true,
  }, new Date('2026-08-30T12:00:00.000Z'));
  assert.equal(result.eligibleForP0InventoryTest, true);
  assert.deepEqual(result.reasons, []);
});

test('points-only or no-cash offers fail closed even when video and Korea/web eligible', () => {
  for (const allowedTraffic of [0, 1, 2] as const) {
    const result = assessAdscendP0VideoOffer({
      offer: { ...cashVideoOffer, allowedTraffic },
      koreaEligible: true,
      webEligible: true,
      accountManagerClearedForB64CashModel: true,
    }, new Date('2026-08-30T12:00:00.000Z'));
    assert.equal(result.eligibleForP0InventoryTest, false);
    assert.equal(result.reasons.includes('CASH_INCENTIVE_NOT_ALLOWED_FOR_OFFER'), true);
  }
});

test('non-video, unconfirmed Korea/web, uncleared cash model and ended offers are suppressed', () => {
  const result = assessAdscendP0VideoOffer({
    offer: { ...cashVideoOffer, categoryIds: [24], endDate: '2026-08-01T00:00:00.000Z' },
    koreaEligible: false,
    webEligible: false,
    accountManagerClearedForB64CashModel: false,
  }, new Date('2026-08-30T12:00:00.000Z'));
  assert.deepEqual(result.reasons, [
    'NOT_VIDEO_CATEGORY',
    'KOREA_NOT_CONFIRMED',
    'WEB_NOT_CONFIRMED',
    'B64_CASH_MODEL_NOT_CLEARED',
    'OFFER_ENDED',
  ]);
});

test('browser config is video-only and cannot contain the publisher API key', () => {
  const config = buildAdscendWebVideoBrowserConfig({
    publisherId: 77,
    offerWallProfileId: 88,
    externalUserId: 'opaque-user-123',
  });
  const url = new URL(config.iframeUrl);
  assert.equal(url.protocol, 'https:');
  assert.equal(url.pathname, '/adwall/publisher/77/profile/88');
  assert.equal(url.searchParams.get('subid1'), 'opaque-user-123');
  assert.equal(url.searchParams.get('category_id'), String(ADSCEND_VIDEO_CATEGORY_ID));
  assert.equal(url.searchParams.has('api_key'), false);
  assert.equal(config.apiKeyExposedToBrowser, false);
});

test('Adscend cannot go live until cash-model, Korea fill, postback security and external fulfillment are real', () => {
  const blocked = assessAdscendP0Readiness({
    publisherApproved: true,
    cashRewardModelApproved: true,
    offerWallProfileReady: true,
    videoOnlyCategoryReady: true,
    stableUserIdsReady: true,
    serverPostbackReady: true,
    secureHashVerified: true,
    apiKeyServerSideOnly: true,
    koreaVideoFillObserved: false,
    offerLevelAllowedTrafficEnforced: true,
    externalRewardFulfillmentReady: false,
    b64CashCustodyEnabled: false,
    fraudControlsReady: true,
  });
  assert.equal(blocked.readyForLiveAuthorizationReview, false);
  assert.equal(blocked.missingRequirements.includes('KOREA_VIDEO_INVENTORY_LIVE_TESTED'), true);
  assert.equal(blocked.missingRequirements.includes('EXTERNAL_REWARD_FULFILLMENT_READY_WITHOUT_B64_CASH_CUSTODY'), true);

  const ready = assessAdscendP0Readiness({
    publisherApproved: true,
    cashRewardModelApproved: true,
    offerWallProfileReady: true,
    videoOnlyCategoryReady: true,
    stableUserIdsReady: true,
    serverPostbackReady: true,
    secureHashVerified: true,
    apiKeyServerSideOnly: true,
    koreaVideoFillObserved: true,
    offerLevelAllowedTrafficEnforced: true,
    externalRewardFulfillmentReady: true,
    b64CashCustodyEnabled: false,
    fraudControlsReady: true,
  });
  assert.equal(ready.readyForLiveAuthorizationReview, true);
  assert.deepEqual(ready.missingRequirements, []);
  assert.equal(ADSCEND_P0_GO_LIVE_REQUIREMENTS.length, 12);
});
