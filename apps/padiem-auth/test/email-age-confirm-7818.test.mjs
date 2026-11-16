// #7818 PR 2 follow-up: an email account created before PR 1 has no
// age_confirmed_at. It answers the same gate once at its next email login.
import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { AuthState } from '../state.mjs';
import { createApp, AuthStateObject } from '../worker.mjs';

const URL_BASE = 'https://auth.padiem.net';
const REDIRECT = 'https://client.example.invalid/callback';
const EMAIL = 'legacy@example.invalid';
const PASSWORD = 'synthetic-safe-password';
const USER_ID = 'usr_legacy_fixture';
const b64 = (x) => Buffer.from(x).toString('base64url');
const sum = async (x) => b64(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(x)));
const rand = () => b64(crypto.getRandomValues(new Uint8Array(32)));

function storage() {
  const db = new DatabaseSync(':memory:');
  return {
    sql: { exec(q, ...p) { const s = db.prepare(q); if (s.columns().length) { const rows = s.all(...p); return { toArray: () => rows }; } s.run(...p); return { toArray: () => [] }; } },
    transactionSync(fn) { db.exec('BEGIN'); try { const out = fn(); db.exec('COMMIT'); return out; } catch (e) { db.exec('ROLLBACK'); throw e; } },
  };
}

async function setup() {
  const signing = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const client = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const publicClient = await crypto.subtle.exportKey('jwk', client.publicKey); publicClient.kid = 'client';
  const publicSigning = await crypto.subtle.exportKey('jwk', signing.publicKey); publicSigning.kid = 'auth';
  const refreshKey = await crypto.subtle.importKey('raw', new Uint8Array(32).fill(8), 'AES-GCM', false, ['encrypt', 'decrypt']);
  const identityKey = await crypto.subtle.importKey('raw', new Uint8Array(32).fill(9), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const authority = { async resolve_or_create_product_link(v) { return { ok: true, link: { state: 'active', product_id: v.product_id, product_user_id: v.product_user_id, canonical_subject_id: 'sub_legacy' } }; } };
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
    clients: { b62: { id: 'b62', password_login: true, redirect_uris: [REDIRECT], jwks: { keys: [publicClient] } } },
    googleClientId: 'google-client', googleClientSecret: 'synthetic', identityKey, refreshKey,
    adminSecret: 'synthetic-admin-secret', accountDeleteRpcSecret: 'synthetic-account-delete-secret-32chars',
    passwordRpcSecret: 'synthetic-password-rpc-secret-32chars-min', passwordRpcOrigin: 'https://chat.example.invalid',
    signingKey: signing.privateKey, signingKid: 'auth', jwks: { keys: [publicSigning] }, stateFor, now: () => 1000,
    async fetcher(address) {
      const path = new URL(String(address)).pathname;
      if (path !== '/internal/password-register' && path !== '/internal/password-verify') throw new Error('unexpected fetch ' + address);
      return Response.json({ ok: true, product_user_id: USER_ID, credential_epoch: '2026-11-12T00:00:00+00:00' });
    },
  });
  async function form(path = '/login') {
    const begun = await app.fetch(new Request(`${URL_BASE}${path}?${new URLSearchParams({ client_id: 'b62', redirect_uri: REDIRECT, state: rand(), code_challenge: await sum(rand()), code_challenge_method: 'S256' })}`));
    const html = await begun.text();
    const action = html.match(/action="(\/(?:login|signup)\/password\?state=[^"]+)"/)[1].replaceAll('&amp;', '&');
    return { action, cookie: begun.headers.get('set-cookie').split(';')[0] };
  }
  async function post(path, fields, extra = {}) {
    const { action, cookie } = await form(path);
    const raw = await app.fetch(new Request(`${URL_BASE}${action}`, {
      method: 'POST', headers: { 'content-type': 'application/x-www-form-urlencoded', cookie, ...extra }, body: new URLSearchParams(fields),
    }));
    return { raw, cookie };
  }
  return { app, form, post, stateFor, registry: () => stateFor('google-account-registry') };
}

test('an unconfirmed legacy email account sees the gate once, then never again', async () => {
  const f = await setup();
  await f.post('/signup', { name: '', email: EMAIL, password: PASSWORD, age_confirm: 'yes' });
  const registry = f.registry();
  const row = registry.sql.exec('SELECT account_id FROM google_accounts').toArray()[0];
  // Simulate a pre-PR 1 account: the row exists but was never confirmed.
  registry.sql.exec('UPDATE google_accounts SET age_confirmed_at=NULL WHERE account_id=?', row.account_id);
  assert.equal(registry.ageConfirmedAt({ accountId: row.account_id }), null);

  const first = await f.post('/login', { email: EMAIL, password: PASSWORD });
  const html = await first.raw.text();
  assert.equal(first.raw.status, 200, 'the gate is shown instead of the code');
  assert.ok(html.includes('name="handle"'));
  assert.ok(html.includes('name="age_confirm"'));
  const handle = html.match(/name="handle" value="([^"]+)"/)[1];

  const done = await f.app.fetch(new Request(`${URL_BASE}/age-confirm/password`, {
    method: 'POST', headers: { 'content-type': 'application/x-www-form-urlencoded', cookie: first.cookie },
    body: new URLSearchParams({ handle, age_confirm: 'yes' }),
  }));
  assert.equal(done.status, 302, 'login resumes to the original service');
  assert.equal(new URL(done.headers.get('location')).origin + new URL(done.headers.get('location')).pathname, REDIRECT);
  assert.notEqual(registry.ageConfirmedAt({ accountId: row.account_id }), null, 'the confirmation was recorded');

  const second = await f.post('/login', { email: EMAIL, password: PASSWORD });
  assert.equal(second.raw.status, 302, 'no second prompt');
});

test('an email account that already has a confirmation goes straight through', async () => {
  const f = await setup();
  await f.post('/signup', { name: '', email: EMAIL, password: PASSWORD, age_confirm: 'yes' });
  const registry = f.registry();
  const row = registry.sql.exec('SELECT account_id FROM google_accounts').toArray()[0];
  const before = registry.ageConfirmedAt({ accountId: row.account_id });
  assert.notEqual(before, null);

  const login = await f.post('/login', { email: EMAIL, password: PASSWORD });
  assert.equal(login.raw.status, 302, 'no gate for a confirmed account');
  assert.ok(login.raw.headers.get('location').startsWith(REDIRECT));
  assert.equal(registry.ageConfirmedAt({ accountId: row.account_id }), before, 'the record is unchanged');
});
