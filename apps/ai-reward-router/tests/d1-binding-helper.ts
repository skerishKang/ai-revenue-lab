import { DatabaseSync } from 'node:sqlite';
import fs from 'node:fs';
import type { D1DatabaseLike, D1PreparedStatementLike } from '../src/income-pipeline/d1-user-income-repository.js';

const MIGRATION_URL = new URL('../../migrations/d1/0001_b64_user_income.sql', import.meta.url);
const MIGRATIONS_DIR = new URL('../../migrations/d1/', import.meta.url);

export function readIncomeMigrationSql(): string {
  return fs.readFileSync(MIGRATION_URL, 'utf8');
}

/**
 * Every D1 migration in filename order. Applying the whole directory is what
 * proves a new table (0002 accounts and sessions) coexists with the income
 * schema instead of replacing it, and it is the same set the provision gate
 * applies.
 */
export function readAllMigrationsSql(): string {
  return fs
    .readdirSync(MIGRATIONS_DIR)
    .filter((name) => name.endsWith('.sql'))
    .sort()
    .map((name) => fs.readFileSync(new URL(name, MIGRATIONS_DIR), 'utf8'))
    .join('\n');
}

/**
 * Wraps a real SQLite database (node:sqlite) in the minimal D1 binding
 * surface, mirroring the in-repo Python precedent where D1 adapter tests run
 * the REAL migration SQL against real SQLite
 * (apps/padiem-ai-engine/tests/test_4379_tool_result_ledger.py).
 */
export function createSqliteD1Binding(location = ':memory:'): { binding: D1DatabaseLike; db: DatabaseSync } {
  const db = new DatabaseSync(location);
  db.exec(readAllMigrationsSql());
  const makeStatement = (sql: string, prebound: unknown[]): D1PreparedStatementLike => {
    const statement = db.prepare(sql);
    const params = prebound as Parameters<typeof statement.run>;
    return {
      bind(...values: unknown[]) {
        return makeStatement(sql, [...prebound, ...values]);
      },
      async run() {
        const info = statement.run(...params);
        return { meta: { changes: Number(info.changes) } };
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
      return makeStatement(sql, []);
    },
  };
  return { binding, db };
}
