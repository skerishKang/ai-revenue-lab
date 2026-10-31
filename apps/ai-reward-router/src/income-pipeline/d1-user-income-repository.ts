import type { UserIncomeRecord, IncomeSourceType, IncomeCurrency, IncomePipelineStatus } from './domain.js';
import type { UserIncomeRepository } from './store.js';

/**
 * Cloudflare D1 adapter for the B64 user income pipeline (issue #987).
 *
 * Satisfies the existing `UserIncomeRepository` contract from
 * `src/income-pipeline/store.ts` — the in-memory prototype remains the
 * default for tests; production wiring (`src/worker.ts`) injects this adapter
 * from the `B64_INCOME_DB` binding instead of silently keeping the
 * non-durable prototype.
 *
 * House rules reused from the existing D1 consumers in this repository
 * (e.g. `apps/padiem-ai-engine/app/idempotency_binding.py`,
 * `apps/padiem-chat/app/b66_quote_history_store.py`):
 * - the constructor fails closed when the binding is absent or unusable;
 * - only prepared statements with bound parameters are executed, so user
 *   input can never change statement shape (user isolation is enforced by
 *   `user_id` appearing in every statement, never by string concatenation);
 * - a D1 result that reports `success: false` is treated as a storage
 *   failure and never ignored;
 * - schema is never created or altered at runtime —
 *   `migrations/d1/0001_b64_user_income.sql` is applied by the dispatch-only
 *   B64 D1 provision gate;
 * - there is deliberately NO global "delete everything" operation: every
 *   statement is scoped to one `user_id`, so no code path can wipe all
 *   users' income records. Test fixtures reset their own test-only stores.
 */

/** Minimal structural surface of the Cloudflare D1 binding this adapter uses. */
export interface D1PreparedStatementLike {
  bind(...values: unknown[]): D1PreparedStatementLike;
  first<T = unknown>(): Promise<T | null>;
  run(): Promise<D1ExecResultLike>;
  all<T = unknown>(): Promise<D1QueryResultLike<T>>;
}

export interface D1ExecResultLike {
  success?: boolean;
  meta?: { changes?: number | null } & Record<string, unknown>;
}

export interface D1QueryResultLike<T> {
  results?: readonly T[] | null;
  meta?: Record<string, unknown>;
}

/** Minimal structural surface of a Cloudflare D1 `database` binding. */
export interface D1DatabaseLike {
  prepare(sql: string): D1PreparedStatementLike;
}

export class IncomeStorageError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'IncomeStorageError';
  }
}

/**
 * Fail-closed stand-in used by the production worker when the D1 binding is
 * not configured. Every operation throws, so the HTTP boundary answers 503
 * instead of pretending the non-durable in-memory prototype is production
 * truth. The prototype singleton is never used as a production fallback.
 */
export class UnboundUserIncomeRepository implements UserIncomeRepository {
  constructor(private readonly bindingName: string) {}

  private fail(): never {
    throw new IncomeStorageError(
      `income storage unavailable: D1 binding ${this.bindingName} is not configured on this deployment`,
    );
  }

  async getByUser(_userId: string): Promise<readonly UserIncomeRecord[]> {
    this.fail();
  }

  async save(_record: UserIncomeRecord): Promise<void> {
    this.fail();
  }

  async delete(_userId: string, _recordId: string): Promise<boolean> {
    this.fail();
  }
}

interface UserIncomeRow {
  id: string;
  user_id: string;
  opportunity_id: string | null;
  external_ref: string | null;
  source_type: string;
  title: string;
  vendor: string;
  status: string;
  expected_amount: number | null;
  expected_currency: string | null;
  actual_amount: number | null;
  actual_currency: string | null;
  applied_at: string | null;
  accepted_at: string | null;
  completed_at: string | null;
  paid_at: string | null;
  expires_at: string | null;
  note: string | null;
  source_url: string | null;
  created_at: string;
  updated_at: string;
}

