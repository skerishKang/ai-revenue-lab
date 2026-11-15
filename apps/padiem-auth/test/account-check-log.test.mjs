// #7542 (P0-B): one countable line per account check.
//
// Retiring the old identity authority needs to know how often the common login
// still asks it, per client. The check itself is unchanged; these tests pin the
// line it writes and that the line carries no identifier.
import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { AuthStateObject } from '../worker.mjs';
import { withProductBoundary } from './authority-products.mjs';

const FINGERPRINT = 'fingerprint-that-must-not-be-logged';
const SUBJECT = 'google-subject-that-must-not-be-logged';
const USER = 'usr_user_that_must_not_be_logged';
const ACCOUNT = 'sub_account_that_must_not_be_logged';

function storage() {
  const db = new DatabaseSync(':memory:');
  return { sql: { exec(q, ...p) { const stmt = db.prepare(q); if (stmt.columns().length) { const rows = stmt.all(...p); return { toArray: () => rows }; } stmt.run(...p); return { toArray: () => [] }; } },
    transactionSync(fn) { db.exec('BEGIN'); try { const out = fn(); db.exec('COMMIT'); return out; } catch (e) { db.exec('ROLLBACK'); throw e; } } };
}

function registry(authority, extra = {}) {
  let queue = Promise.resolve();
  const state = { storage: storage(), blockConcurrencyWhile(fn) { const next = queue.then(fn); queue = next.catch(() => {}); return next; } };
  return new AuthStateObject(state, { IDENTITY_AUTHORITY: authority, ...extra });
}

function accepting() {
  const calls = [], registrations = [];
  const authority = withProductBoundary({
    async resolve_or_create_product_link(v) {
      calls.push(v);
      return { ok: true, link: { state: 'active', product_id: v.product_id, product_user_id: v.product_user_id, canonical_subject_id: ACCOUNT } };
    },
    async resolve_or_create_identity_subject(v) {
      registrations.push(v);
      return { ok: true, canonical_subject_id: ACCOUNT, account_created_at: 1700, already_registered: true };
    },
  });
  return { authority, calls, registrations };
}

// Runs one account check and returns the account-check lines it wrote, with
// everything else the Worker logs kept out of the way.
async function checked(run) {
  const lines = [];
  const originalLog = console.log, originalError = console.error;
  console.log = line => { lines.push(String(line)); };
  console.error = () => {};
  let outcome;
  try { outcome = await run().then(value => ({ value }), error => ({ error })); }
  finally { console.log = originalLog; console.error = originalError; }
  const checks = lines.map(line => { try { return JSON.parse(line); } catch { return null; } })
    .filter(entry => entry?.auth_stage === 'identity_account_check');
  return { ...outcome, checks, raw: lines.join('\n') };
}

const request = (productId, extra = {}) => ({ fingerprint: FINGERPRINT, productId, userId: USER, subject: SUBJECT, ...extra });

test('a first sign-in asks the authority and is counted as called', async () => {
  const { authority, calls } = accepting();
  const r = await checked(() => registry(authority).resolveAccount(request('lovetree-4-0')));
  assert.equal(r.value.account_id, ACCOUNT);
  assert.equal(calls.length, 1);
  assert.deepEqual(r.checks, [{ auth_stage: 'identity_account_check', product: 'lovetree-4-0', method: 'google', known: false, outcome: 'called' }]);
});

test('a known person on another product is not asked again and is counted as skipped', async () => {
  const { authority, calls } = accepting();
  const reg = registry(authority);
  await checked(() => reg.resolveAccount(request('lovetree-4-0')));
  const r = await checked(() => reg.resolveAccount(request('b61')));
  assert.equal(r.value.account_id, ACCOUNT);
  assert.equal(calls.length, 1);
  assert.deepEqual(r.checks, [{ auth_stage: 'identity_account_check', product: 'b61', method: 'google', known: true, outcome: 'skipped_known' }]);
});

test('Chat asks the authority on every sign-in, and that shows as known and called', async () => {
  const { authority, calls } = accepting();
  const reg = registry(authority);
  await checked(() => reg.resolveAccount(request('b62')));
  const r = await checked(() => reg.resolveAccount(request('b62')));
  assert.equal(calls.length, 2);
  assert.deepEqual(r.checks, [{ auth_stage: 'identity_account_check', product: 'b62', method: 'google', known: true, outcome: 'called' }]);
});

test('a refusal from the authority is counted as rejected and still fails the sign-in', async () => {
  const { authority, calls } = accepting();
  const reg = registry(authority);
  const r = await checked(() => reg.resolveAccount(request('b62-staging')));
  assert.ok(r.error);
  assert.equal(calls.length, 0);
  assert.equal(reg.accountByFingerprint(FINGERPRINT), null);
  assert.deepEqual(r.checks, [{ auth_stage: 'identity_account_check', product: 'b62-staging', method: 'google', known: false, outcome: 'rejected' }]);
});

