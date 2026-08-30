export const REWARD_EVENT_TYPES = ['PROVISIONAL', 'CONFIRMED', 'REVERSED'] as const;
export type RewardEventType = (typeof REWARD_EVENT_TYPES)[number];

export const REWARD_STATES = [
  'PENDING_PROVIDER_CONFIRMATION',
  'CONFIRMED',
  'REVERSED',
] as const;
export type RewardState = (typeof REWARD_STATES)[number];

export interface ProviderRewardEvent {
  readonly providerId: string;
  readonly providerTransactionId: string;
  readonly externalUserId: string;
  readonly eventType: RewardEventType;
  readonly amount: number;
  readonly unit: string;
  readonly observedAt: string;
}

export interface RewardStateRecord {
  readonly providerId: string;
  readonly providerTransactionId: string;
  readonly externalUserId: string;
  readonly amount: number;
  readonly unit: string;
  readonly state: RewardState;
  readonly firstObservedAt: string;
  readonly lastObservedAt: string;
  readonly cashCustodyAction: 'NONE';
}

export type RewardTransitionDecision =
  | 'CREATE_PENDING'
  | 'CREATE_CONFIRMED'
  | 'CONFIRM_PENDING'
  | 'REVERSE_PENDING'
  | 'REVERSE_CONFIRMED'
  | 'IGNORE_IDEMPOTENT_DUPLICATE'
  | 'REJECT_INVALID_EVENT'
  | 'REJECT_ORPHAN_REVERSAL'
  | 'REVIEW_IDENTITY_OR_VALUE_MISMATCH'
  | 'REVIEW_REOPEN_AFTER_REVERSAL';

export interface RewardTransitionResult {
  readonly decision: RewardTransitionDecision;
  readonly next: RewardStateRecord | null;
  readonly appendImmutableAuditEvent: boolean;
  readonly userBalanceMutation: 'NONE';
  readonly cashCustodyAction: 'NONE';
}

function validText(value: string): boolean {
  const normalized = value.trim();
  return normalized.length > 0 && normalized.length <= 256;
}

function validEvent(event: ProviderRewardEvent): boolean {
  return validText(event.providerId)
    && validText(event.providerTransactionId)
    && validText(event.externalUserId)
    && Number.isFinite(event.amount)
    && event.amount > 0
    && validText(event.unit)
    && Number.isFinite(Date.parse(event.observedAt));
}

function stateForFirstEvent(eventType: Exclude<RewardEventType, 'REVERSED'>): RewardState {
  return eventType === 'PROVISIONAL' ? 'PENDING_PROVIDER_CONFIRMATION' : 'CONFIRMED';
}

function sameIdentityAndValue(current: RewardStateRecord, event: ProviderRewardEvent): boolean {
  return current.providerId === event.providerId
    && current.providerTransactionId === event.providerTransactionId
    && current.externalUserId === event.externalUserId
    && current.amount === event.amount
    && current.unit === event.unit;
}

function result(
  decision: RewardTransitionDecision,
  next: RewardStateRecord | null,
  appendImmutableAuditEvent: boolean,
): RewardTransitionResult {
  return Object.freeze({
    decision,
    next,
    appendImmutableAuditEvent,
    userBalanceMutation: 'NONE' as const,
    cashCustodyAction: 'NONE' as const,
  });
}

function createRecord(event: ProviderRewardEvent, state: RewardState): RewardStateRecord {
  return Object.freeze({
    providerId: event.providerId,
    providerTransactionId: event.providerTransactionId,
    externalUserId: event.externalUserId,
    amount: event.amount,
    unit: event.unit,
    state,
    firstObservedAt: event.observedAt,
    lastObservedAt: event.observedAt,
    cashCustodyAction: 'NONE' as const,
  });
}

function transitionRecord(current: RewardStateRecord, state: RewardState, observedAt: string): RewardStateRecord {
  return Object.freeze({ ...current, state, lastObservedAt: observedAt });
}

/**
 * Pure provider-independent reward state machine.
 * It records provider-reported reward state only. It never creates a B64 wallet,
 * credits a user balance, or treats a client-side callback as cash settlement.
 */
export function applyProviderRewardEvent(
  current: RewardStateRecord | null,
  event: ProviderRewardEvent,
): RewardTransitionResult {
  if (!validEvent(event)) return result('REJECT_INVALID_EVENT', current, false);

  if (!current) {
    if (event.eventType === 'REVERSED') return result('REJECT_ORPHAN_REVERSAL', null, false);
    const state = stateForFirstEvent(event.eventType);
    return result(
      event.eventType === 'PROVISIONAL' ? 'CREATE_PENDING' : 'CREATE_CONFIRMED',
      createRecord(event, state),
      true,
    );
  }

  if (!sameIdentityAndValue(current, event)) {
    return result('REVIEW_IDENTITY_OR_VALUE_MISMATCH', current, true);
  }

  if (current.state === 'REVERSED') {
    if (event.eventType === 'REVERSED') return result('IGNORE_IDEMPOTENT_DUPLICATE', current, false);
    return result('REVIEW_REOPEN_AFTER_REVERSAL', current, true);
  }

  if (current.state === 'PENDING_PROVIDER_CONFIRMATION') {
    if (event.eventType === 'PROVISIONAL') return result('IGNORE_IDEMPOTENT_DUPLICATE', current, false);
    if (event.eventType === 'CONFIRMED') return result('CONFIRM_PENDING', transitionRecord(current, 'CONFIRMED', event.observedAt), true);
    return result('REVERSE_PENDING', transitionRecord(current, 'REVERSED', event.observedAt), true);
  }

  if (event.eventType === 'CONFIRMED' || event.eventType === 'PROVISIONAL') {
    return result('IGNORE_IDEMPOTENT_DUPLICATE', current, false);
  }
  return result('REVERSE_CONFIRMED', transitionRecord(current, 'REVERSED', event.observedAt), true);
}
