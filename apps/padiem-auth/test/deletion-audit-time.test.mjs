import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { AuthStateObject } from '../worker.mjs';
import { withProductBoundary } from './authority-products.mjs';

const sha256 = async x => [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(x)))]
  .map(b => b.toString(16).padStart(2, '0')).join('');

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

function registry() {
  const authority = withProductBoundary({
    async resolve_or_create_product_link(v) {
      return { ok: true, link: { state: 'active', product_id: v.product_id, product_user_id: v.product_user_id, canonical_subject_id: 'sub_new' } };
    }
  });
  const state = { storage: storage(), blockConcurrencyWhile(fn) { return fn(); } };
  return new AuthStateObject(state, { IDENTITY_AUTHORITY: authority });
}

const DAY = 24 * 60 * 60;

test('a completion retry keeps the first deletion time as the retention anchor (#7648)', async () => {
  const r = registry();
  r.putAccount({ fingerprint: 'fp-email', accountId: 'sub_old' });
  const hash = await sha256('sub_old');
  // The first completion runs at t=1000 (prepare mints the lock, finalize
  // writes the audit row and prunes).
  assert.equal(await r.beginAccountDeletion({ accountId: 'sub_old', lockToken: 'op-1', now: 1000 }), true);
  assert.equal(await r.finalizeAccountDeletion({ accountId: 'sub_old', accountIdHash: hash, lockToken: 'op-1', now: 1000 }), true);
  assert.equal(r.sql.exec('SELECT deleted_at FROM account_deletion_audit').toArray()[0].deleted_at, 1000);

  // The retry lane answers a lost completion days later: a fresh prepare lock
  // makes finalize run its whole transaction again.
  const retryAt = 1000 + 3 * DAY;
  assert.equal(await r.beginAccountDeletion({ accountId: 'sub_old', lockToken: 'op-2', now: retryAt }), true);
  assert.equal(await r.finalizeAccountDeletion({ accountId: 'sub_old', accountIdHash: hash, lockToken: 'op-2', now: retryAt }), true);
  const rows = r.sql.exec('SELECT account_id_hash,deleted_at FROM account_deletion_audit').toArray();
  assert.equal(rows.length, 1);
  assert.equal(rows[0].account_id_hash, hash);
  assert.equal(rows[0].deleted_at, 1000, 'the retry must not restart the audit time');

  // The 365-day retention is computed from the first deletion time, not the
  // retry time: one second before the anchor the row stays, at the anchor it
  // is pruned (deleted_at <= now - 365 days).
  assert.equal(r.nextAccountDeletionAuditExpiry(), 1000 + 365 * DAY);
  assert.equal(r.pruneAccountDeletionAudit({ now: 1000 + 365 * DAY - 1 }), 0);
  assert.equal(r.pruneAccountDeletionAudit({ now: 1000 + 365 * DAY }), 1);
});
