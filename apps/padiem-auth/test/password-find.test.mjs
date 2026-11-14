// #7679 password find: the #7652 mailed proof, widened to a live account.
// A synthetic Chat stands behind the signed RPC; the registry, the session
// objects and the Worker are the real ones. No mail is sent and nothing
// leaves the process.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash, createHmac } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import { AuthState } from '../state.mjs';
import worker, { createApp, AuthStateObject, passwordIdentityFingerprint } from '../worker.mjs';
import { createSkinHarness, EN } from './skin-harness.mjs';

const ORIGIN = 'https://auth.padiem.net';
const EMAIL = 'owner@example.invalid';
const ACCOUNT = 'sub_existing';
const EPOCH = '2026-11-12T00:00:00+00:00';
const SECRET = 'synthetic-password-rpc-secret-32chars';
const IDENTITY_BYTES = new Uint8Array(32).fill(19);
const hash = value => createHash('sha256').update(value).digest('hex');
const USER = 'usr_' + hash(`password:${EMAIL}`).slice(0, 32);
const OBJECT = 'o'.repeat(43), SESSION = 's'.repeat(43);

function storage() {
  const db = new DatabaseSync(':memory:');
  return { sql: { exec(query, ...params) {
    const statement = db.prepare(query);
    if (statement.columns().length) { const rows = statement.all(...params); return { toArray: () => rows }; }
    statement.run(...params); return { toArray: () => [] };
  } }, transactionSync(fn) {
    db.exec('BEGIN');
    try { const value = fn(); db.exec('COMMIT'); return value; }
    catch (error) { db.exec('ROLLBACK'); throw error; }
  } };
}

