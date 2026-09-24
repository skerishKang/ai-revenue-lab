import type { CompletionLedgerRecord, CompletionTransitionDecision, SignedCompletionEvent, TryoutOffer } from './domain.js';
import { isVerifiedCompletionEnvelope } from './signed-completion.js';
import type { VerifiedCompletionEnvelope } from './signed-completion.js';

export interface LedgerUsage {
  readonly completedByUser: number;
  readonly completedCount: number;
  readonly creditedMinor: number;
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

function result(decision: CompletionTransitionDecision['decision'], next: CompletionLedgerRecord | null, balanceDeltaMinor = 0, appendImmutableAuditEvent = false): CompletionTransitionDecision {
  return Object.freeze({ decision, next, balanceDeltaMinor, appendImmutableAuditEvent, externalPayoutAllowed: false as const });
}

function validOffer(offer: TryoutOffer): boolean {
  const startsAt = Date.parse(offer.startsAt);
  const endsAt = offer.endsAt === null ? null : Date.parse(offer.endsAt);
  return typeof offer.offerId === 'string' && offer.offerId.length > 0
    && typeof offer.providerId === 'string' && offer.providerId.length > 0
    && (offer.actionType === 'TRYOUT_COMPLETED' || offer.actionType === 'QUALITY_CHECK_COMPLETED')
    && Number.isSafeInteger(offer.rewardAmountMinor) && offer.rewardAmountMinor > 0
    && /^[A-Z]{3}$/.test(offer.rewardCurrency)
    && Number.isSafeInteger(offer.perUserLimit) && offer.perUserLimit > 0
    && Number.isSafeInteger(offer.fundedBudgetMinor) && offer.fundedBudgetMinor > 0
    && Number.isFinite(startsAt)
    && (endsAt === null || (Number.isFinite(endsAt) && endsAt > startsAt));
}

function validText(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0 && value.length <= 256;
}

function validEventForLedger(event: SignedCompletionEvent): boolean {
  return validText(event.providerId)
    && validText(event.offerId)
    && validText(event.providerTransactionId)
    && validText(event.externalUserId)
    && validText(event.nonce)
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

function createRecord(event: SignedCompletionEvent): CompletionLedgerRecord {
  return Object.freeze({
    providerId: event.providerId,
    offerId: event.offerId,
    providerTransactionId: event.providerTransactionId,
    externalUserId: event.externalUserId,
    actionType: event.actionType,
    state: 'COMPLETED',
    rewardAmountMinor: event.rewardAmountMinor,
    rewardCurrency: event.rewardCurrency,
    firstObservedAt: event.occurredAt,
    lastObservedAt: event.occurredAt,
  });
}

/**
 * Product-local points ledger transition. It consumes only a signature-verified
 * event envelope and never performs network, payout, or user-balance custody.
 */
export function applyVerifiedCompletion(
  records: readonly CompletionLedgerRecord[],
  offer: TryoutOffer,
  envelope: VerifiedCompletionEnvelope,
  observedAt: string,
): CompletionTransitionDecision {
  if (!isVerifiedCompletionEnvelope(envelope)) return result('REJECT_INVALID_EVENT', null, 0, true);
  const event = envelope.event;
  if (event.actionType === 'CLICK' || event.actionType === 'VISIT') return result('REJECT_CLICK_OR_VISIT', null, 0, true);
  if (event.actionType !== 'TRYOUT_COMPLETED' && event.actionType !== 'QUALITY_CHECK_COMPLETED') return result('REJECT_INVALID_EVENT', null, 0, true);
  if (event.providerId !== offer.providerId || event.offerId !== offer.offerId) return result('REJECT_OFFER_IDENTITY_MISMATCH', null, 0, true);
  if (event.actionType !== offer.actionType) return result('REJECT_IDENTITY_OR_VALUE_MISMATCH', null, 0, true);
  if (!validOffer(offer) || !validEventForLedger(event) || !Number.isFinite(Date.parse(observedAt))) return result('REJECT_INVALID_EVENT', null, 0, true);

  const existing = records.find((record) => record.providerId === event.providerId && record.providerTransactionId === event.providerTransactionId);
  if (existing) {
    if (!sameIdentityAndValue(existing, event)) return result('REJECT_IDENTITY_OR_VALUE_MISMATCH', null, 0, true);
    if (existing.state === 'REVERSED') return result(event.eventType === 'REVERSED' ? 'IGNORE_IDEMPOTENT_DUPLICATE' : 'REJECT_REOPEN_AFTER_REVERSAL', null, 0, true);
    if (event.eventType === 'COMPLETED') return result('IGNORE_IDEMPOTENT_DUPLICATE', existing);
    const next = Object.freeze({ ...existing, state: 'REVERSED' as const, lastObservedAt: observedAt });
    return result('REVERSE_COMPLETED_ACTION', next, -existing.rewardAmountMinor, true);
  }

  if (event.eventType === 'REVERSED') return result('REJECT_ORPHAN_REVERSAL', null, 0, true);
  if (offer.state !== 'ACTIVE' || Date.parse(observedAt) < Date.parse(offer.startsAt) || (offer.endsAt !== null && Date.parse(observedAt) > Date.parse(offer.endsAt))) {
    return result('REJECT_OFFER_NOT_ACTIVE', null, 0, true);
  }
  if (event.rewardAmountMinor !== offer.rewardAmountMinor || event.rewardCurrency !== offer.rewardCurrency) return result('REJECT_IDENTITY_OR_VALUE_MISMATCH', null, 0, true);

  const current = usage(records, offer, event.externalUserId);
  if (current.completedByUser >= offer.perUserLimit) return result('REJECT_PER_USER_LIMIT', null, 0, true);
  if (current.creditedMinor + event.rewardAmountMinor > offer.fundedBudgetMinor) return result('REJECT_FUNDED_BUDGET_EXHAUSTED', null, 0, true);

  return result('CREDIT_COMPLETED_ACTION', createRecord(event), event.rewardAmountMinor, true);
}
