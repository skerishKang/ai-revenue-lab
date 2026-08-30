import test from 'node:test';
import assert from 'node:assert/strict';
import {
  AD_CLICK_FIRST_GATE,
  AD_CLICK_P0_ACTION_KINDS,
  AD_CLICK_P0_SOURCE_STRATEGY,
  CURRENT_CONSUMER_SUPPLY_VISIBILITY,
  EXCLUDED_DIRECT_CASH_REWARDED_AD_PATHS,
  filterDefaultConsumerSurface,
  isConsumerSupplyVisible,
} from '../src/ad-click-first/index.js';

test('issue 1112 keeps only ad/click supply visible on the default consumer surface', () => {
  assert.equal(AD_CLICK_FIRST_GATE.issueNumber, 1112);
  assert.equal(AD_CLICK_FIRST_GATE.status, 'IN_PROGRESS');
  assert.equal(isConsumerSupplyVisible('AD_CLICK'), true);
  assert.equal(isConsumerSupplyVisible('SURVEY'), false);
  assert.equal(isConsumerSupplyVisible('MICROTASK'), false);
  assert.equal(isConsumerSupplyVisible('SHORT_GIG'), false);
  assert.equal(isConsumerSupplyVisible('EXTERNAL_JOB_SEARCH'), false);
  assert.deepEqual(CURRENT_CONSUMER_SUPPLY_VISIBILITY, {
    AD_CLICK: 'ENABLED',
    SURVEY: 'HIDDEN_UNTIL_UNLOCK',
    MICROTASK: 'HIDDEN_UNTIL_UNLOCK',
    SHORT_GIG: 'HIDDEN_UNTIL_UNLOCK',
    EXTERNAL_JOB_SEARCH: 'HIDDEN_UNTIL_UNLOCK',
  });
});

test('default consumer filtering fails closed for all later earning tiers', () => {
  const visible = filterDefaultConsumerSurface([
    { id: 'ad-1', tier: 'AD_CLICK' as const },
    { id: 'survey-1', tier: 'SURVEY' as const },
    { id: 'micro-1', tier: 'MICROTASK' as const },
    { id: 'gig-1', tier: 'SHORT_GIG' as const },
    { id: 'job-1', tier: 'EXTERNAL_JOB_SEARCH' as const },
  ]);
  assert.deepEqual(visible, [{ id: 'ad-1', tier: 'AD_CLICK' }]);
});

test('P0 action vocabulary is limited to the lowest-friction earning actions', () => {
  assert.deepEqual(AD_CLICK_P0_ACTION_KINDS, [
    'AD_VIEW',
    'CLICK',
    'VISIT',
    'ATTENDANCE',
    'VERY_SHORT_FREE_ACTION',
  ]);
});

test('ayeT is the first integration candidate but remains blocked until real publisher authority exists', () => {
  const ayet = AD_CLICK_P0_SOURCE_STRATEGY[0];
  assert.equal(ayet?.sourceId, 'SRC-AYET');
  assert.equal(ayet?.rank, 1);
  assert.equal(ayet?.webOfferwall, 'OFFICIAL_SUPPORTED');
  assert.equal(ayet?.webRewardedVideo, 'OFFICIAL_SUPPORTED');
  assert.equal(ayet?.incentiveMechanism, 'OFFICIAL_TERMS_ALLOW_VIRTUAL_OR_REAL_REWARDS');
  assert.equal(ayet?.conversionCallbacks, 'OFFICIAL_SUPPORTED');
  assert.equal(ayet?.liveB64Permission, 'NOT_YET_GRANTED');
  assert.equal(ayet?.activation, 'BLOCKED_UNTIL_ACCOUNT_ADSLOT_TERMS_AND_CREDENTIALS');
});

test('Adscend is the second web P0 candidate but cash permission remains offer-specific and live-blocked', () => {
  const adscend = AD_CLICK_P0_SOURCE_STRATEGY[1];
  assert.equal(adscend?.sourceId, 'ADSCEND_MEDIA');
  assert.equal(adscend?.rank, 2);
  assert.equal(adscend?.incentiveMechanism, 'OFFER_LEVEL_ALLOWED_TRAFFIC_3_REQUIRED_FOR_CASH');
  assert.equal(adscend?.conversionCallbacks, 'SERVER_POSTBACK_SUPPORTED_SECURE_HASH_AVAILABLE');
  assert.equal(adscend?.liveB64Permission, 'NOT_YET_GRANTED');
  assert.equal(adscend?.activation, 'BLOCKED_UNTIL_PUBLISHER_APPROVAL_KR_FILL_AND_EXTERNAL_REWARD_FULFILLMENT');
});

test('Google rewarded ads are excluded from B64 direct-cash P0 due to provider reward policy', () => {
  assert.deepEqual(EXCLUDED_DIRECT_CASH_REWARDED_AD_PATHS, [{
    provider: 'GOOGLE_REWARDED_ADS',
    reason: 'DIRECT_MONETARY_REWARDS_PROHIBITED_BY_PROVIDER_POLICY',
  }]);
});
