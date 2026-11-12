import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import worker, { AuthStateObject, identityFingerprint, googleProductUserId } from '../worker.mjs';

const ORIGIN = 'https://auth.padiem.net';
const REDIRECT = 'https://client.example.invalid/callback';
const ACCOUNT = 'sub_deleted_fixture';
const SUBJECT = 'google-subject-private-fixture';
const SESSION_OBJECT = 'O'.repeat(43);
const SESSION = 'S'.repeat(43);
const SECRET = 'synthetic-chat-deletion-secret-32chars';
const b64 = value => Buffer.from(value).toString('base64url');
const j64 = value => b64(JSON.stringify(value));
const sum = async value => b64(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)));
const random = () => b64(crypto.getRandomValues(new Uint8Array(32)));
const now = () => Math.floor(Date.now() / 1000);

const keys = (async () => {
  const google = await crypto.subtle.generateKey({ name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['sign', 'verify']);
  const signing = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const googleJwk = { ...await crypto.subtle.exportKey('jwk', google.publicKey), kid: 'google-fixture' };
  const signingJwk = { ...await crypto.subtle.exportKey('jwk', signing.publicKey), kid: 'auth-fixture' };
  return { google, googleJwk, signingJwk, privateJwk: await crypto.subtle.exportKey('jwk', signing.privateKey) };
})();

function storage() {
  const db = new DatabaseSync(':memory:');
  return {
    db,
    sql: { exec(query, ...params) {
      const statement = db.prepare(query);
      if (statement.columns().length) { const rows = statement.all(...params); return { toArray: () => rows }; }
      statement.run(...params);
      return { toArray: () => [] };
    } },
    transactionSync(fn) {
      db.exec('BEGIN');
      try { const result = fn(); db.exec('COMMIT'); return result; }
      catch (error) { db.exec('ROLLBACK'); throw error; }
    },
    async setAlarm() {},
  };
}

function snapshot(state) {
  return Object.fromEntries(state.storage.db.prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").all()
    .map(({ name }) => [name, state.storage.db.prepare(`SELECT * FROM "${name.replaceAll('"', '""')}" ORDER BY rowid`).all()]));
}

async function setup(t, { known = true, chatMapping = true, decision = { ok: true, removed_by_account_deletion: true }, binding = true, rejection = { ok: false, error: { code: 'identity_rebind_forbidden' } } } = {}) {
  const k = await keys;
  const objects = new Map(), rpcCalls = [], authorityCalls = [], decisionCalls = [], chatCalls = [], logs = [];
  let nonce = '', linkSnapshot = [], chatStatus = 200;
  const env = {
    GOOGLE_CLIENT_ID: 'google-client-fixture', GOOGLE_CLIENT_SECRET: 'synthetic-google-secret',
    PADIEM_AUTH_CLIENTS: JSON.stringify(Object.fromEntries(['b62', 'lovetree-4-0', 'b61'].map(id => [id, { id, redirect_uris: [REDIRECT], jwks: { keys: [k.signingJwk] } }]))),
    PADIEM_AUTH_JWKS: JSON.stringify({ keys: [k.signingJwk] }),
    PADIEM_AUTH_ES256_PRIVATE_JWK: JSON.stringify(k.privateJwk), PADIEM_AUTH_SIGNING_KID: 'auth-fixture',
    PADIEM_AUTH_IDENTITY_HMAC_KEY: b64(new Uint8Array(32).fill(9)),
    PADIEM_AUTH_REFRESH_ENCRYPTION_KEY: b64(new Uint8Array(32).fill(8)),
    PADIEM_AUTH_PASSWORD_RPC_SECRET: SECRET, PADIEM_CHAT_PASSWORD_RPC_ORIGIN: 'https://chat.example.invalid',
    IDENTITY_AUTHORITY: {
      async resolve_or_create_product_link(input) { authorityCalls.push(structuredClone(input)); return structuredClone(rejection); },
      async list_active_product_links_for_subject(input) {
        assert.deepEqual(input, { canonical_subject_id: ACCOUNT });
        if (linkSnapshot instanceof Error) throw linkSnapshot;
        return { ok: true, links: linkSnapshot };
      },
    },
  };
  if (binding) env.COMMON_LOGIN_DELETION_RECORD = {
    async resolve_subject_removed_by_account_deletion(input) {
      decisionCalls.push(structuredClone(input));
      if (decision instanceof Error) throw decision;
      return structuredClone(decision);
    },
  };
  const objectFor = name => {
    if (!objects.has(name)) {
      let queue = Promise.resolve();
      const state = { storage: storage(), blockConcurrencyWhile(fn) { const run = queue.then(fn); queue = run.catch(() => {}); return run; } };
      objects.set(name, new AuthStateObject(state, env));
    }
    return objects.get(name);
  };
  env.AUTH_STATE = {
    idFromName: name => name,
    get: name => ({ async fetch(input, init) {
      const request = new Request(input, init);
      rpcCalls.push({ name, method: new URL(request.url).pathname.slice(1) });
      // Exercise the deployed HTTP/JSON envelope rather than direct test-only calls.
      return objectFor(name).fetch(request);
    } }),
  };
  t.after(() => { for (const object of objects.values()) object.storage.db.close(); });
  t.mock.method(console, 'log', value => logs.push(String(value)));
  t.mock.method(console, 'error', value => logs.push(String(value)));
  t.mock.method(globalThis, 'fetch', async (address, options = {}) => {
    if (String(address) === 'https://www.googleapis.com/oauth2/v3/certs') return Response.json({ keys: [k.googleJwk] });
    if (String(address) === 'https://oauth2.googleapis.com/token') {
      const header = j64({ alg: 'RS256', kid: k.googleJwk.kid });
      const payload = j64({ iss: 'https://accounts.google.com', aud: env.GOOGLE_CLIENT_ID, sub: SUBJECT, nonce, iat: now() - 1, exp: now() + 300 });
      const input = `${header}.${payload}`;
      const signature = await crypto.subtle.sign('RSASSA-PKCS1-v1_5', k.google.privateKey, new TextEncoder().encode(input));
      return Response.json({ id_token: `${input}.${b64(signature)}` });
    }
    assert.equal(String(address), 'https://chat.example.invalid/internal/account-delete', 'recovery must not HTTP-call its own deletion routes');
    const body = Buffer.from(options.body), h = options.headers;
    const canonical = Buffer.concat([Buffer.from(`v2\nPOST\n/internal/account-delete\n${h['x-padiem-service-at']}\n${h['x-padiem-service-id']}\n`), body]);
    assert.equal(h['x-padiem-service-proof'], 'v2=' + createHmac('sha256', SECRET).update(canonical).digest('hex'));
    assert.equal(options.redirect, 'manual');
    chatCalls.push(JSON.parse(body));
    return Response.json({ ok: chatStatus === 200 }, { status: chatStatus });
  });
  const identityKey = await crypto.subtle.importKey('raw', new Uint8Array(32).fill(9), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const fingerprint = await identityFingerprint(identityKey, SUBJECT), userId = await googleProductUserId(SUBJECT);
  const registry = objectFor('google-account-registry'), sessions = objectFor(SESSION_OBJECT);
  if (known) {
    registry.putAccount({ fingerprint, accountId: ACCOUNT, ...(chatMapping ? { productUserId: userId } : {}), now: now() });
    sessions.createSession({ id: SESSION, client: 'b62', subject: ACCOUNT, accountId: ACCOUNT, expires: now() + 3600, digest: 'synthetic-refresh-digest' });
    registry.indexAccountSession({ accountId: ACCOUNT, objectId: SESSION_OBJECT, sessionId: SESSION, expires: now() + 3600, now: now() });
  }
  async function callback(clientId = 'b62') {
    const params = new URLSearchParams({ client_id: clientId, redirect_uri: REDIRECT, state: random(), code_challenge: await sum(random()), code_challenge_method: 'S256' });
    const begin = await worker.fetch(new Request(`${ORIGIN}/login/google?${params}`), env);
    assert.equal(begin.status, 302);
    const googleURL = new URL(begin.headers.get('location'));
    nonce = googleURL.searchParams.get('nonce');
    const cb = new URL(`${ORIGIN}/oauth/google/callback`);
    cb.searchParams.set('state', googleURL.searchParams.get('state'));
    cb.searchParams.set('code', 'synthetic-callback-code');
    return worker.fetch(new Request(cb, { headers: { cookie: begin.headers.get('set-cookie').split(';')[0], 'accept-language': 'ko' } }), env);
  }
  return {
    env, registry, sessions, fingerprint, userId, callback, rpcCalls, authorityCalls, decisionCalls, chatCalls, logs,
    snapshot: () => ({ registry: snapshot(registry), sessions: snapshot(sessions) }),
    setChatStatus: value => { chatStatus = value; }, setLinkSnapshot: value => { linkSnapshot = value; },
  };
}

async function assertUnavailable(response) {
  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), { error: 'authentication_unavailable' });
}

