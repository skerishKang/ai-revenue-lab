import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildAdClickFirstConsumerHome,
  buildAdClickFirstTodayRoute,
} from '../src/ad-click-first/consumer-home.js';
import type { AdClickConsumerCandidate } from '../src/ad-click-first/consumer-card.js';

const liveAd: AdClickConsumerCandidate = {
  id: 'ad-fast',
  sourceId: 'SRC-AYET',
  title: '30초 광고 보기',
  actionKind: 'AD_VIEW',
  rewardAmount: 10,
  rewardUnit: 'POINT',
  certainty: 'CONDITIONAL',
  conditionSummary: '광고 완료와 공급자 확인이 필요합니다.',
  estimatedActiveSeconds: 30,
  canonicalDestinationUrl: 'https://example.com/reward/ad-fast',
  lastVerifiedAt: '2026-08-30T11:55:00.000Z',
  lifecycle: 'LIVE',
  sourcePolicyCleared: true,
  providerActivation: 'LIVE_AUTHORIZED',
};

const slowerVisit: AdClickConsumerCandidate = {
  ...liveAd,
  id: 'visit-slow',
  title: '짧은 방문 적립',
  actionKind: 'VISIT',
  estimatedActiveSeconds: 90,
  canonicalDestinationUrl: 'https://example.com/reward/visit-slow',
};

test('P0 home exposes one primary navigation item and no later-tier UI', () => {
  const home = buildAdClickFirstConsumerHome([slowerVisit, liveAd]);
  assert.equal(home.mode, 'AD_CLICK_FIRST');
  assert.deepEqual(home.primaryNavigation, [{ id: 'EARN_NOW', label: '바로 적립' }]);
  assert.equal(home.accountOnboardingVisibleToConsumer, false);
  assert.equal(home.laterTierNavigationVisible, false);
  assert.equal(home.laterTierSectionsVisible, false);
  assert.deepEqual(home.sections.map((section) => section.id), ['AVAILABLE_NOW']);
  assert.deepEqual(home.sections[0]?.cards.map((card) => card.id), ['ad-fast', 'visit-slow']);
});

test('empty real supply remains an honest empty state and does not fabricate fallback survey/gig content', () => {
  const home = buildAdClickFirstConsumerHome([]);
  assert.equal(home.emptyState, 'NO_LIVE_REWARD_SUPPLY');
  assert.deepEqual(home.sections[0]?.cards, []);
  assert.equal(home.laterTierSectionsVisible, false);
});

test('blocked or onboarding-only ad supply does not leak into Home', () => {
  const home = buildAdClickFirstConsumerHome([
    { ...liveAd, id: 'pending', providerActivation: 'PENDING_ONBOARDING' },
    { ...liveAd, id: 'uncleared', sourcePolicyCleared: false },
  ]);
  assert.equal(home.emptyState, 'NO_LIVE_REWARD_SUPPLY');
  assert.deepEqual(home.sections[0]?.cards, []);
  assert.equal(home.accountOnboardingVisibleToConsumer, false);
});

test('CLICK still requires explicit rewarded-click authority inside the consumer Home pipeline', () => {
  const blockedClick: AdClickConsumerCandidate = {
    ...liveAd,
    id: 'generic-click',
    actionKind: 'CLICK',
    canonicalDestinationUrl: 'https://example.com/reward/click',
    incentivizedActionPermission: 'NOT_ESTABLISHED',
  };
  const allowedClick: AdClickConsumerCandidate = {
    ...blockedClick,
    id: 'rewarded-click',
    incentivizedActionPermission: 'EXPLICITLY_ALLOWED',
  };
  const home = buildAdClickFirstConsumerHome([blockedClick, allowedClick]);
  assert.deepEqual(home.sections[0]?.cards.map((card) => card.id), ['rewarded-click']);
});

test('Today Route never falls back to later-tier suggestions', () => {
  const route = buildAdClickFirstTodayRoute([slowerVisit, liveAd]);
  assert.equal(route.mode, 'TODAY_ROUTE_AD_CLICK_FIRST');
  assert.deepEqual(route.cards.map((card) => card.id), ['ad-fast', 'visit-slow']);
  assert.equal(route.laterTierSuggestionsVisible, false);
  assert.equal(route.emptyState, null);
});
