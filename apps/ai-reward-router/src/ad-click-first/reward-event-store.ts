import type { D1DatabaseLike } from '../income-pipeline/d1-user-income-repository.js';
import type { RewardState, RewardStateRecord } from './reward-events.js';
import { isB64MemberId } from '../identity/session.js';

/**
 * Durable storage for the provider reward state machine (issue #987).
 *
 * `reward-events.ts` was already the reviewed state machine and
 * `ayet-s2s-postback.ts` already verified the provider signature; what was
 * missing was anywhere to put the result, so a postback could not be received
 * at all. This module adds only that persistence, and keeps the two properties
 * the pure functions guarantee:
 *
 * - the provider's own transaction key is the row identity, so a retry lands on
 *   the same row instead of crediting twice;
 * - a write is claimed against the state it was read in, so two concurrent
 *   postbacks for one transaction cannot both advance it.
 *
 * `memberId` is carried here and not in `RewardStateRecord`, because that record
 * is deliberately provider-shaped and reusable across providers. The link is
 * made once, from a signature-verified subject, and then it is immutable.
 *
 * Nothing here touches a balance. `b64_user_income` is a different table under
 * different authority, and a confirmed provider event never writes to it.
 */

export interface StoredRewardEvent extends RewardStateRecord {
  readonly memberId: string;
  readonly confirmedAt: string | null;
  readonly reversedAt: string | null;
}

/** Whether the write took the row, or another writer had already claimed it. */
export type RewardEventWrite = 'WRITTEN' | 'CONFLICT';

export class RewardEventStorageError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'RewardEventStorageError';
  }
}

export interface RewardEventStore {
  load(providerId: string, providerTransactionId: string): Promise<StoredRewardEvent | null>;
  /** Insert-only: 'CONFLICT' when the provider transaction key already exists. */
  insert(record: StoredRewardEvent): Promise<RewardEventWrite>;
  /** Update guarded on `expectedState`, so a stale read cannot overwrite a newer transition. */
  transition(record: StoredRewardEvent, expectedState: RewardState): Promise<RewardEventWrite>;
  /** Everything one member was reported for, and nothing else. */
  listForMember(memberId: string): Promise<readonly StoredRewardEvent[]>;
}

function assertProviderIdentity(providerId: string, providerTransactionId: string): void {
  if (!providerId.trim() || !providerTransactionId.trim()) {
    throw new RewardEventStorageError('provider id and provider transaction id are required');
  }
}

function assertRecordShape(record: StoredRewardEvent): void {
  if (!isB64MemberId(record.memberId)) {
    throw new RewardEventStorageError('a reward event must be linked to a B64 member');
  }
  assertProviderIdentity(record.providerId, record.providerTransactionId);
  if (!record.externalUserId.trim() || !record.unit.trim() || !Number.isFinite(record.amount)) {
    throw new RewardEventStorageError('a reward event requires subject, unit and a finite amount');
  }
  if (!record.firstObservedAt || !record.lastObservedAt) {
    throw new RewardEventStorageError('a reward event requires observed timestamps');
  }
}

interface RewardEventRow {
  provider_id: string;
  provider_transaction_id: string;
  member_id: string;
  external_subject: string;
  amount: number;
  unit: string;
  state: RewardState;
  provider_verified: number;
  first_observed_at: string;
  last_observed_at: string;
  confirmed_at: string | null;
  reversed_at: string | null;
}

const SELECT_COLUMNS =
  'SELECT provider_id, provider_transaction_id, member_id, external_subject, amount, unit, state, '
  + 'provider_verified, first_observed_at, last_observed_at, confirmed_at, reversed_at FROM b64_reward_event';

function toStoredRecord(row: RewardEventRow): StoredRewardEvent {
  return Object.freeze({
    providerId: row.provider_id,
    providerTransactionId: row.provider_transaction_id,
    externalUserId: row.external_subject,
    amount: row.amount,
    unit: row.unit,
    state: row.state,
    firstObservedAt: row.first_observed_at,
    lastObservedAt: row.last_observed_at,
    cashCustodyAction: 'NONE' as const,
    memberId: row.member_id,
    confirmedAt: row.confirmed_at ?? null,
    reversedAt: row.reversed_at ?? null,
  });
}

export function buildStoredRewardEvent(
  record: RewardStateRecord,
  memberId: string,
): StoredRewardEvent {
  return Object.freeze({
    ...record,
    memberId,
    confirmedAt: record.state === 'CONFIRMED' ? record.lastObservedAt : null,
    reversedAt: record.state === 'REVERSED' ? record.lastObservedAt : null,
  });
}

export class D1RewardEventStore implements RewardEventStore {
  constructor(private readonly db: D1DatabaseLike) {
    if (!db || typeof db.prepare !== 'function') {
      throw new RewardEventStorageError('reward event storage unavailable: D1 binding is not configured');
    }
  }

  async load(providerId: string, providerTransactionId: string): Promise<StoredRewardEvent | null> {
    assertProviderIdentity(providerId, providerTransactionId);
    const row = await this.db
      .prepare(`${SELECT_COLUMNS} WHERE provider_id = ? AND provider_transaction_id = ?`)
      .bind(providerId, providerTransactionId)
      .first<RewardEventRow>();
    return row === null ? null : toStoredRecord(row);
  }

