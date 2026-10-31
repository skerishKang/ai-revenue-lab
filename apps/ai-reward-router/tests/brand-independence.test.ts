import test from 'node:test';
import assert from 'node:assert/strict';
import {
  createIdentityHarness,
  getWithCookie,
  joinMember,
  postForm,
  TEST_ORIGIN,
} from './helpers/b64-identity-harness.js';
import { loadVerifiedPublicOpportunities } from '../src/public-supply/verified-public-opportunities.js';
import { createConsumerHttpHandler } from '../src/http/consumer-http.js';

/**
 * Brand independence of the consumer surface (#987, owner decision 2026-10-27).
 *
 * B64 is an independent business of ai-revenue-lab, so nothing a visitor can
 * read may present it as a PADIEM Chat or PADIEM Apps sub-service. The interim
 * product name stays `B64 AI Reward Router`; no new trademark, domain or company
 * name is asserted here.
 */

const handler = createConsumerHttpHandler({
  loadCandidates: () => [],
  loadPublicOpportunities: loadVerifiedPublicOpportunities,
});

const PUBLIC_PATHS = [
  '/',
  '/earn',
  '/today',
  '/browse',
  '/browse?category=MICROTASK',
  '/detail?id=pub-prolific-participate',
  '/pipeline',
  '/income',
];

async function render(path: string, theme: 'light' | 'dark', cookie?: string): Promise<string> {
  const request = new Request(`${TEST_ORIGIN}${path}`, {
    headers: {
      cookie: `b64_theme=${theme}${cookie ? `; ${cookie}` : ''}`,
    },
  });
  const response = await handler(request);
  assert.equal(response.status, 200, `${path} must render for the audit`);
  return response.text();
}

test('no consumer screen shows a PADIEM word in any theme', async () => {
  for (const theme of ['light', 'dark'] as const) {
    for (const path of PUBLIC_PATHS) {
      const html = await render(path, theme);
      assert.ok(!/PADIEM|Padiem/.test(html), `${path} (${theme}) still carries PADIEM branding`);
    }
  }
});

test('the interim product name is consistent across title, brand and hero', async () => {
  const home = await render('/', 'light');
  assert.match(home, /<title>B64 AI Reward Router<\/title>/);
  assert.match(home, /aria-label="B64 AI Reward Router"/);
  assert.match(home, /class="brand-wordmark">B64</);
  assert.match(home, /<p class="eyebrow">B64 AI Reward Router<\/p>/, 'the hero names the same product as the header');

  const pipeline = await render('/pipeline', 'light');
  assert.match(pipeline, /<title>내 수익 관리 · B64 AI Reward Router<\/title>/);
  assert.match(pipeline, /class="brand-wordmark">B64</);

  const browse = await render('/browse', 'light');
  assert.match(browse, /B64 · REWARD OPPORTUNITIES/);
});

test('the consumer surface links to no other product origin', async () => {
  for (const path of PUBLIC_PATHS) {
    const html = await render(path, 'light');
    assert.ok(!/padiem\.net/.test(html), `${path} links or points at a padiem.net host`);
  }
});

test('verified public supply and the unapproved ad lane stay clearly separated', async () => {
  const home = await render('/', 'light');
  assert.match(home, /검증된 공개 기회/);
  assert.match(home, /data-public-card-count="6"/);
  // The ad lane is an honest status, never a start-now invitation: it carries
  // no reward amount while no provider is approved.
  assert.match(home, /data-empty-state="NO_LIVE_REWARD_SUPPLY"/);
  assert.match(home, /공급자 승인 대기|광고·클릭·방문 적립은 공급자 승인이 완료되면 표시됩니다/);
  assert.ok(!/id="available-now"[\s\S]*적립 시작/.test(home), 'an unapproved lane must not offer to start earning');
});

test('the account gate names B64 and never another product login', async () => {
  const anonymous = await render('/pipeline', 'light');
  assert.match(anonymous, /수익 관리는 B64 계정으로 이용할 수 있습니다/);
  assert.match(anonymous, /<h2 id="account-title">B64 계정<\/h2>/);
  assert.match(anonymous, /이 계정은 B64 단독 계정입니다/);
  assert.match(anonymous, /action="\/join"/);
  assert.match(anonymous, /action="\/login"/);
});

test('a signed-in member view keeps the separation and the payout honesty rules', async () => {
  const { handler: identityHandler } = createIdentityHarness();
  const cookie = await joinMember(identityHandler, 'brand-audit@example.com', 'brand audit password');
  assert.equal((await identityHandler(postForm('/pipeline', {
    action: 'save', title: 'Brand audit record', vendor: 'Prolific', status: 'COMPLETED',
    expectedAmount: '9000', expectedCurrency: 'KRW',
    actualAmount: '12000', actualCurrency: 'KRW',
  }, cookie))).status, 303);

  const memberView = await (await identityHandler(getWithCookie('/pipeline', cookie))).text();
  assert.ok(!/PADIEM|Padiem/.test(memberView), 'the member view carries no PADIEM word');
  assert.match(memberView, /로그아웃/);
  assert.match(memberView, /지급 확인 전/, 'an unpaid amount is not shown as realised');
  assert.match(memberView, /summary-value--actual">0/);
});

test('the removed explainer block is gone rather than merely hidden', async () => {
  const home = await render('/', 'light');
  assert.ok(!/참여 방식/.test(home), 'the never-rendered how-it-works explainer was the duplicated copy');
  assert.ok(!/how-step/.test(home));
});