function assertRecovered(f) {
  assert.equal(f.registry.identityIsDeleted({ fingerprint: f.fingerprint }), true);
  assert.equal(f.registry.accountByFingerprint(f.fingerprint), null);
  assert.deepEqual(f.registry.indexedAccountSessions({ accountId: ACCOUNT }), []);
  assert.deepEqual(f.registry.sql.exec('SELECT * FROM account_deletion_locks').toArray(), []);
  assert.equal(f.sessions.sql.exec('SELECT revoked FROM sessions WHERE id=?', SESSION).toArray()[0].revoked, 1);
}

for (const [label, config] of [
  ['false decision', { decision: { ok: true, removed_by_account_deletion: false } }],
  ['ok false', { decision: { ok: false, removed_by_account_deletion: true } }],
  ['truthy nonboolean decision', { decision: { ok: true, removed_by_account_deletion: 'true' } }],
  ['truthy nonboolean ok', { decision: { ok: 1, removed_by_account_deletion: true } }],
  ['missing decision field', { decision: { ok: true } }],
  ['null decision', { decision: null }],
  ['binding exception', { decision: new Error('private-upstream-error-fixture') }],
  ['missing binding', { binding: false }],
]) test(`${label} preserves all registry/session tables and returns 503`, async t => {
  const f = await setup(t, config), before = f.snapshot();
  await assertUnavailable(await f.callback());
  assert.deepEqual(f.snapshot(), before);
  assert.equal(f.chatCalls.length, 0);
  assert.equal(f.decisionCalls.length, config.binding === false ? 0 : 1);
  if (f.decisionCalls.length) assert.deepEqual(f.decisionCalls[0], { canonical_subject_id: ACCOUNT });
  assert.equal(f.logs.join('\n').includes('private-upstream-error-fixture'), false);
});

