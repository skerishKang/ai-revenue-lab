'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = __dirname;
const read = file => fs.readFileSync(path.join(root, file), 'utf8');

function editorialOpportunities() {
  const sandbox = { window: {} };
  vm.runInNewContext(read('data/editorial-opportunities.js'), sandbox);
  return Array.from(sandbox.window.B60_EDITORIAL_OPPORTUNITIES);
}

test('v13 loads editorial opportunities before the final presentation layer', () => {
  const html = read('index.html');
  assert.match(html, /product-v13-editorial-radar\.css/);
  assert.match(html, /data\/editorial-opportunities\.js/);
  assert.match(html, /data\/editorial-media\.js/);
  assert.match(html, /product-v13-editorial-radar\.js/);
  assert.ok(html.indexOf('data/editorial-opportunities.js') < html.indexOf('product-v13-editorial-radar.js'));
  assert.ok(html.indexOf('korean-v1.js') < html.indexOf('product-v13-editorial-radar.js'));
});

test('editorial surface uses raster photography and no new SVG filler', () => {
  const media = read('data/editorial-media.js');
  const js = read('product-v13-editorial-radar.js');
  assert.doesNotMatch(media, /\.svg(?:[?'"\s]|$)/i);
  assert.doesNotMatch(js, /<svg\b/i);
  assert.ok((media.match(/sourcePage:/g) || []).length >= 9);
  assert.match(media, /fireworks-starter-credit/);
  assert.match(media, /aws-free-tier-signup-credit/);
});

test('canonical mechanics separate temporary access, signup, recurring and always free', () => {
  const canon = read('operations/B60_PRODUCT_CANON.md');
  const ops = read('operations/B60_EDITORIAL_OPERATIONS.md');
  for (const type of ['TEMP_FREE_ACCESS', 'SIGNUP_CREDIT', 'RECURRING_FREE', 'ALWAYS_FREE']) {
    assert.match(canon, new RegExp(type));
    assert.match(ops, new RegExp(type));
  }
  assert.match(canon, /HOTTEST/);
  assert.match(canon, /JUST_DROPPED/);
  assert.match(canon, /hottest does not have to be newest/);
});

test('Ox Alpha is HOTTEST temporary free access without fabricated expiry', () => {
  const items = editorialOpportunities();
  const ox = items.find(item => item.id === 'opencode-ox-alpha-free');
  assert.ok(ox);
  assert.equal(ox.editorialRole, 'HOTTEST');
  assert.equal(ox.opportunityType, 'TEMP_FREE_ACCESS');
  assert.equal(ox.eligibility, 'ACCOUNT_REQUIRED');
  assert.equal(ox.expiresAt, null);
  assert.equal(ox.expiryVerification, null);
  assert.equal(ox.verification, 'VERIFIED_OFFICIAL_WEB');
});

test('GMI MiniMax is JUST_DROPPED with official-social promotion dates', () => {
  const items = editorialOpportunities();
  const gmi = items.find(item => item.id === 'gmi-minimax-free-fortnight');
  assert.ok(gmi);
  assert.equal(gmi.editorialRole, 'JUST_DROPPED');
  assert.equal(gmi.opportunityType, 'TEMP_FREE_ACCESS');
  assert.equal(gmi.startAt, '2026-08-24');
  assert.equal(gmi.expiresAt, '2026-09-06');
  assert.equal(gmi.expiryVerification, 'VERIFIED_OFFICIAL_SOCIAL');
  assert.match(gmi.productOrModel, /MiniMax M3/);
  assert.match(gmi.productOrModel, /Music 3\.0/);
});

test('Fireworks starter credit is a verified signup benefit with no fabricated expiry', () => {
  const items = editorialOpportunities();
  const fireworks = items.find(item => item.id === 'fireworks-starter-credit');
  assert.ok(fireworks);
  assert.equal(fireworks.editorialRole, 'SIGNUP_BENEFIT');
  assert.equal(fireworks.opportunityType, 'SIGNUP_CREDIT');
  assert.equal(fireworks.eligibility, 'ACCOUNT_REQUIRED');
  assert.equal(fireworks.benefitLabel, '$1 free credit');
  assert.equal(fireworks.expiresAt, null);
  assert.equal(fireworks.verification, 'VERIFIED_OFFICIAL_WEB');
  assert.match(fireworks.sources[0].url, /fireworks\.ai\/pricing/);
});

test('AWS signup credit stays broad AWS credit while preserving Bedrock relevance', () => {
  const items = editorialOpportunities();
  const aws = items.find(item => item.id === 'aws-free-tier-signup-credit');
  assert.ok(aws);
  assert.equal(aws.editorialRole, 'SIGNUP_BENEFIT');
  assert.equal(aws.opportunityType, 'SIGNUP_CREDIT');
  assert.equal(aws.eligibility, 'NEW_USER_ONLY');
  assert.equal(aws.benefitLabel, '$100 + up to $100');
  assert.equal(aws.expiresAt, null);
  assert.match(aws.planWindow, /6개월/);
  assert.match(aws.summary, /Bedrock/);
  assert.match(aws.summary, /Bedrock 전용이 아니라 AWS Free Tier 크레딧/);
  assert.ok(aws.sources.some(source => /free-tier-plans-activities/.test(source.url)));
});

test('benefit-first information architecture distinguishes hottest, just dropped and signup benefits', () => {
  const js = read('product-v13-editorial-radar.js');
  for (const label of ['지금 가장 핫함', '방금 뜬 무료', '가입해야 받는 혜택', '종료 임박', '계속 무료', '최근 확인', '확인 중']) {
    assert.match(js, new RegExp(label));
  }
  assert.match(js, /AI 무료 레이더/);
});

test('signup credits cannot displace HOTTEST, JUST_DROPPED or ENDING SOON lanes', () => {
  const js = read('product-v13-editorial-radar.js');
  assert.match(js, /const signupCredits = activeOpportunities\.filter\(item => item\.opportunityType === 'SIGNUP_CREDIT'\)/);
  assert.match(js, /const liveOpportunities = activeOpportunities\.filter\(item => item\.opportunityType !== 'SIGNUP_CREDIT'\)/);
  assert.match(js, /const hottest = liveOpportunities\.find\(item => item\.editorialRole === 'HOTTEST'\)/);
  assert.match(js, /const justDropped = liveOpportunities\.filter/);
  assert.match(js, /const expiring = \[\.\.\.liveOpportunities, \.\.\.signals\]\.filter\(verifiedExpiring\)/);
  assert.doesNotMatch(js, /\|\| activeOpportunities\[0\]/);
  assert.match(js, /가입 크레딧만으로 메인 HOT 영역을 채우지 않습니다/);
});

test('ending soon requires authoritative expiry and a seven-day urgency window', () => {
  const js = read('product-v13-editorial-radar.js');
  assert.match(js, /VERIFIED_OFFICIAL_WEB/);
  assert.match(js, /VERIFIED_OFFICIAL_SOCIAL/);
  assert.match(js, /days >= 0 && days <= 7/);
  assert.match(js, /authoritativeVerification\(item\.expiryVerification\)/);
  assert.match(js, /7일 안에 끝나는 것으로 공식 확인된 혜택/);
});

test('signup credits render as image-led cards with eligibility and source details', () => {
  const js = read('product-v13-editorial-radar.js');
  const css = read('product-v13-editorial-radar-polish.css');
  assert.match(js, /id=\"signup-benefits\"/);
  assert.match(js, /가입하면 받는 것/);
  assert.match(js, /한시 무료와는 따로/);
  assert.match(js, /eligibilityLabel\(item\)/);
  assert.match(js, /imageFigure\(item, 'is-signup'\)/);
  assert.match(js, /creditScope/);
  assert.match(js, /planWindow/);
  assert.match(css, /\.radar-photo\.is-signup/);
  assert.match(css, /\.radar-signup-facts/);
});

test('legacy cinematic is visually dormant while deep explore remains available', () => {
  const css = read('product-v13-editorial-radar.css');
  const js = read('product-v13-editorial-radar.js');
  assert.match(css, /\.cinematic,[\s\S]*\.signal,[\s\S]*\.source[\s\S]*display:\s*none\s*!important/);
  assert.match(js, /document\.getElementById\('explore'\)/);
  assert.match(js, /dispatchEvent\(new PopStateEvent\('popstate'/);
});

test('manual curation presentation remains frontend-only', () => {
  const js = read('product-v13-editorial-radar.js');
  assert.doesNotMatch(js, /fetch\s*\(/);
  assert.doesNotMatch(js, /XMLHttpRequest|WebSocket|EventSource/);
  assert.match(js, /수동 큐레이션/);
});
