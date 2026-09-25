import {
  MAX_OBSERVED_NONCES,
  MAX_PROVIDER_CLOCK_SKEW_MS,
  isSafeIdentifier,
  type CompletionLedgerRecord,
  type CompletionTransitionDecision,
  type CompletionTransitionDecisionCode,
  type SignedCompletionEvent,
  type TryoutOffer,
} from './domain.js';
import { isVerifiedCompletionEnvelope } from './signed-completion.js';
import type { VerifiedCompletionEnvelope } from './signed-completion.js';

export interface LedgerUsage {
  readonly completedByUser: number;
  readonly completedCount: number;
  readonly creditedMinor: number;
}

export interface ApplyVerifiedCompletionOptions {
  /**
   * Overridable provider-clock drift bound. Must be a positive safe integer no larger
   * than `MAX_PROVIDER_CLOCK_SKEW_MS`; an over-large bound fails closed rather than
   * silently widening the accepted window.
   */
  readonly maxProviderClockSkewMs?: number;
}

/**
 * Deterministic record key. A provider transaction is unique within one provider and
 * offer, so the same provider transaction id may exist under two different offers.
 * No identifier may contain a control character, so the NUL join cannot be forged.
 */
export function completionRecordKey(providerId: string, offerId: string, providerTransactionId: string): string {
  return `${providerId}\u0000${offerId}\u0000${providerTransactionId}`;
}

/** Deterministic replay key. Separate from the record key: a nonce is provider-scoped. */
export function completionNonceKey(providerId: string, nonce: string): string {
  return `${providerId}\u0000${nonce}`;
}

export function recordKeyOf(record: CompletionLedgerRecord): string {
  return completionRecordKey(record.providerId, record.offerId, record.providerTransactionId);
}

export function nonceKeyOf(record: CompletionLedgerRecord): string {
  return completionNonceKey(record.providerId, record.nonce);
}

/**
 * Every distinct provider+nonce identity remembered for a record, as replay keys. A
 * single record field cannot soundly represent replay, because a provider may re-issue
 * a duplicate completion or a reversal under a new nonce: the record therefore carries
 * the bounded `observedNonces` list in addition to its canonical `nonce`.
 */
export function observedNonceKeysOf(record: CompletionLedgerRecord): readonly string[] {
  return Object.freeze([...new Set(record.observedNonces.map((nonce) => completionNonceKey(record.providerId, nonce)))]);
}

function usage(records: readonly CompletionLedgerRecord[], offer: TryoutOffer, userId: string): LedgerUsage {
  const relevant = records.filter((record) => record.providerId === offer.providerId
    && record.offerId === offer.offerId
    && record.rewardCurrency === offer.rewardCurrency
    && record.state === 'COMPLETED');
  const userCount = relevant.filter((record) => record.externalUserId === userId).length;
  return {
    completedByUser: userCount,
    completedCount: relevant.length,
    creditedMinor: relevant.reduce((sum, record) => sum + record.rewardAmountMinor, 0),
  };
}

function result(
  decision: CompletionTransitionDecisionCode,
  next: CompletionLedgerRecord | null,
  balanceDeltaMinor: number,
  appendImmutableAuditEvent: boolean,
): CompletionTransitionDecision {
  return Object.freeze({ decision, next, balanceDeltaMinor, appendImmutableAuditEvent, externalPayoutAllowed: false as const });
}

/** Rejection and no-op paths. These never request an append-only audit write. */
function reject(decision: CompletionTransitionDecisionCode): CompletionTransitionDecision {
  return result(decision, null, 0, false);
}

function validOffer(offer: TryoutOffer): boolean {
  const startsAt = Date.parse(offer.startsAt);
  const endsAt = offer.endsAt === null ? null : Date.parse(offer.endsAt);
  return isSafeIdentifier(offer.offerId)
    && isSafeIdentifier(offer.providerId)
    && (offer.actionType === 'TRYOUT_COMPLETED' || offer.actionType === 'QUALITY_CHECK_COMPLETED')
    && Number.isSafeInteger(offer.rewardAmountMinor) && offer.rewardAmountMinor > 0
    && /^[A-Z]{3}$/.test(offer.rewardCurrency)
    && Number.isSafeInteger(offer.perUserLimit) && offer.perUserLimit > 0
    && Number.isSafeInteger(offer.fundedBudgetMinor) && offer.fundedBudgetMinor > 0
    && Number.isFinite(startsAt)
    && (endsAt === null || (Number.isFinite(endsAt) && endsAt > startsAt));
}