test('a refusal without expected account never asks the deletion binding', async t => {
  const f = await setup(t, { known: false }), before = f.snapshot();
  await assertUnavailable(await f.callback());
  assert.equal('expected_canonical_subject_id' in f.authorityCalls[0], false);
  assert.equal(f.decisionCalls.length, 0);
  assert.deepEqual(f.snapshot(), before);
});

test('another refusal code never asks the deletion binding', async t => {
  const f = await setup(t, { rejection: { ok: false, error: { code: 'identity_conflict' } } }), before = f.snapshot();
  await assertUnavailable(await f.callback());
  assert.equal(f.decisionCalls.length, 0);
  assert.deepEqual(f.snapshot(), before);
});

test('an invalid ok:true link cannot trigger deletion even if it carries the refusal code', async t => {
  const f = await setup(t, { rejection: { ok: true, error: { code: 'identity_rebind_forbidden' } } }), before = f.snapshot();
  await assertUnavailable(await f.callback());
  assert.equal(f.decisionCalls.length, 0);
  assert.deepEqual(f.snapshot(), before);
});

test('a live deletion lock preserves every table including unrelated expired locks', async t => {
  const f = await setup(t);
  f.registry.sql.exec('INSERT INTO account_deletion_locks VALUES(?,?,?)', ACCOUNT, 'existing-lock-fixture', now() + 300);
  f.registry.sql.exec('INSERT INTO account_deletion_locks VALUES(?,?,?)', 'sub_other_fixture', 'expired-lock-fixture', now() - 1);
  const before = f.snapshot();
  await assertUnavailable(await f.callback());
  assert.deepEqual(f.snapshot(), before);
  assert.equal(f.decisionCalls.length, 1);
  assert.equal(f.chatCalls.length, 0);
});

