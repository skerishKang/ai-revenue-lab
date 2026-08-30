import type { RewardStateRecord } from './reward-events.js';

export const PAYOUT_CLAIM_STATES = [
  'BLOCKED_NOT_CONFIRMED',
  'CONFIRMED_RISK_HOLD',
  'CONFIRMED_BELOW_EXTERNAL_MINIMUM',
  'ELIGIBLE_FOR_EXTERNAL_FULFILLMENT',
  'REVERSED_BEFORE_FULFILLMENT',
] as const;
export type PayoutClaimState = (typeof PAYOUT_CLAIM_STATES)[number];

export interface PayoutRiskPolicy {
  /** Provider/contract-derived timestamp after which this conversion is eligible to leave risk hold. */
  readonly riskHoldUntil: string | null;
  /** Must identify the authority used for the hold, e.g. provider contract, dashboard setting or approved B64 risk policy. */
  readonly riskHoldAuthority: string | null;
  /** Minimum order denomination from the currently live external fulfillment product/catalog. */
  readonly externalMinimumAmount: number | null;
  readonly externalMinimumCurrency: string | null;
  /** Explicitly approved economics mapping between provider reward and external payout face value. */
  readonly payoutFaceValueAmount: number | null;
  readonly payoutFaceValueCurrency: string | null;
}

export interface PayoutClaimAssessmentInput {
  readonly transaction: RewardStateRecord;
  readonly policy: PayoutRiskPolicy;
  readonly now: string;
}

export interface PayoutClaimAssessment {
  readonly state: PayoutClaimState;
  readonly mayEnterExternalFulfillment: boolean;
  readonly nonTransferableAccountingClaimOnly: true;
  readonly userDepositsAccepted: false;
  readonly peerToPeerTransferAllowed: false;
  readonly b64CashCustody: false;
  readonly reasons: readonly string[];
}

function validPositive(value: number | null): value is number {
  return value !== null && Number.isFinite(value) && value > 0;
}

function validTimestamp(value: string | null): value is string {
  return value !== null && Number.isFinite(Date.parse(value));
}

/**
 * B64 may keep an accounting claim that a confirmed ad conversion is owed a reward,
 * but this is not a transferable wallet or stored-value account. External fulfillment
 * is fail-closed until provider risk timing and live payout denomination are known.
 */
export function assessPayoutClaim(input: PayoutClaimAssessmentInput): PayoutClaimAssessment {
  const base = {
    nonTransferableAccountingClaimOnly: true as const,
    userDepositsAccepted: false as const,
    peerToPeerTransferAllowed: false as const,
    b64CashCustody: false as const,
  };

  if (input.transaction.state === 'REVERSED') {
    return Object.freeze({
      ...base,
      state: 'REVERSED_BEFORE_FULFILLMENT' as const,
      mayEnterExternalFulfillment: false,
      reasons: Object.freeze(['PROVIDER_REVERSED']),
    });
  }

  if (input.transaction.state !== 'CONFIRMED') {
    return Object.freeze({
      ...base,
      state: 'BLOCKED_NOT_CONFIRMED' as const,
      mayEnterExternalFulfillment: false,
      reasons: Object.freeze(['PROVIDER_CONFIRMATION_REQUIRED']),
    });
  }

  const nowMs = Date.parse(input.now);
  if (!Number.isFinite(nowMs)) {
    return Object.freeze({
      ...base,
      state: 'CONFIRMED_RISK_HOLD' as const,
      mayEnterExternalFulfillment: false,
      reasons: Object.freeze(['CURRENT_TIME_INVALID']),
    });
  }

  if (!validTimestamp(input.policy.riskHoldUntil) || !input.policy.riskHoldAuthority?.trim()) {
    return Object.freeze({
      ...base,
      state: 'CONFIRMED_RISK_HOLD' as const,
      mayEnterExternalFulfillment: false,
      reasons: Object.freeze(['RISK_HOLD_POLICY_NOT_ESTABLISHED']),
    });
  }

  if (nowMs < Date.parse(input.policy.riskHoldUntil)) {
    return Object.freeze({
      ...base,
      state: 'CONFIRMED_RISK_HOLD' as const,
      mayEnterExternalFulfillment: false,
      reasons: Object.freeze(['RISK_HOLD_NOT_EXPIRED']),
    });
  }

  if (
    !validPositive(input.policy.externalMinimumAmount)
    || !input.policy.externalMinimumCurrency?.trim()
    || !validPositive(input.policy.payoutFaceValueAmount)
    || !input.policy.payoutFaceValueCurrency?.trim()
  ) {
    return Object.freeze({
      ...base,
      state: 'CONFIRMED_BELOW_EXTERNAL_MINIMUM' as const,
      mayEnterExternalFulfillment: false,
      reasons: Object.freeze(['LIVE_PAYOUT_DENOMINATION_OR_FACE_VALUE_NOT_ESTABLISHED']),
    });
  }

  if (input.policy.externalMinimumCurrency.toUpperCase() !== input.policy.payoutFaceValueCurrency.toUpperCase()) {
    return Object.freeze({
      ...base,
      state: 'CONFIRMED_BELOW_EXTERNAL_MINIMUM' as const,
      mayEnterExternalFulfillment: false,
      reasons: Object.freeze(['PAYOUT_CURRENCY_MISMATCH']),
    });
  }

  if (input.policy.payoutFaceValueAmount < input.policy.externalMinimumAmount) {
    return Object.freeze({
      ...base,
      state: 'CONFIRMED_BELOW_EXTERNAL_MINIMUM' as const,
      mayEnterExternalFulfillment: false,
      reasons: Object.freeze(['PAYOUT_FACE_VALUE_BELOW_LIVE_EXTERNAL_MINIMUM']),
    });
  }

  return Object.freeze({
    ...base,
    state: 'ELIGIBLE_FOR_EXTERNAL_FULFILLMENT' as const,
    mayEnterExternalFulfillment: true,
    reasons: Object.freeze([]),
  });
}

export interface PayoutBatchCandidate {
  readonly claimId: string;
  readonly externalUserId: string;
  readonly assessment: PayoutClaimAssessment;
  readonly payoutFaceValueAmount: number;
  readonly payoutFaceValueCurrency: string;
}

/**
 * Optional batching is accounting-only. It does not create a user-controlled balance,
 * permit deposits/transfers, or create an external reward order. Every included claim
 * must already be individually eligible under the risk and denomination policy.
 */
export function buildEligiblePayoutBatch(candidates: readonly PayoutBatchCandidate[]): readonly PayoutBatchCandidate[] {
  return Object.freeze(candidates.filter((candidate) => (
    candidate.assessment.mayEnterExternalFulfillment
    && candidate.assessment.state === 'ELIGIBLE_FOR_EXTERNAL_FULFILLMENT'
    && Number.isFinite(candidate.payoutFaceValueAmount)
    && candidate.payoutFaceValueAmount > 0
    && candidate.payoutFaceValueCurrency.trim().length > 0
  )));
}
