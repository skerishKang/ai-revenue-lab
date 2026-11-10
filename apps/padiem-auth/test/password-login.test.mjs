import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac, randomUUID } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import { AuthState } from '../state.mjs';
import { createApp, AuthStateObject } from '../worker.mjs';

const url = 'https://auth.padiem.net';
const REDIRECT = 'https://lovetree.example/auth/callback';
const b64 = x => Buffer.from(x).toString('base64url');
const j64 = x => b64(JSON.stringify(x));
const sum = async x => b64(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(x)));
const rand = () => b64(crypto.getRandomValues(new Uint8Array(32)));
const PASSWORD_RPC_SECRET = 'synthetic-password-rpc-secret-32chars-min';
const EMAIL = 'user@example.invalid';
const PASSWORD = 'correct-horse-battery';
const USER_ID = 'usr_password0000000000000000000000';

function storage() {
  const db = new DatabaseSync(':memory:');
  return { sql: { exec(q, ...p) { const stmt = db.prepare(q); if (stmt.columns().length) { const rows = stmt.all(...p); return { toArray: () => rows }; } stmt.run(...p); return { toArray: () => [] }; } },
    transactionSync(fn) { db.exec('BEGIN'); try { const out = fn(); db.exec('COMMIT'); return out; } catch (e) { db.exec('ROLLBACK'); throw e; } } };
}

