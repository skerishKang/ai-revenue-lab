import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash, createHmac } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import { runInNewContext } from 'node:vm';
import { AuthState } from '../state.mjs';
import worker, { createApp, AuthStateObject, passwordIdentityFingerprint } from '../worker.mjs';
import { emailRecoveryEnabled } from '../email-recovery.mjs';

const ORIGIN = 'https://auth.padiem.net';
const EMAIL = 'owner@example.invalid';
const ACCOUNT = 'sub_existing';
const EPOCH = '2026-11-12T00:00:00+00:00';
const TOKEN = 't'.repeat(43);
const SECRET = 'synthetic-password-rpc-secret-32chars';
const IDENTITY_BYTES = new Uint8Array(32).fill(19);
const hash = value => createHash('sha256').update(value).digest('hex');
const OLD_USER = 'usr_' + hash(`password:${EMAIL}`).slice(0, 32);
const USER = 'usr_' + 'd'.repeat(32);

function storage() {
  const db = new DatabaseSync(':memory:');
  return { db, sql: { exec(query, ...params) {
    const statement = db.prepare(query);
    if (statement.columns().length) { const rows = statement.all(...params); return { toArray: () => rows }; }
    statement.run(...params); return { toArray: () => [] };
  } }, transactionSync(fn) {
    db.exec('BEGIN');
    try { const value = fn(); db.exec('COMMIT'); return value; }
    catch (error) { db.exec('ROLLBACK'); throw error; }
  } };
}

