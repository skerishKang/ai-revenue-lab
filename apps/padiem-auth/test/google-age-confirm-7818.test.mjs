// #7818 PR 2: a first Google account and an older unconfirmed account answer
// the same 14-or-older gate before anything is created or resumed. Synthetic
// keys, a fake Google token endpoint and in-memory state only.
import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { AuthState } from '../state.mjs';
import { createApp, AuthStateObject, identityFingerprint } from '../worker.mjs';
import { AUTH_BRANDS, AGE_CONFIRM_TEXT } from '../skin.mjs';

const URL_BASE = 'https://auth.padiem.net';
const SUBJECT = 'google-subject-age-gate-fixture';
const ACCOUNT = 'sub_age_gate';
const b64 = (x) => Buffer.from(x).toString('base64url');
const j64 = (x) => b64(JSON.stringify(x));
const sum = async (x) => b64(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(x)));
const rand = () => b64(crypto.getRandomValues(new Uint8Array(32)));

function storage() {
  const db = new DatabaseSync(':memory:');
  return {
    sql: { exec(q, ...p) { const s = db.prepare(q); if (s.columns().length) { const rows = s.all(...p); return { toArray: () => rows }; } s.run(...p); return { toArray: () => [] }; } },
    transactionSync(fn) { db.exec('BEGIN'); try { const out = fn(); db.exec('COMMIT'); return out; } catch (e) { db.exec('ROLLBACK'); throw e; } },
    db,
  };
}

