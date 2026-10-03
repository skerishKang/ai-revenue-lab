import {
  isSafeIdentifier,
  type ActionType,
  type CompletionLedgerRecord,
} from './domain.js';
import { isValidLedgerRecord, safeSumMinor, snapshotLedgerRecord } from './ledger-history.js';

export { safeSumMinor } from './ledger-history.js';

/** Canonical record key used by the claim gate: (providerId, offerId, providerTransactionId). */
export function claimRecordKey(record: Pick<CompletionLedgerRecord, 'providerId' | 'offerId' | 'providerTransactionId'>): string {
  return `${record.providerId}\u0000${record.offerId}\u0000${record.providerTransactionId}`;
}

export type PointsClaimDecisionCode =
  | 'ASSESS_CLAIMABLE'
  | 'REJECT_INVALID_CLAIM'
  | 'REJECT_UNKNOWN_RECORD'
  | 'REJECT_CURRENCY_MISMATCH'
  | 'REJECT_REVERSED_RECORD'
  | 'REJECT_OVERS_SPEND'
  | 'REJECT_CLAIMS_FROZEN';

/**
 * Why a claim can never leave this source-only slice. Even a fully valid claim stays
 * blocked. `SOURCE_ONLY_PAYOUT_DISABLED` is the truthful terminal reason: this module
 * performs no payment at all, so no caller-supplied readiness flag can unblock it, and
 * the code never claims an integrated payment rail is merely "missing" when a caller
 * asserts one exists.
 */
export type PayoutBlockReason =
  | 'LIVE_PAYOUT_DISABLED'
  | 'DURABLE_STORAGE_NOT_PROVISIONED'
  | 'PROVIDER_NOT_INTEGRATED'
  | 'SOURCE_ONLY_PAYOUT_DISABLED';

export interface PointsClaimRequest {
  readonly providerId: string;
  readonly offerId: string;
  readonly externalUserId: string;
  readonly rewardCurrency: string;
  /** Integer minor units. Must be finite, positive, and a safe integer. */
  readonly claimAmountMinor: number;
  /**
   * Optional explicit scope. When omitted the whole non-reversed balance of the
   * (provider, offer, user, currency) tuple is available.
   */
  readonly recordKeys?: readonly string[];
}

/**
 * Product-local, source-only claim/payout eligibility state. There is no provider
 * client, no payment integration, and no transferable wallet behind this type.
 */
export interface PointsClaimState {
  /** No code path in this slice sets this to true. The default state is non-live. */
  readonly livePayoutEnabled: boolean;
  readonly claimsFrozen: boolean;
  readonly durableStorageProvisioned: boolean;
  readonly providerIntegrated: boolean;
  readonly paymentRailIntegrated: boolean;
}

export interface PointsClaimAssessment {
  readonly decision: PointsClaimDecisionCode;
  readonly claimAmountMinor: number;
  /** Independently available, non-reversed amount for the resolved scope. */
  readonly availableMinor: number;
  readonly claimableMinor: number;
  /** True only when the claim is internally valid and fully covered. Never means payable. */
  readonly claimAccepted: boolean;
  /** Always false in this source-only slice. */
  readonly payoutAllowed: false;
  readonly livePayoutEnabled: boolean;
  readonly payoutBlockReason: PayoutBlockReason;
  readonly consideredRecordKeys: readonly string[];
  readonly reversedRecordKeys: readonly string[];
}

export const DEFAULT_POINTS_CLAIM_STATE: Readonly<PointsClaimState> = Object.freeze({
  livePayoutEnabled: false,
  claimsFrozen: false,
  durableStorageProvisioned: false,
  providerIntegrated: false,
  paymentRailIntegrated: false,
});

export const MAX_CLAIM_RECORD_KEYS = 500;

function payoutBlockReason(state: PointsClaimState): PayoutBlockReason {
  if (state.livePayoutEnabled !== true) return 'LIVE_PAYOUT_DISABLED';
  if (state.durableStorageProvisioned !== true) return 'DURABLE_STORAGE_NOT_PROVISIONED';
  if (state.providerIntegrated !== true) return 'PROVIDER_NOT_INTEGRATED';
  // Every caller-supplied readiness flag may be true, but this module is source-only:
  // it performs no payment. Report the truthful source-slice reason rather than
  // asserting an integrated rail is "missing" (which the all-true input contradicts).
  return 'SOURCE_ONLY_PAYOUT_DISABLED';
}

