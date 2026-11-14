// #7679: the one screen an email signup lands on. It names the address the
// person signed up with (masked), returns to the service by a button and by a
// timed refresh, and exists in Korean and English, plain and inside a
// registered brand's skin. Every other screen keeps its bytes.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createApp } from '../worker.mjs';
import { maskEmail, SIGNUP_COMPLETE_DELAY_SECONDS } from '../signup-complete.mjs';
import { createSkinHarness, EN, REDIRECT } from './skin-harness.mjs';
import { offResponses } from './email-recovery-off-fixture.mjs';

const attr = (value) => value.replaceAll('&amp;', '&');
const returnAddress = (html) => new URL(attr(html.match(/<a class="btn (?:btn-)?primary" href="([^"]+)"/)[1]));

test('the address is masked the same way for short and long local parts', () => {
  assert.equal(maskEmail('minji.kim@example.com'), 'mi***@example.com');
  assert.equal(maskEmail('abc@example.com'), 'ab***@example.com');
  assert.equal(maskEmail('ab@example.com'), 'a***@example.com');
  assert.equal(maskEmail('a@example.com'), 'a***@example.com');
  assert.equal(maskEmail('한글메일@example.com'), '한글***@example.com');
  assert.equal(maskEmail('😀😀😀@example.com'), '😀😀***@example.com');
  for (const broken of ['', '@example.com', 'no-at-sign', null, undefined]) assert.equal(maskEmail(broken), '***');
});

test('a plain service shows the confirmation in Korean and returns by button and by timer', async () => {
  const f = await createSkinHarness();
  const { response, html } = await f.signup('minji.kim@example.com', 'brandless');
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('content-type'), 'text/html; charset=utf-8');
  assert.equal(response.headers.get('cache-control'), 'no-store');
  assert.equal(response.headers.get('referrer-policy'), 'no-referrer');
  assert.ok(response.headers.get('set-cookie').includes('Max-Age=0'), 'the login cookie is cleared as before');
  assert.ok(html.includes('<html lang="ko">'));
  assert.ok(html.includes('<h1>가입했어요</h1>'));
  assert.ok(html.includes('이 이메일로 로그인하시면 됩니다.'));
  assert.ok(html.includes('<p class="done-email">mi***@example.com</p>'));
  assert.ok(!html.includes('minji.kim'), 'the full address is never written');
  assert.ok(html.includes('>서비스로 돌아가기</a>'));
  assert.ok(html.includes(`${SIGNUP_COMPLETE_DELAY_SECONDS}초 뒤 자동으로 이동합니다.`));
  const target = returnAddress(html);
  assert.equal(target.origin + target.pathname, REDIRECT);
  assert.match(target.searchParams.get('code'), /^[A-Za-z0-9_-]{43}\.[A-Za-z0-9_-]{43}$/);
  assert.match(target.searchParams.get('state'), /^[A-Za-z0-9_-]{43}$/);
  // The timed return and the button name the same address.
  const refresh = attr(html.match(/<meta http-equiv="refresh" content="([^"]+)">/)[1]);
  assert.equal(refresh, `${SIGNUP_COMPLETE_DELAY_SECONDS};url=${target.href}`);
  // No script, no form and no external request on this screen.
  assert.ok(!html.includes('<script') && !html.includes('<form'));
  assert.deepEqual([...html.matchAll(/(?:src|href)="([^"]+)"/g)].map((m) => attr(m[1])), [target.href]);
  for (const marker of ['--lt-pearl', 'orbit', 'LoveTree']) assert.ok(!html.includes(marker), marker);
});

test('the plain confirmation follows the browser language', async () => {
  const f = await createSkinHarness();
  const { html } = await f.signup('minji.kim@example.com', 'brandless', {}, EN);
  assert.ok(html.includes('<html lang="en">'));
  assert.ok(html.includes('<h1>You are signed up</h1>'));
  assert.ok(html.includes('Use this email to sign in from now on.'));
  assert.ok(html.includes('>Return to the service</a>'));
  assert.ok(html.includes(`You will be taken back in ${SIGNUP_COMPLETE_DELAY_SECONDS} seconds.`));
  assert.ok(!html.includes('가입했어요'));
});

test('a registered brand shows the confirmation inside its own skin, in both themes and languages', async () => {
  const f = await createSkinHarness();
  const night = await f.signup('minji.kim+night@example.com');
  assert.equal(night.response.status, 200);
  assert.ok(night.html.includes('<body class="night">'));
  assert.ok(night.html.includes('<main class="auth-card" aria-labelledby="signup-complete-title">'));
  assert.ok(night.html.includes('<h1 id="signup-complete-title">가입했어요</h1>'));
  assert.ok(night.html.includes('<p class="eyebrow">PADIEM 계정</p>'));
  assert.ok(night.html.includes('<p class="done-email">mi***@example.com</p>'));
  assert.ok(night.html.includes('>LoveTree로 돌아가기</a>'));
  assert.ok(night.html.includes('<title>가입했어요 · LoveTree</title>'));
  assert.equal([...night.html.matchAll(/<img class="orbit /g)].length, 4, 'the same four photos as the login screen');
  assert.ok(night.html.includes('PADIEM 계정으로 로그인합니다'));
  assert.equal(returnAddress(night.html).origin + returnAddress(night.html).pathname, REDIRECT);
  // Every asset stays on the auth origin.
  for (const match of night.html.matchAll(/(?:src)="([^"]+)"|url\('([^']+)'\)/g)) assert.ok((match[1] || match[2]).startsWith('/assets/auth-skin/'));

  const garden = await f.signup('minji.kim+garden@example.com', 'lovetree-4-0', { lt_theme: 'garden' }, EN);
  assert.ok(garden.html.includes('<body class="garden">'));
  assert.ok(garden.html.includes('<html lang="en">'));
  assert.ok(garden.html.includes('<h1 id="signup-complete-title">You are signed up</h1>'));
  assert.ok(garden.html.includes('>Return to LoveTree</a>'));
  assert.ok(garden.html.includes('Signing in with a PADIEM account'));
});

test('an address with markup characters is written escaped', async () => {
  const f = await createSkinHarness();
  for (const client of ['brandless', 'lovetree-4-0']) {
    const { response, html } = await f.signup(`<b>"x'&${client}@example.com`, client);
    assert.equal(response.status, 200, client);
    assert.ok(html.includes('<p class="done-email">&lt;b***@example.com</p>'), client);
    assert.ok(!html.includes('<b>'), client);
  }
});

test('the confirmation rules travel only with that screen: forms, errors and logins keep their bytes', async () => {
  const f = await createSkinHarness();
  for (const client of ['brandless', 'lovetree-4-0']) {
    for (const path of ['/login', '/signup']) {
      const { html } = await f.begin(path, client);
      for (const marker of ['done-email', 'done-lead', 'done-note', 'http-equiv="refresh"']) assert.ok(!html.includes(marker), `${client} ${path} ${marker}`);
    }
  }
  // The frozen capture pins the other ten responses; only the finished signup differs.
  const responses = await offResponses(createApp);
  assert.deepEqual(responses.filter((r) => r.body.includes('done-email')).map((r) => r.name), ['signup-success']);
  const login = responses.find((r) => r.name === 'login-success');
  assert.equal(login.status, 302);
  assert.equal(login.body, '');
});