// The synthetic Chat keeps what the real one keeps: the live credential, a
// ledger of hashed proofs and the mail it would have sent.
async function setup({ find = true, recovery = true, live = true, existing = true, deleted = false, google = false, blocked = false,
  products = ['b62', 'lovetree-4-0'], chatEpoch = EPOCH, limited = false, mailDown = false, defer } = {}) {
  const identityKey = await crypto.subtle.importKey('raw', IDENTITY_BYTES, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const objects = new Map(), calls = [], mails = [], proofs = new Map(), seen = new Set();
  let clock = 1000, queue = Promise.resolve(), failAction = '', gate = null, minted = 0;
  let credential = live ? { user_id: USER, password: 'old-password', epoch: chatEpoch } : null;
  const stateFor = id => { if (!objects.has(id)) objects.set(id, new AuthState({ storage: storage() })); return objects.get(id); };
  const rpcFetcher = async (address, options) => {
    if (gate) await gate;
    const path = new URL(address).pathname, action = path.split('/').at(-1);
    const bytes = Buffer.from(options.body), headers = options.headers;
    const expected = 'v2=' + createHmac('sha256', SECRET).update(Buffer.concat([
      Buffer.from(`v2\nPOST\n${path}\n${headers['x-padiem-service-at']}\n${headers['x-padiem-service-id']}\n`), bytes,
    ])).digest('hex');
    assert.equal(headers['x-padiem-service-proof'], expected);
    assert.ok(!seen.has(headers['x-padiem-service-id'])); seen.add(headers['x-padiem-service-id']);
    const data = JSON.parse(bytes.toString()); calls.push({ action, data });
    if (failAction === action) return Response.json({ error: { code: 'unavailable' } }, { status: 503 });
    if (action === 'status') {
      const available = !credential && !google;
      return Response.json({ ok: true, available, ...(find ? { present: Boolean(credential) } : {}) });
    }
    if (action === 'request') {
      const reset = data.mode === 'reset';
      if (reset && !find) return Response.json({ error: { code: 'invalid_request' } }, { status: 400 });
      const target = reset ? credential && credential.epoch === data.credential_epoch : data.account_id && !credential && !google;
      if (target && !limited) {
        const token = Buffer.from(hash(`token-${++minted}`), 'hex').toString('base64url');
        proofs.set(hash(token), { expires: clock + 900, consumed: false, reset, email: data.email, account_id: data.account_id, credential_epoch: data.credential_epoch });
        if (!mailDown) mails.push(token);
      }
      return Response.json({ ok: true });
    }
    const row = proofs.get(hash(data.token));
    const open = row && !row.consumed && row.expires > clock ? row : null;
    if (action === 'inspect') {
      if (open && data.new_password.length < 8) return Response.json({ error: { code: 'invalid_password' } }, { status: 400 });
      if (!open) return Response.json({ ok: false });
      const proof = { ok: true, email: open.email, account_id: open.account_id, credential_epoch: open.credential_epoch };
      const liveTarget = find && open.reset && credential && credential.epoch === open.credential_epoch;
      return Response.json(liveTarget ? { ...proof, mode: 'reset', product_user_id: credential.user_id } : proof);
    }
    if (action === 'complete') {
      const liveTarget = find && open && open.reset && credential && credential.epoch === open.credential_epoch;
      if (!liveTarget || open.account_id !== data.account_id || open.credential_epoch !== data.credential_epoch) {
        return Response.json({ error: { code: 'password_recovery_invalid' } }, { status: 400 });
      }
      open.consumed = true;
      for (const other of proofs.values()) if (other !== open && other.email === open.email) other.consumed = true;
      credential = { ...credential, password: data.new_password };
      return Response.json({ ok: true, product_user_id: credential.user_id, account_id: open.account_id, credential_epoch: open.credential_epoch });
    }
    throw new Error('unexpected synthetic route');
  };
  const state = { storage: storage(), blockConcurrencyWhile(fn) { const next = queue.then(fn); queue = next.catch(() => {}); return next; } };
  const registry = new AuthStateObject(state, {
    PADIEM_AUTH_EMAIL_RECOVERY_ENABLED: recovery, PADIEM_AUTH_PASSWORD_FIND_ENABLED: find,
    PADIEM_AUTH_PASSWORD_RPC_SECRET: SECRET, PADIEM_CHAT_PASSWORD_RPC_ORIGIN: 'https://chat.example.invalid',
    PADIEM_AUTH_IDENTITY_HMAC_KEY: Buffer.from(IDENTITY_BYTES).toString('base64url'),
    IDENTITY_AUTHORITY: { async list_active_product_links_for_subject() { return { ok: true, links: products.map(product_id => ({ product_id, product_user_id: USER, state: 'active' })) }; } },
  }, { recoveryFetcher: rpcFetcher, recoveryStateFor: stateFor });
  objects.set('google-account-registry', registry);
  const fingerprint = await passwordIdentityFingerprint(identityKey, EMAIL);
  if (existing) {
    registry.putAccount({ fingerprint: google ? 'google-fingerprint' : fingerprint, accountId: ACCOUNT, productUserId: USER, now: clock });
    if (!google) registry.recordPasswordCredentialEpoch({ fingerprint, epoch: EPOCH });
  }
  const session = stateFor(OBJECT);
  if (existing) {
    session.createSession({ id: SESSION, client: 'lovetree-4-0', subject: ACCOUNT, accountId: ACCOUNT, expires: 5000, digest: 'refresh-digest' });
    registry.indexAccountSession({ accountId: ACCOUNT, objectId: OBJECT, sessionId: SESSION, expires: 5000, now: clock });
  }
  if (deleted) registry.sql.exec('INSERT INTO identity_deletion_tombstone VALUES(?,?)', fingerprint, clock);
  if (blocked) registry.setAccountStatus({ accountId: ACCOUNT, blocked: true });
  const app = createApp({ clients: {}, identityKey, emailRecoveryEnabled: recovery, passwordFindEnabled: find, defer,
    passwordRpcSecret: SECRET, passwordRpcOrigin: 'https://chat.example.invalid', stateFor, fetcher: rpcFetcher, now: () => clock });
  const request = (email = EMAIL, headers = {}) => app.fetch(new Request(`${ORIGIN}/password/recovery/request`, { method: 'POST', headers: { 'cf-connecting-ip': '192.0.2.7', ...headers }, body: new URLSearchParams({ email }) }));
  const complete = (token, password = 'new-safe-password') => app.fetch(new Request(`${ORIGIN}/password/recovery/confirm`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ token, new_password: password }) }));
  const refreshAlive = () => Boolean(session.inspectRefresh({ id: SESSION, client: 'lovetree-4-0', digest: 'refresh-digest', now: clock }));
  return { app, request, complete, registry, session, stateFor, fingerprint, calls, mails, proofs, rpcFetcher, refreshAlive,
    credential: () => credential, time(value) { clock = value; }, fail(value) { failAction = value; },
    hold() { let open; gate = new Promise(resolve => { open = resolve; }); return () => { gate = null; open(); }; },
    recreate(epoch) { credential = { user_id: USER, password: 'recreated', epoch }; } };
}
const picture = async response => ({ status: response.status, headers: [...response.headers], body: await response.text() });

