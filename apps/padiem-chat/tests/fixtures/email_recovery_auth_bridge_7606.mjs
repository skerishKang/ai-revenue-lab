// Synthetic integration fixture: real auth SQL and a local migrated Chat app.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import { AuthState } from '../../../padiem-auth/state.mjs';
import { AuthStateObject, createApp, passwordIdentityFingerprint } from '../../../padiem-auth/worker.mjs';

const [port, scenario] = process.argv.slice(2);
const local = `http://127.0.0.1:${port}`;
const email = 'returning@example.test', account = 'sub_existing_account_7606';
const credentialEpoch = '2026-10-01T10:00:00+00:00';
const password = 'new-mail-proven-password-7606';
const secret = 'email-recovery-rpc-test-secret-00000000';
const keyBytes = new Uint8Array(32).fill(42);
const user = 'usr_' + createHash('sha256').update(`password:${email}`).digest('hex').slice(0, 32);
console.log = () => {}; // Product diagnostics are not the fixture's JSON result.

function storage() {
  const db = new DatabaseSync(':memory:');
  return { sql: { exec(sql, ...args) {
    const stmt = db.prepare(sql);
    if (stmt.columns().length) { const rows = stmt.all(...args); return { toArray: () => rows }; }
    stmt.run(...args); return { toArray: () => [] };
  } }, transactionSync(fn) {
    db.exec('BEGIN');
    try { const result = fn(); db.exec('COMMIT'); return result; }
    catch (error) { db.exec('ROLLBACK'); throw error; }
  } };
}

let lost = false, authorityCalls = 0, restoredUser = '', queue = Promise.resolve();
const identityKey = await crypto.subtle.importKey('raw', keyBytes, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
const objects = new Map();
const stateFor = id => objects.get(id);
const fetcher = async (address, options) => {
  const path = new URL(address).pathname;
  const response = await fetch(local + path, options);
  if (scenario === 'response_lost' && path.endsWith('/complete') && response.status === 200 && !lost) {
    lost = true;
    await response.arrayBuffer();
    throw new Error('synthetic_response_lost_after_commit');
  }
  return response;
};
const registry = new AuthStateObject({ storage: storage(), blockConcurrencyWhile(fn) {
  const next = queue.then(fn); queue = next.catch(() => {}); return next;
} }, {
  PADIEM_AUTH_EMAIL_RECOVERY_ENABLED: 'true',
  PADIEM_AUTH_PASSWORD_RPC_SECRET: secret,
  PADIEM_CHAT_PASSWORD_RPC_ORIGIN: 'https://chat.example.test',
  PADIEM_AUTH_IDENTITY_HMAC_KEY: Buffer.from(keyBytes).toString('base64url'),
  IDENTITY_AUTHORITY: {
    async list_active_product_links_for_subject({ canonical_subject_id }) {
      assert.equal(canonical_subject_id, account);
      return { ok: true, links: [{ product_id: 'other-product', product_user_id: 'other-user', state: 'active' }] };
    },
    async resolve_or_create_product_link(input) {
      authorityCalls++;
      assert.equal(input.expected_canonical_subject_id, account);
      assert.equal(input.product_user_id, restoredUser);
      assert.equal(input.auth_provider, 'password');
      return { ok: true, link: { state: 'active', product_id: 'b62', product_user_id: restoredUser, canonical_subject_id: account } };
    },
  },
}, { recoveryFetcher: fetcher, recoveryStateFor: stateFor });
objects.set('google-account-registry', registry);
const fingerprint = await passwordIdentityFingerprint(identityKey, email);
registry.putAccount({ fingerprint, accountId: account, productUserId: user });
registry.recordPasswordCredentialEpoch({ fingerprint, epoch: credentialEpoch });
const session = new AuthState({ storage: storage() });
objects.set('o'.repeat(43), session);
const now = Math.floor(Date.now() / 1000);
session.createSession({ id: 's'.repeat(43), client: 'other-product', subject: account, accountId: account, expires: now + 900, digest: 'synthetic-refresh' });
registry.indexAccountSession({ accountId: account, objectId: 'o'.repeat(43), sessionId: 's'.repeat(43), expires: now + 900, now });
const app = createApp({ clients: {}, identityKey, stateFor, fetcher, emailRecoveryEnabled: true,
  passwordRpcSecret: secret, passwordRpcOrigin: 'https://chat.example.test' });
const request = address => app.fetch(new Request('https://auth.padiem.net/password/recovery/request', {
  method: 'POST', headers: { 'cf-connecting-ip': '192.0.2.76' }, body: new URLSearchParams({ email: address }),
}));
const target = await request(email), unknown = await request('unknown@example.test');
assert.equal(target.status, 202); assert.equal(unknown.status, target.status);
assert.equal(await target.text(), await unknown.text());
const { token } = await (await fetch(local + '/__test__/mailbox')).json();
const complete = () => app.fetch(new Request('https://auth.padiem.net/password/recovery/confirm', {
  method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ token, new_password: password }),
}));
let firstStatus;
if (scenario === 'rollback' || scenario === 'response_lost') {
  firstStatus = (await complete()).status;
  assert.equal(firstStatus, 503);
  const state = await (await fetch(local + '/__test__/state')).json();
  assert.equal(state.users, scenario === 'rollback' ? 0 : 1);
  assert.equal(state.consumed, scenario === 'rollback' ? 0 : 1);
  if (scenario === 'rollback') await fetch(local + '/__test__/allow-store', { method: 'POST' });
}
let statuses;
if (scenario !== 'response_lost') {
  statuses = (await Promise.all([complete(), complete()])).map(r => r.status).sort();
  assert.deepEqual(statuses, [200, 400]);
} else {
  assert.equal((await complete()).status, 400);
}
assert.equal(session.sql.exec('SELECT revoked FROM sessions').toArray()[0].revoked, 1);
assert.equal(registry.sql.exec('SELECT * FROM google_accounts').toArray().length, 1);
assert.equal(registry.passwordBindingRefused({ fingerprint, epoch: 'new-unproven-generation' }), true);
const finalState = await (await fetch(local + '/__test__/state')).json();
assert.equal(finalState.users, 1); assert.equal(finalState.credentials, 1); assert.equal(finalState.consumed, 1);
restoredUser = finalState.user_id;
assert.match(restoredUser, /^usr_[0-9a-f]{32}$/);
assert.notEqual(restoredUser, user, 'withdrawn local identity is never resurrected');
const linked = await registry.resolveAccount({ fingerprint, productId: 'b62', userId: restoredUser,
  subject: email, provider: 'password', credentialEpoch, register: false });
assert.equal(linked.account_id, account); assert.equal(authorityCalls, 1);
assert.equal(registry.sql.exec('SELECT * FROM google_accounts').toArray().length, 1);
process.stdout.write(JSON.stringify({ same_account: true, no_new_account: true, sessions_revoked: true,
  statuses, first_status: firstStatus, scenario }));
