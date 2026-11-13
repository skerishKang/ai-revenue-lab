// Synthetic integration fixture for password find (#7679): the real auth
// registry and Worker in front of a local migrated Chat app with a live
// credential. No mail is sent; the bridge exposes the fake mailbox.
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { AuthState } from '../../../padiem-auth/state.mjs';
import { AuthStateObject, createApp, passwordIdentityFingerprint } from '../../../padiem-auth/worker.mjs';

const [port, scenario] = process.argv.slice(2);
const local = `http://127.0.0.1:${port}`;
const email = 'returning@example.test', account = 'sub_existing_account_7606';
const password = 'new-mail-proven-password-7606';
const secret = 'email-recovery-rpc-test-secret-00000000';
const keyBytes = new Uint8Array(32).fill(42);
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

const chat = async path => (await fetch(local + path)).json();
const before = await chat('/__test__/state');
const user = before.user_id, credentialEpoch = before.created_at;
let authorityCalls = 0, queue = Promise.resolve();
const identityKey = await crypto.subtle.importKey('raw', keyBytes, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
const objects = new Map();
const stateFor = id => objects.get(id);
const fetcher = (address, options) => fetch(local + new URL(address).pathname, options);
const registry = new AuthStateObject({ storage: storage(), blockConcurrencyWhile(fn) {
  const next = queue.then(fn); queue = next.catch(() => {}); return next;
} }, {
  PADIEM_AUTH_EMAIL_RECOVERY_ENABLED: 'true', PADIEM_AUTH_PASSWORD_FIND_ENABLED: 'true',
  PADIEM_AUTH_PASSWORD_RPC_SECRET: secret,
  PADIEM_CHAT_PASSWORD_RPC_ORIGIN: 'https://chat.example.test',
  PADIEM_AUTH_IDENTITY_HMAC_KEY: Buffer.from(keyBytes).toString('base64url'),
  IDENTITY_AUTHORITY: {
    async list_active_product_links_for_subject({ canonical_subject_id }) {
      assert.equal(canonical_subject_id, account);
      return { ok: true, links: [{ product_id: 'b62', product_user_id: user, state: 'active' }] };
    },
    async resolve_or_create_product_link(input) {
      authorityCalls++;
      assert.equal(input.expected_canonical_subject_id, account);
      assert.equal(input.product_user_id, user);
      assert.equal(input.auth_provider, 'password');
      return { ok: true, link: { state: 'active', product_id: 'b62', product_user_id: user, canonical_subject_id: account } };
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
session.createSession({ id: 's'.repeat(43), client: 'lovetree-4-0', subject: account, accountId: account, expires: now + 900, digest: 'synthetic-refresh' });
registry.indexAccountSession({ accountId: account, objectId: 'o'.repeat(43), sessionId: 's'.repeat(43), expires: now + 900, now });
const deferred = [];
const app = createApp({ clients: {}, identityKey, stateFor, fetcher, emailRecoveryEnabled: true, passwordFindEnabled: true,
  defer: work => deferred.push(work), passwordRpcSecret: secret, passwordRpcOrigin: 'https://chat.example.test' });
const request = address => app.fetch(new Request('https://auth.padiem.net/password/recovery/request', {
  method: 'POST', headers: { 'cf-connecting-ip': '192.0.2.79' }, body: new URLSearchParams({ email: address }),
}));
// The answer comes first; the lookup and the mail run after it. The two
// requests share a source address, so the first is settled before the second.
const target = await request(email);
await Promise.all(deferred);
const unknown = await request('unknown@example.test');
await Promise.all(deferred);
assert.equal(target.status, 202); assert.equal(unknown.status, target.status);
assert.equal(await target.text(), await unknown.text());
const { token, count } = await chat('/__test__/mailbox');
assert.equal(count, 1, 'only the live address was mailed');
const complete = () => app.fetch(new Request('https://auth.padiem.net/password/recovery/confirm', {
  method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ token, new_password: password }),
}));
const alive = () => Boolean(session.inspectRefresh({ id: 's'.repeat(43), client: 'lovetree-4-0', digest: 'synthetic-refresh', now }));
assert.equal(alive(), true);
let firstStatus;
if (scenario === 'chat_sessions_stuck') {
  // Chat cannot end its own sessions: nothing is stored and the link stays open.
  firstStatus = (await complete()).status;
  assert.equal(firstStatus, 503);
  const state = await chat('/__test__/state');
  assert.equal(state.changed, false); assert.equal(state.tokens, 1);
  await fetch(local + '/__test__/allow-sessions', { method: 'POST' });
}
const statuses = (await Promise.all([complete(), complete()])).map(r => r.status).sort();
assert.deepEqual(statuses, [200, 400]);
assert.equal(alive(), false, 'the old refresh token is dead');
assert.equal(registry.sql.exec('SELECT * FROM account_deletion_locks').toArray().length, 0);
const after = await chat('/__test__/state');
assert.equal(after.users, 1); assert.equal(after.user_id, user); assert.equal(after.created_at, credentialEpoch);
assert.equal(after.changed, true); assert.equal(after.tokens, 0);
// The owner signs in with the new password and lands on the same account.
const linked = await registry.resolveAccount({ fingerprint, productId: 'b62', userId: user,
  subject: email, provider: 'password', credentialEpoch, register: false });
assert.equal(linked.account_id, account); assert.equal(authorityCalls, 1);
assert.equal(registry.sql.exec('SELECT * FROM google_accounts').toArray().length, 1);
process.stdout.write(JSON.stringify({ same_account: true, sessions_revoked: true, statuses, first_status: firstStatus ?? null, scenario }));
