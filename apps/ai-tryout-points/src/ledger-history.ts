import {
  MAX_OBSERVED_NONCES,
  MAX_PROVIDER_CLOCK_SKEW_MS,
  isSafeIdentifier,
  type CompletionLedgerRecord,
  type TryoutOffer,
} from './domain.js';

function validTimestamp(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && Number.isFinite(Date.parse(value));
}

function validMinorAmount(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && Number.isSafeInteger(value) && value > 0;
}

/**
 * Bounded, append-only observed-nonce history. The list must be a real array, must be
 * non-empty, must stay within `MAX_OBSERVED_NONCES`, must contain only safe
 * identifiers, must be duplicate-free, and must begin with the canonical `nonce` that
 * the record also carries. A dropped, duplicated, padded, or unbounded history would
 * either hide a nonce that was already bound to this transaction or reopen a replay
 * hole, so every one of those shapes fails closed here.
 */
function validObservedNonces(value: unknown, canonicalNonce: string): value is readonly string[] {
  if (!Array.isArray(value) || value.length === 0 || value.length > MAX_OBSERVED_NONCES) return false;
  if (!value.every((nonce) => isSafeIdentifier(nonce))) return false;
  if (new Set(value).size !== value.length) return false;
  return value[0] === canonicalNonce && value.includes(canonicalNonce);
}

/**
 * Read an untrusted record exactly once into a plain, immutable snapshot. Returning the
 * original object would let a stateful getter pass validation and throw when the ledger
 * reads it again for replay, identity, or transition decisions. The snapshot is the only
 * validated history representation exposed to callers of `validateLedgerHistory`.
 */
export function snapshotLedgerRecord(value: unknown): CompletionLedgerRecord | null {
  try {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
    const source = value as Record<string, unknown>;
    const sourceObservedNonces = source.observedNonces;
    // Copy an array candidate before validating it. Validation and later consumers must
    // use the exact same immutable values; a custom iterator that changes between passes
    // must never smuggle an unvalidated nonce into the frozen snapshot.
    const observedNonces = Array.isArray(sourceObservedNonces)
      ? Object.freeze([...sourceObservedNonces])
      : sourceObservedNonces;
    const snapshot = {
      providerId: source.providerId,
      offerId: source.offerId,
      providerTransactionId: source.providerTransactionId,
      externalUserId: source.externalUserId,
      actionType: source.actionType,
      state: source.state,
      rewardAmountMinor: source.rewardAmountMinor,
      rewardCurrency: source.rewardCurrency,
      providerOccurredAt: source.providerOccurredAt,
      firstObservedAt: source.firstObservedAt,
      lastObservedAt: source.lastObservedAt,
      nonce: source.nonce,
      observedNonces,
    } as unknown as CompletionLedgerRecord;
    if (!isValidLedgerRecord(snapshot)) return null;
    return Object.freeze({ ...snapshot, observedNonces: observedNonces as readonly string[] });
  } catch {
    return null;
  }
}

/**
 * The single authoritative definition of a well-formed historical ledger record.
 *
 * A record is malformed when any identifier (provider, offer, transaction, user,
 * action, state, canonical nonce, observed nonces) is missing, padded, or contains a
 * control character; when the currency is not an uppercase ISO-4217-shaped code; when
 * the reward amount is zero, negative, fractional, non-finite, or outside the safe
 * integer range; when any of the three timestamps is unparseable; or when the
 * timestamps contradict the contract they are written under.
 */
export function isValidLedgerRecord(value: unknown): value is CompletionLedgerRecord {
  try {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  if (!isSafeIdentifier(record.providerId)) return false;
  if (!isSafeIdentifier(record.offerId)) return false;
  if (!isSafeIdentifier(record.providerTransactionId)) return false;
  if (!isSafeIdentifier(record.externalUserId)) return false;
  if (record.actionType !== 'TRYOUT_COMPLETED' && record.actionType !== 'QUALITY_CHECK_COMPLETED') return false;
  if (record.state !== 'COMPLETED' && record.state !== 'REVERSED') return false;
  if (!validMinorAmount(record.rewardAmountMinor)) return false;
  if (typeof record.rewardCurrency !== 'string' || !/^[A-Z]{3}$/.test(record.rewardCurrency)) return false;
  if (!isSafeIdentifier(record.nonce)) return false;
  if (!validObservedNonces(record.observedNonces, record.nonce)) return false;
  if (!validTimestamp(record.providerOccurredAt)) return false;
  if (!validTimestamp(record.firstObservedAt)) return false;
  if (!validTimestamp(record.lastObservedAt)) return false;
  // Timestamp ownership is part of the contract, so it is validated as data:
  // `lastObservedAt` never precedes `firstObservedAt`, and the provider's reported
  // occurrence time never sits outside the documented skew of the server-owned first
  // observation. A record whose own timestamps contradict each other is malformed even
  // though every individual field parses.
  const firstObserved = Date.parse(record.firstObservedAt);
  const lastObserved = Date.parse(record.lastObservedAt);
  const providerOccurred = Date.parse(record.providerOccurredAt);
    if (lastObserved < firstObserved) return false;
    if (Math.abs(providerOccurred - firstObserved) > MAX_PROVIDER_CLOCK_SKEW_MS) return false;
    return true;
  } catch {
    return false;
  }
}