function validEventForLedger(event: SignedCompletionEvent): boolean {
  return isSafeIdentifier(event.providerId)
    && isSafeIdentifier(event.offerId)
    && isSafeIdentifier(event.providerTransactionId)
    && isSafeIdentifier(event.externalUserId)
    && isSafeIdentifier(event.nonce)
    && (event.actionType === 'TRYOUT_COMPLETED' || event.actionType === 'QUALITY_CHECK_COMPLETED')
    && (event.eventType === 'COMPLETED' || event.eventType === 'REVERSED')
    && Number.isSafeInteger(event.rewardAmountMinor) && event.rewardAmountMinor > 0
    && /^[A-Z]{3}$/.test(event.rewardCurrency)
    && Number.isFinite(Date.parse(event.occurredAt));
}

function sameIdentityAndValue(current: CompletionLedgerRecord, event: SignedCompletionEvent): boolean {
  return current.providerId === event.providerId
    && current.offerId === event.offerId
    && current.externalUserId === event.externalUserId
    && current.actionType === event.actionType
    && current.rewardAmountMinor === event.rewardAmountMinor
    && current.rewardCurrency === event.rewardCurrency;
}

function createRecord(event: SignedCompletionEvent, observedAt: string): CompletionLedgerRecord {
  return Object.freeze({
    providerId: event.providerId,
    offerId: event.offerId,
    providerTransactionId: event.providerTransactionId,
    externalUserId: event.externalUserId,
    actionType: event.actionType,
    state: 'COMPLETED',
    rewardAmountMinor: event.rewardAmountMinor,
    rewardCurrency: event.rewardCurrency,
    providerOccurredAt: event.occurredAt,
    firstObservedAt: observedAt,
    lastObservedAt: observedAt,
    nonce: event.nonce,
    observedNonces: Object.freeze([event.nonce]),
  });
}

/**
 * Register a newly observed provider+nonce identity on an existing record, preserving
 * append-only history. The list is bounded: an already-seen nonce is a no-op, a new
 * nonce is appended, and exceeding `MAX_OBSERVED_NONCES` fails closed rather than
 * dropping a nonce (which would reopen a replay hole). The canonical `nonce` field
 * and the completion evidence are never rewritten.
 */
function withObservedNonce(
  record: CompletionLedgerRecord,
  nonce: string,
  observedAt: string,
): CompletionLedgerRecord | null {
  const observed = record.observedNonces;
  if (observed.includes(nonce)) return record;
  if (observed.length >= MAX_OBSERVED_NONCES) return null;
  return Object.freeze({
    ...record,
    lastObservedAt: observedAt,
    observedNonces: Object.freeze([...observed, nonce]),
  });
}

/**
 * Product-local points ledger transition. It consumes only a signature-verified
 * event envelope and never performs network, payout, or user-balance custody.
 *
 * Audit policy: an append-only audit event is requested only when an authenticated
 * callback causes a real state transition (credit, reversal) or a meaningful
 * authenticated conflict. Every rejection, every idempotent duplicate, and all
 * unauthenticated input return `appendImmutableAuditEvent: false`.
 */
