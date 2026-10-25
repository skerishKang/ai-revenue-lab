import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { D1UserIncomeRepository, type D1DatabaseLike, type D1PreparedStatementLike } from '../src/income-pipeline/d1-user-income-repository.js';
import type { UserIncomeRecord } from '../src/income-pipeline/domain.js';
import { readIncomeMigrationSql } from './d1-binding-helper.js';

/**
 * Durable-storage E2E over a REAL on-disk SQLite database (D1-compatible
 * dialect, same migration SQL): the local stand-in for "Worker isolate
 * restart keeps records". The in-repo unit tests cover statement behaviour;
 * this file covers persistence across a full close/reopen cycle.
 */

function makeRecord(overrides: Partial<UserIncomeRecord> = {}): UserIncomeRecord {
  return {
    id: overrides.id ?? 'rec_e2e_1',
    userId: overrides.userId ?? 'usr_e2e_user_a',
    opportunityId: overrides.opportunityId ?? null,
    externalRef: overrides.externalRef ?? null,
    sourceType: overrides.sourceType ?? 'MANUAL',
    title: overrides.title ?? 'Persisted opportunity',
    vendor: overrides.vendor ?? 'Prolific',
    status: overrides.status ?? 'SAVED',
    expectedAmount: overrides.expectedAmount ?? 25,
    expectedCurrency: overrides.expectedCurrency ?? 'USD',
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

/** Opens (or creates) a file-backed SQLite DB and wraps it in the D1 surface. */
function openFileD1(file: string): { binding: D1DatabaseLike; close: () => void } {
  const db = new DatabaseSync(file);
  db.exec(readIncomeMigrationSql());
  const make = (sql: string, prebound: unknown[]): D1PreparedStatementLike => {
    const statement = db.prepare(sql);
    const params = prebound as Parameters<typeof statement.run>;
    return {
      bind(...values: unknown[]) {
        return make(sql, [...prebound, ...values]);
      },
      async run() {
        const info = statement.run(...params);
        return { success: true, meta: { changes: Number(info.changes) } };
      },
      async first<T>() {
        return (statement.get(...params) as T | undefined) ?? null;
      },
      async all<T>() {
        return { results: statement.all(...params) as T[] };
      },
    };
  };
  const binding: D1DatabaseLike = {
    prepare(sql: string) {
      return make(sql, []);
    },
  };
  return { binding, close: () => db.close() };
}

test('records survive a full close/reopen cycle (isolate-restart persistence)', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'b64-d1-e2e-'));
  const file = path.join(dir, 'padiem-b64.sqlite');

  // First isolate: save two records for two users.
  {
    const { binding, close } = openFileD1(file);
    const repo = new D1UserIncomeRepository(binding);
    await repo.save(makeRecord({ id: 'rec_a', userId: 'usr_e2e_user_a', title: 'A record' }));
    await repo.save(makeRecord({ id: 'rec_b', userId: 'usr_e2e_user_b', title: 'B record' }));
    close();
  }

  // Second isolate: fresh repository instance, same durable file.
  {
    const { binding, close } = openFileD1(file);
    const repo = new D1UserIncomeRepository(binding);
    const forA = await repo.getByUser('usr_e2e_user_a');
    const forB = await repo.getByUser('usr_e2e_user_b');
    assert.equal(forA.length, 1);
    assert.equal(forA[0]!.title, 'A record');
    assert.equal(forA[0]!.expectedAmount, 25);
    assert.equal(forA[0]!.expectedCurrency, 'USD');
    assert.equal(forB.length, 1);
    assert.equal(forB[0]!.id, 'rec_b');
    close();
  }

  fs.rmSync(dir, { recursive: true, force: true });
});

test('update, transition and delete persist across reopen; duplicates cannot occur', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'b64-d1-e2e-'));
  const file = path.join(dir, 'padiem-b64.sqlite');

  {
    const { binding, close } = openFileD1(file);
    const repo = new D1UserIncomeRepository(binding);
    await repo.save(makeRecord({ id: 'rec_flow', userId: 'usr_e2e_user_a', status: 'SAVED' }));
    // same id again: upsert, never a duplicate row
    await repo.save(makeRecord({ id: 'rec_flow', userId: 'usr_e2e_user_a', status: 'APPLIED', appliedAt: '2026-10-25T10:00:00.000Z' }));
    // progression SAVED -> APPLIED -> COMPLETED -> PAID with an actual amount
    await repo.save(makeRecord({
      id: 'rec_flow', userId: 'usr_e2e_user_a', status: 'PAID',
      actualAmount: 31.5, actualCurrency: 'USD', paidAt: '2026-10-25T12:00:00.000Z',
      appliedAt: '2026-10-25T10:00:00.000Z',
    }));
    close();
  }

  {
    const { binding, close } = openFileD1(file);
    const repo = new D1UserIncomeRepository(binding);
    const records = await repo.getByUser('usr_e2e_user_a');
    assert.equal(records.length, 1, 'no duplicate row for the same record id');
    assert.equal(records[0]!.status, 'PAID');
    assert.equal(records[0]!.actualAmount, 31.5);
    assert.equal(records[0]!.createdAt, '2026-10-25T09:00:00.000Z', 'creation time survives the whole flow');
    assert.equal(await repo.delete('usr_e2e_user_a', 'rec_flow'), true);
    assert.equal((await repo.getByUser('usr_e2e_user_a')).length, 0);
    close();
  }

  // Third isolate: the delete persisted too.
  {
    const { binding, close } = openFileD1(file);
    const repo = new D1UserIncomeRepository(binding);
    assert.equal((await repo.getByUser('usr_e2e_user_a')).length, 0);
    close();
  }

  fs.rmSync(dir, { recursive: true, force: true });
});

test('a user-scoped delete never touches another user\'s persisted record', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'b64-d1-e2e-'));
  const file = path.join(dir, 'padiem-b64.sqlite');

  {
    const { binding, close } = openFileD1(file);
    const repo = new D1UserIncomeRepository(binding);
    await repo.save(makeRecord({ id: 'rec_shared_id', userId: 'usr_e2e_user_a', title: 'A only' }));
    await repo.save(makeRecord({ id: 'rec_shared_id', userId: 'usr_e2e_user_b', title: 'B only' }));
    assert.equal(await repo.delete('usr_e2e_user_b', 'rec_shared_id'), true);
    close();
  }

  {
    const { binding, close } = openFileD1(file);
    const repo = new D1UserIncomeRepository(binding);
    const forA = await repo.getByUser('usr_e2e_user_a');
    assert.equal(forA.length, 1);
    assert.equal(forA[0]!.title, 'A only', 'A record survives B deleting their own');
    close();
  }

  fs.rmSync(dir, { recursive: true, force: true });
});
