import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import {
  B64MemberExistsError,
  B64MemberStorageError,
  D1B64MemberStore,
  UnboundB64MemberStore,
} from '../src/identity/member-store.js';
import { D1UserIncomeRepository } from '../src/income-pipeline/d1-user-income-repository.js';
import { newB64MemberId, newB64SessionId } from '../src/identity/session.js';
import { createSqliteD1Binding, readAllMigrationsSql } from './d1-binding-helper.js';

/**
 * B64's own account and session storage (#987). The same D1 database holds the
 * income rows and the member rows, so these tests also prove the new schema
 * coexists with the existing one — the income table and its rows are untouched.
 */

interface MemberFixture {
  readonly id: string;
  readonly email: string;
  readonly passwordHash: string;
  readonly createdAt: string;
}

const STORE_HASH = 'pbkdf2_sha512$100000$c2FsdHNhbHRzYWx0c2ExMg==$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=';

function member(email = 'store-user@example.com'): MemberFixture {
  return {
    id: newB64MemberId(),
    email,
    passwordHash: STORE_HASH,
    createdAt: '2026-10-27T00:00:00.000Z',
  };
}

test('a member round-trips and the same address cannot register twice', async () => {
  const { binding } = createSqliteD1Binding();
  const store = new D1B64MemberStore(binding);
  const created = member();
  await store.createMember(created);

  const found = await store.findByEmail('store-user@example.com');
  assert.equal(found!.id, created.id);
  assert.equal(found!.passwordHash, created.passwordHash);
  assert.equal(await store.findByEmail('nobody@example.com'), null);

  await assert.rejects(() => store.createMember(member()), B64MemberExistsError);
});

test('a session is live until revoked, and revocation is scoped to that session', async () => {
  const { binding } = createSqliteD1Binding();
  const store = new D1B64MemberStore(binding);
  const created = member();
  await store.createMember(created);
  const first = { id: newB64SessionId(), memberId: created.id, expiresAt: '2096-10-27T00:00:00.000Z', revokedAt: null };
  const second = { ...first, id: newB64SessionId() };
  await store.createSession(first);
  await store.createSession(second);

  assert.equal((await store.findLiveSession(first.id))!.id, first.id);
  await store.revokeSession(first.id);
  assert.equal(await store.findLiveSession(first.id), null, 'a revoked session row is never live');
  assert.ok(await store.findLiveSession(second.id), 'the member other session is untouched');

  // Revoking twice must not rewrite the original revocation timestamp.
  const before = binding.prepare('SELECT revoked_at FROM b64_session WHERE id = ?').bind(first.id);
  const stamped = (await before.first<{ revoked_at: string }>())!.revoked_at;
  await store.revokeSession(first.id);
  const after = (await binding.prepare('SELECT revoked_at FROM b64_session WHERE id = ?')
    .bind(first.id).first<{ revoked_at: string }>())!.revoked_at;
  assert.equal(after, stamped);
});

test('members and sessions survive a database close and reopen', async () => {
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'b64-d1-')), 'b64.sqlite');
  const opened = createSqliteD1Binding(file);
  const store = new D1B64MemberStore(opened.binding);
  const created = member();
  await store.createMember(created);
  const sessionId = newB64SessionId();
  await store.createSession({ id: sessionId, memberId: created.id, expiresAt: '2096-10-27T00:00:00.000Z', revokedAt: null });
  opened.db.close();

  const reopened = new DatabaseSync(file);
  const row = reopened.prepare('SELECT id, email FROM b64_member WHERE email = ?').get(created.email) as { id: string };
  assert.equal(row.id, created.id, 'the account is durable storage, not isolate memory');
  const session = reopened.prepare('SELECT member_id FROM b64_session WHERE id = ?').get(sessionId) as { member_id: string };
  assert.equal(session.member_id, created.id);
  reopened.close();
});

test('the account schema and the income schema share one database without disturbing each other', async () => {
  const { binding } = createSqliteD1Binding();
  const store = new D1B64MemberStore(binding);
  const created = member();
  await store.createMember(created);
  const income = new D1UserIncomeRepository(binding);
  await income.save({
    id: 'rec-1', userId: created.id, opportunityId: null, externalRef: null, sourceType: 'MANUAL',
    title: 'Kept record', vendor: 'Prolific', status: 'SAVED',
    expectedAmount: 10, expectedCurrency: 'USD', actualAmount: null, actualCurrency: null,
    appliedAt: null, acceptedAt: null, completedAt: null, paidAt: null, expiresAt: null,
    note: null, sourceUrl: null, createdAt: '2026-10-27T00:00:00.000Z', updatedAt: '2026-10-27T00:00:00.000Z',
  });

  const records = await income.getByUser(created.id);
  assert.equal(records.length, 1);
  assert.equal(records[0]!.title, 'Kept record');
  assert.ok(await store.findByEmail(created.email), 'the income write did not disturb the account');
});

test('migrations are replay-safe as a set', () => {
  const sql = readAllMigrationsSql();
  assert.match(sql, /CREATE TABLE IF NOT EXISTS b64_user_income/);
  assert.match(sql, /CREATE TABLE IF NOT EXISTS b64_member/);
  assert.match(sql, /CREATE TABLE IF NOT EXISTS b64_session/);
  const { db } = createSqliteD1Binding();
  db.exec(sql);
  db.exec(sql);
  db.close();
});

test('a missing binding fails closed and no statement can reach another member', async () => {
  const unbound = new UnboundB64MemberStore('B64_INCOME_DB');
  await assert.rejects(() => unbound.findByEmail('x@example.com'), B64MemberStorageError);
  await assert.rejects(() => unbound.revokeSession('b64s_000000000000000000000000'), B64MemberStorageError);
  assert.throws(() => new D1B64MemberStore(undefined as never), B64MemberStorageError);
  assert.throws(() => new D1B64MemberStore({} as never), B64MemberStorageError);

  const source = fs.readFileSync(new URL('../../src/identity/member-store.ts', import.meta.url), 'utf8');
  assert.ok(!/DELETE FROM b64_member/.test(source), 'no wipe path for accounts');
  assert.ok(!/DELETE FROM b64_session/.test(source), 'sessions are revoked, never bulk deleted');
  assert.match(source, /UPDATE b64_session SET revoked_at = \? WHERE id = \? AND revoked_at IS NULL/,
    'revocation is addressed by one session id and never rewrites an existing stamp');
});
