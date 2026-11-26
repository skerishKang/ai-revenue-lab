import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac, randomUUID } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { AuthState } from '../../padiem-auth/state.mjs';
import { AuthStateObject } from '../../padiem-auth/worker.mjs';
import { signStateRpc } from '../../padiem-auth/state-rpc.mjs';
import { createStateService } from '../server.mjs';
import { openStateDatabase, sqliteAdapter, transactionSync } from '../sqlite.mjs';

const secret = 'synthetic-state-service-secret-at-least-32-bytes';
const objectName = 'O'.repeat(43);
const epoch = 1000;

function authorityEnv() {
  return {
    PADIEM_AUTH_EMAIL_RECOVERY_ENABLED: true,
    PADIEM_AUTH_EMAIL_CONFIRMATION_ENABLED: true,
    IDENTITY_AUTHORITY: {
      async resolve_or_create_product_link(input) {
        const accountId = input.product_user_id === 'usr_new' ? 'sub_resolved_new' : input.product_user_id === 'usr_pwd' ? 'sub_password' : 'sub_resolved';
        return { ok: true, link: { state: 'active', product_id: input.product_id, product_user_id: input.product_user_id, canonical_subject_id: accountId } };
      },
      async resolve_or_create_identity_subject() {
        return { ok: true, canonical_subject_id: 'sub_resolved', account_created_at: 900, already_registered: false };
      },
      async list_active_product_links_for_subject(input) {
        return { ok: true, links: input.canonical_subject_id === 'sub_password' ? [{ product_id: 'lovetree-4-0', product_user_id: 'usr_pwd', state: 'active' }] : [] };
      },
    },
  };
}

async function startService(t, { database = openStateDatabase(':memory:'), env = authorityEnv(), now = () => epoch } = {}) {
  const service = createStateService({ database, secret, env, now });
  await new Promise((resolve, reject) => {
    service.server.once('error', reject);
    service.server.listen(0, 'localhost', resolve);
  });
  const origin = `http://localhost:${service.server.address().port}`;
  t.after(async () => {
    await new Promise(resolve => service.server.close(resolve));
    database.close();
  });
  const signed = async (method, name, args, { at = now(), nonce = randomUUID(), signingSecret = secret } = {}) => {
    const path = `/rpc/${method}`;
    const body = Buffer.from(JSON.stringify({ name, args }));
    const headers = await signStateRpc({ secret: signingSecret, path, at, nonce, body });
    return { path, init: { method: 'POST', headers, body } };
  };
  const call = async (method, name, args, options) => {
    const request = await signed(method, name, args, options);
    return fetch(origin + request.path, request.init);
  };
  return { service, stateFor: service.stateFor, database, origin, signed, call };
}

function startDoRuntime(t, env = authorityEnv()) {
  const objects = new Map();
  const stateFor = (name) => {
    if (!objects.has(name)) {
      const database = new DatabaseSync(':memory:');
      let queue = Promise.resolve();
      const storage = {
        id: name,
        database,
        sql: sqliteAdapter(database),
        transactionSync(operation) { return transactionSync(database, operation); },
        blockConcurrencyWhile(operation) { const next = queue.then(operation); queue = next.catch(() => {}); return next; },
        async setAlarm() {},
      };
      const state = { storage, blockConcurrencyWhile(operation) { return storage.blockConcurrencyWhile(operation); } };
      objects.set(name, new AuthStateObject(state, env, { recoveryStateFor: stateFor }));
    }
    return objects.get(name);
  };
  t.after(() => { for (const object of objects.values()) object.storage.database.close(); });
  return {
    stateFor,
    async invoke(name, method, args) {
      const response = await stateFor(name).fetch(new Request(`https://internal/${method}`, { method: 'POST', body: JSON.stringify(args) }));
      return { status: response.status, body: await response.json() };
    },
  };
}

async function compare(doRuntime, service, method, name, args) {
  const expected = await doRuntime.invoke(name, method, args);
  const response = await service.call(method, name, args);
  const actual = { status: response.status, body: await response.json() };
  assert.deepEqual(actual, expected, method);
  return actual.body.value;
}

