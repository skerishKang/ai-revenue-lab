'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = __dirname;
const core = require(path.join(root, 'product-v14-opportunity-detail-core.js'));
const uiSource = fs.readFileSync(path.join(root, 'product-v14-opportunity-detail.js'), 'utf8');
const cssSource = fs.readFileSync(path.join(root, 'product-v14-opportunity-detail.css'), 'utf8');
const indexSource = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const fixedNow = new Date('2026-08-25T00:00:00+09:00');

function opportunity(overrides = {}) {
  return {
    id: 'example-free',
    opportunityType: 'TEMP_FREE_ACCESS',
    eligibility: 'ACCOUNT_REQUIRED',
    provider: 'Example AI',
    productOrModel: 'Example Model',
    headline: 'Example Model이 지금 무료',
    benefitLabel: '$0 · 1M context',
    summary: '공식 출처로 확인한 기간 한정 무료 모델입니다.',
    access: ['Console', 'API'],
    priceOrCredit: '$0 during promotion',
    limit: '공식 제한은 경로별 확인',
    conditions: ['계정 필요'],
    ctaUrl: 'https://example.com/use',
    verifiedAt: '2026-08-25',
    verification: 'VERIFIED_OFFICIAL_WEB',
    sources: [
      { label: 'Example · Docs', url: 'https://example.com/docs', authority: 'OFFICIAL_WEB' },
      { label: 'Example · X', url: 'https://x.com/example/status/1', authority: 'OFFICIAL_SOCIAL' }
    ],
    ...overrides
  };
}

test('resolves an editorial opportunity from either its CTA or one of its recorded sources', () => {
  const item = opportunity();
  assert.equal(core.resolveOpportunityByUrl([item], 'https://example.com/use').id, item.id);
  assert.equal(core.resolveOpportunityByUrl([item], 'https://example.com/docs/').id, item.id);
  assert.equal(core.resolveOpportunityByUrl([item], 'https://example.com/other'), null);
});

test('temporary free access without an authoritative end date says the expiry is officially unpublished', () => {
  const vm = core.viewModel(opportunity({ expiresAt: null, expiryVerification: null }), fixedNow);
  assert.equal(vm.expiry, '기간 한정 · 종료일 공식 미공개');
});

test('verified expiry can show a remaining-day label while unverified expiry cannot', () => {
  const verified = core.viewModel(opportunity({
    expiresAt: '2026-08-28',
    expiryVerification: 'VERIFIED_OFFICIAL_SOCIAL'
  }), fixedNow);
  assert.match(verified.expiry, /2026\.08\.28까지/);
  assert.match(verified.expiry, /3일 남음/);

  const pending = core.viewModel(opportunity({
    expiresAt: '2026-08-28',
    expiryVerification: null
  }), fixedNow);
  assert.equal(pending.expiry, '종료일 주장 확인 중');
  assert.doesNotMatch(pending.expiry, /3일 남음/);
});

test('source authority labels preserve official-web and official-social distinctions', () => {
  assert.equal(core.sourceAuthorityLabel('OFFICIAL_WEB'), '공식 웹');
  assert.equal(core.sourceAuthorityLabel('OFFICIAL_SOCIAL'), '공식 발표');
  assert.equal(core.sourceAuthorityLabel('COMMUNITY'), '커뮤니티 출처');
});

test('deal deep links preserve unrelated query state and hash, and clear only the deal parameter', () => {
  const opened = core.buildDealLink('https://example.com/radar?route=abc#explore', 'example-free');
  const openedUrl = new URL(opened);
  assert.equal(openedUrl.searchParams.get('route'), 'abc');
  assert.equal(openedUrl.searchParams.get('deal'), 'example-free');
  assert.equal(openedUrl.hash, '#explore');

  const closed = new URL(core.clearDealLink(opened));
  assert.equal(closed.searchParams.get('deal'), null);
  assert.equal(closed.searchParams.get('route'), 'abc');
  assert.equal(closed.hash, '#explore');
});

test('editorial primary handoff is intercepted into the on-site detail sheet, while final CTA remains explicit', () => {
  assert.match(uiSource, /closest\('\[data-radar-url\]'\)/);
  assert.match(uiSource, /stopImmediatePropagation\(\)/);
  assert.match(uiSource, /resolveOpportunityByUrl/);
  assert.match(uiSource, /실제 사용하기 ↗/);
  assert.match(uiSource, /공식 출처 먼저 보기 ↗/);
  assert.match(uiSource, /role="dialog"/);
  assert.match(uiSource, /event\.key === 'Escape'/);
  assert.doesNotMatch(uiSource, /fetch\s*\(|XMLHttpRequest|Authorization|Bearer/);
});

test('explicit source links are not generically intercepted', () => {
  assert.doesNotMatch(uiSource, /closest\('a\[href\]'\)/);
  assert.doesNotMatch(uiSource, /querySelectorAll\('a'/);
});

test('detail UI has a real hidden-state lock and responsive mobile sheet rules', () => {
  assert.match(cssSource, /\.b60-opportunity-detail\[hidden\]\s*\{\s*display:\s*none\s*!important/);
  assert.match(cssSource, /@media \(max-width: 760px\)/);
  assert.match(cssSource, /height:\s*95dvh/);
});

test('index loads V14 detail assets after the V13 radar', () => {
  const v13Js = indexSource.indexOf('product-v13-editorial-radar.js');
  const coreJs = indexSource.indexOf('product-v14-opportunity-detail-core.js');
  const v14Js = indexSource.indexOf('product-v14-opportunity-detail.js');
  const v14Css = indexSource.indexOf('product-v14-opportunity-detail.css');
  assert.ok(v14Css > -1);
  assert.ok(v13Js > -1 && coreJs > v13Js && v14Js > coreJs);
});