test('pre-tombstone failure releases the acquired lock and the next login recovers', async t => {
  const f = await setup(t), originalExec = f.registry.sql.exec;
  let failOnce = true;
  f.registry.sql.exec = (query, ...args) => {
    if (failOnce && query.includes('INSERT INTO identity_deletion_tombstone')) {
      failOnce = false;
      throw new Error('synthetic-before-tombstone');
    }
    return originalExec(query, ...args);
  };
  await assertUnavailable(await f.callback());
  assert.equal(f.registry.identityIsDeleted({ fingerprint: f.fingerprint }), false);
  assert.equal(f.registry.accountByFingerprint(f.fingerprint).account_id, ACCOUNT);
  assert.equal(f.registry.indexedAccountSessions({ accountId: ACCOUNT }).length, 1);
  assert.deepEqual(f.registry.sql.exec('SELECT * FROM account_deletion_locks').toArray(), []);
  assert.equal(f.sessions.sql.exec('SELECT revoked FROM sessions WHERE id=?', SESSION).toArray()[0].revoked, 1, 'revocation is correct for an already deleted account');
  const retry = await f.callback();
  assert.equal(retry.status, 403);
  assertRecovered(f);
  assert.equal(f.decisionCalls.length, 2);
});

test('failure after the tombstone INSERT but before transaction commit rolls the tombstone back', async t => {
  const f = await setup(t), originalExec = f.registry.sql.exec;
  f.registry.sql.exec = (query, ...args) => {
    if (query === 'DELETE FROM google_accounts WHERE account_id=?') throw new Error('synthetic-mid-transaction');
    return originalExec(query, ...args);
  };
  await assertUnavailable(await f.callback());
  assert.equal(f.registry.identityIsDeleted({ fingerprint: f.fingerprint }), false);
  assert.equal(f.registry.accountByFingerprint(f.fingerprint).account_id, ACCOUNT);
  assert.deepEqual(f.registry.sql.exec('SELECT * FROM account_deletion_locks').toArray(), []);
  assert.equal(f.chatCalls.length, 0);
});

test('confirmed deletion revokes sessions, finalizes once and reuses the tombstone response', async t => {
  const f = await setup(t);
  const first = await f.callback();
  assert.equal(first.status, 403);
  const body = await first.text();
  assert.match(body, /탈퇴한 계정입니다/);
  assert.equal(first.headers.get('location'), null);
  assertRecovered(f);
  assert.deepEqual(f.decisionCalls, [{ canonical_subject_id: ACCOUNT }]);
  assert.equal(f.authorityCalls[0].expected_canonical_subject_id, ACCOUNT);
  assert.deepEqual(f.chatCalls, [{ product_user_id: f.userId }]);
  assert.deepEqual(f.registry.pendingChatAccountDeletions(), []);
  assert.equal(f.rpcCalls.some(call => call.name === SESSION_OBJECT && call.method === 'forceRevokeForAccountDeletion'), true);
  assert.equal(f.rpcCalls.some(call => call.name === 'google-account-registry' && ['beginAccountDeletion', 'finalizeAccountDeletion'].includes(call.method)), false, 'recovery must use direct registry methods');
  const second = await f.callback();
  assert.equal(second.status, 403);
  assert.equal(await second.text(), body);
  assert.equal(f.decisionCalls.length, 1);
  assert.equal(f.authorityCalls.length, 1);
  assert.equal(f.chatCalls.length, 1);
  const stages = f.logs.map(line => JSON.parse(line)).filter(entry => entry.auth_stage === 'account_deletion_record_check' || entry.auth_stage?.startsWith('account_deletion_recovery_'));
  assert.ok(stages.length > 0);
  for (const entry of stages) assert.deepEqual(Object.keys(entry), ['auth_stage']);
  for (const secret of [SUBJECT, ACCOUNT, f.fingerprint, f.userId, SECRET]) assert.equal(f.logs.join('\n').includes(secret), false);
});