function asStringOrNull(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

function asNumberOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function rowToRecord(row: UserIncomeRow): UserIncomeRecord {
  return {
    id: row.id,
    userId: row.user_id,
    opportunityId: asStringOrNull(row.opportunity_id),
    externalRef: asStringOrNull(row.external_ref),
    sourceType: row.source_type as IncomeSourceType,
    title: row.title,
    vendor: row.vendor,
    status: row.status as IncomePipelineStatus,
    expectedAmount: asNumberOrNull(row.expected_amount),
    expectedCurrency: asStringOrNull(row.expected_currency) as IncomeCurrency | null,
    actualAmount: asNumberOrNull(row.actual_amount),
    actualCurrency: asStringOrNull(row.actual_currency) as IncomeCurrency | null,
    appliedAt: asStringOrNull(row.applied_at),
    acceptedAt: asStringOrNull(row.accepted_at),
    completedAt: asStringOrNull(row.completed_at),
    paidAt: asStringOrNull(row.paid_at),
    expiresAt: asStringOrNull(row.expires_at),
    note: asStringOrNull(row.note),
    sourceUrl: asStringOrNull(row.source_url),
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

const SELECT_BY_USER =
  'SELECT id, user_id, opportunity_id, external_ref, source_type, title, vendor, status, ' +
  'expected_amount, expected_currency, actual_amount, actual_currency, applied_at, accepted_at, ' +
  'completed_at, paid_at, expires_at, note, source_url, created_at, updated_at ' +
  'FROM b64_user_income WHERE user_id = ? ORDER BY updated_at DESC, id ASC';

// Upsert scoped to (user_id, id): a save can never create a duplicate row for
// the same record, and can never touch another user's row because the
// conflict target includes user_id. created_at is intentionally absent from
// the UPDATE list so a re-save preserves the original creation time.
const UPSERT =
  'INSERT INTO b64_user_income (' +
  'id, user_id, opportunity_id, external_ref, source_type, title, vendor, status, ' +
  'expected_amount, expected_currency, actual_amount, actual_currency, applied_at, accepted_at, ' +
  'completed_at, paid_at, expires_at, note, source_url, created_at, updated_at) ' +
  'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ' +
  'ON CONFLICT(user_id, id) DO UPDATE SET ' +
  'opportunity_id = excluded.opportunity_id, ' +
  'external_ref = excluded.external_ref, ' +
  'source_type = excluded.source_type, ' +
  'title = excluded.title, ' +
  'vendor = excluded.vendor, ' +
  'status = excluded.status, ' +
  'expected_amount = excluded.expected_amount, ' +
  'expected_currency = excluded.expected_currency, ' +
  'actual_amount = excluded.actual_amount, ' +
  'actual_currency = excluded.actual_currency, ' +
  'applied_at = excluded.applied_at, ' +
  'accepted_at = excluded.accepted_at, ' +
  'completed_at = excluded.completed_at, ' +
  'paid_at = excluded.paid_at, ' +
  'expires_at = excluded.expires_at, ' +
  'note = excluded.note, ' +
  'source_url = excluded.source_url, ' +
  'updated_at = excluded.updated_at';

const DELETE_BY_USER_AND_ID = 'DELETE FROM b64_user_income WHERE user_id = ? AND id = ?';

export class D1UserIncomeRepository implements UserIncomeRepository {
  private readonly db: D1DatabaseLike;

  constructor(db: D1DatabaseLike | undefined | null) {
    if (!db || typeof db.prepare !== 'function') {
      throw new IncomeStorageError('D1 binding is required: expected an object providing prepare(sql)');
    }
    this.db = db;
  }

  private async runStatement(statement: D1PreparedStatementLike): Promise<D1ExecResultLike> {
    const result = await statement.run();
    // A D1 result can report failure without throwing; treating that as
    // success would silently drop writes, so it is surfaced to the HTTP
    // boundary (which answers 503) instead of being ignored.
    if (result.success === false) {
      throw new IncomeStorageError('d1 statement reported success=false');
    }
    return result;
  }

  async getByUser(userId: string): Promise<readonly UserIncomeRecord[]> {
    const result = await this.db.prepare(SELECT_BY_USER).bind(userId).all<UserIncomeRow>();
    const rows = result.results ?? [];
    return Object.freeze(rows.map(rowToRecord));
  }

  async save(record: UserIncomeRecord): Promise<void> {
    await this.runStatement(
      this.db
        .prepare(UPSERT)
        .bind(
          record.id,
          record.userId,
          record.opportunityId,
          record.externalRef,
          record.sourceType,
          record.title,
          record.vendor,
          record.status,
          record.expectedAmount,
          record.expectedCurrency,
          record.actualAmount,
          record.actualCurrency,
          record.appliedAt,
          record.acceptedAt,
          record.completedAt,
          record.paidAt,
          record.expiresAt,
          record.note,
          record.sourceUrl,
          record.createdAt,
          record.updatedAt,
        ),
    );
  }

  async delete(userId: string, recordId: string): Promise<boolean> {
    const result = await this.runStatement(
      this.db.prepare(DELETE_BY_USER_AND_ID).bind(userId, recordId),
    );
    return (result.meta?.changes ?? 0) > 0;
  }
}