export function applyVerifiedCompletion(
  records: readonly CompletionLedgerRecord[],
  offer: TryoutOffer,
  envelope: VerifiedCompletionEnvelope,
  observedAt: string,
  options: ApplyVerifiedCompletionOptions = {},
): CompletionTransitionDecision {
  // Unauthenticated input is rejected before any authority, conflict, or audit decision.
  if (!isVerifiedCompletionEnvelope(envelope)) return reject('REJECT_INVALID_EVENT');
  const event = envelope.event;
  if (event.actionType === 'CLICK' || event.actionType === 'VISIT') return reject('REJECT_CLICK_OR_VISIT');
  if (event.actionType !== 'TRYOUT_COMPLETED' && event.actionType !== 'QUALITY_CHECK_COMPLETED') return reject('REJECT_INVALID_EVENT');
  if (event.providerId !== offer.providerId || event.offerId !== offer.offerId) return reject('REJECT_OFFER_IDENTITY_MISMATCH');
  if (event.actionType !== offer.actionType) return reject('REJECT_IDENTITY_OR_VALUE_MISMATCH');
  if (!validOffer(offer) || !validEventForLedger(event) || !Number.isFinite(Date.parse(observedAt))) return reject('REJECT_INVALID_EVENT');

  const maxSkew = options.maxProviderClockSkewMs ?? MAX_PROVIDER_CLOCK_SKEW_MS;
  // An over-large bound is a configuration error, not permission to widen the window.
  if (!Number.isSafeInteger(maxSkew) || maxSkew <= 0 || maxSkew > MAX_PROVIDER_CLOCK_SKEW_MS) return reject('REJECT_INVALID_EVENT');
  if (Math.abs(Date.parse(observedAt) - Date.parse(event.occurredAt)) > maxSkew) return reject('REJECT_PROVIDER_CLOCK_SKEW');

  // Replay protection: one provider+nonce may only ever describe one transaction.
  // A record remembers every nonce ever observed for it, so a nonce first seen on a
  // duplicate completion or on a reversal is equally bound to this transaction.
  const nonceKey = completionNonceKey(event.providerId, event.nonce);
  const nonceOwner = records.find((record) => observedNonceKeysOf(record).includes(nonceKey));
  if (nonceOwner && (nonceOwner.offerId !== event.offerId || nonceOwner.providerTransactionId !== event.providerTransactionId)) {
    return result('REJECT_NONCE_REPLAY', null, 0, true);
  }

  const recordKey = completionRecordKey(event.providerId, event.offerId, event.providerTransactionId);
  const existing = records.find((record) => recordKeyOf(record) === recordKey);
  if (existing) {
    if (!sameIdentityAndValue(existing, event)) return reject('REJECT_IDENTITY_OR_VALUE_MISMATCH');
    // The incoming callback observes a provider+nonce identity for this transaction,
    // even when it is a duplicate. Remember it so a later reuse for a different
    // transaction is detected. Re-observing an already-remembered nonce is a no-op.
    const registered = withObservedNonce(existing, event.nonce, observedAt);
    if (registered === null) return reject('REJECT_NONCE_HISTORY_EXHAUSTED');
    if (existing.state === 'REVERSED') {
      // A duplicate REVERSED is idempotent: return the preserved reversed record,
      // zero delta, and no bogus audit event. It never reopens.
      if (event.eventType === 'REVERSED') return result('IGNORE_IDEMPOTENT_DUPLICATE', registered, 0, false);
      return result('REJECT_REOPEN_AFTER_REVERSAL', null, 0, true);
    }
    if (event.eventType === 'COMPLETED') return result('IGNORE_IDEMPOTENT_DUPLICATE', registered, 0, false);
    // Reversal preserves completion history: providerOccurredAt, firstObservedAt,
    // the canonical nonce, and every already-observed nonce are carried forward
    // untouched. Only lastObservedAt advances.
    const next = Object.freeze({ ...registered, state: 'REVERSED' as const, lastObservedAt: observedAt });
    return result('REVERSE_COMPLETED_ACTION', next, -existing.rewardAmountMinor, true);
  }

  if (event.eventType === 'REVERSED') return reject('REJECT_ORPHAN_REVERSAL');
  if (offer.state !== 'ACTIVE' || Date.parse(observedAt) < Date.parse(offer.startsAt) || (offer.endsAt !== null && Date.parse(observedAt) > Date.parse(offer.endsAt))) {
    return reject('REJECT_OFFER_NOT_ACTIVE');
  }
  if (event.rewardAmountMinor !== offer.rewardAmountMinor || event.rewardCurrency !== offer.rewardCurrency) return reject('REJECT_IDENTITY_OR_VALUE_MISMATCH');

  const current = usage(records, offer, event.externalUserId);
  if (current.completedByUser >= offer.perUserLimit) return reject('REJECT_PER_USER_LIMIT');
  if (current.creditedMinor + event.rewardAmountMinor > offer.fundedBudgetMinor) return reject('REJECT_FUNDED_BUDGET_EXHAUSTED');

  return result('CREDIT_COMPLETED_ACTION', createRecord(event, observedAt), event.rewardAmountMinor, true);
}