test('Map RPC decision is normalized before the strict boolean check', async t => {
  const f = await setup(t, { decision: new Map([['ok', true], ['removed_by_account_deletion', true]]) });
  assert.equal((await f.callback()).status, 403);
  assertRecovered(f);
});

test('Chat failure after commit keeps the tombstone, so the next login is 403', async t => {
  const f = await setup(t);
  f.setChatStatus(503);
  await assertUnavailable(await f.callback());
  assertRecovered(f);
  assert.deepEqual(f.registry.pendingChatAccountDeletions(), [f.userId]);
  assert.equal((await f.callback()).status, 403);
  assert.equal(f.decisionCalls.length, 1);
  assert.equal(f.chatCalls.length, 1);
});

test('alarm failure after finalize commit leaves a tombstone for the next login', async t => {
  const f = await setup(t);
  f.registry.storage.setAlarm = async () => { throw new Error('synthetic-post-commit-alarm-failure'); };
  await assertUnavailable(await f.callback());
  assertRecovered(f);
  assert.equal((await f.callback()).status, 403);
  assert.equal(f.decisionCalls.length, 1);
  assert.equal(f.chatCalls.length, 0);
});

test('a missing historical Chat mapping does not invent a Chat user id', async t => {
  const f = await setup(t, { chatMapping: false });
  assert.equal((await f.callback()).status, 403);
  assertRecovered(f);
  assert.deepEqual(f.chatCalls, []);
  assert.deepEqual(f.registry.pendingChatAccountDeletions(), []);
});

test('prepare retains its optional Chat mapping enrichment and revokes indexed sessions', async t => {
  const f = await setup(t, { chatMapping: false });
  f.setLinkSnapshot([{ product_id: 'b62', product_user_id: 'usr_existing_chat_fixture', state: 'active' }]);
  assert.equal((await f.callback()).status, 403);
  assertRecovered(f);
  assert.deepEqual(f.chatCalls, [{ product_user_id: 'usr_existing_chat_fixture' }]);
});

test('the optional link snapshot can fail without preventing recovery', async t => {
  const f = await setup(t);
  f.setLinkSnapshot(new Error('synthetic-already-removed-subject'));
  assert.equal((await f.callback()).status, 403);
  assertRecovered(f);
});

test('prepare session revocation failure aborts the lock without finalizing', async t => {
  const f = await setup(t);
  f.sessions.forceRevokeForAccountDeletion = () => false;
  await assertUnavailable(await f.callback());
  assert.equal(f.registry.identityIsDeleted({ fingerprint: f.fingerprint }), false);
  assert.equal(f.registry.accountByFingerprint(f.fingerprint).account_id, ACCOUNT);
  assert.deepEqual(f.registry.sql.exec('SELECT * FROM account_deletion_locks').toArray(), []);
  assert.equal(f.chatCalls.length, 0);
});

for (const productId of ['lovetree-4-0', 'b61']) test(`${productId} existing Google login does not enter deletion recovery`, async t => {
  const f = await setup(t), before = f.snapshot();
  assert.equal((await f.callback(productId)).status, 302);
  assert.equal(f.authorityCalls.length, 0);
  assert.equal(f.decisionCalls.length, 0);
  assert.deepEqual(f.snapshot(), before);
});

test('password rebind refusal never queries the Google recovery binding', async t => {
  const f = await setup(t), before = f.snapshot();
  const response = await f.registry.fetch(new Request('https://internal/resolveAccount', {
    method: 'POST', body: JSON.stringify({ fingerprint: f.fingerprint, productId: 'b62', userId: f.userId, subject: 'user@example.invalid', provider: 'password', now: now(), credentialEpoch: '2026-11-13T00:00:00Z' }),
  }));
  assert.equal(response.status, 500);
  assert.equal(f.authorityCalls.length, 1);
  assert.equal(f.decisionCalls.length, 0);
  assert.deepEqual(f.snapshot(), before);
});