async function setup({ profile = false } = {}) {
  const signing = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const refreshKey = await crypto.subtle.importKey('raw', new Uint8Array(32).fill(8), 'AES-GCM', false, ['encrypt', 'decrypt']);
  const identityKey = await crypto.subtle.importKey('raw', new Uint8Array(32).fill(9), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const publicSigning = await crypto.subtle.exportKey('jwk', signing.publicKey); publicSigning.kid = 'auth';
  const clientKey = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const publicClient = await crypto.subtle.exportKey('jwk', clientKey.publicKey); publicClient.kid = 'client';
  let authorityCalls = 0; let linked = null; const passwordCalls = [];
  const authority = { async resolve_or_create_product_link(v) { authorityCalls++; linked = v; return { ok: true, link: { state: 'active', product_id: v.product_id, product_user_id: v.product_user_id, canonical_subject_id: 'sub_existing' } }; } };
  const objects = new Map(); let queue = Promise.resolve();
  const stateFor = id => { if (!objects.has(id)) { const state = { storage: storage(), blockConcurrencyWhile(fn) { const next = queue.then(fn); queue = next.catch(() => {}); return next; } }; objects.set(id, id === 'google-account-registry' ? new AuthStateObject(state, { IDENTITY_AUTHORITY: authority }) : new AuthState(state)); } return objects.get(id); };
  const app = createApp({
    clients: {
      'lovetree-pw': { id: 'lovetree-pw', password_login: true, ...(profile ? { profile_claims: ['email', 'email_verified', 'name', 'picture'] } : {}), redirect_uris: [REDIRECT], jwks: { keys: [publicClient] } },
      plain: { id: 'plain', redirect_uris: [REDIRECT], jwks: { keys: [publicClient] } },
    },
    googleClientId: 'google-client', googleClientSecret: 'synthetic', identityKey, refreshKey,
    adminSecret: 'synthetic-admin-secret', accountDeleteRpcSecret: 'synthetic-account-delete-secret-32chars',
    passwordRpcSecret: PASSWORD_RPC_SECRET, passwordRpcOrigin: 'https://chat.padiem.net',
    signingKey: signing.privateKey, signingKid: 'auth', jwks: { keys: [publicSigning] },
    stateFor, now: () => 1000,
    async fetcher(address, options) {
      const path = new URL(address).pathname;
      if (path === '/internal/password-verify' || path === '/internal/password-register') {
        const body = Buffer.from(options.body);
        const h = options.headers;
        const canonical = Buffer.concat([Buffer.from(`v2\nPOST\n${path}\n${h['x-padiem-service-at']}\n${h['x-padiem-service-id']}\n`, 'utf8'), body]);
        const proofValid = h['x-padiem-service-proof'] === 'v2=' + createHmac('sha256', PASSWORD_RPC_SECRET).update(canonical).digest('hex');
        const payload = JSON.parse(body.toString());
        passwordCalls.push({ path, payload, proofValid });
        if (!proofValid) return Response.json({ error: { code: 'unauthorized', message: 'unauthorized' } }, { status: 401 });
        if (path === '/internal/password-verify') {
          if (payload.email === EMAIL && payload.password === PASSWORD) return Response.json({ ok: true, product_user_id: USER_ID });
          return Response.json({ error: { code: 'invalid_credentials', message: '이메일 또는 비밀번호가 올바르지 않습니다.' } }, { status: 401 });
        }
        if (payload.email === 'taken@example.invalid') return Response.json({ error: { code: 'account_exists', message: '이미 사용 중인 이메일입니다.' } }, { status: 409 });
        return Response.json({ ok: true, product_user_id: USER_ID });
      }
      throw new Error('unexpected fetch ' + address);
    },
  });
  async function assertion(clientId = 'lovetree-pw') {
    const h = j64({ alg: 'ES256', kid: 'client' }), p = j64({ iss: clientId, sub: clientId, aud: `${url}/token`, iat: 1000, exp: 1100, jti: rand() });
    const input = `${h}.${p}`, sig = await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, clientKey.privateKey, new TextEncoder().encode(input));
    return `${input}.${b64(sig)}`;
  }
  async function post(fields) {
    const params = new URLSearchParams({ client_id: 'lovetree-pw', client_assertion_type: 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer', client_assertion: await assertion(), ...fields });
    return app.fetch(new Request(`${url}/token`, { method: 'POST', body: params }));
  }
  // Renders one login/signup screen for the password-enabled client and returns
  // the form binding (state param + browser cookie) its POST must carry.
  async function begin(path = '/login', clientId = 'lovetree-pw') {
    const verifier = rand(), state = rand();
    const q = new URLSearchParams({ client_id: clientId, redirect_uri: REDIRECT, state, code_challenge: await sum(verifier), code_challenge_method: 'S256' });
    const response = await app.fetch(new Request(`${url}${path}?${q}`));
    const html = await response.text();
    const actionPath = path === '/signup' ? '/signup/password' : '/login/password';
    const match = html.match(new RegExp(actionPath.replace('/', '\\/') + '\\?state=([A-Za-z0-9._%-]+)'));
    return { verifier, state, response, html, cookie: response.headers.get('set-cookie')?.split(';')[0] || '', formState: match ? decodeURIComponent(match[1]) : '' };
  }
  async function postForm(actionPath, formState, cookie, fields, extraHeaders = {}) {
    return app.fetch(new Request(`${url}${actionPath}?state=${encodeURIComponent(formState)}`, { method: 'POST', headers: { 'content-type': 'application/x-www-form-urlencoded', cookie, ...extraHeaders }, body: new URLSearchParams(fields) }));
  }
  return { app, post, begin, postForm, stateFor, evidence: () => ({ authorityCalls, linked, passwordCalls }) };
}

test('default stays a straight Google redirect; opting in shows the choice screen with the same state and cookie', async () => {
  const f = await setup();
  const plain = await f.begin('/login', 'plain');
  assert.equal(plain.response.status, 302);
  assert.ok(plain.response.headers.get('location').startsWith('https://accounts.google.com/o/oauth2/v2/auth'));
  const chosen = await f.begin('/login', 'lovetree-pw');
  assert.equal(chosen.response.status, 200);
  assert.ok(chosen.html.includes('Google로 계속'));
  assert.ok(chosen.html.includes('이메일로 로그인'));
  assert.ok(chosen.cookie.startsWith('__Host-padiem-auth-state='));
  // provider=google skips the choice screen even for a password-enabled client.
  const verifier = rand(), state = rand();
  const googleQuery = new URLSearchParams({ client_id: 'lovetree-pw', redirect_uri: REDIRECT, state, code_challenge: await sum(verifier), code_challenge_method: 'S256', provider: 'google' });
  const directGoogle = await f.app.fetch(new Request(`${url}/login?${googleQuery}`));
  assert.equal(directGoogle.status, 302);
  assert.ok(directGoogle.headers.get('location').startsWith('https://accounts.google.com/o/oauth2/v2/auth'));
  assert.ok(directGoogle.headers.get('set-cookie').startsWith('__Host-padiem-auth-state='));
  const signup = await f.begin('/signup', 'lovetree-pw');
  assert.equal(signup.response.status, 200);
  assert.ok(signup.html.includes('이메일로 회원가입'));
  const plainSignup = await f.begin('/signup', 'plain');
  assert.equal(plainSignup.response.status, 404);
  assert.equal(f.evidence().authorityCalls, 0);
});

test('email login verifies through the signed Chat RPC and finishes the shared code flow', async () => {
  const f = await setup();
  const begun = await f.begin();
  const done = await f.postForm('/login/password', begun.formState, begun.cookie, { email: EMAIL, password: PASSWORD });
  assert.equal(done.status, 302);
  const target = new URL(done.headers.get('location'));
  assert.equal(target.origin + target.pathname, REDIRECT);
  assert.equal(target.searchParams.get('state'), begun.state);
  assert.ok(target.searchParams.get('code'));
  const evidence = f.evidence();
  assert.equal(evidence.passwordCalls.length, 1);
  assert.equal(evidence.passwordCalls[0].path, '/internal/password-verify');
  assert.deepEqual(evidence.passwordCalls[0].payload, { email: EMAIL, password: PASSWORD });
  assert.equal(evidence.passwordCalls[0].proofValid, true);
  assert.equal(evidence.linked.auth_provider, 'password');
  assert.equal(evidence.linked.provider_subject, EMAIL);
  assert.equal(evidence.linked.product_user_id, USER_ID);
  assert.equal(done.headers.get('set-cookie').includes('Max-Age=0'), true);
  const minted = await (await f.post({ grant_type: 'authorization_code', code: target.searchParams.get('code'), code_verifier: begun.verifier, redirect_uri: REDIRECT })).json();
  assert.equal(minted.access_token.split('.').length, 3);
  assert.deepEqual(JSON.parse(Buffer.from(minted.access_token.split('.')[1], 'base64url')).amr, ['pwd']);
  const refreshed = await (await f.post({ grant_type: 'refresh_token', refresh_token: minted.refresh_token })).json();
  assert.deepEqual(JSON.parse(Buffer.from(refreshed.access_token.split('.')[1], 'base64url')).amr, ['pwd']);
});

test('password accounts disclose the login identifier without claiming a verified mailbox', async () => {
  const f = await setup({ profile: true });
  const begun = await f.begin();
  const done = await f.postForm('/login/password', begun.formState, begun.cookie, { email: EMAIL, password: PASSWORD });
  const target = new URL(done.headers.get('location'));
  const body = await (await f.post({ grant_type: 'authorization_code', code: target.searchParams.get('code'), code_verifier: begun.verifier, redirect_uri: REDIRECT })).json();
  assert.deepEqual(body.profile, { email: EMAIL, email_verified: false, name: '', picture: '' });
  assert.equal(body.profile.email_verified === true, false);
  assert.equal(JSON.stringify(body).includes(USER_ID), false);
});

test('a wrong password keeps the state alive for a corrected retry and never reaches the authority', async () => {
  const f = await setup();
  const begun = await f.begin();
  const failed = await f.postForm('/login/password', begun.formState, begun.cookie, { email: EMAIL, password: 'wrong-password' });
  assert.equal(failed.status, 200);
  assert.ok((await failed.text()).includes('올바르지 않습니다'));
  assert.equal(f.evidence().authorityCalls, 0);
  const retried = await f.postForm('/login/password', begun.formState, begun.cookie, { email: EMAIL, password: PASSWORD });
  assert.equal(retried.status, 302);
});

test('the sixth attempt against one state exhausts it', async () => {
  const f = await setup();
  const begun = await f.begin();
  for (let i = 0; i < 5; i++) {
    const attempt = await f.postForm('/login/password', begun.formState, begun.cookie, { email: EMAIL, password: 'wrong-password' });
    assert.equal(attempt.status, 200);
  }
  const exhausted = await f.postForm('/login/password', begun.formState, begun.cookie, { email: EMAIL, password: PASSWORD });
  assert.equal(exhausted.status, 429);
});

test('the form POST requires the browser cookie and a live state pair', async () => {
  const f = await setup();
  const begun = await f.begin();
  const cookieless = await f.postForm('/login/password', begun.formState, '', { email: EMAIL, password: PASSWORD });
  assert.equal(cookieless.status, 400);
  const forged = await f.postForm('/login/password', `forged.${rand()}`, begun.cookie, { email: EMAIL, password: PASSWORD });
  assert.equal(forged.status, 400);
});

test('attempts from one address are frequency limited per minute', async () => {
  const f = await setup();
  const ip = { 'cf-connecting-ip': '203.0.113.9' };
  for (let i = 0; i < 10; i++) {
    const begun = await f.begin();
    const attempt = await f.postForm('/login/password', begun.formState, begun.cookie, { email: EMAIL, password: 'wrong-password' }, ip);
    assert.equal(attempt.status, 200);
  }
  const begun = await f.begin();
  const blocked = await f.postForm('/login/password', begun.formState, begun.cookie, { email: EMAIL, password: PASSWORD }, ip);
  assert.equal(blocked.status, 429);
});

test('signup registers through the signed RPC and finishes the same code flow', async () => {
  const f = await setup();
  const begun = await f.begin('/signup');
  const done = await f.postForm('/signup/password', begun.formState, begun.cookie, { name: 'Test User', email: 'new@example.invalid', password: 'another-good-password' });
  assert.equal(done.status, 302);
  const evidence = f.evidence();
  assert.equal(evidence.passwordCalls[0].path, '/internal/password-register');
  assert.deepEqual(evidence.passwordCalls[0].payload, { email: 'new@example.invalid', password: 'another-good-password', name: 'Test User' });
  assert.equal(evidence.linked.auth_provider, 'password');
  const taken = await f.begin('/signup');
  const conflict = await f.postForm('/signup/password', taken.formState, taken.cookie, { name: '', email: 'taken@example.invalid', password: 'another-good-password' });
  assert.equal(conflict.status, 200);
  assert.ok((await conflict.text()).includes('이미 사용 중인 이메일입니다.'));
  assert.equal(f.evidence().authorityCalls, 1);
});