async function setup({ enabled = true, existing = true, activeChat = false, deleted = false, google = false, links = true } = {}) {
  const identityKey = await crypto.subtle.importKey('raw', IDENTITY_BYTES, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const objects = new Map();
  const calls = []; const seen = new Set();
  let clock = 1000, queue = Promise.resolve(), failAction = '', deliveries = 0;
  const chat = new DatabaseSync(':memory:');
  chat.exec('CREATE TABLE proof(digest TEXT PRIMARY KEY, expires INTEGER, consumed INTEGER DEFAULT 0); CREATE TABLE credential(user_id TEXT PRIMARY KEY, password TEXT, epoch TEXT)');
  chat.prepare('INSERT INTO proof(digest,expires) VALUES(?,?)').run(hash(TOKEN), 1900);
  if (activeChat) chat.prepare('INSERT INTO credential VALUES(?,?,?)').run(USER, 'old-password', EPOCH);
  const stateFor = id => {
    if (!objects.has(id)) objects.set(id, new AuthState({ storage: storage() }));
    return objects.get(id);
  };
  const rpcFetcher = async (address, options) => {
    const path = new URL(address).pathname, action = path.split('/').at(-1);
    const bytes = Buffer.from(options.body), headers = options.headers;
    const expected = 'v2=' + createHmac('sha256', SECRET).update(Buffer.concat([
      Buffer.from(`v2\nPOST\n${path}\n${headers['x-padiem-service-at']}\n${headers['x-padiem-service-id']}\n`), bytes,
    ])).digest('hex');
    assert.equal(headers['x-padiem-service-proof'], expected);
    assert.ok(!seen.has(headers['x-padiem-service-id']), 'each call has a fresh signed replay id');
    seen.add(headers['x-padiem-service-id']);
    assert.equal(options.redirect, 'manual');
    const data = JSON.parse(bytes.toString()); calls.push({ action, data });
    if (failAction === action) return Response.json({ error: { code: 'unavailable' } }, { status: 503 });
    if (action === 'status') return Response.json({ ok: true, available: chat.prepare('SELECT * FROM credential').all().length === 0 });
    if (action === 'request') { if (data.account_id) deliveries++; return Response.json({ ok: true }); }
    const row = chat.prepare('SELECT * FROM proof WHERE digest=? AND consumed=0 AND expires>?').get(hash(data.token), clock);
    if (action === 'inspect') {
      if (row && data.new_password.length < 8) return Response.json({ error: { code: 'invalid_password' } }, { status: 400 });
      return Response.json(row ? { ok: true, email: EMAIL, account_id: ACCOUNT, credential_epoch: EPOCH } : { ok: false });
    }
    if (action === 'complete') {
      if (data.new_password.length < 8) return Response.json({ error: { code: 'invalid_password' } }, { status: 400 });
      chat.exec('BEGIN');
      try {
        const consumed = chat.prepare('UPDATE proof SET consumed=1 WHERE digest=? AND consumed=0 AND expires>? RETURNING digest').get(hash(data.token), clock);
        if (!consumed || chat.prepare('SELECT * FROM credential').get()) { chat.exec('ROLLBACK'); return Response.json({ error: { code: 'password_recovery_invalid' } }, { status: 400 }); }
        chat.prepare('INSERT INTO credential VALUES(?,?,?)').run(USER, data.new_password, data.credential_epoch);
        chat.exec('COMMIT');
        return Response.json({ ok: true, product_user_id: USER, account_id: ACCOUNT, credential_epoch: data.credential_epoch });
      } catch (error) { chat.exec('ROLLBACK'); throw error; }
    }
    throw new Error('unexpected synthetic route');
  };
  const state = { storage: storage(), blockConcurrencyWhile(fn) { const next = queue.then(fn); queue = next.catch(() => {}); return next; } };
  const registry = new AuthStateObject(state, {
    PADIEM_AUTH_EMAIL_RECOVERY_ENABLED: enabled,
    PADIEM_AUTH_PASSWORD_RPC_SECRET: SECRET, PADIEM_CHAT_PASSWORD_RPC_ORIGIN: 'https://chat.example.invalid',
    PADIEM_AUTH_IDENTITY_HMAC_KEY: Buffer.from(IDENTITY_BYTES).toString('base64url'),
    IDENTITY_AUTHORITY: { async list_active_product_links_for_subject() { return { ok: true, links: links ? [{ product_id: 'lovetree-4-0', product_user_id: USER, state: 'active' }] : [] }; } },
  }, { recoveryFetcher: rpcFetcher, recoveryStateFor: stateFor });
  objects.set('google-account-registry', registry);
  const fingerprint = await passwordIdentityFingerprint(identityKey, EMAIL);
  if (existing) {
    registry.putAccount({ fingerprint: google ? 'google-fingerprint' : fingerprint, accountId: ACCOUNT, productUserId: OLD_USER, now: clock });
    if (!google) registry.recordPasswordCredentialEpoch({ fingerprint, epoch: EPOCH });
  }
  if (deleted) registry.sql.exec('INSERT INTO identity_deletion_tombstone VALUES(?,?)', fingerprint, clock);
  const session = stateFor('o'.repeat(43));
  if (existing) {
    session.createSession({ id: 's'.repeat(43), client: 'lovetree-4-0', subject: ACCOUNT, accountId: ACCOUNT, expires: 2000, digest: 'refresh' });
    registry.indexAccountSession({ accountId: ACCOUNT, objectId: 'o'.repeat(43), sessionId: 's'.repeat(43), expires: 2000, now: clock });
  }
  const app = createApp({ clients: {}, identityKey, emailRecoveryEnabled: enabled,
    passwordRpcSecret: SECRET, passwordRpcOrigin: 'https://chat.example.invalid', stateFor, fetcher: rpcFetcher, now: () => clock });
  const request = (email = EMAIL, headers = {}) => app.fetch(new Request(`${ORIGIN}/password/recovery/request`, { method: 'POST', headers: { 'cf-connecting-ip': '192.0.2.7', ...headers }, body: new URLSearchParams({ email }) }));
  const complete = (token = TOKEN, password = 'new-safe-password', headers = {}) => app.fetch(new Request(`${ORIGIN}/password/recovery/confirm`, { method: 'POST', headers: { 'content-type': 'application/json', ...headers }, body: JSON.stringify({ token, new_password: password }) }));
  return { app, request, complete, registry, session, fingerprint, chat, calls, identityKey,
    time(value) { clock = value; }, fail(value) { failAction = value; }, deliveries: () => deliveries };
}

test('email recovery request is available behind the explicit opt-in', async () => {
  const { request } = await setup({ existing: false });
  const response = await request('unknown@example.invalid');
  assert.equal(response.status, 202);
});

test('request responses are byte-identical for eligible, unknown, active, deleted, Google, and delivery failure', async () => {
  const answers = [];
  for (const variant of [{}, { existing: false }, { activeChat: true }, { deleted: true }, { google: true }, { links: false }, { failure: true }]) {
    const f = await setup(variant);
    if (variant.failure) f.fail('request');
    const response = await f.request();
    answers.push({ status: response.status, headers: [...response.headers], body: await response.text() });
    const request = f.calls.find(call => call.action === 'request');
    assert.equal(request.data.source_digest.length, 43);
    assert.ok(!JSON.stringify(request.data).includes('192.0.2.7'));
    if (variant.existing === false || variant.activeChat || variant.deleted || variant.google || variant.links === false) {
      assert.equal(request.data.account_id, null); assert.equal(request.data.credential_epoch, null);
      assert.equal(f.deliveries(), 0);
    }
  }
  for (const answer of answers) assert.deepEqual(answer, answers[0]);
});

test('proof restores a fresh password to the same shared identity and revokes all indexed sessions', async () => {
  const f = await setup();
  const before = f.registry.sql.exec('SELECT * FROM google_accounts').toArray();
  const response = await f.complete();
  assert.equal(response.status, 200);
  assert.equal((await response.json()).ok, true);
  assert.deepEqual(f.registry.sql.exec('SELECT * FROM google_accounts').toArray(), before);
  assert.equal(f.registry.passwordCredentialEpoch({ fingerprint: f.fingerprint }), EPOCH);
  assert.equal(f.registry.passwordBindingRefused({ fingerprint: f.fingerprint, epoch: 'different' }), true);
  assert.equal(f.registry.passwordBindingRefused({ fingerprint: f.fingerprint, epoch: EPOCH, register: true }), true);
  assert.equal(f.registry.passwordBindingRefused({ fingerprint: f.fingerprint, epoch: EPOCH }), false);
  assert.deepEqual({ ...f.chat.prepare('SELECT * FROM credential').get() }, { user_id: USER, password: 'new-safe-password', epoch: EPOCH });
  assert.notEqual(USER, OLD_USER);
  assert.equal(f.session.sql.exec('SELECT revoked FROM sessions').toArray()[0].revoked, 1);
  assert.equal(f.registry.sql.exec('SELECT * FROM account_deletion_locks').toArray().length, 0);
  assert.ok(f.calls.every(call => !('old_password' in call.data)));
});

test('expired, reused, invalid, and simultaneous proof submissions cannot succeed twice', async () => {
  const f = await setup();
  const both = await Promise.all([f.complete(), f.complete()]);
  assert.deepEqual(both.map(response => response.status).sort(), [200, 400]);
  const reused = await f.complete();
  const expired = await setup(); expired.time(1900);
  const expiredResponse = await expired.complete();
  const invalid = await expired.complete('x'.repeat(43));
  assert.equal(reused.status, 400);
  assert.equal(await reused.text(), await expiredResponse.text());
  const invalidBody = await invalid.text();
  const invalidAgain = await f.complete('broken');
  assert.equal(await invalidAgain.text(), invalidBody);
  assert.equal(f.chat.prepare('SELECT count(*) AS n FROM credential').get().n, 1);
});

test('completion rechecks current eligibility and preserves proof on rejection', async () => {
  for (const variant of [{ activeChat: true }, { deleted: true }, { google: true }, { links: false }]) {
    const f = await setup(variant);
    assert.equal((await f.complete()).status, 400);
    assert.equal(f.chat.prepare('SELECT consumed FROM proof').get().consumed, 0);
    assert.equal(f.calls.filter(call => call.action === 'complete').length, 0);
  }
});

test('session revocation failure does not consume the token or create a credential', async () => {
  const f = await setup();
  f.session.forceRevokeForAccountDeletion = () => false;
  assert.equal((await f.complete()).status, 503);
  assert.equal(f.chat.prepare('SELECT consumed FROM proof').get().consumed, 0);
  assert.equal(f.chat.prepare('SELECT * FROM credential').get(), undefined);
  assert.equal(f.registry.sql.exec('SELECT * FROM account_deletion_locks').toArray().length, 0);
});

test('Chat failure after revocation is retryable without half-created account state', async () => {
  const f = await setup(); f.fail('complete');
  assert.equal((await f.complete()).status, 503);
  assert.equal(f.chat.prepare('SELECT consumed FROM proof').get().consumed, 0);
  assert.equal(f.chat.prepare('SELECT * FROM credential').get(), undefined);
  assert.equal(f.session.sql.exec('SELECT revoked FROM sessions').toArray()[0].revoked, 1);
  f.fail(''); assert.equal((await f.complete()).status, 200);
});

test('new paths and registry methods are absent with the default-off switch', async () => {
  const f = await setup({ enabled: false });
  for (const path of ['/password/recovery', '/password/recovery/request', '/password/recovery/confirm']) {
    for (const method of ['GET', 'POST']) {
      const request = new Request(ORIGIN + path, { method });
      assert.equal((await f.app.fetch(request)).status, 404);
      assert.equal((await worker.fetch(request, {})).status, 404);
    }
  }
  for (const method of ['emailRecoveryCandidate', 'completeEmailRecovery']) {
    assert.equal((await f.registry.fetch(new Request('https://internal/' + method, { method: 'POST', body: '{}' }))).status, 404);
  }
  assert.equal(f.calls.length, 0);
});

test('only explicit true enables recovery and a changed ownership binding invalidates an open proof', async () => {
  for (const value of [undefined, null, false, '', 'false', '0', '1', 'yes', 'on']) assert.equal(emailRecoveryEnabled(value), false);
  for (const value of [true, 'true', ' TRUE ']) assert.equal(emailRecoveryEnabled(value), true);
  const f = await setup();
  f.registry.sql.exec('UPDATE password_credential_epochs SET epoch=?', '2026-11-13T00:00:00+00:00');
  assert.equal((await f.complete()).status, 400);
  assert.equal(f.chat.prepare('SELECT consumed FROM proof').get().consumed, 0);
  assert.equal(f.chat.prepare('SELECT * FROM credential').get(), undefined);
  assert.equal(f.session.sql.exec('SELECT revoked FROM sessions').toArray()[0].revoked, 0);
});

test('recovery screens use both locales and read the completion response without exposing the fragment', async () => {
  const f = await setup();
  const english = await f.app.fetch(new Request(ORIGIN + '/password/recovery/confirm', { headers: { 'accept-language': 'en-US' } }));
  const html = await english.text();
  assert.match(html, /New password/); assert.match(html, /location.hash/);
  assert.match(html, /history.replaceState/); assert.match(html, /result.textContent=data.message/);
  const form = html.match(/<form\b[^>]*id="recovery"[^>]*>/)[0];
  assert.match(form, /method="post"/, 'without JavaScript, a password must never enter a GET URL');
  assert.match(form, /action="\/password\/recovery\/confirm"/);
  assert.doesNotMatch(html, /current-password|old_password/);
  const korean = await f.app.fetch(new Request(ORIGIN + '/password/recovery'));
  assert.match(await korean.text(), /복구 링크 요청/);
  const response = await f.complete(TOKEN, 'short', { 'accept-language': 'en' });
  assert.equal(response.status, 400);
  assert.match((await response.json()).message, /Check your new password/);
  assert.equal(f.chat.prepare('SELECT consumed FROM proof').get().consumed, 0);
  assert.equal(f.session.sql.exec('SELECT revoked FROM sessions').toArray()[0].revoked, 0);
});

test('the browser clears the token fragment, posts only the new password, and displays the response', async () => {
  const f = await setup();
  const page = await f.app.fetch(new Request(ORIGIN + '/password/recovery/confirm'));
  const script = (await page.text()).match(/<script>([\s\S]*?)<\/script>/)[1];
  const events = []; const result = { textContent: '' }; const button = { disabled: false };
  let submit;
  const form = {
    elements: { new_password: { value: 'new-safe-password' } }, hidden: false,
    addEventListener(event, handler) { assert.equal(event, 'submit'); submit = handler; },
    querySelector(selector) { assert.equal(selector, 'button'); return button; },
    reset() { events.push('reset'); },
  };
  runInNewContext(script, {
    URLSearchParams, location: { hash: `#token=${TOKEN}`, pathname: '/password/recovery/confirm' },
    history: { replaceState(_state, _title, path) { assert.equal(path, '/password/recovery/confirm'); events.push('fragment-cleared'); } },
    document: { getElementById(id) { return id === 'recovery' ? form : result; } },
    async fetch(path, options) {
      assert.deepEqual(events, ['fragment-cleared']);
      assert.equal(path, '/password/recovery/confirm'); assert.equal(options.method, 'POST');
      assert.deepEqual(JSON.parse(options.body), { token: TOKEN, new_password: 'new-safe-password' });
      return { async json() { return { ok: true, message: 'synthetic completion message' }; } };
    },
  });
  await submit({ preventDefault() {} });
  assert.equal(result.textContent, 'synthetic completion message');
  assert.equal(form.hidden, true); assert.equal(button.disabled, false);
  assert.deepEqual(events, ['fragment-cleared', 'reset']);
});