test('COM2 HTTP responses match the Durable Object implementation across the state contract', async t => {
  const service = await startService(t);
  const durable = startDoRuntime(t);
  const login = {
    stateDigest: 'synthetic-state', browserDigest: 'synthetic-browser', client: 'b62',
    redirect: 'https://client.example.invalid/callback', serviceState: 'synthetic-service-state',
    serviceChallenge: 'synthetic-challenge', googleNonce: 'synthetic-google-nonce',
    googleVerifier: 'synthetic-verifier', expires: 1600,
  };
  await compare(durable, service, 'createLogin', objectName, login);
  await compare(durable, service, 'consumeLogin', objectName, { stateDigest: login.stateDigest, browserDigest: login.browserDigest, now: epoch });
  await compare(durable, service, 'beginPasswordAttempt', objectName, { stateDigest: login.stateDigest, browserDigest: login.browserDigest, now: epoch });

  const code = { digest: 'synthetic-code', client: 'b62', redirect: login.redirect, challenge: login.serviceChallenge, subject: 'sub_resolved', accountId: 'sub_resolved', expires: 1060 };
  await compare(durable, service, 'createCode', objectName, code);
  await compare(durable, service, 'createCode', objectName, { ...code, digest: 'synthetic-profile-code', encryptedProfile: 'synthetic-ciphertext' });
  await compare(durable, service, 'exchangeCode', objectName, {
    codeDigest: 'synthetic-profile-code', client: code.client, redirect: code.redirect, challenge: code.challenge,
    now: epoch, id: 'synthetic-session', expires: 3000, refreshDigest: 'synthetic-refresh',
  });
  await compare(durable, service, 'inspectRefresh', objectName, { id: 'synthetic-session', client: code.client, digest: 'synthetic-refresh', now: epoch });
  await compare(durable, service, 'rotate', objectName, { id: 'synthetic-session', client: code.client, digest: 'synthetic-refresh', replacement: 'synthetic-refresh-2', encryptedResult: 'synthetic-encrypted-result', now: epoch });
  await compare(durable, service, 'rotate', objectName, { id: 'synthetic-session', client: code.client, digest: 'synthetic-refresh', replacement: 'synthetic-other', encryptedResult: 'synthetic-other-result', now: epoch + 1 });

  await compare(durable, service, 'claimAssertion', 'client-assertion-replay', { key: 'synthetic-jti', expires: 1100, now: epoch });
  await compare(durable, service, 'claimAssertion', 'client-assertion-replay', { key: 'synthetic-jti', expires: 1100, now: epoch });
  await compare(durable, service, 'loginFailureBudget', 'password-login-gate', { source: 'synthetic-source', day: 1, charge: true });
  await compare(durable, service, 'loginFailureBudget', 'password-login-gate', { source: 'synthetic-source', day: 1 });

  const age = { handleDigest: 'synthetic-handle', browserDigest: 'synthetic-browser', payload: 'synthetic-payload', expires: 1600, now: epoch };
  await compare(durable, service, 'createAgeConfirmation', 'google-age-confirmation', age);
  await compare(durable, service, 'readAgeConfirmation', 'google-age-confirmation', age);
  await compare(durable, service, 'claimAgeConfirmation', 'google-age-confirmation', age);
  await compare(durable, service, 'recordAgeConfirmationResult', 'google-age-confirmation', { ...age, result: 'synthetic-location', expires: 1060 });
  await compare(durable, service, 'readAgeConfirmationResult', 'google-age-confirmation', age);
  await compare(durable, service, 'consumeAgeConfirmation', 'google-age-confirmation', age);
  await compare(durable, service, 'resetLoginFailureBudget', 'password-login-gate', { source: 'synthetic-source', day: 1 });

  await compare(durable, service, 'putAccount', 'google-account-registry', { fingerprint: 'synthetic-fingerprint', accountId: 'sub_resolved', productUserId: 'usr_resolved', accountCreatedAt: 900, ageConfirmedAt: 950, now: epoch });
  await compare(durable, service, 'accountById', 'google-account-registry', 'sub_resolved');
  await compare(durable, service, 'accountCreatedAt', 'google-account-registry', { accountId: 'sub_resolved' });
  await compare(durable, service, 'ageConfirmedAt', 'google-account-registry', { fingerprint: 'synthetic-fingerprint' });
  await compare(durable, service, 'indexAccountSession', 'google-account-registry', { accountId: 'sub_resolved', objectId: objectName, sessionId: 'synthetic-session', expires: 3000, now: epoch });
  await compare(durable, service, 'indexedAccountSessions', 'google-account-registry', { accountId: 'sub_resolved' });
  await compare(durable, service, 'accountIdsForChatUser', 'google-account-registry', { productUserId: 'usr_resolved' });
  await compare(durable, service, 'resolveAccount', 'google-account-registry', { fingerprint: 'synthetic-new-fingerprint', productId: 'b62', userId: 'usr_new', subject: 'synthetic-subject', now: epoch });
  await compare(durable, service, 'resolveAccount', 'google-account-registry', { fingerprint: 'synthetic-password-fingerprint', productId: 'b62', userId: 'usr_pwd', subject: 'user@example.invalid', provider: 'password', credentialEpoch: '2026-11-26T00:00:00+00:00', now: epoch });
  await compare(durable, service, 'passwordBindingRefused', 'google-account-registry', { fingerprint: 'synthetic-password-fingerprint', epoch: '2026-11-26T00:00:00+00:00' });
  await compare(durable, service, 'passwordBindingRefused', 'google-account-registry', { fingerprint: 'synthetic-password-fingerprint', epoch: '2026-11-26T00:00:01+00:00' });
  await compare(durable, service, 'reserveEmailConfirmation', 'google-account-registry', { fingerprint: 'synthetic-password-fingerprint', epoch: '2026-11-26T00:00:00+00:00', sourceDigest: 'a'.repeat(43), now: epoch });
  await compare(durable, service, 'recordEmailConfirmationToken', 'google-account-registry', { fingerprint: 'synthetic-password-fingerprint', epoch: '2026-11-26T00:00:00+00:00', tokenDigest: 'b'.repeat(64), expires: epoch + 7000, now: epoch });
  await compare(durable, service, 'completeEmailConfirmation', 'google-account-registry', { tokenDigest: 'b'.repeat(64), now: epoch });
  await compare(durable, service, 'passwordEmailConfirmed', 'google-account-registry', { fingerprint: 'synthetic-password-fingerprint', epoch: '2026-11-26T00:00:00+00:00' });
  await compare(durable, service, 'emailRecoveryCandidate', 'google-account-registry', { fingerprint: 'synthetic-password-fingerprint', now: epoch });
  await compare(durable, service, 'recordAccountChatUsers', 'google-account-registry', { accountId: 'sub_password', productUserIds: ['usr_pwd_extra'] });
  await compare(durable, service, 'setAccountStatus', 'google-account-registry', { accountId: 'sub_resolved_new', blocked: true });
  await compare(durable, service, 'forceRevokeForAccountDeletion', objectName, { id: 'synthetic-session' });
  await compare(durable, service, 'revoke', objectName, { id: 'synthetic-session', client: code.client, digest: 'synthetic-refresh', now: epoch });
  await compare(durable, service, 'beginAccountDeletion', 'google-account-registry', { accountId: 'sub_resolved', lockToken: 'synthetic-lock', now: epoch });
  await compare(durable, service, 'finalizeAccountDeletion', 'google-account-registry', { accountId: 'sub_resolved', accountIdHash: 'a'.repeat(64), lockToken: 'synthetic-lock', now: epoch });
  await compare(durable, service, 'identityIsDeleted', 'google-account-registry', { fingerprint: 'synthetic-fingerprint' });
  await compare(durable, service, 'pendingChatAccountDeletions', 'google-account-registry', {});
  await compare(durable, service, 'completeChatAccountDeletion', 'google-account-registry', { productUserId: 'usr_resolved' });
  await compare(durable, service, 'clearIdentityDeletion', 'google-account-registry', { fingerprint: 'synthetic-fingerprint' });
  await compare(durable, service, 'pruneAccountDeletionAudit', 'google-account-registry', { now: epoch });
  await compare(durable, service, 'nextAccountDeletionAuditExpiry', 'google-account-registry', {});
});

