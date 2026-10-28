import test from 'node:test';
import assert from 'node:assert/strict';
import {
  VERIFIED_PUBLIC_OPPORTUNITIES,
  publicOpportunityById,
  loadVerifiedPublicOpportunities,
} from '../src/public-supply/verified-public-opportunities.js';
import {
  isPublicOpportunityDisplayable,
  dedupePublicOpportunities,
  assessPublicSupplyFreshness,
  displayablePublicOpportunityCards,
  PUBLIC_OPPORTUNITY_MAX_AGE_DAYS,
  PUBLIC_SUPPLY_EXPIRY_WARNING_DAYS,
  toPublicOpportunityCard,
  toPublicOpportunityDetail,
  computeUserValueScore,
  type PublicOpportunity,
} from '../src/public-supply/domain.js';
import {
  buildAdClickFirstBrowse,
  buildAdClickFirstTodayRoute,
  buildAdClickFirstOpportunityDetail,
} from '../src/ad-click-first/consumer-home.js';
import {
  renderAdClickFirstBrowseWeb,
  renderAdClickFirstTodayRouteWeb,
  renderAdClickFirstOpportunityDetailWeb,
} from '../src/ad-click-first/consumer-web.js';
import {
  createEmptySupplyConsumerHttpHandler,
  createPublicSupplyConsumerHttpHandler,
} from '../src/http/consumer-http.js';
import worker from '../src/worker.js';

const VERIFIED_AT = '2026-10-25T00:50:00.000Z';

test('verified public supply covers 5 vendors with at least 5 opportunities', () => {
  assert.ok(VERIFIED_PUBLIC_OPPORTUNITIES.length >= 5);
  const vendors = new Set(VERIFIED_PUBLIC_OPPORTUNITIES.map((item) => item.vendor));
  for (const expected of ['Prolific', 'Outlier', 'OneForma', 'DataAnnotation', 'TELUS Digital']) {
    assert.ok(vendors.has(expected), `missing vendor ${expected}`);
  }
});

