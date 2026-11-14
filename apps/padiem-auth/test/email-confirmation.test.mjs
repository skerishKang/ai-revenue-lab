// #7679 optional email confirmation: after an email signup one "is this
// address yours" mail goes out. The account works without it; pressing the
// button in the link makes the next sign-in's profile say email_verified.
// A synthetic Chat stands behind the signed RPC and no mail is sent.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash, createHmac } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import { AuthState } from '../state.mjs';
import worker, { createApp, AuthStateObject } from '../worker.mjs';
import { EMAIL_CONFIRMATION_TTL_SECONDS, confirmationTokenDigest } from '../email-confirmation.mjs';
import { withProductBoundary } from './authority-products.mjs';

const url = 'https://auth.padiem.net';
const REDIRECT = 'https://lovetree.example/auth/callback';
const SECRET = 'synthetic-password-rpc-secret-32chars-min';
const EPOCH = '2026-11-12T00:00:00+00:00';
const PASSWORD = 'correct-horse-battery';
const b64 = x => Buffer.from(x).toString('base64url');
const j64 = x => b64(JSON.stringify(x));
const sum = async x => b64(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(x)));
const rand = () => b64(crypto.getRandomValues(new Uint8Array(32)));
const sha = value => createHash('sha256').update(value).digest('hex');
const userFor = email => 'usr_' + sha(`password:${email}`).slice(0, 32);

function storage() {
  const db = new DatabaseSync(':memory:');
  return { sql: { exec(q, ...p) { const stmt = db.prepare(q); if (stmt.columns().length) { const rows = stmt.all(...p); return { toArray: () => rows }; } stmt.run(...p); return { toArray: () => [] }; } },
    transactionSync(fn) { db.exec('BEGIN'); try { const out = fn(); db.exec('COMMIT'); return out; } catch (e) { db.exec('ROLLBACK'); throw e; } } };
}

