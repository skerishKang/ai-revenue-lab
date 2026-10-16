export const ACTION_TYPES = ['TRYOUT_COMPLETED', 'QUALITY_CHECK_COMPLETED', 'CLICK', 'VISIT'] as const;
export type ActionType = (typeof ACTION_TYPES)[number];

export const COMPLETION_EVENT_TYPES = ['COMPLETED', 'REVERSED'] as const;
export type CompletionEventType = (typeof COMPLETION_EVENT_TYPES)[number];

/** Longest accepted identifier. Identifiers are opaque and are never trimmed or normalized. */
export const MAX_IDENTIFIER_LENGTH = 256;

/**
 * Upper bound on distinct provider nonces remembered for one transaction. A provider
 * may re-issue a completion or a reversal under a new nonce; every such nonce must be
 * remembered so a later reuse for a different transaction is rejected. The list is
 * bounded, and exceeding the bound fails closed rather than dropping a nonce (which
 * would reopen a replay hole).
 */
export const MAX_OBSERVED_NONCES = 8;

/**
 * Control characters that are never allowed in an identifier. Composite record and
 * nonce keys join their parts with NUL, so a NUL inside any part could make two
 * different records collide on one key. All ASCII control characters (including
 * NUL and DEL), the C1 range, and the Unicode line/paragraph separators are
 * rejected so that no identifier can be split, reordered, or merged by a key join.
 */
const FORBIDDEN_IDENTIFIER_CHARACTERS = /[\u0000-\u001F\u007F-\u009F\u2028\u2029]/;

/**
 * Accepts an identifier only when it is a non-empty, length-bounded string with no
 * leading or trailing whitespace and no control characters. Whitespace-padded
 * identifiers are rejected rather than normalized so that two spellings can never
 * map to one record key. Control characters are rejected for the same reason: a NUL
 * or other control byte inside an identifier would let two different identifier
 * triples collide on one composite key.
 */
export function isSafeIdentifier(value: unknown): value is string {
  return typeof value === 'string'
    && value.length > 0
    && value.length <= MAX_IDENTIFIER_LENGTH
    && value.trim() === value
    && !FORBIDDEN_IDENTIFIER_CHARACTERS.test(value);
}

/**
 * Maximum tolerated difference between the provider-reported `occurredAt` and the
 * server-owned `observedAt` of the same callback. Provider clocks are never trusted
 * for ledger ordering; this bound only limits how far a provider clock may drift.
 */
export const MAX_PROVIDER_CLOCK_SKEW_MS = 24 * 60 * 60 * 1000;

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
  /** Provider-reported occurrence time. Stored for evidence only, never for ordering. */
  readonly occurredAt: string;
  /** Provider-scoped replay token. Unique per provider and never reused across transactions. */
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
  /** Provider-reported occurrence time of the originating completion, preserved across reversal. */
  readonly providerOccurredAt: string;
  /** Server-owned first time this record was observed. */
  readonly firstObservedAt: string;
  /** Server-owned most recent time this record changed state or was re-observed. */
  readonly lastObservedAt: string;
  /**
   * First provider-scoped replay token observed for this transaction, retained in
   * ledger history. It is the canonical completion nonce and is preserved across
   * reversal.
   */
  readonly nonce: string;
  /**
   * Every distinct provider+nonce identity observed for this transaction, in
   * first-observed order and bounded by `MAX_OBSERVED_NONCES`. A provider may
   * re-issue a duplicate completion or a reversal under a new nonce; each of those
   * nonces is recorded here so a later reuse of any of them for a different offer or
   * transaction is rejected. The list is append-only within a record's history and
   * always includes `nonce` as its first element.
   */
  readonly observedNonces: readonly string[];
}

export type CompletionTransitionDecisionCode =
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
  | 'REJECT_FUNDED_BUDGET_EXHAUSTED'
  | 'REJECT_PROVIDER_CLOCK_SKEW'
  | 'REJECT_OBSERVATION_TIME_REGRESSION'
  | 'REJECT_AMOUNT_OVERFLOW'
  | 'REJECT_NONCE_REPLAY'
  | 'REJECT_NONCE_HISTORY_EXHAUSTED'
  | 'REJECT_INVALID_LEDGER_HISTORY';

export interface CompletionTransitionDecision {
  readonly decision: CompletionTransitionDecisionCode;
  readonly next: CompletionLedgerRecord | null;
  readonly balanceDeltaMinor: number;
  /**
   * True only for authenticated, meaningful state transitions and conflicts.
   * Rejections, idempotent duplicates, and unauthenticated input never request an
   * append-only audit write.
   */
  readonly appendImmutableAuditEvent: boolean;
  readonly externalPayoutAllowed: false;
}
