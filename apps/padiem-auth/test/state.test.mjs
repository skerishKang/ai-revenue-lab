import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { AuthState } from '../state.mjs';

function setup() {
  const db = new DatabaseSync(':memory:');
  const storage = {
    sql: { exec(query, ...params) { const statement = db.prepare(query); return { toArray: () => statement.all(...params) }; } },
    transactionSync(fn) { db.exec('BEGIN'); try { const out = fn(); db.exec('COMMIT'); return out; } catch (error) { db.exec('ROLLBACK'); throw error; } }
  };
  // Cloudflare SQL exec runs immediately, unlike the adapter's lazy result above.
  storage.sql.exec = (query, ...params) => {
    const statement = db.prepare(query);
    if (statement.columns().length) { const rows = statement.all(...params); return { toArray: () => rows }; }
    statement.run(...params); return { toArray: () => [] };
  };
  return new AuthState({ storage });
}

test('code is bound to client, callback, challenge, expiry, and consumed once', () => {
  const s = setup(); const code = { digest: 'a', client: 'lovetree', redirect: 'https://example.test/cb', challenge: 'c', subject: 'u', accountId: 'sub_u', expires: 60 };
  s.createCode(code);
  assert.equal(s.consumeCode({ ...code, challenge: 'wrong', now: 1 }), false);
  assert.equal(s.consumeCode({ ...code, now: 1 }), true);
  assert.equal(s.consumeCode({ ...code, now: 1 }), false);
  s.createCode({ ...code, digest: 'b' });
  assert.equal(s.consumeCode({ ...code, digest: 'b', now: 60 }), false);
});

test('refresh rotates, replay revokes the whole session, wrong client cannot revoke', () => {
  const s = setup(); s.createSession({ id: 's', client: 'lovetree', subject: 'sub', accountId: 'sub_u', expires: 100, digest: 'one' });
  assert.equal(s.rotate({ id: 's', client: 'wrong', digest: 'one', replacement: 'two', encryptedResult: 'box', now: 1 }).ok, false);
  assert.equal(s.rotate({ id: 's', client: 'lovetree', digest: 'one', replacement: 'two', encryptedResult: 'box', now: 1 }).ok, true);
  assert.equal(s.rotate({ id: 's', client: 'lovetree', digest: 'one', replacement: 'three', now: 31 }).replay, true);
  assert.equal(s.rotate({ id: 's', client: 'lovetree', digest: 'two', replacement: 'four', now: 32 }).ok, false);
});

test('replacement collision rolls back consumption and expired session is rejected', () => {
  const s = setup(); s.createSession({ id: 's', client: 'c', subject: 'sub', accountId: 'sub_u', expires: 100, digest: 'one' });
  assert.throws(() => s.rotate({ id: 's', client: 'c', digest: 'one', replacement: 'one', encryptedResult: 'box', now: 1 }));
  assert.equal(s.rotate({ id: 's', client: 'c', digest: 'one', replacement: 'two', encryptedResult: 'box', now: 2 }).ok, true);
  assert.equal(s.rotate({ id: 's', client: 'c', digest: 'two', replacement: 'three', now: 100 }).ok, false);
});

test('code exchange is single-use and session creation rolls back with a collision', () => {
  const s = setup();
  const code = { digest: 'code', client: 'client', redirect: 'https://example.test/cb', challenge: 'challenge', subject: 'u', accountId: 'sub_u', expires: 60 };
  s.createCode(code);
  s.createSession({ id: 'existing', client: 'client', subject: 'u', accountId: 'sub_u', expires: 100, digest: 'taken' });
  const req = { codeDigest: 'code', client: 'client', redirect: code.redirect, challenge: code.challenge, now: 1, id: 'new', subject: 'u', accountId: 'sub_u', expires: 100, refreshDigest: 'taken' };
  assert.throws(() => s.exchangeCode(req));
  assert.deepEqual(s.exchangeCode({ ...req, refreshDigest: 'fresh' }), { subject: 'u', accountId: 'sub_u' });
  assert.equal(s.exchangeCode({ ...req, id: 'other', refreshDigest: 'other' }), false);
  assert.equal(s.rotate({ id: 'new', client: 'client', digest: 'fresh', replacement: 'next', encryptedResult: 'box', now: 2 }).ok, true);
});

test('Google login state is browser bound, expires, and is consumed once', () => {
  const s = setup();
  const req = { stateDigest: 'state', browserDigest: 'browser', client: 'c', redirect: 'https://example.test/cb', serviceState: 'service', serviceChallenge: 'challenge', googleNonce: 'nonce', googleVerifier: 'verifier', expires: 60 };
  s.createLogin(req);
  assert.equal(s.consumeLogin({ stateDigest: 'state', browserDigest: 'wrong', now: 1 }), null);
  assert.equal(s.consumeLogin({ stateDigest: 'state', browserDigest: 'browser', now: 1 }).google_nonce, 'nonce');
  assert.equal(s.consumeLogin({ stateDigest: 'state', browserDigest: 'browser', now: 2 }), null);
  s.createLogin({ ...req, stateDigest: 'expired' });
  assert.equal(s.consumeLogin({ stateDigest: 'expired', browserDigest: 'browser', now: 60 }), null);
});
