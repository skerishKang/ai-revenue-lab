import test from 'node:test';
import assert from 'node:assert/strict';
import { createConsumerHttpHandler, createEmptySupplyConsumerHttpHandler } from '../src/http/consumer-http.js';
import type { AdClickConsumerCandidate } from '../src/ad-click-first/consumer-card.js';

const liveAd: AdClickConsumerCandidate = {
  id: 'http-live-ad',
  sourceId: 'SRC-AYET',
  title: '15초 광고 보기',
  actionKind: 'AD_VIEW',
  rewardAmount: 5,
  rewardUnit: 'POINT',
  certainty: 'CONDITIONAL',
  conditionSummary: '광고 완료와 공급자 확인 필요',
  estimatedActiveSeconds: 15,
  canonicalDestinationUrl: 'https://example.com/reward/http-live-ad',
  lastVerifiedAt: '2026-08-30T14:00:00.000Z',
  lifecycle: 'LIVE',
  sourcePolicyCleared: true,
  providerActivation: 'LIVE_AUTHORIZED',
};

function assertSecurityHeaders(response: Response): void {
  assert.equal(response.headers.get('cache-control'), 'no-store');
  assert.equal(response.headers.get('x-content-type-options'), 'nosniff');
  assert.equal(response.headers.get('x-frame-options'), 'DENY');
  assert.equal(response.headers.get('referrer-policy'), 'no-referrer');
  assert.match(response.headers.get('content-security-policy') ?? '', /script-src 'none'/);
}

test('default HTTP entrypoint renders honest zero-supply P0 Home at root', async () => {
  const handler = createEmptySupplyConsumerHttpHandler();
  const response = await handler(new Request('https://b64.example/'));
  assert.equal(response.status, 200);
  assert.match(response.headers.get('content-type') ?? '', /text\/html/);
  assertSecurityHeaders(response);
  const html = await response.text();
  assert.match(html, /data-empty-state="NO_LIVE_REWARD_SUPPLY"/);
  assert.match(html, /바로 적립/);
  assert.doesNotMatch(html, /설문|마이크로태스크|단기 프로젝트|구직/);
});

test('/earn uses injected candidates but still passes through consumer policy filtering', async () => {
  const handler = createConsumerHttpHandler({ loadCandidates: () => [liveAd] });
  const response = await handler(new Request('https://b64.example/earn'));
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /data-visible-card-count="1"/);
  assert.match(html, /15초 광고 보기/);
  assert.match(html, /5 POINT/);
});

test('uncleared injected supply remains hidden rather than becoming a card', async () => {
  const handler = createConsumerHttpHandler({
    loadCandidates: () => [{ ...liveAd, id: 'uncleared', sourcePolicyCleared: false }],
  });
  const response = await handler(new Request('https://b64.example/'));
  const html = await response.text();
  assert.doesNotMatch(html, /data-card-id="uncleared"/);
  assert.match(html, /NO_LIVE_REWARD_SUPPLY/);
});

test('health route is diagnostic only and grants no provider permission', async () => {
  const handler = createEmptySupplyConsumerHttpHandler();
  const response = await handler(new Request('https://b64.example/healthz'));
  assert.equal(response.status, 200);
  assertSecurityHeaders(response);
  const body = await response.json() as Record<string, unknown>;
  assert.equal(body.status, 'ok');
  assert.equal(body.consumerMode, 'AD_CLICK_FIRST');
  assert.equal(body.supplyActivation, 'OWNER_ACTION_PENDING');
  assert.equal(body.providerPermissionGranted, false);
});

test('HEAD returns headers without a body', async () => {
  const handler = createEmptySupplyConsumerHttpHandler();
  const response = await handler(new Request('https://b64.example/earn', { method: 'HEAD' }));
  assert.equal(response.status, 200);
  assert.equal(await response.text(), '');
  assertSecurityHeaders(response);
});

test('unsupported methods fail closed with 405', async () => {
  const handler = createEmptySupplyConsumerHttpHandler();
  const response = await handler(new Request('https://b64.example/earn', { method: 'POST' }));
  assert.equal(response.status, 405);
  assert.equal(response.headers.get('allow'), 'GET, HEAD');
  assertSecurityHeaders(response);
});

test('unknown routes return secured 404 responses', async () => {
  const handler = createEmptySupplyConsumerHttpHandler();
  const response = await handler(new Request('https://b64.example/survey'));
  assert.equal(response.status, 404);
  assertSecurityHeaders(response);
  assert.equal(await response.text(), 'Not Found');
});

test('candidate loader failure returns 503 instead of pretending supply is empty', async () => {
  const handler = createConsumerHttpHandler({
    loadCandidates: () => { throw new Error('provider unavailable'); },
  });
  const response = await handler(new Request('https://b64.example/'));
  assert.equal(response.status, 503);
  assert.equal(response.headers.get('retry-after'), '60');
  assertSecurityHeaders(response);
  assert.match(await response.text(), /temporarily unavailable/);
});