function assessment(
  decision: PointsClaimDecisionCode,
  claimAmountMinor: number,
  availableMinor: number,
  claimableMinor: number,
  state: PointsClaimState,
  consideredRecordKeys: readonly string[],
  reversedRecordKeys: readonly string[],
): PointsClaimAssessment {
  return Object.freeze({
    decision,
    claimAmountMinor,
    availableMinor,
    claimableMinor,
    claimAccepted: decision === 'ASSESS_CLAIMABLE',
    payoutAllowed: false as const,
    livePayoutEnabled: state.livePayoutEnabled === true,
    payoutBlockReason: payoutBlockReason(state),
    consideredRecordKeys: Object.freeze([...consideredRecordKeys]),
    reversedRecordKeys: Object.freeze([...reversedRecordKeys]),
  });
}

function validClaimAmount(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && Number.isSafeInteger(value) && value > 0;
}

/**
 * A record is claimable input only when every field it contributes to the available
 * amount is well-formed. This delegates to the one authoritative ledger-record
 * validator so the claim path and the completion path can never disagree about what
 * "well-formed" means: a record with a non-finite, non-integer, zero, or negative
 * reward, a malformed identifier, an unexpected action or state, a bad currency, an
 * unparseable or self-contradictory timestamp, or a malformed observed-nonce history
 * can never be counted toward a claim and can never make a claim `ASSESS_CLAIMABLE`.
 */
export function isValidClaimRecord(record: CompletionLedgerRecord): boolean {
  return isValidLedgerRecord(record);
}

function validRequestedKeys(keys: unknown): keys is readonly string[] {
  return Array.isArray(keys)
    && keys.length > 0
    && keys.length <= MAX_CLAIM_RECORD_KEYS
    // Record keys are opaque: they are never trimmed or normalized.
    && keys.every((key) => typeof key === 'string' && key.length > 0 && key.length <= 1024 && key.trim() === key)
    && new Set(keys).size === keys.length;
}

export interface AvailableClaimableMinor {
  readonly availableMinor: number;
  readonly considered: readonly string[];
  readonly reversed: readonly string[];
  /** Requested keys that match no record in the claim scope at all. */
  readonly unknown: readonly string[];
  /** Requested keys that resolve to a record with a different reward currency. */
  readonly currencyMismatch: readonly string[];
}

interface ResolvedScope {
  readonly kind: 'ok';
  readonly selected: readonly CompletionLedgerRecord[];
  readonly availableMinor: number;
  readonly considered: readonly string[];
  readonly reversed: readonly string[];
  readonly unknown: readonly string[];
  readonly currencyMismatch: readonly string[];
}

interface InvalidScope {
  readonly kind: 'invalid';
}

/**
 * Resolve the claim scope and independently available amount. Fails closed (`invalid`)
 * when any supplied record is malformed (bad identifiers, reward, currency, state,
 * timestamp, or nonce history) or when the available sum is not a safe integer. Reversed records are
 * reported separately and never counted as available.
 */
function resolveScopeUnsafe(
  records: readonly CompletionLedgerRecord[],
  request: PointsClaimRequest,
): ResolvedScope | InvalidScope {
  // Snapshot every readable record before scope selection and summation. Validation and
  // balance calculation must consume the same immutable values; a stateful getter must
  // not pass validation and then contribute a different amount to the claim.
  const snapshots = records.map((record) => snapshotLedgerRecord(record));
  // The claim input is authoritative history, just like the completion input. A bad
  // record is not filtered out by scope before validation, and no caller-owned getter
  // is read again for summation.
  if (snapshots.some((record) => record === null)) return { kind: 'invalid' };
  const validSnapshots = snapshots as CompletionLedgerRecord[];
  const scoped = validSnapshots.filter((record) => record.providerId === request.providerId
    && record.offerId === request.offerId
    && record.externalUserId === request.externalUserId);
  const requestedKeys = request.recordKeys;
  const selected = requestedKeys === undefined
    ? scoped
    : requestedKeys.map((key) => scoped.find((record) => claimRecordKey(record) === key)).filter((record): record is CompletionLedgerRecord => record !== undefined);

  // Fail closed on any malformed record that contributes to the considered scope.
  if (selected.some((record) => !isValidClaimRecord(record))) return { kind: 'invalid' };

  const amountList = selected
    .filter((record) => record.state === 'COMPLETED' && record.rewardCurrency === request.rewardCurrency)
    .map((record) => record.rewardAmountMinor);
  const available = safeSumMinor(amountList);
  // An unsafe or imprecise running sum is not a real balance; fail closed rather than
  // crediting a rounded total.
  if (available === null) return { kind: 'invalid' };

  const considered: string[] = requestedKeys === undefined ? scoped.map(claimRecordKey) : selected.map(claimRecordKey);
  const reversed = selected.filter((record) => record.state === 'REVERSED').map(claimRecordKey);
  const unknown = requestedKeys === undefined ? [] : requestedKeys.filter((key) => !scoped.some((record) => claimRecordKey(record) === key));
  const currencyMismatch = requestedKeys === undefined
    ? []
    : requestedKeys.filter((key) => {
      const match = scoped.find((record) => claimRecordKey(record) === key);
      return match !== undefined && match.rewardCurrency !== request.rewardCurrency;
    });

  return { kind: 'ok', selected, availableMinor: available, considered, reversed, unknown, currencyMismatch };
}