test('the request answer is byte-identical for a target, an unknown address, Google-only, deleted, blocked, re-created, over-limit and failed mail', async () => {
  const variants = {
    target: {}, unknown: { existing: false, live: false }, google: { google: true, live: false }, deleted: { deleted: true },
    blocked: { blocked: true }, recreated: { chatEpoch: '2026-11-13T09:00:00+00:00' }, unlinked: { products: [] },
    limited: { limited: true }, mailDown: { mailDown: true }, chatDown: { chatDown: true },
  };
  const answers = {};
  for (const [name, variant] of Object.entries(variants)) {
    const f = await setup(variant);
    if (variant.chatDown) f.fail('request');
    answers[name] = await picture(await f.request());
    const sent = f.calls.find(call => call.action === 'request');
    assert.equal(sent.data.source_digest.length, 43, name);
    assert.ok(!JSON.stringify(f.calls).includes('192.0.2.7'), name);
    const asked = ['target', 'limited', 'mailDown', 'chatDown', 'recreated'].includes(name);
    assert.equal(sent.data.mode, asked ? 'reset' : undefined, name);
    assert.equal(sent.data.account_id, asked ? ACCOUNT : null, name);
    assert.equal(f.mails.length, name === 'target' ? 1 : 0, name);
  }
  assert.equal(answers.target.status, 202);
  for (const [name, answer] of Object.entries(answers)) assert.deepEqual(answer, answers.target, name);
});

test('the answer leaves before any lookup or mail starts, for a target and for an unknown address alike', async () => {
  for (const variant of [{}, { existing: false, live: false }]) {
    const deferred = [];
    const f = await setup({ ...variant, defer: work => deferred.push(work) });
    const release = f.hold();
    const response = await f.request();
    assert.equal(response.status, 202);
    assert.equal(f.calls.length, 0, 'nothing was asked of Chat before the answer');
    assert.equal(deferred.length, 1);
    release();
    await Promise.all(deferred);
    assert.deepEqual(f.calls.map(call => call.action), ['status', 'request']);
    assert.equal(f.mails.length, variant.existing === false ? 0 : 1);
  }
});

test('a failure in the deferred work is contained and logged with a fixed word only', async () => {
  const deferred = [], lines = [];
  const f = await setup({ defer: work => deferred.push(work) });
  const original = console.error; console.error = line => lines.push(String(line));
  try {
    const response = await f.app.fetch(new Request(`${ORIGIN}/password/recovery/request`, { method: 'POST', headers: { 'content-length': '9999' }, body: 'x'.repeat(9999) }));
    assert.equal(response.status, 202);
    await Promise.all(deferred);
  } finally { console.error = original; }
  assert.deepEqual(lines, ['{"auth_stage":"email_recovery_request_unavailable"}']);
});

test('the mailed link changes the password of the same account and ends its sessions and refresh tokens', async () => {
  const f = await setup();
  await f.request();
  assert.equal(f.refreshAlive(), true);
  const before = f.registry.sql.exec('SELECT * FROM google_accounts').toArray();
  const response = await f.complete(f.mails[0]);
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.ok, true);
  assert.match(body.message, /비밀번호를 바꿨습니다/);
  assert.deepEqual(f.credential(), { user_id: USER, password: 'new-safe-password', epoch: EPOCH });
  assert.equal(f.refreshAlive(), false, 'the old refresh token no longer works');
  assert.equal(f.session.sql.exec('SELECT revoked FROM sessions').toArray()[0].revoked, 1);
  assert.deepEqual(f.registry.sql.exec('SELECT * FROM google_accounts').toArray(), before);
  assert.equal(f.registry.passwordCredentialEpoch({ fingerprint: f.fingerprint }), EPOCH);
  assert.equal(f.registry.passwordBindingRefused({ fingerprint: f.fingerprint, epoch: EPOCH }), false, 'the owner signs in with the new password');
  assert.equal(f.registry.sql.exec('SELECT * FROM account_deletion_locks').toArray().length, 0);
  assert.deepEqual(f.calls.map(call => call.action), ['status', 'request', 'inspect', 'status', 'complete']);
  assert.deepEqual(f.calls.at(-1).data, { token: f.mails[0], new_password: 'new-safe-password', account_id: ACCOUNT, credential_epoch: EPOCH });
});

