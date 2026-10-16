import type { CompletionLedgerRecord, CompletionTransitionDecision } from './domain.js';
import type { PointsClaimAssessment } from './claim.js';

/**
 * Safe, allowlisted projection of a ledger record. It is built field by field from a
 * known schema, so no signature, secret, token, or raw provider payload can leak in
 * through an unexpected or extra property.
 */
export interface SafeLedgerRecordView {
  readonly providerId: string;
  readonly offerId: string;
  readonly providerTransactionId: string;
  readonly externalUserId: string;
  readonly actionType: string;
  readonly state: 'COMPLETED' | 'REVERSED';
  readonly rewardAmountMinor: number;
  readonly rewardCurrency: string;
  readonly providerOccurredAt: string;
  readonly firstObservedAt: string;
  readonly lastObservedAt: string;
}

export interface SafeTransitionView {
  readonly decision: string;
  readonly balanceDeltaMinor: number;
  readonly appendImmutableAuditEvent: boolean;
  readonly externalPayoutAllowed: false;
  readonly next: SafeLedgerRecordView | null;
}

/** Safe, allowlisted projection of a claim assessment. */
export interface SafeClaimView {
  readonly decision: string;
  readonly claimAmountMinor: number;
  readonly availableMinor: number;
  readonly claimableMinor: number;
  readonly claimAccepted: boolean;
  readonly payoutAllowed: false;
  readonly livePayoutEnabled: boolean;
  readonly payoutBlockReason: string;
}

export function toSafeLedgerRecordView(record: CompletionLedgerRecord): SafeLedgerRecordView {
  return Object.freeze({
    providerId: record.providerId,
    offerId: record.offerId,
    providerTransactionId: record.providerTransactionId,
    externalUserId: record.externalUserId,
    actionType: record.actionType,
    state: record.state,
    rewardAmountMinor: record.rewardAmountMinor,
    rewardCurrency: record.rewardCurrency,
    providerOccurredAt: record.providerOccurredAt,
    firstObservedAt: record.firstObservedAt,
    lastObservedAt: record.lastObservedAt,
  });
}

export function toSafeTransitionView(decision: CompletionTransitionDecision): SafeTransitionView {
  return Object.freeze({
    decision: decision.decision,
    balanceDeltaMinor: decision.balanceDeltaMinor,
    appendImmutableAuditEvent: decision.appendImmutableAuditEvent,
    externalPayoutAllowed: decision.externalPayoutAllowed,
    next: decision.next === null ? null : toSafeLedgerRecordView(decision.next),
  });
}

export function toSafeClaimView(assessment: PointsClaimAssessment): SafeClaimView {
  return Object.freeze({
    decision: assessment.decision,
    claimAmountMinor: assessment.claimAmountMinor,
    availableMinor: assessment.availableMinor,
    claimableMinor: assessment.claimableMinor,
    claimAccepted: assessment.claimAccepted,
    payoutAllowed: assessment.payoutAllowed,
    livePayoutEnabled: assessment.livePayoutEnabled,
    payoutBlockReason: assessment.payoutBlockReason,
  });
}

/**
 * The nonce and the observed-nonce history are internal replay keys, not caller-facing
 * data. They are deliberately absent from every safe projection above.
 */
export const SAFE_PROJECTION_OMITTED_FIELDS = Object.freeze(['nonce', 'observedNonces', 'signature', 'rawBody', 'secret', 'signatureHeader']);