test('every verified public opportunity is displayable today and evidence-complete', () => {
  const now = new Date(VERIFIED_AT);
  for (const item of VERIFIED_PUBLIC_OPPORTUNITIES) {
    assert.equal(item.monetizationRole, 'NONE');
    assert.equal(item.status, 'OPEN');
    assert.ok(Number.isFinite(Date.parse(item.verifiedAt)), 'verifiedAt must parse');
    assert.match(item.applyUrl, /^https:\/\//);
    assert.match(item.sourceUrl, /^https:\/\//);
    assert.equal(item.userValueScore, computeUserValueScore({
      rewardConfirmed: item.reward.confirmed,
      todayTier: item.todayTier,
      koreaConfirmed: item.koreaStatus === 'CONFIRMED',
    }));
    assert.ok(isPublicOpportunityDisplayable(item, now), `${item.id} must be displayable at verified time`);
  }
});

test('reward units never mix ad points with hourly project pay', () => {
  const hourly = VERIFIED_PUBLIC_OPPORTUNITIES.find((item) => item.reward.basis === 'HOURLY');
  assert.ok(hourly, 'an hourly public opportunity must exist');
  const card = toPublicOpportunityCard(hourly);
  assert.match(card.rewardLabel, /\$/);
  assert.equal(card.rewardBasisLabel, '시간당');
});

test('stale public opportunities are not displayed active without re-verification', () => {
  const staleDays = PUBLIC_OPPORTUNITY_MAX_AGE_DAYS + 1;
  const staleAt = new Date(Date.parse(VERIFIED_AT) - staleDays * 24 * 60 * 60 * 1000).toISOString();
  const staleBase = VERIFIED_PUBLIC_OPPORTUNITIES[0]!;
  const stale: PublicOpportunity = { ...staleBase, verifiedAt: staleAt };
  assert.ok(stale, 'record exists');
  assert.equal(isPublicOpportunityDisplayable(stale, new Date(VERIFIED_AT)), false);
  const closed: PublicOpportunity = { ...staleBase, status: 'CLOSED' };
  assert.equal(isPublicOpportunityDisplayable(closed, new Date(VERIFIED_AT)), false);
  const unsafe: PublicOpportunity = { ...staleBase, applyUrl: 'javascript:alert(1)' };
  assert.equal(isPublicOpportunityDisplayable(unsafe, new Date(VERIFIED_AT)), false);
});

test('browse activates public categories and keeps the ad-click lane untouched', () => {
  const vm = buildAdClickFirstBrowse([], { publicOpportunities: VERIFIED_PUBLIC_OPPORTUNITIES });
  const byId = new Map(vm.categories.map((cat) => [cat.id, cat]));
  assert.equal(byId.get('SURVEY')?.active, true);
  assert.equal(byId.get('SURVEY')?.count, 1);
  assert.equal(byId.get('MICROTASK')?.active, true);
  assert.equal(byId.get('MICROTASK')?.count, 4);
  assert.equal(byId.get('SHORT_GIG')?.active, true);
  assert.equal(byId.get('USABILITY')?.active, false, 'usability has no verified live opportunity');
  assert.equal(vm.cards.length, 0, 'no ad-click cards in this lane');
  assert.equal(vm.publicCards.length, 6);
  assert.equal(vm.emptyState, null);
  assert.match(vm.publicSupplyNote ?? '', /B64는 수익을 받지 않습니다/);
});

test('browse category selection filters public cards and query matches title/vendor', () => {
  const vm = buildAdClickFirstBrowse([], { category: 'SURVEY', publicOpportunities: VERIFIED_PUBLIC_OPPORTUNITIES });
  assert.equal(vm.publicCards.length, 1);
  assert.equal(vm.publicCards[0]?.vendor, 'Prolific');
  const queried = buildAdClickFirstBrowse([], { category: 'MICROTASK', query: 'outlier', publicOpportunities: VERIFIED_PUBLIC_OPPORTUNITIES });
  assert.equal(queried.publicCards.length, 1);
  assert.equal(queried.publicCards[0]?.vendor, 'Outlier');
});

test('maxSeconds filter applies to ad cards only, never to public opportunities', () => {
  const vm = buildAdClickFirstBrowse([], { category: 'ALL', maxSeconds: 10, publicOpportunities: VERIFIED_PUBLIC_OPPORTUNITIES });
  assert.equal(vm.cards.length, 0);
  assert.equal(vm.publicCards.length, 6);
});

test('today route splits immediate from screening-required opportunities', () => {
  const vm = buildAdClickFirstTodayRoute([], { publicOpportunities: VERIFIED_PUBLIC_OPPORTUNITIES });
  assert.equal(vm.publicImmediateCards.length, 1);
  assert.equal(vm.publicImmediateCards[0]?.vendor, 'Prolific');
  assert.equal(vm.publicScreeningCards.length, 5);
  assert.equal(vm.emptyState, null);
  for (const card of vm.publicScreeningCards) {
    assert.equal(card.tierLabel, '신청·심사 후 참여');
  }
});

test('today page shows screening-required projects, not instant rewards', () => {
  const vm = buildAdClickFirstTodayRoute([], { publicOpportunities: VERIFIED_PUBLIC_OPPORTUNITIES });
  const html = renderAdClickFirstTodayRouteWeb(vm);
  assert.match(html, /신청·심사 후 참여/);
  assert.match(html, /지금 바로 보상이 확정되는 항목은 아닙니다/);
});

test('public detail renders required facts and a safe outbound link', () => {
  const vm = buildAdClickFirstOpportunityDetail([], 'pub-outlier-ko-voice', { publicOpportunities: VERIFIED_PUBLIC_OPPORTUNITIES });
  assert.equal(vm.found, true);
  assert.equal(vm.card, null);
  assert.ok(vm.publicDetail);
  const html = renderAdClickFirstOpportunityDetailWeb(vm);
  assert.match(html, /한국어 Voice AI Evaluator/);
  assert.match(html, /시급 최대 \$31/);
  assert.match(html, /B64 수익/);
  assert.match(html, /없음 · 업체에 직접 참여/);
  assert.match(html, /한국 참여 확인/);
  assert.match(html, /href="https:\/\/app\.outlier\.ai\/login\?job_post_id=4722459005"/);
  assert.match(html, /target="_blank"/);
  assert.match(html, /noopener noreferrer nofollow/);
});

test('Prolific card distinguishes participation eligibility from live study inventory', () => {
  const vm = buildAdClickFirstBrowse([], { category: 'SURVEY', publicOpportunities: VERIFIED_PUBLIC_OPPORTUNITIES });
  const card = vm.publicCards[0];
  assert.ok(card, 'Prolific card exists');
  assert.equal(card.vendor, 'Prolific');
  assert.equal(card.tierLabel, '참가자 등록 가능');
  assert.match(card.tierNote ?? '', /설문은 기간에 따라 공개됩니다/);
  assert.match(card.tierNote ?? '', /현재 가용 설문 수 미확인/);
  const html = renderAdClickFirstBrowseWeb(vm);
  assert.doesNotMatch(html, /바로 참여 가능/);
  assert.match(html, /참가자 등록 가능/);
  assert.match(html, /설문은 기간에 따라 공개됩니다/);
  const detailVm = buildAdClickFirstOpportunityDetail([], 'pub-prolific-participate', { publicOpportunities: VERIFIED_PUBLIC_OPPORTUNITIES });
  const detailHtml = renderAdClickFirstOpportunityDetailWeb(detailVm);
  assert.match(detailHtml, /참여 단계/);
  assert.match(detailHtml, /설문은 기간에 따라 공개됩니다/);
});

test('DataAnnotation card and detail surface unconfirmed Korea residency eligibility', () => {
  const vm = buildAdClickFirstBrowse([], { category: 'MICROTASK', publicOpportunities: VERIFIED_PUBLIC_OPPORTUNITIES });
  const da = vm.publicCards.find((card) => card.vendor === 'DataAnnotation');
  assert.ok(da, 'DataAnnotation card exists');
  assert.equal(da.koreaStatus, 'UNCONFIRMED');
  assert.match(da.koreaLabel, /한국 거주 자격 미확인/);
  const html = renderAdClickFirstBrowseWeb(vm);
  assert.match(html, /한국 거주 자격 미확인/);
  const detailVm = buildAdClickFirstOpportunityDetail([], 'pub-dataannotation-korean', { publicOpportunities: VERIFIED_PUBLIC_OPPORTUNITIES });
  const detailHtml = renderAdClickFirstOpportunityDetailWeb(detailVm);
  assert.match(detailHtml, /한국 거주 자격 미확인/);
  assert.doesNotMatch(detailHtml, /한국 참여 확인/);
  const count = (detailHtml.match(/한국 거주 자격 미확인/g) || []).length;
  assert.equal(count, 1);
});

test('reward display never doubles the unknown-amount wording', () => {
  for (const item of VERIFIED_PUBLIC_OPPORTUNITIES) {
    const card = toPublicOpportunityCard(item);
    assert.doesNotMatch(`${card.rewardLabel} ${card.rewardNote}`, /금액 미확인/);
  }
  assert.equal(toPublicOpportunityCard(VERIFIED_PUBLIC_OPPORTUNITIES.find((item) => item.id === 'pub-telus-korea-ai-community') as PublicOpportunity).rewardNote, '미확인');
  const oneforma = toPublicOpportunityCard(VERIFIED_PUBLIC_OPPORTUNITIES.find((item) => item.id === 'pub-oneforma-local-search-korea') as PublicOpportunity);
  assert.equal(oneforma.rewardNote, '시간당 · 미확인');
  const outlier = toPublicOpportunityCard(VERIFIED_PUBLIC_OPPORTUNITIES.find((item) => item.id === 'pub-outlier-ko-voice') as PublicOpportunity);
  assert.equal(outlier.rewardNote, '시간당');
});

test('today hero covers application-based opportunities, not only instant rewards', () => {
  const vm = buildAdClickFirstTodayRoute([], { publicOpportunities: VERIFIED_PUBLIC_OPPORTUNITIES });
  const html = renderAdClickFirstTodayRouteWeb(vm);
  assert.match(html, /오늘의 기회/);
  assert.match(html, /신청·심사가 필요한 프로젝트는 별도 구분됩니다/);
  assert.doesNotMatch(html, /지금 바로 할 수 있는 적립/);
  assert.match(html, /참가자 등록 가능/);
  assert.match(html, /신청·심사 후 참여/);
});

test('public detail hides stale records as not found', () => {
  const staleAt = new Date(Date.parse(VERIFIED_AT) - (PUBLIC_OPPORTUNITY_MAX_AGE_DAYS + 2) * 24 * 60 * 60 * 1000).toISOString();
  const staleBase = VERIFIED_PUBLIC_OPPORTUNITIES[0]!;
  const stale: PublicOpportunity = { ...staleBase, verifiedAt: staleAt };
  const vm = buildAdClickFirstOpportunityDetail([], stale.id, { publicOpportunities: [stale] });
  assert.equal(vm.found, false);
  assert.equal(vm.publicDetail, null);
});

test('public detail lookup falls back to ad cards first, then public lane', () => {
  const missing = buildAdClickFirstOpportunityDetail([], 'does-not-exist', { publicOpportunities: VERIFIED_PUBLIC_OPPORTUNITIES });
  assert.equal(missing.found, false);
  assert.equal(missing.emptyState, 'NO_LIVE_REWARD_SUPPLY');
});

test('empty-supply handler keeps browse/today without public cards (no behavior change)', async () => {
  const handler = createEmptySupplyConsumerHttpHandler();
  const browse = await handler(new Request('https://b64.example/browse'));
  const browseHtml = await browse.text();
  assert.match(browseHtml, /data-empty-state="NO_LIVE_REWARD_SUPPLY"/);
  assert.doesNotMatch(browseHtml, /검증된 공개 기회/);
  const today = await handler(new Request('https://b64.example/today'));
  assert.match(await today.text(), /data-empty-state="NO_LIVE_REWARD_SUPPLY"/);
});

test('public-supply handler serves verified opportunities on browse, today, and detail', async () => {
  const handler = createPublicSupplyConsumerHttpHandler();
  const browse = await handler(new Request('https://b64.example/browse'));
  assert.equal(browse.status, 200);
  const browseHtml = await browse.text();
  assert.match(browseHtml, /data-public-card-count="6"/);
  assert.match(browseHtml, /검증된 공개 기회/);
  assert.match(browseHtml, /아직 미확인/, 'ad lane stays honest zero-supply');

  const survey = await handler(new Request('https://b64.example/browse?category=SURVEY'));
  assert.match(await survey.text(), /Prolific 유료 온라인 리서치 참여/);

  const today = await handler(new Request('https://b64.example/today'));
  const todayHtml = await today.text();
  assert.match(todayHtml, /참가자 등록 가능/);
  assert.match(todayHtml, /신청·심사 후 참여/);

  const detail = await handler(new Request('https://b64.example/detail?id=pub-telus-korea-ai-community'));
  assert.equal(detail.status, 200);
  assert.match(await detail.text(), /TELUS Digital AI Community/);

  const missing = await handler(new Request('https://b64.example/detail?id=unknown'));
  assert.equal(missing.status, 404);
});

test('deployed worker home leads with verified public supply and keeps the ad lane honest (#5830)', async () => {
  const home = await worker.fetch(new Request('https://b64.example/'));
  const homeHtml = await home.text();
  // OWNER decision #5830: existing verified public opportunities are the first
  // actionable content on the home screen; the unapproved ad lane stays an
  // honest compact status and is never advertised as startable.
  const publicIndex = homeHtml.indexOf('home-public-opportunities');
  const adIndex = homeHtml.indexOf('id="available-now"');
  assert.ok(publicIndex >= 0 && adIndex > publicIndex, 'verified public supply renders first');
  assert.match(homeHtml, /data-public-card-count="6"/);
  assert.match(homeHtml, /data-empty-state="NO_LIVE_REWARD_SUPPLY"/);
  assert.match(homeHtml, /공급자 승인 대기/);
  assert.doesNotMatch(homeHtml, /지금 바로|즉시 적립|바로 적립 가능/);

  const browse = await worker.fetch(new Request('https://b64.example/browse'));
  assert.match(await browse.text(), /data-public-card-count="6"/);
});

test('public supply html escapes injected copy and blocks unsafe outbound links', () => {
  const malicious: PublicOpportunity = {
    ...VERIFIED_PUBLIC_OPPORTUNITIES[0]!,
    id: 'pub-evil',
    titleKo: '<script>alert("x")</script>',
    qualifications: 'a & b <c>',
    applyUrl: 'https://example.com/apply',
  };
  const vm = buildAdClickFirstBrowse([], { category: 'SURVEY', publicOpportunities: [malicious] });
  const html = renderAdClickFirstBrowseWeb(vm);
  assert.doesNotMatch(html, /<script>alert/);
  assert.match(html, /&lt;script&gt;/);
  const detailVm = buildAdClickFirstOpportunityDetail([], 'pub-evil', { publicOpportunities: [malicious] });
  const detailHtml = renderAdClickFirstOpportunityDetailWeb(detailVm);
  assert.doesNotMatch(detailHtml, /javascript:/);
  assert.match(detailHtml, /a &amp; b &lt;c&gt;/);
});

test('public opportunity lookup helper returns null for unknown ids', () => {
  assert.equal(publicOpportunityById(VERIFIED_PUBLIC_OPPORTUNITIES, 'missing'), null);
  assert.equal(publicOpportunityById(VERIFIED_PUBLIC_OPPORTUNITIES, 'pub-oneforma-local-search-korea')?.vendor, 'OneForma');
  assert.ok(loadVerifiedPublicOpportunities().length >= 5);
});

test('public detail card exposes payer and confirmation time', () => {
  const detail = toPublicOpportunityDetail(VERIFIED_PUBLIC_OPPORTUNITIES.find((item) => item.id === 'pub-outlier-ko-voice') as PublicOpportunity);
  assert.equal(detail.payer.includes('Outlier'), true);
  assert.match(detail.card.verifiedAt, /^\d{4}-\d{2}-\d{2}T/);
  assert.equal(detail.monetizationRole, 'NONE');
});

test('duplicated curation of one offer reaches the consumer once', () => {
  const base = VERIFIED_PUBLIC_OPPORTUNITIES[0]!;
  const twin: PublicOpportunity = { ...base, id: 'pub-curation-twin' };
  const otherProject: PublicOpportunity = { ...base, id: 'pub-curation-other', titleKo: 'Prolific 별개 연구 모집' };

  assert.equal(dedupePublicOpportunities([base, twin]).length, 1);
  assert.equal(dedupePublicOpportunities([base, otherProject]).length, 2, 'a different project of the same vendor is not a duplicate');

  const cards = displayablePublicOpportunityCards([base, twin, otherProject]);
  assert.equal(cards.length, 2);
});

test('freshness reads when verified supply stops displaying', () => {
  const now = new Date('2026-10-27T00:00:00.000Z');
  const dayMs = 24 * 60 * 60 * 1000;
  const windowMs = PUBLIC_OPPORTUNITY_MAX_AGE_DAYS * dayMs;
  const fresh: PublicOpportunity = { ...VERIFIED_PUBLIC_OPPORTUNITIES[0]!, verifiedAt: now.toISOString() };
  const expiringSoon: PublicOpportunity = {
    ...VERIFIED_PUBLIC_OPPORTUNITIES[1]!,
    verifiedAt: new Date(now.getTime() - (PUBLIC_OPPORTUNITY_MAX_AGE_DAYS - PUBLIC_SUPPLY_EXPIRY_WARNING_DAYS) * dayMs).toISOString(),
  };
  const expired: PublicOpportunity = {
    ...VERIFIED_PUBLIC_OPPORTUNITIES[2]!,
    verifiedAt: new Date(now.getTime() - (PUBLIC_OPPORTUNITY_MAX_AGE_DAYS + 1) * dayMs).toISOString(),
  };

  const report = assessPublicSupplyFreshness([fresh, expiringSoon, expired], now);
  assert.equal(report.activeCount, 2);
  assert.equal(report.staleCount, 1);
  assert.equal(report.expiringWithinDays, 1);
  assert.equal(report.nextExpiryAt, new Date(Date.parse(expiringSoon.verifiedAt) + windowMs).toISOString());
  assert.equal(report.laneEmptyAt, new Date(Date.parse(fresh.verifiedAt) + windowMs).toISOString());

  const empty = assessPublicSupplyFreshness([expired], now);
  assert.equal(empty.activeCount, 0);
  assert.equal(empty.nextExpiryAt, null);
  assert.equal(empty.laneEmptyAt, null);
});

test('no curated record claims a source check that has not happened yet', () => {
  const now = Date.now();
  for (const item of VERIFIED_PUBLIC_OPPORTUNITIES) {
    assert.ok(
      Date.parse(item.verifiedAt) <= now,
      `${item.id} carries a future verifiedAt, which would keep an unread source on screen`,
    );
  }
});