function resolveScope(
  records: readonly CompletionLedgerRecord[],
  request: PointsClaimRequest,
): ResolvedScope | InvalidScope {
  try {
    return resolveScopeUnsafe(records, request);
  } catch {
    // Claim input is not durable persistence, but a throwing getter/iterator is still
    // not a valid scope. Keep the public claim boundary fail-closed instead of leaking
    // an exception from source-only eligibility assessment.
    return { kind: 'invalid' };
  }
}

/**
 * Independently available, non-reversed amount for a claim scope. This is a fail-closed
 * read: a malformed record in scope, or an unsafe sum, yields an available amount of 0
 * rather than a partial or rounded total. Callers that must distinguish a real zero
 * balance from a malformed scope use {@link assessPointsClaim}, which returns
 * `REJECT_INVALID_CLAIM`.
 */
export function availableClaimableMinor(
  records: readonly CompletionLedgerRecord[],
  request: PointsClaimRequest,
): AvailableClaimableMinor {
  const resolved = resolveScope(records, request);
  if (resolved.kind === 'invalid') {
    return { availableMinor: 0, considered: [], reversed: [], unknown: [], currencyMismatch: [] };
  }
  return {
    availableMinor: resolved.availableMinor,
    considered: resolved.considered,
    reversed: resolved.reversed,
    unknown: resolved.unknown,
    currencyMismatch: resolved.currencyMismatch,
  };
}

/**
 * Fail-closed claim gate. It only decides whether a claim is internally consistent and
 * fully covered by independently available, non-reversed ledger value. It never moves
 * money, never contacts a provider, and never authorizes a payout: `payoutAllowed` is
 * always `false` and the default state is non-live.
 */
export function assessPointsClaim(
  records: readonly CompletionLedgerRecord[],
  request: PointsClaimRequest,
  state: PointsClaimState = DEFAULT_POINTS_CLAIM_STATE,
): PointsClaimAssessment {
  if (!request || typeof request !== 'object') return assessment('REJECT_INVALID_CLAIM', 0, 0, 0, state, [], []);
  if (!isSafeIdentifier(request.providerId)
    || !isSafeIdentifier(request.offerId)
    || !isSafeIdentifier(request.externalUserId)
    || typeof request.rewardCurrency !== 'string'
    || !/^[A-Z]{3}$/.test(request.rewardCurrency)
    || !validClaimAmount(request.claimAmountMinor)
    || (request.recordKeys !== undefined && !validRequestedKeys(request.recordKeys))) {
    return assessment('REJECT_INVALID_CLAIM', 0, 0, 0, state, [], []);
  }

  // Any malformed record in scope, or an unsafe sum, fails closed as an invalid claim.
  const resolved = resolveScope(records, request);
  if (resolved.kind === 'invalid') return assessment('REJECT_INVALID_CLAIM', 0, 0, 0, state, [], []);

  const { availableMinor, considered, reversed, unknown, currencyMismatch } = resolved;
  if (unknown.length > 0) return assessment('REJECT_UNKNOWN_RECORD', request.claimAmountMinor, availableMinor, 0, state, considered, reversed);
  if (currencyMismatch.length > 0) return assessment('REJECT_CURRENCY_MISMATCH', request.claimAmountMinor, availableMinor, 0, state, considered, reversed);
  if (reversed.length > 0) return assessment('REJECT_REVERSED_RECORD', request.claimAmountMinor, availableMinor, 0, state, considered, reversed);
  if (request.claimAmountMinor > availableMinor) return assessment('REJECT_OVERS_SPEND', request.claimAmountMinor, availableMinor, 0, state, considered, reversed);
  if (state.claimsFrozen) return assessment('REJECT_CLAIMS_FROZEN', request.claimAmountMinor, availableMinor, 0, state, considered, reversed);

  return assessment('ASSESS_CLAIMABLE', request.claimAmountMinor, availableMinor, request.claimAmountMinor, state, considered, reversed);
}