test('sessions of another account recorded for the same Chat user end too', async () => {
  const f = await setup();
  f.registry.putAccount({ fingerprint: 'another-fingerprint', accountId: 'sub_other', productUserId: USER, now: 1000 });
  const other = f.stateFor('p'.repeat(43));
  other.createSession({ id: 'q'.repeat(43), client: 'b62', subject: 'sub_other', accountId: 'sub_other', expires: 5000, digest: 'other-digest' });
  f.registry.indexAccountSession({ accountId: 'sub_other', objectId: 'p'.repeat(43), sessionId: 'q'.repeat(43), expires: 5000, now: 1000 });
  await f.request();
  assert.equal((await f.complete(f.mails[0])).status, 200);
  assert.equal(other.sql.exec('SELECT revoked FROM sessions').toArray()[0].revoked, 1);
});

test('expired, reused, unknown and simultaneous submissions share one refusal and succeed once at most', async () => {
  const f = await setup();
  await f.request();
  const token = f.mails[0];
  const unknown = await picture(await f.complete('u'.repeat(43)));
  assert.equal(unknown.status, 400);
  f.time(1900);
  assert.deepEqual(await picture(await f.complete(token)), unknown, 'expired');
  f.time(1000);
  const pair = await Promise.all([f.complete(token), f.complete(token, 'second-safe-password')]);
  assert.deepEqual(pair.map(response => response.status).sort(), [200, 400]);
  assert.deepEqual(await picture(await f.complete(token)), unknown, 'reused');
  assert.equal(f.credential().password, 'new-safe-password');
});

test('a proof for another account, a changed binding, or a credential created again is refused before anything is touched', async () => {
  for (const tamper of ['account', 'recreated', 'blocked', 'deleted', 'unlinked']) {
    const f = await setup();
    await f.request();
    const token = f.mails[0], row = f.proofs.get(hash(token));
    if (tamper === 'account') row.account_id = 'sub_other';
    if (tamper === 'recreated') f.recreate('2026-11-13T09:00:00+00:00');
    if (tamper === 'blocked') f.registry.setAccountStatus({ accountId: ACCOUNT, blocked: true });
    if (tamper === 'deleted') f.registry.sql.exec('INSERT INTO identity_deletion_tombstone VALUES(?,?)', f.fingerprint, 1000);
    if (tamper === 'unlinked') f.registry.env.IDENTITY_AUTHORITY = { async list_active_product_links_for_subject() { return { ok: true, links: [] }; } };
    const response = await f.complete(token);
    assert.equal(response.status, 400, tamper);
    assert.equal((await response.json()).error, 'password_recovery_invalid', tamper);
    assert.equal(row.consumed, false, tamper);
    assert.equal(f.refreshAlive(), true, `${tamper}: no session was ended by the refused proof`);
    assert.notEqual(f.credential().password, 'new-safe-password', tamper);
    assert.ok(!f.calls.some(call => call.action === 'complete'), tamper);
  }
});

test('a session that cannot be ended, or a Chat failure, leaves the link usable and the password unchanged', async () => {
  const f = await setup();
  await f.request();
  const token = f.mails[0];
  const revoke = f.session.forceRevokeForAccountDeletion;
  f.session.forceRevokeForAccountDeletion = () => false;
  assert.equal((await f.complete(token)).status, 503);
  assert.equal(f.credential().password, 'old-password');
  assert.equal(f.proofs.get(hash(token)).consumed, false);
  assert.equal(f.registry.sql.exec('SELECT * FROM account_deletion_locks').toArray().length, 0);
  f.session.forceRevokeForAccountDeletion = revoke;
  f.fail('complete');
  assert.equal((await f.complete(token)).status, 503);
  assert.equal(f.credential().password, 'old-password');
  f.fail('');
  assert.equal((await f.complete(token)).status, 200);
});

