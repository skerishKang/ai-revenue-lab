import test from 'node:test';
import assert from 'node:assert/strict';
import { assessAdClickConsumerCandidate, buildDefaultAdClickCards, type AdClickConsumerCandidate } from '../src/ad-click-first/consumer-card.js';

const liveCandidate: AdClickConsumerCandidate = {
  id: 'ad-1',
  sourceId: 'SRC-AYET',
  title: '광고 보고 보상 받기',
  actionKind: 'AD_VIEW',
  rewardAmount: 10,
  rewardUnit: 'POINT',
  certainty: 'CONDITIONAL',
  conditionSummary: '광고를 끝까지 보고 공급자 보상 확인이 완료되어야 합니다.',
  estimatedActiveSeconds: 30,
  canonicalDestinationUrl: 'https://example.com/ad/1',
  lastVerifiedAt: '2026-08-30T11:40:00.000Z',
  lifecycle: 'LIVE',
  sourcePolicyCleared: true,
  providerActivation: 'LIVE_AUTHORIZED',
};

test('only live authorized low-friction supply with a confirmed reward becomes a consumer card', () => {
  const assessment = assessAdClickConsumerCandidate(liveCandidate);
  assert.equal(assessment.visible, true);
  assert.deepEqual(assessment.reasons, []);
  assert.equal(assessment.card?.tier, 'AD_CLICK');
  assert.equal(assessment.card?.rewardLabel, '10 POINT');
  assert.equal(assessment.card?.estimatedActiveSeconds, 30);
});

test('the current ayeT integration must stay invisible until publisher onboarding is live-authorized', () => {
  const assessment = assessAdClickConsumerCandidate({ ...liveCandidate, providerActivation: 'PENDING_ONBOARDING' });
  assert.equal(assessment.visible, false);
  assert.equal(assessment.reasons.includes('PROVIDER_NOT_LIVE_AUTHORIZED'), true);
  assert.equal(assessment.card, null);
});

test('unknown reward never leaks into the click-first default surface', () => {
  const assessment = assessAdClickConsumerCandidate({ ...liveCandidate, rewardAmount: null, rewardUnit: null });
  assert.equal(assessment.visible, false);
  assert.equal(assessment.reasons.includes('REWARD_NOT_CONFIRMED'), true);
});

test('a generic clickable ad is not a rewarded CLICK action', () => {
  const assessment = assessAdClickConsumerCandidate({ ...liveCandidate, actionKind: 'CLICK', estimatedActiveSeconds: 5 });
  assert.equal(assessment.visible, false);
  assert.equal(assessment.reasons.includes('CLICK_INCENTIVE_NOT_EXPLICITLY_ALLOWED'), true);
});

test('CLICK becomes eligible only with explicit campaign/provider incentive authority', () => {
  const assessment = assessAdClickConsumerCandidate({
    ...liveCandidate,
    actionKind: 'CLICK',
    estimatedActiveSeconds: 5,
    incentivizedActionPermission: 'EXPLICITLY_ALLOWED',
  });
  assert.equal(assessment.visible, true);
  assert.deepEqual(assessment.reasons, []);
});

test('an explicitly prohibited CLICK remains suppressed', () => {
  const assessment = assessAdClickConsumerCandidate({
    ...liveCandidate,
    actionKind: 'CLICK',
    estimatedActiveSeconds: 5,
    incentivizedActionPermission: 'PROHIBITED',
  });
  assert.equal(assessment.visible, false);
  assert.equal(assessment.reasons.includes('CLICK_INCENTIVE_NOT_EXPLICITLY_ALLOWED'), true);
});

test('tasks longer than five minutes are not treated as click-first even when they come from an offerwall', () => {
  const assessment = assessAdClickConsumerCandidate({ ...liveCandidate, actionKind: 'VERY_SHORT_FREE_ACTION', estimatedActiveSeconds: 301 });
  assert.equal(assessment.visible, false);
  assert.equal(assessment.reasons.includes('ACTION_NOT_LOW_FRICTION'), true);
});

test('stale, ended, broken, non-HTTPS and uncleared supply are suppressed', () => {
  const candidates: AdClickConsumerCandidate[] = [
    liveCandidate,
    { ...liveCandidate, id: 'stale', lifecycle: 'STALE' },
    { ...liveCandidate, id: 'ended', lifecycle: 'ENDED' },
    { ...liveCandidate, id: 'broken', lifecycle: 'BROKEN' },
    { ...liveCandidate, id: 'http', canonicalDestinationUrl: 'http://example.com/ad' },
    { ...liveCandidate, id: 'policy', sourcePolicyCleared: false },
  ];
  assert.deepEqual(buildDefaultAdClickCards(candidates).map((card) => card.id), ['ad-1']);
});
