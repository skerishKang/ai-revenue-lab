import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { AuthStateObject } from '../worker.mjs';

function storage() {
  const db = new DatabaseSync(':memory:');
  return {
    sql: {
      exec(q, ...p) {
        const stmt = db.prepare(q);
        if (stmt.columns().length) return { toArray: () => stmt.all(...p) };
        stmt.run(...p);
        return { toArray: () => [] };
      }
    },
    transactionSync(fn) {
      db.exec('BEGIN');
      try { const out = fn(); db.exec('COMMIT'); return out; } catch (e) { db.exec('ROLLBACK'); throw e; }
    }
  };
}

const sha256 = async x => [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(x)))]
  .map(b => b.toString(16).padStart(2, '0')).join('');

function registryWith(authorityCalls) {
  const authority = {
    async resolve_or_create_product_link(v) {
      authorityCalls.push(v);
      return { ok: true, link: { state: 'active', product_id: v.product_id, product_user_id: v.product_user_id, canonical_subject_id: 'sub_new' } };
    }
  };
  const state = { storage: storage(), blockConcurrencyWhile(fn) { return fn(); } };
  return new AuthStateObject(state, { IDENTITY_AUTHORITY: authority });
}

test('last-link deletion records a fingerprint tombstone and no longer maps the account', async () => {
  const registry = registryWith([]);
  registry.putAccount({ fingerprint: 'fp-email', accountId: 'sub_old' });
  assert.equal(await registry.beginAccountDeletion({ accountId: 'sub_old', lockToken: 'op', now: 1000 }), true);
  assert.equal(await registry.finalizeAccountDeletion({ accountId: 'sub_old', accountIdHash: await sha256('sub_old'), lockToken: 'op', now: 1000 }), true);
  assert.equal(registry.identityIsDeleted({ fingerprint: 'fp-email' }), true);
  assert.equal(registry.accountByFingerprint('fp-email'), null);
});

test('a tombstoned identity cannot mint a new sub on login, but explicit sign-up may', async () => {
  const calls = [];
  const registry = registryWith(calls);
  registry.putAccount({ fingerprint: 'fp-email', accountId: 'sub_old' });
  await registry.beginAccountDeletion({ accountId: 'sub_old', lockToken: 'op', now: 1000 });
  await registry.finalizeAccountDeletion({ accountId: 'sub_old', accountIdHash: await sha256('sub_old'), lockToken: 'op', now: 1000 });
  await assert.rejects(
    () => registry.resolveAccount({ fingerprint: 'fp-email', productId: 'lovetree-4-0', userId: 'usr_test', subject: 'user@example.test', provider: 'password', now: 1100 }),
    /identity_deleted/
  );
  assert.equal(calls.length, 0, 'login must not reach the identity authority');
  registry.clearIdentityDeletion({ fingerprint: 'fp-email' });
  const created = await registry.resolveAccount({ fingerprint: 'fp-email', productId: 'lovetree-4-0', userId: 'usr_test', subject: 'user@example.test', provider: 'password', now: 1200, allowRecreate: true });
  assert.equal(created.account_id, 'sub_new');
  assert.equal(calls.length, 1);
});