test('a weak password is refused before any session ends', async () => {
  const f = await setup();
  await f.request();
  const response = await f.complete(f.mails[0], 'short');
  assert.equal(response.status, 400);
  assert.equal((await response.json()).error, 'password_recovery_password_invalid');
  assert.equal(f.refreshAlive(), true);
});

test('with password find off a live account is never asked for and a reset proof is refused', async () => {
  const f = await setup({ find: false });
  await f.request();
  assert.deepEqual(f.calls.map(call => call.action), ['status', 'request']);
  assert.deepEqual(Object.keys(f.calls[1].data).sort(), ['account_id', 'credential_epoch', 'email', 'source_digest']);
  assert.equal(f.calls[1].data.account_id, null);
  assert.equal(await f.registry.emailRecoveryCandidate({ fingerprint: f.fingerprint, now: 1000, mode: 'reset' }), null);
  // Even if Chat named a reset proof, the registry does not honour it.
  const token = 'r'.repeat(43);
  f.registry.recoveryFetcher = async (address, options) => {
    const action = new URL(address).pathname.split('/').at(-1);
    f.calls.push({ action, data: JSON.parse(Buffer.from(options.body).toString()) });
    return Response.json({ ok: true, email: EMAIL, account_id: ACCOUNT, credential_epoch: EPOCH, mode: 'reset', product_user_id: USER });
  };
  assert.equal((await f.complete(token)).status, 400);
  assert.equal(f.refreshAlive(), true);
  assert.ok(!f.calls.some(call => call.action === 'complete'));
  // An unknown mode is never a candidate, whatever the switches say.
  const on = await setup();
  assert.equal(await on.registry.emailRecoveryCandidate({ fingerprint: on.fingerprint, now: 1000, mode: 'other' }), null);
  assert.deepEqual(await on.registry.emailRecoveryCandidate({ fingerprint: on.fingerprint, now: 1000, mode: 'reset' }), { account_id: ACCOUNT, credential_epoch: EPOCH });
  assert.equal(await on.registry.emailRecoveryCandidate({ fingerprint: on.fingerprint, now: 1000 }), null, 'a live Chat link is not a restoration');
});

test('the token and the address stay out of every log line, registry row and server screen', async () => {
  const lines = [];
  const originals = [console.log, console.error];
  console.log = line => lines.push(String(line)); console.error = line => lines.push(String(line));
  let f, token, screens;
  try {
    f = await setup();
    screens = [await (await f.request()).text()];
    token = f.mails[0];
    screens.push(await (await f.app.fetch(new Request(`${ORIGIN}/password/recovery/confirm`))).text());
    screens.push(await (await f.complete(token)).text());
    screens.push(await (await f.complete(token)).text());
  } finally { [console.log, console.error] = originals; }
  const stored = JSON.stringify(['google_accounts', 'password_credential_epochs', 'client_assertions', 'auth_session_index', 'account_deletion_locks', 'account_chat_users']
    .map(table => f.registry.sql.exec(`SELECT * FROM ${table}`).toArray()));
  for (const text of [...lines, ...screens, stored]) {
    assert.ok(!text.includes(token));
    assert.ok(!text.includes(EMAIL));
  }
});

test('screens: the entry on the login form, the request page with the Google note, and both languages', async () => {
  const f = await setup();
  const page = async (path, headers = {}) => (await f.app.fetch(new Request(ORIGIN + path, { headers }))).text();
  const ko = await page('/password/recovery');
  assert.match(ko, /<h1>비밀번호 찾기<\/h1>/);
  assert.match(ko, /가입한 이메일을 입력하면 비밀번호를 새로 정할 수 있는 링크를 보내드립니다\./);
  assert.match(ko, /<p class="hint">Google로 가입한 계정은 비밀번호가 없습니다\. 로그인 화면에서 Google로 계속해 주세요\.<\/p>/);
  assert.match(ko, /<button type="submit">링크 받기<\/button>/);
  const en = await page('/password/recovery', EN);
  assert.match(en, /<h1>Reset your password<\/h1>/);
  assert.match(en, /An account created with Google has no password\./);
  const sent = await (await f.request()).text();
  assert.match(sent, /이 이메일로 가입한 계정이 있으면/);
  assert.match(sent, /15분 동안 한 번만/);
  assert.match(sent, /class="hint"/);
  const confirm = await page('/password/recovery/confirm');
  assert.match(confirm, /새 비밀번호 저장/);
  assert.doesNotMatch(confirm, /<p class="hint">/);
});