async function setup({ clientId = 'lovetree-4-0', lang = 'ko', ltTheme = '' } = {}) {
  const google = await crypto.subtle.generateKey({ name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['sign', 'verify']);
  const googleJwk = await crypto.subtle.exportKey('jwk', google.publicKey); googleJwk.kid = 'google';
  const signing = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const client = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const publicClient = await crypto.subtle.exportKey('jwk', client.publicKey); publicClient.kid = 'client';
  const publicSigning = await crypto.subtle.exportKey('jwk', signing.publicKey); publicSigning.kid = 'auth';
  const refreshKey = await crypto.subtle.importKey('raw', new Uint8Array(32).fill(8), 'AES-GCM', false, ['encrypt', 'decrypt']);
  const identityKey = await crypto.subtle.importKey('raw', new Uint8Array(32).fill(9), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  let t = 1000, nonce = '', authorityCalls = 0;
  const authority = {
    async resolve_or_create_product_link(v) {
      authorityCalls++;
      return { ok: true, link: { state: 'active', product_id: v.product_id, product_user_id: v.product_user_id, canonical_subject_id: ACCOUNT } };
    },
  };
  const objects = new Map();
  const stateFor = (id) => {
    if (!objects.has(id)) {
      let queue = Promise.resolve();
      const state = { storage: storage(), blockConcurrencyWhile(fn) { const next = queue.then(fn); queue = next.catch(() => {}); return next; } };
      objects.set(id, id === 'google-account-registry' ? new AuthStateObject(state, { IDENTITY_AUTHORITY: authority }) : new AuthState(state));
    }
    return objects.get(id);
  };
  const app = createApp({
    clients: { [clientId]: { id: clientId, redirect_uris: ['https://client.example.invalid/callback'], jwks: { keys: [publicClient] } } },
    googleClientId: 'google-client', googleClientSecret: 'synthetic', identityKey, refreshKey,
    adminSecret: 'synthetic-admin-secret', accountDeleteRpcSecret: 'synthetic-account-delete-secret-32chars',
    signingKey: signing.privateKey, signingKid: 'auth', jwks: { keys: [publicSigning] },
    stateFor, now: () => t,
    async fetcher(address) {
      if (String(address).includes('/certs')) return Response.json({ keys: [googleJwk] });
      if (String(address).includes('/oauth2.googleapis.com/token')) {
        const h = j64({ alg: 'RS256', kid: 'google' });
        const p = j64({ iss: 'https://accounts.google.com', aud: 'google-client', sub: SUBJECT, nonce, iat: 999, exp: 1100 });
        const input = `${h}.${p}`;
        const sig = await crypto.subtle.sign('RSASSA-PKCS1-v1_5', google.privateKey, new TextEncoder().encode(input));
        return Response.json({ id_token: `${input}.${b64(sig)}` });
      }
      throw new Error('unexpected fetch ' + address);
    },
  });
  const fingerprint = await identityFingerprint(identityKey, SUBJECT);
  const registry = stateFor('google-account-registry');
  async function callback() {
    const params = new URLSearchParams({ client_id: clientId, redirect_uri: 'https://client.example.invalid/callback', state: rand(), code_challenge: await sum(rand()), code_challenge_method: 'S256' });
    if (ltTheme) params.set('lt_theme', ltTheme);
    const begin = await app.fetch(new Request(`${URL_BASE}/login/google?${params}`, { headers: { 'accept-language': lang } }));
    assert.equal(begin.status, 302);
    const googleURL = new URL(begin.headers.get('location'));
    nonce = googleURL.searchParams.get('nonce');
    const cb = new URL(`${URL_BASE}/oauth/google/callback`);
    cb.searchParams.set('state', googleURL.searchParams.get('state'));
    cb.searchParams.set('code', 'synthetic-code');
    const cookie = begin.headers.get('set-cookie').split(';')[0];
    const response = await app.fetch(new Request(cb, { headers: { cookie, 'accept-language': lang } }));
    return { response, cookie };
  }
  function handleOf(html) {
    const m = html.match(/name="handle" value="([^"]+)"/);
    assert.ok(m, 'gate carries a handle');
    return m[1];
  }
  async function answer(cookie, handle, fields) {
    return app.fetch(new Request(`${URL_BASE}/age-confirm/google`, {
      method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded', cookie, 'accept-language': lang },
      body: new URLSearchParams({ handle, ...fields }),
    }));
  }
  return { app, callback, answer, handleOf, registry, stateFor, fingerprint, calls: () => authorityCalls, setNow: (v) => { t = v; } };
}

test('a first Google login shows the gate before any account is created', async () => {
  const f = await setup();
  const { response } = await f.callback();
  const html = await response.text();
  assert.equal(response.status, 200);
  assert.ok(html.includes('name="age_confirm"'), 'checkbox');
  assert.ok(html.includes('name="under14"'), 'under-14 choice');
  assert.ok(html.includes('id="signupSubmit"'), 'gated submit');
  assert.equal(f.registry.accountByFingerprint(f.fingerprint), null, 'no account yet');
  assert.equal(html.includes(SUBJECT), false, 'no Google subject in the browser');
});

test('checking creates the account, records the confirmation and is never asked again', async () => {
  const f = await setup();
  const first = await f.callback();
  const html = await first.response.text();
  const done = await f.answer(first.cookie, f.handleOf(html), { age_confirm: 'yes' });
  assert.equal(done.status, 302, 'resumes the original redirect');
  assert.equal(new URL(done.headers.get('location')).searchParams.has('code'), true);
  assert.equal(f.registry.ageConfirmedAt({ fingerprint: f.fingerprint }), 1000);
  assert.ok(f.registry.accountByFingerprint(f.fingerprint)?.account_id);
  assert.equal(f.calls(), 1);
  const second = await f.callback();
  assert.equal(second.response.status, 302, 'the gate is not shown twice');
});

test('under-14 on a first Google login creates no account and shows the skin notice', async () => {
  const f = await setup();
  const gate = await f.callback();
  const html = await gate.response.text();
  const notice = await f.answer(gate.cookie, f.handleOf(html), { under14: '1' });
  assert.equal(notice.status, 200);
  assert.ok((await notice.text()).includes('러브트리는 만 14세 이상부터 가입할 수 있어요.'));
  assert.equal(f.registry.accountByFingerprint(f.fingerprint), null, 'no account created');
  assert.equal(f.calls(), 0, 'identity authority never called');
});

test('an existing unconfirmed account is asked once, then never again', async () => {
  const f = await setup();
  f.registry.putAccount({ fingerprint: f.fingerprint, accountId: ACCOUNT, now: 900 });
  assert.equal(f.registry.ageConfirmedAt({ fingerprint: f.fingerprint }), null);
  const gate = await f.callback();
  assert.equal(gate.response.status, 200);
  const done = await f.answer(gate.cookie, f.handleOf(await gate.response.text()), { age_confirm: 'yes' });
  assert.equal(done.status, 302);
  assert.equal(f.registry.ageConfirmedAt({ fingerprint: f.fingerprint }), 1000);
  const next = await f.callback();
  assert.equal(next.response.status, 302, 'no second prompt');
});

test('the three skins and both languages use the age-gate wording, never signup words', async () => {
  for (const clientId of ['lovetree-4-0', 'b62', 'brandless']) {
    for (const lang of ['ko', 'en']) {
      const f = await setup({ clientId, lang });
      const gate = await f.callback();
      const html = await gate.response.text();
      assert.equal(gate.response.status, 200, `${clientId} ${lang}`);
      const s = AUTH_BRANDS[clientId]?.strings?.[lang];
      const a = AGE_CONFIRM_TEXT[lang] || AGE_CONFIRM_TEXT.ko;
      const expectedCheck = s ? s.ageConfirm : (lang === 'en' ? 'I am 14 or older' : '만 14세 이상입니다');
      const expectedUnder14 = s ? s.under14 : (lang === 'en' ? 'I am under 14' : '만 14세 미만이에요');
      assert.ok(html.includes(a.title), `${clientId} ${lang} title`);
      assert.ok(html.includes(a.lead), `${clientId} ${lang} lead`);
      assert.ok(html.includes(a.submit), `${clientId} ${lang} submit`);
      assert.ok(html.includes(expectedCheck), `${clientId} ${lang} check`);
      assert.ok(html.includes(expectedUnder14), `${clientId} ${lang} under-14`);
      assert.ok(!html.includes('회원가입'), `${clientId} ${lang} no signup word`);
      assert.ok(html.includes('href="/privacy"') && html.includes('href="/terms"'), `${clientId} ${lang} doc links`);
      const notice = await f.answer(gate.cookie, f.handleOf(html), { under14: '1' });
      const noticeHtml = await notice.text();
      const expectedNotice = s ? s.under14Notice : (lang === 'en' ? 'You must be 14 or older to sign up for PADIEM.' : 'PADIEM은 만 14세 이상부터 가입할 수 있어요.');
      assert.ok(noticeHtml.includes(a.notice), `${clientId} ${lang} notice title`);
      assert.ok(noticeHtml.includes(expectedNotice), `${clientId} ${lang} notice body`);
    }
  }
});

test('two visitors waiting at once: the first handle survives the second start', async () => {
  const f = await setup();
  const first = await f.callback();
  const firstHandle = f.handleOf(await first.response.text());
  const second = await f.callback();
  assert.equal(second.response.status, 200, 'the second visitor also sees the gate');
  void f.handleOf(await second.response.text());
  const store = f.stateFor('google-age-confirmation');
  assert.equal(store.sql.exec('SELECT COUNT(*) AS n FROM age_confirmations').toArray()[0].n, 2, 'both pending rows coexist');
  const done = await f.answer(first.cookie, firstHandle, { age_confirm: 'yes' });
  assert.equal(done.status, 302, 'the first visitor can still confirm');
  assert.equal(f.registry.ageConfirmedAt({ fingerprint: f.fingerprint }), 1000);
  // The answered row stays only as a short-lived result (double-submit safety);
  // exactly one gate is still open.
  assert.equal(store.sql.exec('SELECT COUNT(*) AS n FROM age_confirmations WHERE claimed=0').toArray()[0].n, 1, 'only the answered row was consumed');
});

test('a Google gate handle is refused at the password endpoint and stays answerable', async () => {
  const f = await setup();
  const gate = await f.callback();
  const handle = f.handleOf(await gate.response.text());
  const wrong = await f.app.fetch(new Request('https://auth.padiem.net/age-confirm/password', {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded', cookie: gate.cookie },
    body: new URLSearchParams({ handle, age_confirm: 'yes' }),
  }));
  assert.equal(wrong.status, 400, 'the wrong endpoint refuses the Google record');
  const right = await f.answer(gate.cookie, handle, { age_confirm: 'yes' });
  assert.equal(right.status, 302, 'the unconsumed record still works at its own endpoint');
});

test('the stored handle is bound to the login cookie and expires', async () => {
  const f = await setup();
  const gate = await f.callback();
  const handle = f.handleOf(await gate.response.text());
  const wrong = await f.answer('__Host-padiem-auth-state=' + 'A'.repeat(43), handle, { age_confirm: 'yes' });
  assert.equal(wrong.status, 400, 'another browser cannot answer the gate');
  f.setNow(2000);
  const expired = await f.answer(gate.cookie, handle, { age_confirm: 'yes' });
  assert.equal(expired.status, 400, 'the pending record expires');
  assert.equal(f.registry.accountByFingerprint(f.fingerprint), null, 'no account from an expired gate');
});


test('a double submit of the confirmed gate follows the first result instead of an error', async () => {
  const f = await setup();
  const gate = await f.callback();
  const handle = f.handleOf(await gate.response.text());
  // Both clicks leave the browser before either answer comes back.
  const [one, two] = await Promise.all([
    f.answer(gate.cookie, handle, { age_confirm: 'yes' }),
    f.answer(gate.cookie, handle, { age_confirm: 'yes' }),
  ]);
  assert.equal(one.status, 302, 'first submit resumes');
  assert.equal(two.status, 302, 'second submit is not invalid_request');
  assert.equal(two.headers.get('location'), one.headers.get('location'), 'same place, same one-time code');
  assert.equal(f.calls(), 1, 'the account is resolved once');
  // A later resend (browser reload) inside the code lifetime lands the same way.
  const resend = await f.answer(gate.cookie, handle, { age_confirm: 'yes' });
  assert.equal(resend.status, 302);
  assert.equal(resend.headers.get('location'), one.headers.get('location'));
  // After the code lifetime the repeat is refused as before.
  f.setNow(1000 + 61);
  const late = await f.answer(gate.cookie, handle, { age_confirm: 'yes' });
  assert.equal(late.status, 400);
});

test('the age screen locks its submit after the first press', async () => {
  for (const clientId of ['lovetree-4-0', 'brandless']) {
    const f = await setup({ clientId });
    const html = await (await f.callback()).response.text();
    assert.ok(html.includes('b.form.addEventListener("submit"'), `${clientId} submit-once script`);
  }
});