export const ACTION_TYPES = ['TRYOUT_COMPLETED', 'QUALITY_CHECK_COMPLETED', 'CLICK', 'VISIT'] as const;
export type ActionType = (typeof ACTION_TYPES)[number];

export const COMPLETION_EVENT_TYPES = ['COMPLETED', 'REVERSED'] as const;
export type CompletionEventType = (typeof COMPLETION_EVENT_TYPES)[number];

export interface TryoutOffer {
  readonly offerId: string;
  readonly providerId: string;
  readonly actionType: ActionType;
  readonly rewardAmountMinor: number;
  readonly rewardCurrency: string;
  readonly perUserLimit: number;
  readonly fundedBudgetMinor: number;
  readonly startsAt: string;
  readonly endsAt: string | null;
  readonly state: 'DRAFT' | 'ACTIVE' | 'PAUSED' | 'EXPIRED' | 'REVOKED';
}

export interface SignedCompletionEvent {
  readonly providerId: string;
  readonly offerId: string;
  readonly providerTransactionId: string;
  readonly externalUserId: string;
  readonly actionType: ActionType;
  readonly eventType: CompletionEventType;
  readonly rewardAmountMinor: number;
  readonly rewardCurrency: string;
  readonly occurredAt: string;
  readonly nonce: string;
}

export interface CompletionLedgerRecord {
  readonly providerId: string;
  readonly offerId: string;
  readonly providerTransactionId: string;
  readonly externalUserId: string;
  readonly actionType: ActionType;
  readonly state: 'COMPLETED' | 'REVERSED';
  readonly rewardAmountMinor: number;
  readonly rewardCurrency: string;
  readonly firstObservedAt: string;
  readonly lastObservedAt: string;
}

export interface CompletionTransitionDecision {
  readonly decision:
    | 'CREDIT_COMPLETED_ACTION'
    | 'REVERSE_COMPLETED_ACTION'
    | 'IGNORE_IDEMPOTENT_DUPLICATE'
    | 'REJECT_CLICK_OR_VISIT'
    | 'REJECT_INVALID_EVENT'
    | 'REJECT_OFFER_NOT_ACTIVE'
    | 'REJECT_OFFER_IDENTITY_MISMATCH'
    | 'REJECT_IDENTITY_OR_VALUE_MISMATCH'
    | 'REJECT_ORPHAN_REVERSAL'
    | 'REJECT_REOPEN_AFTER_REVERSAL'
    | 'REJECT_PER_USER_LIMIT'
    | 'REJECT_FUNDED_BUDGET_EXHAUSTED';
  readonly next: CompletionLedgerRecord | null;
  readonly balanceDeltaMinor: number;
  readonly appendImmutableAuditEvent: boolean;
  readonly externalPayoutAllowed: false;
}