async function setup({ confirm = true, defer, mailDown = false } = {}) {
  const signing = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const refreshKey = await crypto.subtle.importKey('raw', new Uint8Array(32).fill(8), 'AES-GCM', false, ['encrypt', 'decrypt']);
  const identityKey = await crypto.subtle.importKey('raw', new Uint8Array(32).fill(9), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const publicSigning = await crypto.subtle.exportKey('jwk', signing.publicKey); publicSigning.kid = 'auth';
  const clientKey = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const publicClient = await crypto.subtle.exportKey('jwk', clientKey.publicKey); publicClient.kid = 'client';
  const calls = [], mails = [];
  let clock = 1000, queue = Promise.resolve(), gate = null, failSend = false;
  const authority = withProductBoundary({ async resolve_or_create_product_link(v) {
    return { ok: true, link: { state: 'active', product_id: v.product_id, product_user_id: v.product_user_id, canonical_subject_id: `sub_${v.product_user_id.slice(4)}` } };
  } });
  const objects = new Map();
  const env = { IDENTITY_AUTHORITY: authority, PADIEM_AUTH_EMAIL_CONFIRMATION_ENABLED: confirm };
  const stateFor = id => { if (!objects.has(id)) { const state = { storage: storage(), blockConcurrencyWhile(fn) { const next = queue.then(fn); queue = next.catch(() => {}); return next; } }; objects.set(id, id === 'google-account-registry' ? new AuthStateObject(state, env) : new AuthState(state)); } return objects.get(id); };
  const app = createApp({
    clients: { b62: { id: 'b62', password_login: true, profile_claims: ['email', 'email_verified', 'name', 'picture'], redirect_uris: [REDIRECT], jwks: { keys: [publicClient] } } },
    googleClientId: 'google-client', googleClientSecret: 'synthetic', identityKey, refreshKey,
    passwordRpcSecret: SECRET, passwordRpcOrigin: 'https://chat.padiem.net', emailConfirmationEnabled: confirm, defer,
    signingKey: signing.privateKey, signingKid: 'auth', jwks: { keys: [publicSigning] }, stateFor, now: () => clock,
    async fetcher(address, options) {
      const path = new URL(address).pathname, body = Buffer.from(options.body), h = options.headers;
      const canonical = Buffer.concat([Buffer.from(`v2\nPOST\n${path}\n${h['x-padiem-service-at']}\n${h['x-padiem-service-id']}\n`, 'utf8'), body]);
      assert.equal(h['x-padiem-service-proof'], 'v2=' + createHmac('sha256', SECRET).update(canonical).digest('hex'));
      const payload = JSON.parse(body.toString());
      if (path === '/internal/email-confirmation/send') {
        if (gate) await gate;
        calls.push({ path, payload });
        if (failSend) throw new Error('synthetic network failure');
        if (mailDown) return Response.json({ ok: false });
        const token = b64(createHash('sha256').update(`link-${mails.length}`).digest());
        mails.push({ to: payload.email, lang: payload.lang, token });
        return Response.json({ ok: true, token_digest: sha('padiem-email-confirmation:v1\0' + token) });
      }
      calls.push({ path, payload: { ...payload, password: undefined } });
      if (path === '/internal/password-register' || payload.password === PASSWORD) return Response.json({ ok: true, product_user_id: userFor(payload.email), credential_epoch: EPOCH });
      return Response.json({ error: { code: 'invalid_credentials' } }, { status: 401 });
    },
  });
  async function assertion() {
    const input = `${j64({ alg: 'ES256', kid: 'client' })}.${j64({ iss: 'b62', sub: 'b62', aud: `${url}/token`, iat: clock, exp: clock + 100, jti: rand() })}`;
    return `${input}.${b64(await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, clientKey.privateKey, new TextEncoder().encode(input)))}`;
  }
  // One whole email signup or sign-in, ending in the profile a service receives.
  async function enter(kind, email, { ip = '192.0.2.7', lang } = {}) {
    const verifier = rand();
    const q = new URLSearchParams({ client_id: 'b62', redirect_uri: REDIRECT, state: rand(), code_challenge: await sum(verifier), code_challenge_method: 'S256' });
    const form = await app.fetch(new Request(`${url}/${kind}?${q}`));
    const action = (await form.text()).match(new RegExp(`action="(/${kind}/password\\?state=[^"]+)"`))[1];
    const response = await app.fetch(new Request(url + action, { method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded', cookie: form.headers.get('set-cookie').split(';')[0], 'cf-connecting-ip': ip, ...(lang ? { 'accept-language': lang } : {}) },
      body: new URLSearchParams({ name: '', email, password: PASSWORD }) }));
    const text = await response.text();
    // Either the immediate return or a page that carries the same address.
    const location = response.headers.get('location') || text.match(/href="(https:\/\/lovetree\.example[^"]+)"/)?.[1].replaceAll('&amp;', '&');
    if (!location) return { response, text };
    const code = new URL(location).searchParams.get('code');
    const params = new URLSearchParams({ client_id: 'b62', client_assertion_type: 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer', client_assertion: await assertion(), grant_type: 'authorization_code', code, code_verifier: verifier, redirect_uri: REDIRECT });
    const tokens = await (await app.fetch(new Request(`${url}/token`, { method: 'POST', body: params }))).json();
    return { response, text, profile: tokens.profile, accountId: tokens.account_id };
  }
  const press = (token, headers = {}) => app.fetch(new Request(`${url}/email/confirm`, { method: 'POST', headers: { 'content-type': 'application/json', ...headers }, body: JSON.stringify({ token }) }));
  return { app, enter, press, calls, mails, registry: stateFor('google-account-registry'),
    time(value) { clock = value; }, now: () => clock, failSend(value) { failSend = value; },
    hold() { let open; gate = new Promise(resolve => { open = resolve; }); return () => { gate = null; open(); }; } };
}
const picture = async response => ({ status: response.status, headers: [...response.headers], body: await response.text() });

test('this Worker and Chat compute the same digest for a link (shared vector)', async () => {
  // The same constant is pinned in apps/padiem-chat/tests/test_email_confirmation_7679.py.
  assert.equal(await confirmationTokenDigest('t'.repeat(43)), 'afe9bf3d6c203d28561b28b427cdd6abc285ab1c5b8158a7212e6336644b6d80');
});

const sends = f => f.calls.filter(call => call.path === '/internal/email-confirmation/send');

test('switch off: no mail is asked for, the page does not exist and a profile is never verified', async () => {
  const f = await setup({ confirm: false });
  const signup = await f.enter('signup', 'new@example.invalid');
  assert.deepEqual(signup.profile, { email: 'new@example.invalid', email_verified: false, name: '', picture: '' });
  assert.deepEqual(f.calls.map(call => call.path), ['/internal/password-register']);
  for (const method of ['GET', 'POST']) {
    const request = () => new Request(`${url}/email/confirm`, { method, ...(method === 'POST' ? { headers: { 'content-type': 'application/json' }, body: '{"token":"x"}' } : {}) });
    assert.equal((await f.app.fetch(request())).status, 404);
    assert.equal((await worker.fetch(request(), {})).status, 404);
  }
  for (const method of ['passwordEmailConfirmed', 'reserveEmailConfirmation', 'recordEmailConfirmationToken', 'completeEmailConfirmation']) {
    assert.equal((await f.registry.fetch(new Request('https://internal/' + method, { method: 'POST', body: '{}' }))).status, 404);
  }
  // Even a confirmation recorded earlier is not claimed while the switch is off.
  f.registry.sql.exec('INSERT INTO email_confirmations SELECT fingerprint,?,? FROM google_accounts', EPOCH, 1000);
  assert.equal((await f.enter('login', 'new@example.invalid')).profile.email_verified, false);
});

test('a signup asks Chat for one mail in the browser language and keeps only the digest of its link', async () => {
  const f = await setup();
  const signup = await f.enter('signup', 'new@example.invalid', { lang: 'en-US,en;q=0.9' });
  assert.equal(signup.profile.email_verified, false, 'a new account starts unconfirmed');
  assert.deepEqual(sends(f).map(call => call.payload), [{ email: 'new@example.invalid', lang: 'en' }]);
  assert.equal(f.mails.length, 1);
  const rows = f.registry.sql.exec('SELECT * FROM email_confirmation_tokens').toArray();
  assert.equal(rows.length, 1);
  assert.equal(rows[0].token_digest, await confirmationTokenDigest(f.mails[0].token));
  assert.equal(rows[0].expires, f.now() + EMAIL_CONFIRMATION_TTL_SECONDS);
  assert.equal(rows[0].epoch, EPOCH);
  assert.ok(!JSON.stringify(rows).includes(f.mails[0].token));
  // A sign-in sends nothing.
  await f.enter('login', 'new@example.invalid');
  assert.equal(sends(f).length, 1);
});

test('the account works without the link, and pressing the button verifies the next sign-in', async () => {
  const f = await setup();
  await f.enter('signup', 'new@example.invalid');
  assert.equal((await f.enter('login', 'new@example.invalid')).profile.email_verified, false);
  const pressed = await f.press(f.mails[0].token);
  assert.equal(pressed.status, 200);
  assert.deepEqual(await pressed.json(), { ok: true, message: '이메일을 확인했습니다. 이 창은 닫으셔도 됩니다.' });
  const login = await f.enter('login', 'new@example.invalid');
  assert.deepEqual(login.profile, { email: 'new@example.invalid', email_verified: true, name: '', picture: '' });
  assert.equal(f.registry.sql.exec('SELECT * FROM email_confirmation_tokens').toArray().length, 0);
  // Another person's account is untouched.
  await f.enter('signup', 'other@example.invalid', { ip: '192.0.2.8' });
  assert.equal((await f.enter('login', 'other@example.invalid')).profile.email_verified, false);
});

test('used, expired, unknown and malformed links share one refusal and verify nothing', async () => {
  const f = await setup();
  await f.enter('signup', 'new@example.invalid');
  const token = f.mails[0].token;
  const unknown = await picture(await f.press('u'.repeat(43)));
  assert.equal(unknown.status, 400);
  assert.equal(JSON.parse(unknown.body).error, 'email_confirmation_invalid');
  assert.deepEqual(await picture(await f.press('short')), unknown);
  assert.deepEqual(await picture(await f.app.fetch(new Request(`${url}/email/confirm`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ token, extra: 1 }) }))), unknown);
  assert.deepEqual(await picture(await f.app.fetch(new Request(`${url}/email/confirm`, { method: 'POST', body: new URLSearchParams({ token }) }))), unknown);
  f.time(1000 + EMAIL_CONFIRMATION_TTL_SECONDS);
  assert.deepEqual(await picture(await f.press(token)), unknown, 'expired');
  assert.equal((await f.enter('login', 'new@example.invalid')).profile.email_verified, false);
  // A second account's link works once and only once.
  await f.enter('signup', 'second@example.invalid', { ip: '192.0.2.9' });
  const second = f.mails[1].token;
  assert.equal((await f.press(second)).status, 200);
  assert.deepEqual(await picture(await f.press(second)), unknown, 'used');
});

