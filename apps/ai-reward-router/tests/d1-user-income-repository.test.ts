import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import {
  D1UserIncomeRepository,
  IncomeStorageError,
  UnboundUserIncomeRepository,
  type D1DatabaseLike,
  type D1PreparedStatementLike,
} from '../src/income-pipeline/d1-user-income-repository.js';
import type { UserIncomeRecord } from '../src/income-pipeline/domain.js';
import { createSqliteD1Binding, readIncomeMigrationSql } from './d1-binding-helper.js';

function makeRecord(overrides: Partial<UserIncomeRecord> = {}): UserIncomeRecord {
  return {
    id: overrides.id ?? 'rec_00000001',
    userId: overrides.userId ?? 'usr_user_aaaa',
    opportunityId: overrides.opportunityId ?? null,
    externalRef: overrides.externalRef ?? null,
    sourceType: overrides.sourceType ?? 'MANUAL',
    title: overrides.title ?? 'Test opportunity',
    vendor: overrides.vendor ?? 'TestVendor',
    status: overrides.status ?? 'SAVED',
    expectedAmount: overrides.expectedAmount ?? null,
    expectedCurrency: overrides.expectedCurrency ?? null,
    actualAmount: overrides.actualAmount ?? null,
    actualCurrency: overrides.actualCurrency ?? null,
    appliedAt: overrides.appliedAt ?? null,
    acceptedAt: overrides.acceptedAt ?? null,
    completedAt: overrides.completedAt ?? null,
    paidAt: overrides.paidAt ?? null,
    expiresAt: overrides.expiresAt ?? null,
    note: overrides.note ?? null,
    sourceUrl: overrides.sourceUrl ?? null,
    createdAt: overrides.createdAt ?? '2026-10-25T09:00:00.000Z',
    updatedAt: overrides.updatedAt ?? '2026-10-25T09:00:00.000Z',
  };
}

test('migration SQL is replay-safe (applied twice without error)', () => {
  const db = new DatabaseSync(':memory:');
  db.exec(readIncomeMigrationSql());
  db.exec(readIncomeMigrationSql());
  const tables = db.prepare("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'b64_user_income'").all();
  assert.equal(tables.length, 1);
});

test('save and getByUser round-trip preserves amounts, currencies and timestamps', async () => {
  const { binding } = createSqliteD1Binding();
  const repo = new D1UserIncomeRepository(binding);
  const record = makeRecord({
    expectedAmount: 25000,
    expectedCurrency: 'KRW',
    actualAmount: 12.5,
    actualCurrency: 'USD',
    status: 'PAID',
    paidAt: '2026-10-24T12:00:00.000Z',
    note: 'first payout',
  });
  await repo.save(record);
  const records = await repo.getByUser('usr_user_aaaa');
  assert.equal(records.length, 1);
  assert.deepEqual(records[0], record);
});

test('getByUser returns only the requesting user\'s records (user isolation)', async () => {
  const { binding } = createSqliteD1Binding();
  const repo = new D1UserIncomeRepository(binding);
  await repo.save(makeRecord({ id: 'rec_a', userId: 'usr_user_aaaa', title: 'A record' }));
  await repo.save(makeRecord({ id: 'rec_b', userId: 'usr_user_bbbb', title: 'B record' }));
  const forA = await repo.getByUser('usr_user_aaaa');
  const forB = await repo.getByUser('usr_user_bbbb');
  assert.equal(forA.length, 1);
  assert.equal(forA[0]!.id, 'rec_a');
  assert.equal(forB.length, 1);
  assert.equal(forB[0]!.id, 'rec_b');
  assert.equal(await repo.getByUser('usr_unknown').then((r) => r.length), 0);
});