  async insert(record: StoredRewardEvent): Promise<RewardEventWrite> {
    assertRecordShape(record);
    const result = await this.db
      .prepare(
        'INSERT INTO b64_reward_event (provider_id, provider_transaction_id, member_id, external_subject, '
        + 'amount, unit, state, provider_verified, first_observed_at, last_observed_at, confirmed_at, reversed_at) '
        + 'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) '
        // The primary key is the provider transaction itself, so a second create
        // for one transaction is a conflict the caller must see — not a storage
        // outage. DO NOTHING on that key only; anything else still raises.
        + 'ON CONFLICT (provider_id, provider_transaction_id) DO NOTHING',
      )
      .bind(
        record.providerId,
        record.providerTransactionId,
        record.memberId,
        record.externalUserId,
        record.amount,
        record.unit,
        record.state,
        1,
        record.firstObservedAt,
        record.lastObservedAt,
        record.confirmedAt,
        record.reversedAt,
      )
      .run();
    if (result.success === false) throw new RewardEventStorageError('reward event insert failed');
    const inserted = Number((result.meta as { changes?: number } | undefined)?.changes ?? 0);
    return inserted > 0 ? 'WRITTEN' : 'CONFLICT';
  }

  async transition(record: StoredRewardEvent, expectedState: RewardState): Promise<RewardEventWrite> {
    assertRecordShape(record);
    const result = await this.db
      .prepare(
        'UPDATE b64_reward_event SET state = ?, last_observed_at = ?, confirmed_at = ?, reversed_at = ? '
        + 'WHERE provider_id = ? AND provider_transaction_id = ? AND state = ?',
      )
      .bind(
        record.state,
        record.lastObservedAt,
        record.confirmedAt,
        record.reversedAt,
        record.providerId,
        record.providerTransactionId,
        expectedState,
      )
      .run();
    if (result.success === false) throw new RewardEventStorageError('reward event transition failed');
    const changes = Number((result.meta as { changes?: number } | undefined)?.changes ?? 0);
    return changes > 0 ? 'WRITTEN' : 'CONFLICT';
  }

  async listForMember(memberId: string): Promise<readonly StoredRewardEvent[]> {
    if (!isB64MemberId(memberId)) throw new RewardEventStorageError('member id is not a B64 member id');
    const { results } = await this.db
      .prepare(`${SELECT_COLUMNS} WHERE member_id = ? ORDER BY first_observed_at DESC`)
      .bind(memberId)
      .all<RewardEventRow>();
    return (results ?? []).map(toStoredRecord);
  }
}

/** Fail-closed stand-in for a deployment without the D1 binding. */
export class UnboundRewardEventStore implements RewardEventStore {
  constructor(private readonly bindingName: string) {}

  private fail(): never {
    throw new RewardEventStorageError(
      `reward event storage unavailable: D1 binding ${this.bindingName} is not configured on this deployment`,
    );
  }

  async load(_providerId: string, _providerTransactionId: string): Promise<StoredRewardEvent | null> { this.fail(); }
  async insert(_record: StoredRewardEvent): Promise<RewardEventWrite> { this.fail(); }
  async transition(_record: StoredRewardEvent, _expectedState: RewardState): Promise<RewardEventWrite> { this.fail(); }
  async listForMember(_memberId: string): Promise<readonly StoredRewardEvent[]> { this.fail(); }
}

/** Test/local-prototype store. Never injected as a production fallback. */
export class InMemoryRewardEventStore implements RewardEventStore {
  private readonly rows = new Map<string, StoredRewardEvent>();

  private key(providerId: string, providerTransactionId: string): string {
    return `${providerId}\u0000${providerTransactionId}`;
  }

  async load(providerId: string, providerTransactionId: string): Promise<StoredRewardEvent | null> {
    assertProviderIdentity(providerId, providerTransactionId);
    return this.rows.get(this.key(providerId, providerTransactionId)) ?? null;
  }

  async insert(record: StoredRewardEvent): Promise<RewardEventWrite> {
    assertRecordShape(record);
    const key = this.key(record.providerId, record.providerTransactionId);
    if (this.rows.has(key)) return 'CONFLICT';
    this.rows.set(key, Object.freeze({ ...record }));
    return 'WRITTEN';
  }

  async transition(record: StoredRewardEvent, expectedState: RewardState): Promise<RewardEventWrite> {
    assertRecordShape(record);
    const key = this.key(record.providerId, record.providerTransactionId);
    const current = this.rows.get(key);
    if (!current || current.state !== expectedState) return 'CONFLICT';
    this.rows.set(key, Object.freeze({ ...record }));
    return 'WRITTEN';
  }

  async listForMember(memberId: string): Promise<readonly StoredRewardEvent[]> {
    if (!isB64MemberId(memberId)) throw new RewardEventStorageError('member id is not a B64 member id');
    return [...this.rows.values()].filter((row) => row.memberId === memberId);
  }
}
