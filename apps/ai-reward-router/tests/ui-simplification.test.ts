import test from 'node:test';
import assert from 'node:assert/strict';
import { createPublicSupplyConsumerHttpHandler } from '../src/http/consumer-http.js';
import worker from '../src/worker.js';
import { VERIFIED_PUBLIC_OPPORTUNITIES } from '../src/public-supply/verified-public-opportunities.js';
import { buildAdClickFirstConsumerHome } from '../src/ad-click-first/consumer-home.js';
import { renderAdClickFirstConsumerWeb, renderAdClickFirstBrowseWeb } from '../src/ad-click-first/consumer-web.js';
import { buildIncomePipelineViewModel, renderIncomePipelineWeb } from '../src/income-pipeline/consumer-view.js';
import type { UserIncomeRecord } from '../src/income-pipeline/domain.js';

const handler = createPublicSupplyConsumerHttpHandler();

test('home leads with one short value line and the "수익 기회 보기" CTA (#5830)', async () => {
  const html = await (await handler(new Request('https://b64.example/'))).text();
  assert.match(html, /수익 기회 보기/);
  assert.ok(!html.includes('수익 기회 찾기</a>'), 'the home primary CTA wording is the owner-approved one');
  // hero description stays one line; the old multi-paragraph intro is gone
  const heroMatch = html.match(/<section class="hero"[\s\S]*?<\/section>/);
  assert.ok(heroMatch);
  assert.ok((heroMatch[0].match(/<p>/g) ?? []).length <= 2, 'hero keeps at most eyebrow + one description line');
});

test('home shows verified public opportunities BEFORE the compact ad-lane status', async () => {
  const html = await (await handler(new Request('https://b64.example/'))).text();
  const publicIndex = html.indexOf('home-public-opportunities');
  const adIndex = html.indexOf('id="available-now"');
  assert.ok(publicIndex >= 0 && adIndex > publicIndex, 'verified supply is the first content a visitor can act on');
  assert.match(html, /data-public-card-count="6"/);
  assert.match(html, /아래 기회는 각 업체에서 직접 참여하며 PADIEM 수익은 0입니다\./);
});

test('home ad lane stays an honest compact status, never a "start now" invitation', async () => {
  const html = await (await handler(new Request('https://b64.example/'))).text();
  assert.match(html, /data-empty-state="NO_LIVE_REWARD_SUPPLY"/);
  assert.match(html, /아직 확인된 적립이 없습니다\. 검증된 공급자가 연결되면 이곳에 표시됩니다\./);
  assert.match(html, /공급자 승인 대기/);
  // The large empty card (brand mark + paragraphs) is reserved for detail pages.
  assert.ok(!html.includes('class="empty-state"'), 'home keeps no oversized empty-state card');
});

test('empty-supply home still keeps the compact honest status only (no public lane invented)', () => {
  const html = renderAdClickFirstConsumerWeb(buildAdClickFirstConsumerHome([]));
  assert.match(html, /data-empty-state="NO_LIVE_REWARD_SUPPLY"/);
  assert.ok(!html.includes('home-public-opportunities'), 'no public section is fabricated without supply');
});

test('browse category tabs and cards carry inline category icons (no external assets)', async () => {
  const html = await (await handler(new Request('https://b64.example/browse'))).text();
  assert.match(html, /class="category-icon"/);
  assert.ok((html.match(/category-icon/g) ?? []).length >= 6, 'tabs carry visual category markers');
  assert.match(html, /class="action-chip[\s\S]*?category-icon/, 'cards carry the earning-type icon');
  assert.ok(!/<img/i.test(html), 'no bitmap assets introduced');
});

test('detail puts the participation CTA at the top and long provenance into a collapsible section', async () => {
  const html = await (await handler(new Request('https://b64.example/detail?id=pub-telus-korea-ai-community'))).text();
  const ctaIndex = html.indexOf('<div class="detail-actions detail-actions--top">');
  const factsIndex = html.indexOf('<div class="detail-facts">');
  assert.ok(ctaIndex >= 0 && factsIndex > ctaIndex, 'CTA renders above the long fact list');
  assert.match(html, /<details class="detail-more">/);
  assert.match(html, /<summary>상세 정보 · 참여 조건 · 출처<\/summary>/);
  assert.match(html, /외부 제공자 사이트에서 직접 참여합니다\. PADIEM이 지급을 대행하거나 보장하지 않습니다\./);
  // truth survives the restructure: the zero-PADIEM-revenue fact is still present
  assert.match(html, /0 \(이용자 가치 제공용 — PADIEM 제휴 수익 없음\)/);
});

test('collapsed details are keyboard-accessible (native details/summary, no script)', async () => {
  const html = await (await handler(new Request('https://b64.example/detail?id=pub-telus-korea-ai-community'))).text();
  assert.match(html, /detail-more summary:focus-visible/);
  assert.ok(!/<script/i.test(html));
  assert.equal(
    html.match(/content-security-policy/i) === null,
    true,
  );
  const csp = (await handler(new Request('https://b64.example/'))).headers.get('content-security-policy');
  assert.ok(csp!.includes("script-src 'none'"));
});

test('pipeline summary is status-centred with icons and a short login gate', async () => {
  const record = {
    id: 'rec-1', userId: 'usr_x', opportunityId: null, externalRef: null,
    sourceType: 'MANUAL' as const, title: 'T', vendor: 'V', status: 'SAVED' as const,
    expectedAmount: null, expectedCurrency: null, actualAmount: null, actualCurrency: null,
    appliedAt: null, acceptedAt: null, completedAt: null, paidAt: null, expiresAt: null,
    note: null, sourceUrl: null, createdAt: '2026-10-25T00:00:00.000Z', updatedAt: '2026-10-25T00:00:00.000Z',
  } satisfies UserIncomeRecord;
  const html = renderIncomePipelineWeb(buildIncomePipelineViewModel({ userId: 'usr_x', records: [record] }));
  assert.match(html, /class="summary-card[\s\S]*?summary-icon/, 'summary cards carry status icons');
  assert.match(html, /summary-icon/);

  const anonymous = renderIncomePipelineWeb(buildIncomePipelineViewModel({ userId: null, records: [] }));
  assert.match(anonymous, /PADIEM 계정 로그인 후 이용할 수 있습니다\./);
  assert.ok(!anonymous.includes('장황한'), '');
});

test('today keeps the honest split between immediate and screening opportunities', async () => {
  const html = await (await handler(new Request('https://b64.example/today'))).text();
  assert.match(html, /참가자 등록 가능/);
  assert.match(html, /신청·심사 후 참여/);
  assert.match(html, /지금 바로 보상이 확정되는 항목은 아닙니다\./, 'screening tier never reads as instant reward');
});

test('public opportunity data is untouched: same cards, same links, same counts', async () => {
  const browse = await (await handler(new Request('https://b64.example/browse'))).text();
  assert.match(browse, /data-public-card-count="6"/);
  assert.ok(!browse.includes('data-visible-card-count'), 'ad lane renders no card count when zero');
  assert.ok(VERIFIED_PUBLIC_OPPORTUNITIES.length >= 6);
});