/**
 * Sum minor-unit amounts with checked addition. A running total that ever leaves the
 * safe-integer range is reported as `null` so callers fail closed instead of
 * crediting a rounded, inexact total.
 */
export function safeSumMinor(amounts: readonly number[]): number | null {
  let total = 0;
  for (const amount of amounts) {
    if (!Number.isSafeInteger(amount) || amount < 0) return null;
    total += amount;
    if (!Number.isSafeInteger(total)) return null;
  }
  return total;
}

export interface LedgerUsage {
  readonly completedByUser: number;
  readonly completedCount: number;
  readonly creditedMinor: number;
}

export interface ValidatedLedgerHistory {
  /**
   * Every supplied record, validated. A caller that receives `ok: true` may rely on
   * every record being well formed, so no valid sibling can mask a malformed one.
   */
  readonly records: readonly CompletionLedgerRecord[];
  /** Already-computed usage for the supplied offer, currency, and user. Never unchecked. */
  readonly usage: LedgerUsage;
}

export type LedgerHistoryRejection =
  | 'HISTORY_NOT_A_LIST'
  | 'HISTORY_ACCESS_THREW'
  | 'MALFORMED_RECORD'
  | 'DUPLICATE_RECORD_KEY'
  | 'DUPLICATE_NONCE_OWNER'
  | 'UNSAFE_AGGREGATE_SUM';

export type LedgerHistoryValidation =
  | { readonly ok: true; readonly history: ValidatedLedgerHistory }
  | { readonly ok: false; readonly reason: LedgerHistoryRejection };

/**
 * Validate the complete authoritative history supplied by the caller, then compute
 * the usage that the offer, its currency, and one user would draw on.
 *
 * Order is load-bearing: every record is checked first, so a malformed sibling is
 * never skipped by a filter, and only then are aggregates summed with checked
 * addition. This is pure source: it reads the array it is given, stores nothing, and
 * contacts no provider.
 */
export function validateLedgerHistory(
  records: unknown,
  offer: Pick<TryoutOffer, 'providerId' | 'offerId' | 'rewardCurrency'>,
  externalUserId: string,
): LedgerHistoryValidation {
  try {
    if (!Array.isArray(records)) return { ok: false, reason: 'HISTORY_NOT_A_LIST' };

    const recordKeys = new Set<string>();
    const nonceKeys = new Set<string>();
    const snapshots: CompletionLedgerRecord[] = [];
    // Partial valid records can never mask invalid history: one malformed entry fails
    // the whole history closed, before any replay, usage, duplicate, or reversal work.
    for (const candidate of records) {
      const record = snapshotLedgerRecord(candidate);
      if (record === null) return { ok: false, reason: 'MALFORMED_RECORD' };
      snapshots.push(record);

      const recordKey = `${record.providerId}\u0000${record.offerId}\u0000${record.providerTransactionId}`;
      if (recordKeys.has(recordKey)) return { ok: false, reason: 'DUPLICATE_RECORD_KEY' };
      recordKeys.add(recordKey);

      for (const observedNonce of record.observedNonces) {
        const nonceKey = `${record.providerId}\u0000${observedNonce}`;
        if (nonceKeys.has(nonceKey)) return { ok: false, reason: 'DUPLICATE_NONCE_OWNER' };
        nonceKeys.add(nonceKey);
      }
    }

    const relevant = snapshots.filter((record) => record.providerId === offer.providerId
      && record.offerId === offer.offerId
      && record.rewardCurrency === offer.rewardCurrency
      && record.state === 'COMPLETED');
    const completedByUser = relevant.filter((record) => record.externalUserId === externalUserId).length;
    const creditedMinor = safeSumMinor(relevant.map((record) => record.rewardAmountMinor));
    // An unsafe aggregate is not a balance. Fail closed rather than comparing a budget
    // against a rounded total that a malformed history produced.
    if (creditedMinor === null) return { ok: false, reason: 'UNSAFE_AGGREGATE_SUM' };

    return {
      ok: true,
      history: {
        records: Object.freeze([...snapshots]),
        usage: { completedByUser, completedCount: relevant.length, creditedMinor },
      },
    };
  } catch {
    // A hostile proxy, throwing getter, or throwing iterator is not a valid history
    // object. It must return the same fail-closed contract rather than escaping.
    return { ok: false, reason: 'HISTORY_ACCESS_THREW' };
  }
}

/**
 * Checked addition used for every budget comparison against an already-validated
 * aggregate. Returns `null` when the prospective total would leave the safe-integer
 * range, so an unsafe total is rejected rather than compared.
 */
export function safeAddMinor(left: number, right: number): number | null {
  if (!Number.isSafeInteger(left) || !Number.isSafeInteger(right) || left < 0 || right < 0) return null;
  const total = left + right;
  return Number.isSafeInteger(total) ? total : null;
}