test('an answer in another shape is counted as rejected', async () => {
  const authority = withProductBoundary({ async resolve_or_create_product_link(v) {
    return { ok: true, link: { state: 'active', product_id: v.product_id, product_user_id: 'usr_someone_else', canonical_subject_id: ACCOUNT } };
  } });
  const r = await checked(() => registry(authority).resolveAccount(request('lovetree-4-0')));
  assert.ok(r.error);
  assert.equal(r.checks.length, 1);
  assert.equal(r.checks[0].outcome, 'rejected');
});

test('an unreachable authority is counted as failed and still fails the sign-in', async () => {
  const authority = withProductBoundary({ async resolve_or_create_product_link() { throw new Error('binding unavailable'); } });
  const reg = registry(authority);
  const r = await checked(() => reg.resolveAccount(request('lovetree-4-0')));
  assert.ok(r.error);
  assert.equal(reg.accountByFingerprint(FINGERPRINT), null);
  assert.deepEqual(r.checks, [{ auth_stage: 'identity_account_check', product: 'lovetree-4-0', method: 'google', known: false, outcome: 'failed' }]);
});

test('a password sign-in is counted under its own method', async () => {
  const { authority } = accepting();
  const r = await checked(() => registry(authority).resolveAccount(request('b62', { provider: 'password', credentialEpoch: '2026-11-12T00:00:00+00:00' })));
  assert.equal(r.checks.length, 1);
  assert.equal(r.checks[0].method, 'password');
  assert.equal(r.checks[0].outcome, 'called');
});

test('the line never carries an identifier, and an odd client id is not echoed', async () => {
  const { authority } = accepting();
  const reg = registry(authority);
  const first = await checked(() => reg.resolveAccount(request('lovetree-4-0')));
  const again = await checked(() => reg.resolveAccount(request('Not A Client <script>')));
  for (const r of [first, again]) {
    assert.equal(r.checks.length, 1);
    assert.deepEqual(Object.keys(r.checks[0]).sort(), ['auth_stage', 'known', 'method', 'outcome', 'product']);
    for (const secret of [FINGERPRINT, SUBJECT, USER, ACCOUNT]) assert.equal(r.raw.includes(secret), false, secret);
  }
  assert.equal(again.checks[0].product, 'other');
  assert.equal(again.raw.includes('script'), false);
});

test('P7 on registers once, then treats the known person as local and keeps the UTC birthday', async () => {
  const { authority, calls, registrations } = accepting();
  const reg = registry(authority, { PADIEM_AUTH_ACCOUNT_ISSUER_MODE: 'on' });
  const first = await reg.resolveAccount(request('lovetree-4-0'));
  const second = await reg.resolveAccount(request('lovetree-4-0'));
  assert.equal(first.account_id, second.account_id);
  assert.equal(calls.length, 1);
  assert.equal(registrations.length, 1);
  assert.equal(reg.accountCreatedAt({ accountId: ACCOUNT }).account_created_at, 1700);
});

test('P7 shadow records only closed matching fields and no identifier', async () => {
  const { authority, calls, registrations } = accepting();
  const reg = registry(authority, { PADIEM_AUTH_ACCOUNT_ISSUER_MODE: 'shadow' });
  const r = await checked(() => reg.resolveAccount(request('lovetree-4-0')));
  assert.equal(r.value.account_id, ACCOUNT);
  assert.equal(calls.length, 1);
  assert.equal(registrations.length, 1);
  const shadow = r.raw.split('\n').map(line => { try { return JSON.parse(line); } catch { return null; } })
    .find(entry => entry?.auth_stage === 'identity_provisioning_shadow');
  assert.deepEqual(shadow, { auth_stage: 'identity_provisioning_shadow', product: 'lovetree-4-0', method: 'google', known: false, outcome: 'match' });
  for (const secret of [FINGERPRINT, SUBJECT, USER, ACCOUNT]) assert.equal(r.raw.includes(secret), false, secret);
});

test('P7 on fails closed before storing an account when registration is rejected', async () => {
  const { authority, calls } = accepting();
  authority.resolve_or_create_identity_subject = async () => ({ ok: false, error: { code: 'identity_subject_conflict' } });
  const reg = registry(authority, { PADIEM_AUTH_ACCOUNT_ISSUER_MODE: 'on' });
  await assert.rejects(() => reg.resolveAccount(request('lovetree-4-0')));
  assert.equal(reg.accountByFingerprint(FINGERPRINT), null);
  assert.equal(calls.length, 0);
});

test('P7 shadow registration failure does not change the accepted legacy response', async () => {
  const { authority, calls } = accepting();
  authority.resolve_or_create_identity_subject = async () => { throw new Error('private-upstream-error'); };
  const reg = registry(authority, { PADIEM_AUTH_ACCOUNT_ISSUER_MODE: 'shadow' });
  const r = await checked(() => reg.resolveAccount(request('lovetree-4-0')));
  assert.equal(r.value.account_id, ACCOUNT);
  assert.equal(calls.length, 1);
  assert.match(r.raw, /"outcome":"registration_rejected"/);
  assert.equal(r.raw.includes('private-upstream-error'), false);
});