test('the mail never delays or fails a signup', async () => {
  const deferred = [], lines = [];
  const f = await setup({ defer: work => deferred.push(work) });
  const release = f.hold();
  const signup = await f.enter('signup', 'new@example.invalid');
  assert.equal(signup.profile.email, 'new@example.invalid', 'the signup finished');
  assert.equal(sends(f).length, 0, 'Chat was not asked before the answer');
  release();
  await Promise.all(deferred);
  assert.equal(f.mails.length, 1);
  // A network failure and an unsent mail are contained.
  const original = console.error; console.error = line => lines.push(String(line));
  try {
    f.failSend(true);
    assert.equal((await f.enter('signup', 'broken@example.invalid', { ip: '192.0.2.8' })).profile.email, 'broken@example.invalid');
    await Promise.all(deferred);
  } finally { console.error = original; }
  assert.deepEqual(lines, ['{"auth_stage":"email_confirmation_unavailable"}']);
  const down = await setup({ mailDown: true });
  assert.equal((await down.enter('signup', 'new@example.invalid')).profile.email_verified, false);
  assert.equal(down.registry.sql.exec('SELECT * FROM email_confirmation_tokens').toArray().length, 0);
});

test('mails are budgeted per source per hour and for the whole service per day', async () => {
  const f = await setup();
  for (let i = 0; i < 4; i++) await f.enter('signup', `person${i}@example.invalid`);
  assert.equal(f.mails.length, 3, 'the fourth signup from one source in an hour gets no mail');
  await f.enter('signup', 'elsewhere@example.invalid', { ip: '192.0.2.99' });
  assert.equal(f.mails.length, 4);
  f.time(1000 + 3600);
  await f.enter('signup', 'later@example.invalid');
  assert.equal(f.mails.length, 5, 'the next hour admits the source again');
  // The daily budget, shown on the registry with a small limit.
  const fingerprint = f.registry.sql.exec('SELECT fingerprint FROM google_accounts ORDER BY rowid DESC').toArray()[0].fingerprint;
  const reserve = sourceDigest => f.registry.reserveEmailConfirmation({ fingerprint, epoch: EPOCH, sourceDigest, now: f.now(), globalDaily: 6 });
  assert.equal(reserve('a'.repeat(43)), true);
  assert.equal(reserve('b'.repeat(43)), false, 'the service-wide daily budget is spent');
  assert.equal(f.registry.reserveEmailConfirmation({ fingerprint: 'unknown', epoch: EPOCH, sourceDigest: 'c'.repeat(43), now: f.now() }), false);
});