test('same record id under different users stays independent (no cross-user overwrite)', async () => {
  const { binding } = createSqliteD1Binding();
  const repo = new D1UserIncomeRepository(binding);
  await repo.save(makeRecord({ id: 'rec_shared', userId: 'usr_user_aaaa', title: 'Owned by A' }));
  await repo.save(makeRecord({ id: 'rec_shared', userId: 'usr_user_bbbb', title: 'Owned by B' }));
  const forA = await repo.getByUser('usr_user_aaaa');
  const forB = await repo.getByUser('usr_user_bbbb');
  assert.equal(forA[0]!.title, 'Owned by A');
  assert.equal(forB[0]!.title, 'Owned by B');
});

test('re-saving the same record updates in place and preserves createdAt', async () => {
  const { binding } = createSqliteD1Binding();
  const repo = new D1UserIncomeRepository(binding);
  const created = '2026-10-01T00:00:00.000Z';
  await repo.save(makeRecord({ id: 'rec_1', userId: 'usr_user_aaaa', status: 'SAVED', createdAt: created, updatedAt: created }));
  await repo.save(
    makeRecord({
      id: 'rec_1',
      userId: 'usr_user_aaaa',
      status: 'APPLIED',
      appliedAt: '2026-10-25T10:00:00.000Z',
      // A caller that wrongly changes createdAt must not move the stored
      // creation time: the upsert never rewrites created_at.
      createdAt: '2099-01-01T00:00:00.000Z',
      updatedAt: '2026-10-25T10:00:00.000Z',
    }),
  );
  const records = await repo.getByUser('usr_user_aaaa');
  assert.equal(records.length, 1, 'no duplicate row for the same record');
  assert.equal(records[0]!.createdAt, created);
  assert.equal(records[0]!.status, 'APPLIED');
  assert.equal(records[0]!.updatedAt, '2026-10-25T10:00:00.000Z');
});

test('delete removes only the named user\'s record and reports whether it existed', async () => {
  const { binding } = createSqliteD1Binding();
  const repo = new D1UserIncomeRepository(binding);
  await repo.save(makeRecord({ id: 'rec_1', userId: 'usr_user_aaaa' }));
  assert.equal(await repo.delete('usr_user_bbbb', 'rec_1'), false, 'another user cannot delete it');
  assert.equal((await repo.getByUser('usr_user_aaaa')).length, 1);
  assert.equal(await repo.delete('usr_user_aaaa', 'rec_missing'), false);
  assert.equal(await repo.delete('usr_user_aaaa', 'rec_1'), true);
  assert.equal((await repo.getByUser('usr_user_aaaa')).length, 0);
});

test('the D1 adapter exposes no global delete path (per-user statements only)', async () => {
  const { binding, db } = createSqliteD1Binding();
  const repo = new D1UserIncomeRepository(binding);
  assert.equal(
    (repo as unknown as { clear?: unknown }).clear,
    undefined,
    'the production repository must not offer a wipe-everything operation',
  );
  await repo.save(makeRecord({ userId: 'usr_user_aaaa' }));
  await repo.save(makeRecord({ userId: 'usr_user_bbbb' }));
  // The only reset path is the test's own test-only store, never the adapter.
  db.exec('DELETE FROM b64_user_income');
  assert.equal((await repo.getByUser('usr_user_aaaa')).length, 0);
  assert.equal((await repo.getByUser('usr_user_bbbb')).length, 0);
});

test('the repository contract has no clear() member', async () => {
  const { binding } = createSqliteD1Binding();
  const repo = new D1UserIncomeRepository(binding);
  const keys = Object.getOwnPropertyNames(Object.getPrototypeOf(repo));
  assert.ok(!keys.includes('clear'), `contract methods must exclude clear, found: ${keys.join(',')}`);
  for (const required of ['getByUser', 'save', 'delete'] as const) {
    assert.ok(keys.includes(required), `contract keeps ${required}`);
  }
});