test('every AuthState method is present on the COM2 object without a second SQL implementation', async t => {
  const service = await startService(t);
  const local = service.stateFor(objectName);
  for (const method of Object.getOwnPropertyNames(AuthState.prototype)) {
    if (method === 'constructor') continue;
    assert.equal(typeof local[method], 'function', method);
  }
});

test('a fresh logical object initializes only its required schema group', () => {
  const service = createStateService({ secret, now: () => epoch });
  service.stateFor('client-assertion-replay').claimAssertion({ key: 'synthetic-jti', expires: 1100, now: epoch });
  const tables = service.database.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name<>'auth_state_nonces' ORDER BY name").all().map(row => row.name);
  assert.deepEqual(tables, ['client_assertions']);
  service.database.close();
});

test('same one-time code has exactly one winner under concurrent HTTP requests', async t => {
  const service = await startService(t);
  const code = { digest: 'race-code', client: 'b62', redirect: 'https://client.example.invalid/callback', challenge: 'challenge', subject: 'sub_race', accountId: 'sub_race', expires: 1060 };
  await service.call('createCode', objectName, code);
  const input = { codeDigest: code.digest, client: code.client, redirect: code.redirect, challenge: code.challenge, now: epoch };
  const responses = await Promise.all([
    service.call('exchangeCode', objectName, { ...input, id: 'race-session-one', expires: 3000, refreshDigest: 'race-refresh-one' }),
    service.call('exchangeCode', objectName, { ...input, id: 'race-session-two', expires: 3000, refreshDigest: 'race-refresh-two' }),
  ]);
  const values = await Promise.all(responses.map(response => response.json()));
  assert.equal(values.filter(value => value.value === false).length, 1);
  assert.equal(values.filter(value => value.value && value.value.subject === 'sub_race').length, 1);
});

