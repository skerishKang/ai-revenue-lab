'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = __dirname;
const workbench = path.join(root, 'operator', 'editorial-intake');
const core = require(path.join(workbench, 'intake-core.js'));
const read = file => fs.readFileSync(path.join(workbench, file), 'utf8');
const fixedNow = new Date('2026-08-25T00:00:00Z');

function validBase(overrides = {}) {
  return {
    provider: 'Example AI',
    productOrModel: 'Example Model',
    headline: 'Example Model이 지금 무료',
    benefitLabel: '$0',
    summary: '공식 출처에서 현재 무료 사용 가능함을 확인한 테스트 후보입니다.',
    opportunityType: 'TEMP_FREE_ACCESS',
    editorialRole: 'STANDARD',
    eligibility: 'ACCOUNT_REQUIRED',
    categories: 'API, CODING',
    access: 'API',
    conditions: '계정 필요',
    ctaUrl: 'https://example.com/use',
    sourceUrl: 'https://example.com/docs',
    sourceLabel: 'Example · Docs',
    sourceAuthority: 'OFFICIAL_WEB',
    verification: 'VERIFIED_OFFICIAL_WEB',
    verifiedAt: '2026-08-25',
    observedAt: '2026-08-25T08:30:00+09:00',
    ...overrides
  };
}

test('workbench exposes only the four canonical opportunity mechanics', () => {
  assert.deepEqual(Array.from(core.OPPORTUNITY_TYPES), [
    'TEMP_FREE_ACCESS', 'SIGNUP_CREDIT', 'RECURRING_FREE', 'ALWAYS_FREE'
  ]);
  assert.deepEqual(Array.from(core.EDITORIAL_ROLES), ['HOTTEST', 'JUST_DROPPED', 'STANDARD', 'REFERENCE']);
});

test('verified temporary free access becomes a publish-now candidate', () => {
  const result = core.validateDraft(validBase({
    startAt: '2026-08-24',
    expiresAt: '2026-09-06',
    expiryVerification: 'VERIFIED_OFFICIAL_WEB'
  }), fixedNow);
  assert.equal(result.verdict, 'READY');
  assert.equal(result.disposition, 'PUBLISH_NOW');
  assert.equal(result.urgencyEligible, true);
  assert.equal(result.candidate.sources[0].authority, 'OFFICIAL_WEB');
  assert.deepEqual(Array.from(result.candidate.categories), ['API', 'CODING']);
});

test('an expiry date without authoritative expiry evidence remains pending and cannot claim urgency', () => {
  const result = core.validateDraft(validBase({
    expiresAt: '2026-08-28',
    expiryVerification: ''
  }), fixedNow);
  assert.equal(result.verdict, 'PENDING');
  assert.equal(result.disposition, 'PENDING_VERIFICATION');
  assert.equal(result.urgencyEligible, false);
  assert.ok(result.pending.some(item => item.code === 'UNVERIFIED_EXPIRY'));
});

test('signup credit is routed to signup benefits and HOTTEST requires an explicit exception', () => {
  const normal = core.validateDraft(validBase({
    opportunityType: 'SIGNUP_CREDIT',
    editorialRole: 'REFERENCE',
    eligibility: 'NEW_USER_ONLY',
    benefitLabel: '$100 credit'
  }), fixedNow);
  assert.equal(normal.verdict, 'READY');
  assert.equal(normal.disposition, 'PUBLISH_SIGNUP_BENEFIT');

  const hot = core.validateDraft(validBase({
    opportunityType: 'SIGNUP_CREDIT',
    editorialRole: 'HOTTEST',
    eligibility: 'NEW_USER_ONLY'
  }), fixedNow);
  assert.equal(hot.verdict, 'PENDING');
  assert.ok(hot.pending.some(item => item.code === 'SIGNUP_HOTTEST_EXCEPTION'));
});

test('recurring free requires an explicit cadence and preserves refill metadata', () => {
  const missing = core.validateDraft(validBase({
    opportunityType: 'RECURRING_FREE',
    editorialRole: 'REFERENCE'
  }), fixedNow);
  assert.equal(missing.verdict, 'BLOCKED');
  assert.ok(missing.errors.some(item => item.code === 'MISSING_RECURRENCE_CADENCE'));

  const ready = core.validateDraft(validBase({
    opportunityType: 'RECURRING_FREE',
    editorialRole: 'REFERENCE',
    recurrenceCadence: 'DAILY',
    recurrenceLabel: '50 requests / 매일',
    resetRule: '공식 리셋 시각 미표기'
  }), fixedNow);
  assert.equal(ready.verdict, 'READY');
  assert.equal(ready.disposition, 'PUBLISH_ALWAYS_FREE');
  assert.equal(ready.candidate.recurrence.cadence, 'DAILY');
  assert.equal(ready.candidate.recurrence.label, '50 requests / 매일');
});

test('expired opportunity is classified EXPIRED instead of publishable', () => {
  const result = core.validateDraft(validBase({
    expiresAt: '2026-08-20',
    expiryVerification: 'VERIFIED_OFFICIAL_SOCIAL'
  }), fixedNow);
  assert.equal(result.disposition, 'EXPIRED');
  assert.equal(result.urgencyEligible, false);
});

test('outputs create a compatible opportunity snippet and optional separate media candidate', () => {
  const outputs = core.buildOutputs(validBase({
    image: 'assets/editorial-example.webp',
    imageAlt: '노트북으로 AI API를 확인하는 화면',
    imageSource: 'Official media',
    imageCredit: 'Example AI',
    imageSourcePage: 'https://example.com/media'
  }), fixedNow);
  const parsed = JSON.parse(outputs.json);
  assert.equal(parsed.opportunity.provider, 'Example AI');
  assert.equal(parsed.media.image, 'assets/editorial-example.webp');
  assert.match(outputs.opportunityJs, /provider:\s*'Example AI'/);
  assert.doesNotMatch(outputs.opportunityJs, /mediaDraft/);
  assert.match(outputs.mediaJs, /sourcePage/);
});

test('workbench is frontend-only and has no publication transport', () => {
  const html = read('index.html');
  const app = read('app.js');
  const coreSource = read('intake-core.js');
  const operations = fs.readFileSync(path.join(root, 'operations', 'B60_EDITORIAL_OPERATIONS.md'), 'utf8');

  assert.match(html, /이 도구는 <strong>게시하지 않습니다/);
  assert.match(html, /GitHub 쓰기 · 자동 게시 · API 호출 없음/);
  assert.doesNotMatch(app, /fetch\s*\(|XMLHttpRequest|WebSocket|EventSource/);
  assert.doesNotMatch(coreSource, /fetch\s*\(|XMLHttpRequest|WebSocket|EventSource/);
  assert.doesNotMatch(app, /github\.com\/api|api\.github\.com|Authorization|Bearer/);
  assert.match(operations, /편집 인입 워크벤치/);
  assert.match(operations, /게시 권한을 갖지 않는다/);
});