test('the login screens carry the entry inside the plain card and inside the brand skin', async () => {
  const off = await createSkinHarness();
  const on = await createSkinHarness({ emailRecoveryEnabled: true, passwordFindEnabled: true });
  for (const client of ['brandless', 'lovetree-4-0']) {
    for (const path of ['/login', '/signup']) {
      assert.doesNotMatch((await off.begin(path, client)).html, /password\/recovery/);
      const ko = (await on.begin(path, client)).html;
      assert.match(ko, /<a class="link alt-link" href="\/password\/recovery">비밀번호 찾기<\/a><\/main>/, `${client} ${path}`);
      assert.match((await on.begin(path, client, {}, EN)).html, /href="\/password\/recovery">Forgot your password\?<\/a><\/main>/);
    }
  }
});

test('the deployed entry point hands the request work to waitUntil only while password find is on', async () => {
  const signing = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const publicJwk = await crypto.subtle.exportKey('jwk', signing.publicKey); publicJwk.kid = 'auth';
  const privateJwk = await crypto.subtle.exportKey('jwk', signing.privateKey);
  const key = Buffer.from(new Uint8Array(32).fill(3)).toString('base64url');
  const objects = new Map();
  const env = find => ({
    PADIEM_AUTH_CLIENTS: '{}', PADIEM_AUTH_JWKS: JSON.stringify({ keys: [publicJwk] }),
    PADIEM_AUTH_ES256_PRIVATE_JWK: JSON.stringify(privateJwk), PADIEM_AUTH_IDENTITY_HMAC_KEY: key, PADIEM_AUTH_REFRESH_ENCRYPTION_KEY: key,
    GOOGLE_CLIENT_ID: 'google-client', GOOGLE_CLIENT_SECRET: 'synthetic', PADIEM_AUTH_SIGNING_KID: 'auth', IDENTITY_AUTHORITY: {},
    PADIEM_AUTH_PASSWORD_RPC_SECRET: SECRET, PADIEM_CHAT_PASSWORD_RPC_ORIGIN: 'https://chat.example.invalid',
    PADIEM_AUTH_EMAIL_RECOVERY_ENABLED: 'true', PADIEM_AUTH_PASSWORD_FIND_ENABLED: find ? 'true' : 'false',
    AUTH_STATE: { idFromName: name => name, get: name => ({ async fetch(address, init) {
      if (!objects.has(name)) objects.set(name, new AuthState({ storage: storage() }));
      const value = await objects.get(name)[new URL(address).pathname.slice(1)]?.(JSON.parse(init.body));
      return Response.json({ value: value ?? null });
    } }) },
  });
  const original = globalThis.fetch;
  const asked = [];
  globalThis.fetch = async address => { asked.push(new URL(address).pathname); return Response.json({ ok: true, available: false, present: false }); };
  try {
    for (const find of [true, false]) {
      asked.length = 0;
      const waiting = [];
      const send = () => new Request(`${ORIGIN}/password/recovery/request`, { method: 'POST', headers: { 'cf-connecting-ip': '192.0.2.7' }, body: new URLSearchParams({ email: EMAIL }) });
      const response = await worker.fetch(send(), env(find), { waitUntil: work => waiting.push(work) });
      assert.equal(response.status, 202);
      assert.equal(waiting.length, find ? 1 : 0, `find ${find}`);
      await Promise.all(waiting);
      assert.deepEqual(asked, ['/internal/password-recovery/status', '/internal/password-recovery/request']);
    }
  } finally { globalThis.fetch = original; }
});
