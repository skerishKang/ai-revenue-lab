import test from 'node:test';
import assert from 'node:assert/strict';
import { buildAdClickFirstConsumerHome } from '../src/ad-click-first/consumer-home.js';
import { renderAdClickFirstConsumerWeb } from '../src/ad-click-first/consumer-web.js';
import type { AdClickConsumerCandidate, AdClickConsumerCard } from '../src/ad-click-first/consumer-card.js';
import type { AdClickFirstConsumerHomeViewModel } from '../src/ad-click-first/consumer-home.js';

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
  canonicalDestinationUrl: 'https://example.com/reward/ad-live?a=1&b=2',
  lastVerifiedAt: '2026-08-30T11:55:00.000Z',
  lifecycle: 'LIVE',
  sourcePolicyCleared: true,
  providerActivation: 'LIVE_AUTHORIZED',
};

test('zero-supply P0 renders an honest consumer state with one navigation lane', () => {
  const html = renderAdClickFirstConsumerWeb(buildAdClickFirstConsumerHome([]));
  assert.match(html, /data-consumer-mode="AD_CLICK_FIRST"/);
  assert.match(html, /바로 적립/);
  assert.match(html, /data-empty-state="NO_LIVE_REWARD_SUPPLY"/);
  assert.match(html, /실제로 참여할 수 있고 보상 조건이 확인된 항목만/);
  assert.doesNotMatch(html, /설문|마이크로태스크|단기 프로젝트|구직/);
  assert.doesNotMatch(html, /publisher|onboarding|API key/i);
});

test('eligible P0 card renders reward, action, time, freshness and safe outbound CTA', () => {
  const html = renderAdClickFirstConsumerWeb(buildAdClickFirstConsumerHome([liveAd]));
  assert.match(html, /data-visible-card-count="1"/);
  assert.match(html, /광고 보기/);
  assert.match(html, /10 POINT/);
  assert.match(html, /약 30초/);
  assert.match(html, /2026\.08\.30 확인/);
  assert.match(html, /href="https:\/\/example\.com\/reward\/ad-live\?a=1&amp;b=2"/);
  assert.match(html, /target="_blank"/);
  assert.match(html, /rel="noopener noreferrer nofollow"/);
});

test('consumer-controlled card copy is HTML escaped', () => {
  const candidate: AdClickConsumerCandidate = {
    ...liveAd,
    id: 'escaped',
    title: '<script>alert("x")</script>',
    conditionSummary: '완료 & 확인 <필수>',
  };
  const html = renderAdClickFirstConsumerWeb(buildAdClickFirstConsumerHome([candidate]));
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;alert\(&quot;x&quot;\)&lt;\/script&gt;/);
  assert.match(html, /완료 &amp; 확인 &lt;필수&gt;/);
});

test('renderer defensively suppresses an unsafe outbound URL even if a malformed view-model is injected', () => {
  const unsafeCard: AdClickConsumerCard = {
    id: 'unsafe',
    sourceId: 'TEST',
    tier: 'AD_CLICK',
    title: 'unsafe',
    actionKind: 'VISIT',
    rewardLabel: '1 POINT',
    certainty: 'GUARANTEED',
    conditionSummary: 'test',
    estimatedActiveSeconds: 10,
    canonicalDestinationUrl: 'javascript:alert(1)',
    lastVerifiedAt: '2026-08-30T11:55:00.000Z',
  };
  const malformed: AdClickFirstConsumerHomeViewModel = {
    ...buildAdClickFirstConsumerHome([]),
    sections: [{ id: 'AVAILABLE_NOW', title: '바로 가능한 적립', cards: [unsafeCard] }],
    emptyState: null,
  };
  const html = renderAdClickFirstConsumerWeb(malformed);
  assert.doesNotMatch(html, /javascript:/);
  assert.match(html, /data-empty-state="NO_LIVE_REWARD_SUPPLY"/);
});

test('responsive and accessibility contracts are present without external visual dependencies', () => {
  const html = renderAdClickFirstConsumerWeb(buildAdClickFirstConsumerHome([liveAd]));
  assert.match(html, /<meta name="viewport"/);
  assert.match(html, /prefers-reduced-motion: reduce/);
  assert.match(html, /:focus-visible/);
  assert.match(html, /<main id="top">/);
  assert.match(html, /aria-label="주요 메뉴"/);
  assert.doesNotMatch(html, /<img|@font-face|fonts\.googleapis|cdn\./i);
});
