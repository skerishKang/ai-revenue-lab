import type { RewardTransaction } from './reward-events.js';

export const REWARD_FULFILLMENT_PROVIDER_STRATEGY = Object.freeze([
  Object.freeze({
    providerId: 'TREMENDOUS',
    rank: 1,
    koreaRecipientSupport: 'OFFICIAL_SUPPORTED' as const,
    koreaRewardOptions: Object.freeze(['NAVER_PAY', 'TEENCASH', 'PAYPAL_INTERNATIONAL', 'VIRTUAL_VISA'] as const),
    api: 'OFFICIAL_SUPPORTED' as const,
    idempotency: 'EXTERNAL_ID_SUPPORTED' as const,
    productionAccess: 'COMPLIANCE_APPROVAL_REQUIRED' as const,
    activateForB64: false,
  }),
  Object.freeze({
    providerId: 'GIFTBIT',
    rank: 2,
    koreaRecipientSupport: 'OFFICIAL_SUPPORTED' as const,
    koreaRewardOptions: Object.freeze(['LOCAL_DIGITAL_REWARDS', 'GLOBAL_PREPAID_OPTIONS'] as const),
    api: 'OFFICIAL_SUPPORTED' as const,
    idempotency: 'CLIENT_ORDER_ID_SUPPORTED' as const,
    productionAccess: 'KYB_REVIEW_REQUIRED' as const,
    activateForB64: false,
  }),
]);

export type RewardFulfillmentReadinessState =
  | 'BLOCKED_NOT_PROVIDER_CONFIRMED'
  | 'BLOCKED_REWARD_VALUE_INVALID'
  | 'BLOCKED_PROVIDER_NOT_APPROVED'
  | 'BLOCKED_PAYOUT_POLICY_NOT_READY'
  | 'BLOCKED_CHARGEBACK_RISK_NOT_READY'
  | 'READY_FOR_EXTERNAL_FULFILLMENT';

export interface RewardFulfillmentAssessmentInput {
  readonly transaction: RewardTransaction;
  readonly rewardFaceValue: number;
  readonly rewardCurrency: string;
  readonly externalFulfillmentProviderApproved: boolean;
  readonly payoutPolicyApproved: boolean;
  readonly chargebackReservePolicyReady: boolean;
}

export interface RewardFulfillmentAssessment {
  readonly state: RewardFulfillmentReadinessState;
  readonly mayCreateExternalRewardOrder: boolean;
  readonly b64UserCashCustody: false;
}

/**
 * User payout never starts from a client-side/provisional ad event.
 * A provider-confirmed reward transaction plus payout/chargeback policy is required.
 */
export function assessRewardFulfillment(
  input: RewardFulfillmentAssessmentInput,
): RewardFulfillmentAssessment {
  if (input.transaction.state !== 'CONFIRMED') {
    return Object.freeze({ state: 'BLOCKED_NOT_PROVIDER_CONFIRMED' as const, mayCreateExternalRewardOrder: false, b64UserCashCustody: false as const });
  }
  if (!Number.isFinite(input.rewardFaceValue) || input.rewardFaceValue <= 0 || !input.rewardCurrency.trim()) {
    return Object.freeze({ state: 'BLOCKED_REWARD_VALUE_INVALID' as const, mayCreateExternalRewardOrder: false, b64UserCashCustody: false as const });
  }
  if (!input.externalFulfillmentProviderApproved) {
    return Object.freeze({ state: 'BLOCKED_PROVIDER_NOT_APPROVED' as const, mayCreateExternalRewardOrder: false, b64UserCashCustody: false as const });
  }
  if (!input.payoutPolicyApproved) {
    return Object.freeze({ state: 'BLOCKED_PAYOUT_POLICY_NOT_READY' as const, mayCreateExternalRewardOrder: false, b64UserCashCustody: false as const });
  }
  if (!input.chargebackReservePolicyReady) {
    return Object.freeze({ state: 'BLOCKED_CHARGEBACK_RISK_NOT_READY' as const, mayCreateExternalRewardOrder: false, b64UserCashCustody: false as const });
  }
  return Object.freeze({ state: 'READY_FOR_EXTERNAL_FULFILLMENT' as const, mayCreateExternalRewardOrder: true, b64UserCashCustody: false as const });
}

export interface TremendousRewardOrderInput {
  readonly transaction: RewardTransaction;
  readonly recipientEmail: string;
  readonly amount: number;
  readonly currency: string;
  readonly campaignId: string;
}

export interface TremendousRewardOrderDraft {
  readonly externalId: string;
  readonly recipientEmail: string;
  readonly amount: number;
  readonly currency: string;
  readonly campaignId: string;
  readonly accessTokenExposure: 'SERVER_SIDE_ONLY';
  readonly idempotencyKeySource: 'AD_PROVIDER_TRANSACTION_ID';
}

function requireNonEmpty(value: string, field: string): string {
  const trimmed = value.trim();
  if (!trimmed) throw new Error(`${field} is required`);
  return trimmed;
}

function requireEmail(value: string): string {
  const trimmed = value.trim();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed)) throw new Error('recipientEmail must be a valid email');
  return trimmed;
}

/**
 * Drafts an idempotent Tremendous order identity only after the caller has separately
 * passed assessRewardFulfillment. It does not call Tremendous or mutate a user balance.
 */
export function buildTremendousRewardOrderDraft(input: TremendousRewardOrderInput): TremendousRewardOrderDraft {
  if (input.transaction.state !== 'CONFIRMED') throw new Error('provider-confirmed transaction required before reward order drafting');
  if (!Number.isFinite(input.amount) || input.amount <= 0) throw new Error('amount must be positive');
  return Object.freeze({
    externalId: `b64-${requireNonEmpty(input.transaction.providerId, 'providerId')}-${requireNonEmpty(input.transaction.providerTransactionId, 'providerTransactionId')}`,
    recipientEmail: requireEmail(input.recipientEmail),
    amount: input.amount,
    currency: requireNonEmpty(input.currency, 'currency').toUpperCase(),
    campaignId: requireNonEmpty(input.campaignId, 'campaignId'),
    accessTokenExposure: 'SERVER_SIDE_ONLY' as const,
    idempotencyKeySource: 'AD_PROVIDER_TRANSACTION_ID' as const,
  });
}

export const TREMENDOUS_B64_GO_LIVE_REQUIREMENTS = Object.freeze([
  'PRODUCTION_ACCOUNT_APPROVED',
  'PRODUCTION_API_ACCESS_APPROVED',
  'SERVER_SIDE_ACCESS_TOKEN_READY',
  'KOREA_RECIPIENT_CATALOG_LIVE_VERIFIED',
  'NAVER_PAY_OR_OTHER_KOREA_PAYOUT_OPTION_LIVE_VERIFIED',
  'FUNDING_PATH_READY',
  'PAYOUT_FACE_VALUE_POLICY_APPROVED',
  'CHARGEBACK_RESERVE_OR_DELAY_POLICY_APPROVED',
  'IDEMPOTENT_ORDER_EXTERNAL_ID_ENFORCED',
  'REWARD_DELIVERY_AND_FAILURE_RECONCILIATION_READY',
] as const);