test('concurrent refresh rotation keeps the single-winner 30-second retry contract', async t => {
  const service = await startService(t);
  const code = { digest: 'refresh-seed-code', client: 'b62', redirect: 'https://client.example.invalid/callback', challenge: 'challenge', subject: 'sub_race', accountId: 'sub_race', expires: 1060 };
  await service.call('createCode', objectName, code);
  await service.call('exchangeCode', objectName, { codeDigest: code.digest, client: code.client, redirect: code.redirect, challenge: code.challenge, now: epoch, id: 'race-session', expires: 3000, refreshDigest: 'race-refresh' });
  const input = { id: 'race-session', client: 'b62', digest: 'race-refresh', now: epoch };
  const responses = await Promise.all([
    service.call('rotate', objectName, { ...input, replacement: 'race-refresh-2', encryptedResult: 'race-result' }),
    service.call('rotate', objectName, { ...input, replacement: 'race-refresh-3', encryptedResult: 'other-result' }),
  ]);
  const values = await Promise.all(responses.map(response => response.json()));
  assert.equal(values[0].value.ok, true);
  assert.equal(values[1].value.ok, true);
  assert.deepEqual(values[0].value, values[1].value);
  assert.equal(values[0].value.accountId, 'sub_race');
  assert.ok(['race-result', 'other-result'].includes(values[0].value.encryptedResult));
});

test('expired code, login and session are refused with the same null or false results', async t => {
  const service = await startService(t);
  const code = { digest: 'expired-code', client: 'b62', redirect: 'https://client.example.invalid/callback', challenge: 'challenge', subject: 'sub_expired', accountId: 'sub_expired', expires: 1000 };
  await service.call('createCode', objectName, code);
  assert.equal((await (await service.call('exchangeCode', objectName, { codeDigest: code.digest, client: code.client, redirect: code.redirect, challenge: code.challenge, now: 1000, id: 'expired-code-session', expires: 2000, refreshDigest: 'expired-code-refresh' })).json()).value, false);
  const login = { stateDigest: 'expired-state', browserDigest: 'browser', client: 'b62', redirect: code.redirect, serviceState: 'service', serviceChallenge: 'challenge', googleNonce: 'nonce', googleVerifier: 'verifier', expires: 1000 };
  await service.call('createLogin', objectName, login);
  assert.equal((await (await service.call('consumeLogin', objectName, { stateDigest: login.stateDigest, browserDigest: login.browserDigest, now: 1000 })).json()).value, null);
  service.stateFor(objectName).createSession({ id: 'expired-session', client: 'b62', subject: 'sub_expired', accountId: 'sub_expired', expires: 1000, digest: 'expired-refresh' });
  assert.deepEqual((await (await service.call('rotate', objectName, { id: 'expired-session', client: 'b62', digest: 'expired-refresh', replacement: 'next', encryptedResult: 'result', now: 1000 })).json()).value, { ok: false });
});

