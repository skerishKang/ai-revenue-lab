// #7818: the 14-or-older gate on every email signup skin and the shared
// account documents (auth.padiem.net/privacy, /terms).
import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { AuthState } from '../state.mjs';
import { createSkinHarness, url, EN } from './skin-harness.mjs';

const KO = { 'accept-language': 'ko-KR,ko;q=0.9' };

async function beginSignup(clientId = 'lovetree-4-0', headers = {}) {
  const f = await createSkinHarness();
  const form = await f.begin('/signup', clientId, {}, headers);
  assert.equal(form.response.status, 200);
  return { f, form, headers };
}

async function postSignup(f, form, fields, headers = {}) {
  const action = form.html.match(/action="(\/signup\/password\?state=[^"]+)"/)[1].replaceAll('&amp;', '&');
  // A browser submits the hidden skin/carry inputs with the visible fields.
  const hidden = {};
  for (const [, name, value] of form.html.matchAll(/<input type="hidden" name="([^"]+)" value="([^"]*)">/g)) hidden[name] = value.replaceAll('&amp;', '&');
  const response = await f.app.fetch(new Request(`${url}${action}`, {
    method: 'POST', body: new URLSearchParams({ ...hidden, ...fields }),
    headers: { 'content-type': 'application/x-www-form-urlencoded', cookie: form.response.headers.get('set-cookie').split(';')[0], ...headers },
  }));
  return { response, html: await response.text() };
}

const signupFields = (email) => ({ name: '', email, password: 'synthetic-safe-password', age_confirm: 'yes' });

test('every signup skin asks for the 14-or-older confirmation and links the shared docs', async () => {
  for (const clientId of ['lovetree-4-0', 'b62', 'brandless']) {
    for (const [name, headers] of [['ko', KO], ['en', EN]]) {
      const begun = await beginSignup(clientId, headers); const { f, form } = begun;
      void f;
      assert.ok(form.html.includes('name="age_confirm"'), `${clientId} ${name} checkbox`);
      assert.ok(form.html.includes('name="under14"'), `${clientId} ${name} under-14 choice`);
      assert.ok(form.html.includes('id="signupSubmit"'), `${clientId} ${name} gated submit`);
      assert.ok(form.html.includes('href="/privacy"') && form.html.includes('href="/terms"'), `${clientId} ${name} doc links`);
    }
  }
  assert.ok(!(await beginSignup('lovetree-4-0', KO)).form.html.includes('러브트리는 만 14세 이상부터 가입할 수 있어요.'), 'notice lives on the under-14 screen, not the form');
  assert.ok((await beginSignup('lovetree-4-0', KO)).form.html.includes('만 14세 이상입니다'), 'lovetree ko checkbox label');
  assert.ok((await beginSignup('b62', EN)).form.html.includes('I am 14 or older'), 'chat en checkbox label');
  assert.ok((await beginSignup('brandless', KO)).form.html.includes('만 14세 미만이에요'), 'plain ko under-14 label');
});

test('login screens link the shared docs and stay free of the age gate', async () => {
  for (const clientId of ['lovetree-4-0', 'b62', 'brandless']) {
    const f = await createSkinHarness();
    const page = await f.begin('/login', clientId);
    assert.ok(page.html.includes('href="/privacy"') && page.html.includes('href="/terms"'), `${clientId} login doc links`);
    assert.ok(!page.html.includes('age_confirm'), `${clientId} login has no age gate`);
  }
});

test('the server refuses a signup without the confirmation and creates nothing', async () => {
  const { f, form, headers } = await beginSignup('b62', KO);
  const refused = await postSignup(f, form, { name: '', email: 'minor@example.invalid', password: 'synthetic-safe-password' }, headers);
  assert.equal(refused.response.status, 200);
  assert.ok(refused.html.includes('만 14세 이상 확인에 체크해 주세요.'), 'ko refusal message');
  assert.ok(refused.html.includes('PADIEM Chat'), 'refusal keeps the Chat skin');
  // The same address signs up cleanly afterwards: the refused attempt left
  // no Chat credential and no account row behind.
  const done = await postSignup(f, form, signupFields('minor@example.invalid'));
  assert.equal(done.response.status, 200);
  assert.ok(done.html.includes('done-email'), 'fresh signup finishes');
});

test('the refusal message follows the browser language', async () => {
  const { f, form, headers } = await beginSignup('b62', EN);
  const refused = await postSignup(f, form, { name: '', email: 'minor@example.invalid', password: 'synthetic-safe-password' }, headers);
  assert.ok(refused.html.includes('Please confirm you are 14 or older.'), 'en refusal message');
});

