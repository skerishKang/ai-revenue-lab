import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { AuthState } from '../state.mjs';
import { createApp } from '../worker.mjs';

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
async function setup() {
  const google = await crypto.subtle.generateKey({ name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['sign', 'verify']);
  const googleJwk = await crypto.subtle.exportKey('jwk', google.publicKey); googleJwk.kid = 'google';
  const signing = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const publicSigning = await crypto.subtle.exportKey('jwk', signing.publicKey); publicSigning.kid = 'auth';
  const client = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const publicClient = await crypto.subtle.exportKey('jwk', client.publicKey); publicClient.kid = 'client';
  const objects = new Map(); const stateFor = id => { if (!objects.has(id)) objects.set(id, new AuthState({ storage: storage() })); return objects.get(id); };
  let nonce = ''; let linked = null; const t = 1000;
  const app = createApp({ clients: { lovetree: { id: 'lovetree', redirect_uris: ['https://lovetree.example/auth/callback'], jwks: { keys: [publicClient] } } }, googleClientId: 'google-client', googleClientSecret: 'synthetic', signingKey: signing.privateKey, signingKid: 'auth', jwks: { keys: [publicSigning] }, stateFor, now: () => t,
    authority: { async resolve_or_create_product_link(v) { linked = v; return { ok: true, link: { state: 'active', product_id: v.product_id, product_user_id: v.product_user_id, canonical_subject_id: 'sub_existing' } }; }, async resolve_product_user_for_subject() { return {ok:true,product_user_id:linked.product_user_id}; } },
    async fetcher(address) { if (address.includes('/certs')) return Response.json({ keys: [googleJwk] });
      const h = j64({ alg: 'RS256', kid: 'google' }), p = j64({ iss: 'https://accounts.google.com', aud: 'google-client', sub: 'google-sub', nonce, iat: 999, exp: 1100 });
      const input = `${h}.${p}`, sig = await crypto.subtle.sign('RSASSA-PKCS1-v1_5', google.privateKey, new TextEncoder().encode(input));
      return Response.json({ id_token: `${input}.${b64(sig)}` }); } });
  async function assertion() { const h = j64({ alg: 'ES256', kid: 'client' }), p = j64({ iss: 'lovetree', sub: 'lovetree', aud: `${url}/token`, iat: 1000, exp: 1100, jti: rand() });
    const input = `${h}.${p}`, sig = await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, client.privateKey, new TextEncoder().encode(input)); return `${input}.${b64(sig)}`; }
  async function post(path, fields) { const params = new URLSearchParams({ client_id: 'lovetree', client_assertion_type: 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer', client_assertion: await assertion(), ...fields }); return app.fetch(new Request(`${url}${path}`, { method: 'POST', body: params })); }
  async function login() { const verifier = rand(), state = rand(), redirectUri = 'https://lovetree.example/auth/callback';
    const start = new URL(`${url}/login`); for (const [k,v] of Object.entries({ client_id: 'lovetree', redirect_uri: redirectUri, state, code_challenge: await sum(verifier), code_challenge_method: 'S256' })) start.searchParams.set(k,v);
    const begun = await app.fetch(new Request(start)); assert.equal(begun.status, 302); const googleURL = new URL(begun.headers.get('location')); nonce = googleURL.searchParams.get('nonce');
    const callback = new URL(`${url}/oauth/google/callback`); callback.searchParams.set('state', googleURL.searchParams.get('state')); callback.searchParams.set('code', 'synthetic-code');
    const done = await app.fetch(new Request(callback, { headers: { cookie: begun.headers.get('set-cookie').split(';')[0] } })); assert.equal(done.status, 302);
    const target = new URL(done.headers.get('location')); assert.equal(target.searchParams.get('state'), state); assert.equal(linked.provider_subject, 'google-sub');
    return { code: target.searchParams.get('code'), verifier, redirectUri }; }
  return { app, post, login, publicSigning };
}

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
  const refreshed = await f.post('/token', { grant_type: 'refresh_token', refresh_token: minted.refresh_token }); assert.equal(refreshed.status, 200);
  const newToken = (await refreshed.json()).refresh_token;
  assert.equal((await f.post('/token', { grant_type: 'refresh_token', refresh_token: minted.refresh_token })).status, 400);
  assert.equal((await f.post('/token', { grant_type: 'refresh_token', refresh_token: newToken })).status, 400);
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