test('a confirmation belongs to the linked credential and goes away with the account', async () => {
  const f = await setup();
  const signup = await f.enter('signup', 'new@example.invalid');
  assert.equal((await f.press(f.mails[0].token)).status, 200);
  const { fingerprint } = f.registry.sql.exec('SELECT fingerprint FROM google_accounts').toArray()[0];
  assert.equal(f.registry.passwordEmailConfirmed({ fingerprint, epoch: EPOCH }), true);
  assert.equal(f.registry.passwordEmailConfirmed({ fingerprint, epoch: '2026-11-13T09:00:00+00:00' }), false);
  assert.equal(f.registry.reserveEmailConfirmation({ fingerprint, epoch: EPOCH, sourceDigest: 'a'.repeat(43), now: f.now() }), false, 'a confirmed address is not mailed again');
  const lockToken = 'synthetic-lock';
  assert.equal(await f.registry.beginAccountDeletion({ accountId: signup.accountId, lockToken, now: f.now(), leaseSeconds: 300 }), true);
  assert.equal(await f.registry.finalizeAccountDeletion({ accountId: signup.accountId, accountIdHash: sha(signup.accountId), lockToken, now: f.now() }), true);
  assert.equal(f.registry.sql.exec('SELECT * FROM email_confirmations').toArray().length, 0);
  assert.equal(f.registry.passwordEmailConfirmed({ fingerprint, epoch: EPOCH }), false);
});