test('an under-14 choice renders the skin notice and creates nothing', async () => {
  const cases = [
    ['lovetree-4-0', KO, '러브트리는 만 14세 이상부터 가입할 수 있어요.'],
    ['b62', KO, 'PADIEM Chat은 만 14세 이상부터 가입할 수 있어요.'],
    ['brandless', KO, 'PADIEM은 만 14세 이상부터 가입할 수 있어요.'],
  ];
  for (const [clientId, headers, notice] of cases) {
    const { f, form } = await beginSignup(clientId, headers);
    const page = await postSignup(f, form, { name: '', email: 'young@example.invalid', password: 'synthetic-safe-password', under14: '1' }, headers);
    assert.equal(page.response.status, 200);
    assert.ok(page.html.includes(notice), `${clientId} notice wording`);
    assert.ok(!page.html.includes('name="password"'), `${clientId} notice carries no form`);
    const done = await postSignup(f, form, signupFields('young@example.invalid'));
    assert.ok(done.html.includes('done-email'), `${clientId} fresh signup still finishes`);
  }
});

test('a confirmed signup records the confirmation time, readable by account', async () => {
  const f = await createSkinHarness();
  const form = await f.begin('/signup', 'lovetree-4-0');
  const done = await postSignup(f, form, signupFields('confirmed@example.invalid'));
  assert.ok(done.html.includes('done-email'), 'signup finishes');
  const registry = f.stateObjects.get('google-account-registry');
  // The harness authority mints one deterministic account per signup.
  assert.equal(registry.ageConfirmedAt({ accountId: 'sub_00000000000000000000000000000001' }), 1000);
});

function memoryState() {
  const db = new DatabaseSync(':memory:');
  const storage = {
    sql: { exec: () => { throw new Error('unreachable'); } },
    transactionSync(fn) { db.exec('BEGIN'); try { const out = fn(); db.exec('COMMIT'); return out; } catch (error) { db.exec('ROLLBACK'); throw error; } },
  };
  storage.sql.exec = (query, ...params) => {
    const statement = db.prepare(query);
    if (statement.columns().length) return { toArray: () => statement.all(...params) };
    statement.run(...params);
    return { toArray: () => [] };
  };
  return new AuthState({ storage });
}

test('age_confirmed_at is nullable, stored once and readable by fingerprint or account', () => {
  const s = memoryState();
  s.putAccount({ fingerprint: 'fp_plain', accountId: 'sub_plain', now: 1 });
  assert.equal(s.ageConfirmedAt({ fingerprint: 'fp_plain' }), null);
  assert.equal(s.ageConfirmedAt({ accountId: 'sub_plain' }), null);
  s.putAccount({ fingerprint: 'fp_aged', accountId: 'sub_aged', ageConfirmedAt: 700, now: 1000 });
  assert.equal(s.ageConfirmedAt({ fingerprint: 'fp_aged' }), 700);
  assert.equal(s.ageConfirmedAt({ accountId: 'sub_aged' }), 700);
  s.putAccount({ fingerprint: 'fp_aged', accountId: 'sub_aged', ageConfirmedAt: 1500, now: 1500 });
  assert.equal(s.ageConfirmedAt({ fingerprint: 'fp_aged' }), 700, 'the first confirmation wins');
  assert.throws(() => s.putAccount({ fingerprint: 'other', accountId: 'sub_other', ageConfirmedAt: 1.5 }), 'non-integer confirmation time is rejected');
});

test('/privacy and /terms serve the shared documents with the verbatim LoveTree section', async () => {
  const f = await createSkinHarness();
  // #7846: 처리방침은 v2(날짜는 PRIVACY_EFFECTIVE 한 곳에서만 변경), 약관은 v1 그대로.
  for (const [path, title, meta] of [
    ['/privacy', '개인정보처리방침', /시행일: \d{4}-\d{2}-\d{2} · 버전: v2/],
    ['/terms', '이용약관', '시행일: 2026-11-16 · 버전: v1'],
  ]) {
    const response = await f.app.fetch(new Request(`${url}${path}`));
    assert.equal(response.status, 200, path);
    assert.equal(response.headers.get('content-type'), 'text/html; charset=utf-8', path);
    const html = await response.text();
    assert.ok(html.includes(`<title>${title} — PADIEM 계정</title>`), `${path} title`);
    if (meta instanceof RegExp) assert.match(html, meta, `${path} effective line`);
    else assert.ok(html.includes(meta), `${path} effective line`);
    assert.ok(html.includes('만 14세 미만은 가입할 수 없습니다'), `${path} common age rule`);
  }
  const privacy = await (await f.app.fetch(new Request(`${url}/privacy`))).text();
  assert.ok(privacy.includes('id="lovetree"'), 'lovetree anchor');
  // Verbatim sentences from issue #7818 comment issuecomment-6903332192.
  for (const sentence of [
    '공유를 취소하면 그 즉시 열리지 않음.',
    '공개 화면에는 내 이름·아이디·이메일을 보여 주지 않음.',
    '재생은 youtube-nocookie 주소로 함.',
    '내용 속 전화번호·이메일 같은 개인정보는 저장 전에 가림.',
  ]) assert.ok(privacy.includes(sentence), sentence);
  assert.ok(privacy.includes('padiem_session'), 'chat section keeps the session cookie disclosure');
  assert.ok(privacy.includes('drive.readonly'), 'chat section keeps the read-only scopes');
  assert.ok(!privacy.includes('/password/recovery'), 'docs carry no recovery entry');
  const terms = await (await f.app.fetch(new Request(`${url}/terms`))).text();
  assert.ok(terms.includes('준거법'), 'terms keep the governing law');
});
