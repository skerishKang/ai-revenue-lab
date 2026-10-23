import test from 'node:test';
import assert from 'node:assert/strict';
import { buildAdClickFirstConsumerHome } from '../src/ad-click-first/consumer-home.js';
import {
  buildAdClickFirstBrowse,
  buildAdClickFirstOpportunityDetail,
} from '../src/ad-click-first/consumer-home.js';
import {
  renderAdClickFirstBrowseWeb,
  renderAdClickFirstOpportunityDetailWeb,
} from '../src/ad-click-first/consumer-web.js';
import type { AdClickConsumerCandidate } from '../src/ad-click-first/consumer-card.js';

const liveAd: AdClickConsumerCandidate = {
  id: 'ad-live',
  sourceId: 'SRC-AYET',
  title: '30초 광고 보기',
  actionKind: 'AD_VIEW',
  rewardAmount: 10,
  rewardUnit: 'POINT',
  certainty: 'CONDITIONAL',
  conditionSummary: '광고 완료와 공급자 확인이 필요합니다.',
  estimatedActiveSeconds: 30,
  canonicalDestinationUrl: 'https://example.com/reward/ad-live',
  lastVerifiedAt: '2026-08-30T11:55:00.000Z',
  lifecycle: 'LIVE',
  sourcePolicyCleared: true,
  providerActivation: 'LIVE_AUTHORIZED',
};

test('browse empty supply renders honest empty state and inactive category notice', () => {
  const html = renderAdClickFirstBrowseWeb(buildAdClickFirstBrowse([]));
  assert.match(html, /data-consumer-mode="OPPORTUNITY_BROWSE_AD_CLICK_FIRST"/);
  assert.match(html, /data-empty-state="NO_LIVE_REWARD_SUPPLY"/);
  assert.match(html, /준비 중/);
});

test('browse renders eligible cards with category tabs and filter form', () => {
  const html = renderAdClickFirstBrowseWeb(buildAdClickFirstBrowse([liveAd]));
  assert.match(html, /data-visible-card-count="1"/);
  assert.match(html, /30초 광고 보기/);
  assert.match(html, /name="q"/);
  assert.match(html, /name="maxSeconds"/);
  assert.match(html, /aria-label="카테고리"/);
});

test('browse maxSeconds filter narrows results', () => {
  const vm = buildAdClickFirstBrowse([liveAd], { maxSeconds: 10 });
  assert.equal(vm.cards.length, 0);
  assert.equal(vm.emptyState, 'NO_LIVE_REWARD_SUPPLY');
});

test('browse query filter narrows by title', () => {
  const vm = buildAdClickFirstBrowse([liveAd], { query: '광고' });
  assert.equal(vm.cards.length, 1);
  const vm2 = buildAdClickFirstBrowse([liveAd], { query: '없는제목' });
  assert.equal(vm2.cards.length, 0);
});

test('browse inactive category yields empty without exposing later-tier cards', () => {
  const vm = buildAdClickFirstBrowse([liveAd], { category: 'SURVEY' });
  assert.equal(vm.cards.length, 0);
  assert.equal(vm.selectedCategory, 'SURVEY');
});

test('detail renders card fields and safe outbound CTA', () => {
  const html = renderAdClickFirstOpportunityDetailWeb(buildAdClickFirstOpportunityDetail([liveAd], 'ad-live'));
  assert.match(html, /data-consumer-mode="OPPORTUNITY_DETAIL_AD_CLICK_FIRST"/);
  assert.match(html, /30초 광고 보기/);
  assert.match(html, /10 POINT/);
  assert.match(html, /SRC-AYET/);
  assert.match(html, /href="https:\/\/example\.com\/reward\/ad-live"/);
  assert.match(html, /target="_blank"/);
});

test('detail not found renders empty state and no outbound link', () => {
  const html = renderAdClickFirstOpportunityDetailWeb(buildAdClickFirstOpportunityDetail([liveAd], 'missing'));
  assert.match(html, /수익 기회를 찾을 수 없습니다/);
  assert.doesNotMatch(html, /href="https:/);
});

test('browse HTML escapes injected copy', () => {
  const candidate: AdClickConsumerCandidate = { ...liveAd, id: 'x', title: '<script>alert(1)</script>' };
  const html = renderAdClickFirstBrowseWeb(buildAdClickFirstBrowse([candidate]));
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;/);
});

test('detail HTML escapes injected copy', () => {
  const candidate: AdClickConsumerCandidate = { ...liveAd, id: 'y', title: '<img src=x>', conditionSummary: 'a & b' };
  const html = renderAdClickFirstOpportunityDetailWeb(buildAdClickFirstOpportunityDetail([candidate], 'y'));
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /a &amp; b/);
});
