import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { AuthState } from '../state.mjs';
import { createApp, AuthStateObject, identityFingerprint } from '../worker.mjs';

const url = 'https://auth.padiem.net';
const b64 = x => Buffer.from(x).toString('base64url');
const j64 = x => b64(JSON.stringify(x));
const sum = async x => b64(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(x)));
const rand = () => b64(crypto.getRandomValues(new Uint8Array(32)));
function storage() {
  const db = new DatabaseSync(':memory:');
  return { sql: { exec(q, ...p) { const stmt = db.prepare(q); if (stmt.columns().length) { const rows = stmt.all(...p); return { toArray: () => rows }; } stmt.run(...p); return { toArray: () => [] }; } },
    transactionSync(fn) { db.exec('BEGIN'); try { const out = fn(); db.exec('COMMIT'); return out; } catch (e) { db.exec('ROLLBACK'); throw e; } } };
}
async function setup({ advanceDuringExchange = false, clientId = 'lovetree', profile = false } = {}) {
  const google = await crypto.subtle.generateKey({ name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['sign', 'verify']);
  const googleJwk = await crypto.subtle.exportKey('jwk', google.publicKey); googleJwk.kid = 'google';
  const signing = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const refreshKey = await crypto.subtle.importKey('raw', new Uint8Array(32).fill(8), 'AES-GCM', false, ['encrypt', 'decrypt']);
  const identityKey = await crypto.subtle.importKey('raw', new Uint8Array(32).fill(9), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const publicSigning = await crypto.subtle.exportKey('jwk', signing.publicKey); publicSigning.kid = 'auth';
  const client = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const publicClient = await crypto.subtle.exportKey('jwk', client.publicKey); publicClient.kid = 'client';
  let nonce = ''; let linked = null; let authorityCalls = 0; let t = 1000;
  const authority = { async resolve_or_create_product_link(v) { authorityCalls++; linked = v; return { ok: true, link: { state: 'active', product_id: v.product_id, product_user_id: v.product_user_id, canonical_subject_id: 'sub_existing' } }; } };
  const objects = new Map(); const stateFor = id => { if (!objects.has(id)) { let queue = Promise.resolve(); const state = { storage: storage(), blockConcurrencyWhile(fn) { const next = queue.then(fn); queue = next.catch(() => {}); return next; } }; objects.set(id, id === 'google-account-registry' ? new AuthStateObject(state, { IDENTITY_AUTHORITY: authority }) : new AuthState(state)); } return objects.get(id); };
  const app = createApp({ clients: { [clientId]: { id: clientId, ...(profile ? {profile_claims: ['email','email_verified','name','picture']} : {}), redirect_uris: ['https://lovetree.example/auth/callback'], jwks: { keys: [publicClient] } } }, googleClientId: 'google-client', googleClientSecret: 'synthetic', identityKey, refreshKey, adminSecret: 'synthetic-admin-secret', signingKey: signing.privateKey, signingKid: 'auth', jwks: { keys: [publicSigning] }, stateFor, now: () => t,
    async fetcher(address, options) { assert.equal(options.redirect, 'manual'); if (address.includes('/certs')) return Response.json({ keys: [googleJwk] });
      if (advanceDuringExchange) t += 1;
      const h = j64({ alg: 'RS256', kid: 'google' }), p = j64({ iss: 'https://accounts.google.com', aud: 'google-client', sub: 'google-sub', email: 'test@example.invalid', email_verified: true, name: 'Test User', picture: '', nonce, iat: advanceDuringExchange ? t : 999, exp: 1100 });
      const input = `${h}.${p}`, sig = await crypto.subtle.sign('RSASSA-PKCS1-v1_5', google.privateKey, new TextEncoder().encode(input));
      return Response.json({ id_token: `${input}.${b64(sig)}` }); } });
  async function assertion() { const h = j64({ alg: 'ES256', kid: 'client' }), p = j64({ iss: clientId, sub: clientId, aud: `${url}/token`, iat: 1000, exp: 1100, jti: rand() });
    const input = `${h}.${p}`, sig = await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, client.privateKey, new TextEncoder().encode(input)); return `${input}.${b64(sig)}`; }
  async function post(path, fields) { const params = new URLSearchParams({ client_id: clientId, client_assertion_type: 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer', client_assertion: await assertion(), ...fields }); return app.fetch(new Request(`${url}${path}`, { method: 'POST', body: params })); }
  async function login() { const verifier = rand(), state = rand(), redirectUri = 'https://lovetree.example/auth/callback';
    const start = new URL(`${url}/login`); for (const [k,v] of Object.entries({ client_id: clientId, redirect_uri: redirectUri, state, code_challenge: await sum(verifier), code_challenge_method: 'S256' })) start.searchParams.set(k,v);
    const begun = await app.fetch(new Request(start)); assert.equal(begun.status, 302); const googleURL = new URL(begun.headers.get('location')); nonce = googleURL.searchParams.get('nonce');
    const callback = new URL(`${url}/oauth/google/callback`); callback.searchParams.set('state', googleURL.searchParams.get('state')); callback.searchParams.set('code', 'synthetic-code');
    const done = await app.fetch(new Request(callback, { headers: { cookie: begun.headers.get('set-cookie').split(';')[0] } })); assert.equal(done.status, 302);
    const target = new URL(done.headers.get('location')); assert.equal(target.searchParams.get('state'), state); assert.equal(linked.provider_subject, 'google-sub'); assert.equal(done.headers.get('location').includes('test@example.invalid'), false); assert.equal(done.headers.get('location').includes('google-sub'), false);
    return { code: target.searchParams.get('code'), verifier, redirectUri }; }
  return { app, post, login, publicSigning, stateFor, setNow(value) { t = value; }, calls() { return authorityCalls; }, block() { stateFor('google-account-registry').setAccountStatus({ accountId: 'sub_existing', blocked: true }); } };
}

test('a token issued after callback starts uses the current verification time', async () => {
  const f = await setup({ advanceDuringExchange: true });
  const login = await f.login();
  assert.ok(login.code);
});

test('synthetic Google login, code exchange, refresh, replay revocation and JWKS', async () => {
  const f = await setup(); const l = await f.login();
  const fields = { grant_type: 'authorization_code', code: l.code, code_verifier: l.verifier, redirect_uri: l.redirectUri };
  const results = await Promise.all([f.post('/token', fields), f.post('/token', fields)]);
  assert.deepEqual(results.map(x => x.status).sort(), [200, 400]);
  const minted = await results.find(x => x.status === 200).json();
  const parts = minted.access_token.split('.');
  const key = await crypto.subtle.importKey('jwk', f.publicSigning, { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify']);
  assert.equal(await crypto.subtle.verify({ name: 'ECDSA', hash: 'SHA-256' }, key, Buffer.from(parts[2], 'base64url'), new TextEncoder().encode(`${parts[0]}.${parts[1]}`)), true);
  assert.equal(JSON.parse(Buffer.from(parts[1], 'base64url')).exp, 1900);
  assert.equal(JSON.parse(Buffer.from(parts[1], 'base64url')).account_id, 'sub_existing');
  assert.equal(JSON.parse(Buffer.from(parts[1], 'base64url')).sub, 'sub_existing');
  const refreshed = await f.post('/token', { grant_type: 'refresh_token', refresh_token: minted.refresh_token }); assert.equal(refreshed.status, 200);
  const firstResult = await refreshed.json();
  const within = await f.post('/token', { grant_type: 'refresh_token', refresh_token: minted.refresh_token });
  assert.equal(within.status, 200);
  assert.deepEqual(await within.json(), firstResult);
  f.setNow(1030);
  assert.equal((await f.post('/token', { grant_type: 'refresh_token', refresh_token: minted.refresh_token })).status, 400);
  assert.equal((await f.post('/token', { grant_type: 'refresh_token', refresh_token: firstResult.refresh_token })).status, 400);
  assert.equal((await f.app.fetch(new Request(`${url}/.well-known/jwks.json`))).status, 200);
});

test('rejects non-allowlisted callback', async () => {
  const f = await setup(); const q = new URLSearchParams({ client_id: 'lovetree', redirect_uri: 'https://evil.example', state: rand(), code_challenge: rand(), code_challenge_method: 'S256' });
  assert.equal((await f.app.fetch(new Request(`${url}/login?${q}`))).status, 400);
});

test('logout requires the current refresh credential and prevents refresh', async () => {
  const f = await setup(), l = await f.login();
  const response = await f.post('/token', { grant_type: 'authorization_code', code: l.code, code_verifier: l.verifier, redirect_uri: l.redirectUri });
  const { refresh_token: refresh } = await response.json();
  const forged = refresh.split('.'); forged[2] = rand();
  assert.equal((await f.post('/logout', { refresh_token: forged.join('.') })).status, 400);
  assert.equal((await f.post('/logout', { refresh_token: refresh })).status, 200);
  assert.equal((await f.post('/token', { grant_type: 'refresh_token', refresh_token: refresh })).status, 400);
});

test('revoked authority link prevents refresh', async () => {
  const f = await setup(), l = await f.login();
  const response = await f.post('/token', { grant_type: 'authorization_code', code: l.code, code_verifier: l.verifier, redirect_uri: l.redirectUri });
  const { refresh_token: refresh } = await response.json();
  f.block();
  assert.equal((await f.post('/token', { grant_type: 'refresh_token', refresh_token: refresh })).status, 400);
});

test('first login calls authority once; known account and refresh never do', async () => {
  const f = await setup(), l = await f.login();
  assert.equal(f.calls(), 1);
  const response = await f.post('/token', { grant_type: 'authorization_code', code: l.code, code_verifier: l.verifier, redirect_uri: l.redirectUri });
  const { refresh_token: refresh } = await response.json();
  assert.equal((await f.post('/token', { grant_type: 'refresh_token', refresh_token: refresh })).status, 200);
  assert.equal(f.calls(), 1);
  await f.login();
  assert.equal(f.calls(), 1);
});

test('simultaneous first registrations serialize the authority lookup', async () => {
  const f = await setup();
  const registry = f.stateFor('google-account-registry');
  const request = { fingerprint: 'synthetic', productId: 'lovetree', userId: 'usr_synthetic', subject: 'synthetic-subject' };
  const values = await Promise.all([registry.resolveAccount(request), registry.resolveAccount(request)]);
  assert.equal(values[0].account_id, 'sub_existing');
  assert.equal(values[1].account_id, 'sub_existing');
  assert.equal(f.calls(), 1);
});

test('private account-block endpoint requires its secret and closes refresh', async () => {
  const f = await setup(), l = await f.login();
  const response = await f.post('/token', { grant_type: 'authorization_code', code: l.code, code_verifier: l.verifier, redirect_uri: l.redirectUri });
  const { refresh_token: refresh } = await response.json();
  const block = token => f.app.fetch(new Request(`${url}/internal/account-block`, { method: 'POST', headers: { authorization: token }, body: JSON.stringify({ account_id: 'sub_existing' }) }));
  assert.equal((await block('Bearer wrong')).status, 401);
  assert.equal((await block('Bearer synthetic-admin-secret')).status, 200);
  assert.equal((await block('Bearer synthetic-admin-secret')).status, 200);
  assert.equal((await f.post('/token', { grant_type: 'refresh_token', refresh_token: refresh })).status, 400);
});

test('blocking an account before its first login persists a tombstone', async () => {
  const f = await setup();
  const block = await f.app.fetch(new Request(`${url}/internal/account-block`, { method: 'POST', headers: { authorization: 'Bearer synthetic-admin-secret' }, body: JSON.stringify({ account_id: 'sub_existing' }) }));
  assert.equal(block.status, 200);
  await assert.rejects(() => f.login());
});

test('identity fingerprints are keyed and differ across secrets', async () => {
  const key = bytes => crypto.subtle.importKey('raw', new Uint8Array(32).fill(bytes), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const a = await identityFingerprint(await key(1), 'google-sub');
  assert.equal(a, await identityFingerprint(await key(1), 'google-sub'));
  assert.notEqual(a, await identityFingerprint(await key(2), 'google-sub'));
  assert.equal(a.includes('google-sub'), false);
});

test('concurrent refresh requests return the same rotated token pair', async () => {
  const f = await setup(), l = await f.login();
  const minted = await (await f.post('/token', { grant_type: 'authorization_code', code: l.code, code_verifier: l.verifier, redirect_uri: l.redirectUri })).json();
  const params = { grant_type: 'refresh_token', refresh_token: minted.refresh_token };
  const [a, b] = await Promise.all([f.post('/token', params), f.post('/token', params)]);
  assert.equal(a.status, 200); assert.equal(b.status, 200);
  const first = await a.json(), second = await b.json();
  assert.deepEqual(first, second);
  assert.notEqual(first.refresh_token, minted.refresh_token);
  assert.equal((await f.post('/token', { grant_type: 'refresh_token', refresh_token: first.refresh_token })).status, 200);
  // Reusing anything older than the immediate predecessor is still a replay.
  assert.equal((await f.post('/token', params)).status, 400);
});

test('b62 code exchange releases profile only server side and once', async () => {
  const f = await setup({clientId: 'b62', profile: true});
  const login = await f.login();
  const fields = {grant_type:'authorization_code', code: login.code, code_verifier: login.verifier, redirect_uri: login.redirectUri};
  const response = await f.post('/token', fields);
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.account_id, 'sub_existing');
  assert.deepEqual(body.profile, {email:'test@example.invalid', email_verified:true, name:'Test User', picture:''});
  assert.equal(JSON.stringify(body).includes('google-sub'), false);
  assert.equal((await f.post('/token', fields)).status, 400);
  const refreshed = await (await f.post('/token', {grant_type:'refresh_token', refresh_token:body.refresh_token})).json();
  assert.equal('profile' in refreshed, false);
});

test('unlisted service does not receive profile', async () => {
  const f = await setup(), login = await f.login();
  const body = await (await f.post('/token', {grant_type:'authorization_code', code:login.code, code_verifier:login.verifier, redirect_uri:login.redirectUri})).json();
  assert.equal('profile' in body, false);
  assert.equal(JSON.stringify(body).includes('test@example.invalid'), false);
});

test('existing other-product account can safely add b62 without identity drift', async () => {
  const f = await setup();
  const registry = f.stateFor('google-account-registry');
  const base = {fingerprint:'test-fingerprint', userId:'usr_synthetic', subject:'synthetic-sub'};
  const first = await registry.resolveAccount({...base, productId:'lovetree'});
  const second = await registry.resolveAccount({...base, productId:'b62'});
  assert.equal(first.account_id, second.account_id);
  assert.equal(f.calls(), 2);
});

test('b62 existing account rejects a different canonical identity', async () => {
  const store = storage();
  let t = Promise.resolve();
  const state = {storage: store, blockConcurrencyWhile(fn) {const next = t.then(fn); t = next.catch(() => {}); return next;}};
  const authority = {async resolve_or_create_product_link(v) {return {ok:true, link:{state:'active', product_id:v.product_id, product_user_id:v.product_user_id, canonical_subject_id:'sub_wrong'}};}};
  const registry = new AuthStateObject(state, {IDENTITY_AUTHORITY:authority});
  registry.putAccount({fingerprint:'test', accountId:'sub_original'});
  await assert.rejects(() => registry.resolveAccount({fingerprint:'test', productId:'b62', userId:'usr_test', subject:'google-sub'}));
  assert.equal(registry.accountByFingerprint('test').account_id, 'sub_original');
});

test('code profile schedules durable expiry and alarm deletes ciphertext', async () => {
  const store = storage();
  let scheduled;
  store.setAlarm = async at => { scheduled = at; };
  const state = {storage:store, blockConcurrencyWhile(fn) { return fn(); }};
  const object = new AuthStateObject(state, {});
  const expires = Math.floor(Date.now() / 1000) - 1;
  await object.createCode({digest:'d', client:'b62', redirect:'r', challenge:'c', subject:'sub_a', accountId:'sub_a', expires, encryptedProfile:'ciphertext'});
  assert.equal(scheduled, expires * 1000);
  assert.equal(store.sql.exec('SELECT * FROM code_profiles').toArray().length, 1);
  await object.alarm();
  assert.equal(store.sql.exec('SELECT * FROM code_profiles').toArray().length, 0);
});