test('replay, bad signature, body tampering, stale time and malformed nonce are rejected without mutation', async t => {
  const service = await startService(t);
  const request = await service.signed('createCode', objectName, { digest: 'secured-code', client: 'b62', redirect: 'https://client.example.invalid/callback', challenge: 'challenge', subject: 'sub_secure', accountId: 'sub_secure', expires: 1060 });
  assert.equal((await fetch(service.origin + request.path, request.init)).status, 200);
  assert.equal((await fetch(service.origin + request.path, request.init)).status, 409);

  const badSignature = await service.signed('createCode', objectName, { digest: 'bad-signature' }, { signingSecret: 'synthetic-wrong-secret-at-least-32-bytes' });
  assert.equal((await fetch(service.origin + badSignature.path, badSignature.init)).status, 401);
  const tampered = await service.signed('createCode', objectName, { digest: 'tampered-code' });
  tampered.init.body = Buffer.concat([tampered.init.body, Buffer.from(' ')]);
  assert.equal((await fetch(service.origin + tampered.path, tampered.init)).status, 401);
  const stale = await service.signed('createCode', objectName, { digest: 'stale-code' }, { at: epoch - 301 });
  assert.equal((await fetch(service.origin + stale.path, stale.init)).status, 401);
  const future = await service.signed('createCode', objectName, { digest: 'future-code' }, { at: epoch + 301 });
  assert.equal((await fetch(service.origin + future.path, future.init)).status, 401);
  const malformed = await service.signed('createCode', objectName, { digest: 'nonce-code' }, { nonce: 'not-a-uuid' }).catch(error => error);
  assert.ok(malformed instanceof Error);
  const malformedPath = '/rpc/createCode';
  const malformedBody = Buffer.from(JSON.stringify({ name: objectName, args: { digest: 'malformed-nonce-code' } }));
  const malformedNonce = 'not-a-uuid';
  const malformedProof = 'v1=' + createHmac('sha256', secret).update(Buffer.concat([
    Buffer.from(`v1\nPOST\n${malformedPath}\n${epoch}\n${malformedNonce}\n`), malformedBody,
  ])).digest('hex');
  const malformedResponse = await fetch(service.origin + malformedPath, {
    method: 'POST', body: malformedBody,
    headers: {
      'content-type': 'application/json', 'x-padiem-auth-at': String(epoch),
      'x-padiem-auth-nonce': malformedNonce, 'x-padiem-auth-proof': malformedProof,
    },
  });
  assert.equal(malformedResponse.status, 401);

  const rows = service.database.prepare('SELECT digest FROM codes ORDER BY digest').all().map(row => row.digest);
  assert.deepEqual(rows, ['secured-code']);
});

test('maintenance removes expired state and WAL is enabled on a file database', async t => {
  const directory = mkdtempSync(join(tmpdir(), 'auth-state-'));
  const path = join(directory, 'state.sqlite');
  const database = openStateDatabase(path);
  t.after(() => { database.close(); rmSync(directory, { recursive: true, force: true }); });
  const service = await createStateService({ database, secret, now: () => epoch });
  assert.equal(database.prepare('PRAGMA journal_mode').get().journal_mode, 'wal');
  service.stateFor(objectName).createCode({ digest: 'expired', client: 'b62', redirect: 'https://client.example.invalid/callback', challenge: 'challenge', subject: 'sub', accountId: 'sub', expires: epoch });
  service.stateFor(objectName).createSession({ id: 'expired', client: 'b62', subject: 'sub', accountId: 'sub', expires: epoch, digest: 'refresh' });
  service.stateFor('google-account-registry').putAccount({ fingerprint: 'fp', accountId: 'sub', now: epoch });
  service.stateFor('google-account-registry').indexAccountSession({ accountId: 'sub', objectId: objectName, sessionId: 'expired', expires: epoch, now: epoch });
  const originalNow = Date.now;
  Date.now = () => (epoch + 1000) * 1000;
  try { service.maintenance(); } finally { Date.now = originalNow; }
  assert.equal(service.database.prepare('SELECT COUNT(*) AS n FROM codes').get().n, 0);
  assert.equal(service.database.prepare('SELECT COUNT(*) AS n FROM sessions').get().n, 0);
  assert.equal(service.database.prepare('SELECT COUNT(*) AS n FROM refresh_tokens').get().n, 0);
  assert.equal(service.database.prepare('SELECT COUNT(*) AS n FROM auth_session_index').get().n, 0);
});