test('a link for an account that was deleted or blocked afterwards confirms nothing', async () => {
  const f = await setup();
  const signup = await f.enter('signup', 'new@example.invalid');
  f.registry.setAccountStatus({ accountId: signup.accountId, blocked: true });
  assert.equal((await f.press(f.mails[0].token)).status, 400);
  assert.equal(f.registry.sql.exec('SELECT * FROM email_confirmations').toArray().length, 0);
  assert.equal(f.registry.sql.exec('SELECT * FROM email_confirmation_tokens').toArray().length, 0, 'the link is spent either way');
});

test('the page asks for a deliberate press, in both languages, and never contains the token', async () => {
  const f = await setup();
  await f.enter('signup', 'new@example.invalid');
  const get = async headers => (await f.app.fetch(new Request(`${url}/email/confirm`, { headers }))).text();
  const ko = await get({});
  assert.match(ko, /<h1>이메일 확인<\/h1>/);
  assert.match(ko, /<button type="submit">맞아요, 제 이메일입니다<\/button>/);
  assert.match(ko, /누르지 않아도 계정은 그대로 쓸 수 있습니다/);
  const en = await get({ 'accept-language': 'en-US,en;q=0.9' });
  assert.match(en, /<h1>Confirm your email<\/h1>/);
  assert.match(en, /<button type="submit">Yes, this is my email<\/button>/);
  for (const html of [ko, en]) {
    assert.ok(!html.includes(f.mails[0].token));
    assert.ok(!html.includes('new@example.invalid'));
    assert.match(html, /history\.replaceState\(null,'',location\.pathname\)/);
    assert.match(html, /<meta name="referrer" content="no-referrer">/);
  }
  // Opening the page alone confirms nothing.
  assert.equal(f.registry.sql.exec('SELECT * FROM email_confirmations').toArray().length, 0);
});

test('the token and the address stay out of log lines and registry rows', async () => {
  const lines = [], originals = [console.log, console.error];
  console.log = line => lines.push(String(line)); console.error = line => lines.push(String(line));
  let f;
  try {
    f = await setup();
    await f.enter('signup', 'new@example.invalid');
    await f.press(f.mails[0].token);
    await f.press(f.mails[0].token);
  } finally { [console.log, console.error] = originals; }
  const stored = JSON.stringify(['email_confirmation_tokens', 'email_confirmations', 'email_confirmation_budget']
    .map(table => f.registry.sql.exec(`SELECT * FROM ${table}`).toArray()));
  for (const text of [...lines, stored]) {
    assert.ok(!text.includes(f.mails[0].token));
    assert.ok(!text.includes('new@example.invalid'));
    assert.ok(!text.includes('192.0.2.7'));
  }
});