test('schema CHECK constraints reject out-of-domain status, currency and source types', async () => {
  const { binding } = createSqliteD1Binding();
  const repo = new D1UserIncomeRepository(binding);
  await assert.rejects(
    () => repo.save(makeRecord({ status: 'NOT_A_STATUS' as never })),
    'invalid status must be rejected by the database constraint',
  );
  await assert.rejects(() => repo.save(makeRecord({ expectedCurrency: 'BTC' as never })));
  await assert.rejects(() => repo.save(makeRecord({ sourceType: 'HACKED' as never })));
  const records = await repo.getByUser('usr_user_aaaa');
  assert.equal(records.length, 0, 'a rejected write must leave no partial row');
});

test('getByUser orders by updated_at descending', async () => {
  const { binding } = createSqliteD1Binding();
  const repo = new D1UserIncomeRepository(binding);
  await repo.save(makeRecord({ id: 'rec_old', userId: 'usr_user_aaaa', updatedAt: '2026-10-01T00:00:00.000Z' }));
  await repo.save(makeRecord({ id: 'rec_new', userId: 'usr_user_aaaa', updatedAt: '2026-10-25T00:00:00.000Z' }));
  const records = await repo.getByUser('usr_user_aaaa');
  assert.deepEqual(records.map((r) => r.id), ['rec_new', 'rec_old']);
});

test('constructor fails closed on a missing or unusable binding', () => {
  assert.throws(() => new D1UserIncomeRepository(undefined), IncomeStorageError);
  assert.throws(() => new D1UserIncomeRepository(null), IncomeStorageError);
  assert.throws(() => new D1UserIncomeRepository({} as D1DatabaseLike), IncomeStorageError);
});

test('unbound fail-closed repository throws instead of pretending storage exists', async () => {
  const repo = new UnboundUserIncomeRepository('B64_INCOME_DB');
  await assert.rejects(() => repo.getByUser('usr_user_aaaa'), IncomeStorageError);
  await assert.rejects(() => repo.save(makeRecord()), IncomeStorageError);
  await assert.rejects(() => repo.delete('usr_user_aaaa', 'rec_1'), IncomeStorageError);
});

test('a run() result reporting success=false is surfaced, never ignored', async () => {
  let succeed = true;
  const inner = createSqliteD1Binding();
  const flaky: D1DatabaseLike = {
    prepare(sql: string) {
      const make = (prebound: unknown[]): D1PreparedStatementLike => {
        const statement = inner.binding.prepare(sql).bind(...prebound);
        return {
          bind(...more: unknown[]) {
            return make([...prebound, ...more]);
          },
          async run() {
            // Simulate a D1 failure that reports success=false and writes nothing.
            if (!succeed) return { success: false, meta: { changes: 0 } };
            return statement.run();
          },
          first: () => statement.first(),
          all: () => statement.all(),
        };
      };
      return make([]);
    },
  };
  const repo = new D1UserIncomeRepository(flaky);
  succeed = false;
  await assert.rejects(
    () => repo.save(makeRecord({ id: 'rec_flagged', userId: 'usr_user_aaaa' })),
    IncomeStorageError,
    'a reported-failure write must surface as a storage error',
  );
  const rowCount = await inner.binding.prepare('SELECT COUNT(*) AS n FROM b64_user_income').first<{ n: number }>();
  assert.equal(rowCount!.n, 0, 'a reported-failure write must leave no row behind');
  succeed = true;
  await repo.save(makeRecord({ id: 'rec_flagged', userId: 'usr_user_aaaa' }));
  assert.equal((await repo.getByUser('usr_user_aaaa')).length, 1);
});

test('a binding whose prepare throws surfaces the failure instead of losing data silently', async () => {
  const broken: D1DatabaseLike = {
    prepare() {
      throw new Error('d1 unavailable');
    },
  };
  const repo = new D1UserIncomeRepository(broken);
  await assert.rejects(() => repo.getByUser('usr_user_aaaa'), /d1 unavailable/);
  await assert.rejects(() => repo.save(makeRecord()), /d1 unavailable/);
});
