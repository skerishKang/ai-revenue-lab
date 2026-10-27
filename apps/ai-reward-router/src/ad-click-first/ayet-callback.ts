import { normalizeVerifiedAyetS2SRewardPostback, type AyetS2SParameters } from './ayet-s2s-postback.js';
import { applyProviderRewardEvent, type RewardStateRecord } from './reward-events.js';
import {
  buildStoredRewardEvent,
  RewardEventStorageError,
  type RewardEventStore,
  type StoredRewardEvent,
} from './reward-event-store.js';
import { readB64RewardSubject } from '../identity/reward-subject.js';
import type { ProviderRuntimeMode } from './provider-runtime-config.js';

/**
 * The ayeT server-to-server postback, connected (issue #987).
 *
 * Everything that decides whether a callback may be trusted already existed and
 * is reused unchanged: `verifyAyetS2SSecurityHash` /
 * `normalizeVerifiedAyetS2SRewardPostback` for the signature and field contract,
 * `applyProviderRewardEvent` for idempotency, orphan-reversal and identity
 * rules. This module only supplies what was missing — a transport, a member
 * link and a place to write.
 *
 * Provider contract notes, from ayeT-Studios' own callback documentation:
 * the signature arrives in the `X-Ayetstudios-Security-Hash` header, not as a
 * query parameter, and `{transaction_id}` is what prevents granting a
 * conversion twice. The hash is documented as optional; B64 requires it, because
 * an unsigned callback is a reward request with no proof behind it.
 */

export const AYET_S2S_SECURITY_HASH_HEADER = 'x-ayetstudios-security-hash';
export const AYET_S2S_CALLBACK_PATH = '/callbacks/ayet/s2s';
/** What the provider's own retry bookkeeping expects back on a handled callback. */
export const AYET_S2S_ACK_BODY = 'OK';

export interface AyetCallbackRequestContext {
  readonly parameters: AyetS2SParameters;
  readonly securityHash: string | null;
  readonly observedAt: string;
}

export interface AyetCallbackOutcome {
  readonly status: number;
  readonly body: string;
  readonly decision: string;
}

export interface AyetCallbackDependencies {
  readonly mode: ProviderRuntimeMode;
  readonly publisherApiKey: string | undefined;
  readonly signingSecret: string | undefined;
  readonly rewardEvents: RewardEventStore;
  /**
   * `B64_AYET_REWARDED_ADSLOT_ID`. ayeT warns that a single callback URL shared
   * by several adslots must pass and validate `{adslot_id}`; when B64 names its
   * rewarded-video adslot, a callback from any other adslot is refused.
   */
  readonly rewardedAdslotId?: string | undefined;
}

function outcome(status: number, decision: string, body = ''): AyetCallbackOutcome {
  return Object.freeze({ status, body, decision });
}

/**
 * Acknowledged without crediting. ayeT resends any postback that is not
 * answered HTTP 200, twelve times over an hour, so this is the answer for
 * outcomes a retry can never change: a bad signature, a subject this Worker
 * never signed, a transaction that already belongs to someone else. The
 * acknowledgement says "received"; the reward decision is the row, and no row
 * is written here.
 */
function permanent(decision: string): AyetCallbackOutcome {
  return outcome(200, decision, AYET_S2S_ACK_BODY);
}

/**
 * Retried. ayeT's own resend behaviour is the recovery mechanism, so it is used
 * deliberately for the cases where another attempt can genuinely land: storage
 * is down, the provider is not configured yet, a reversal arrived before the
 * conversion it refers to, or a concurrent writer is mid-transition.
 */
function retryLater(status: number, decision: string): AyetCallbackOutcome {
  return outcome(status, decision);
}

/**
 * Every query parameter participates in the canonical string, which is what the
 * provider's own recipe says ("get all request parameters"). The signature
 * itself travels in the `X-Ayetstudios-Security-Hash` header, so it is never
 * part of the URL and needs no special case here.
 */
export function ayetS2SParametersFromUrl(url: URL): AyetS2SParameters {
  const parameters: Record<string, string> = {};
  for (const [key, value] of url.searchParams) parameters[key] = value;
  return parameters;
}

function asStateRecord(row: StoredRewardEvent): RewardStateRecord {
  return {
    providerId: row.providerId,
    providerTransactionId: row.providerTransactionId,
    externalUserId: row.externalUserId,
    amount: row.amount,
    unit: row.unit,
    state: row.state,
    firstObservedAt: row.firstObservedAt,
    lastObservedAt: row.lastObservedAt,
    cashCustodyAction: 'NONE',
  };
}

/**
 * Handles one postback. Nothing here throws for a request the provider could
 * plausibly send: ayeT resends anything it is not answered HTTP 200, so the
 * status code is transport policy and the stored row is the reward decision.
 * A storage failure is the one case re-thrown, so the HTTP layer can answer 503
 * and the provider's retry window can recover the event.
 */
export async function handleAyetS2SCallback(
  deps: AyetCallbackDependencies,
  context: AyetCallbackRequestContext,
): Promise<AyetCallbackOutcome> {
  if (deps.mode === 'DISABLED') throw new AyetCallbackDisabled();
  if (!deps.publisherApiKey || !deps.signingSecret) throw new AyetCallbackUnconfigured();

  const securityHash = (context.securityHash ?? '').trim();
  if (!securityHash) return permanent('REJECT_MISSING_SIGNATURE');

  const normalized = normalizeVerifiedAyetS2SRewardPostback({
    parameters: context.parameters,
    securityHash,
    publisherApiKey: deps.publisherApiKey,
    observedAt: context.observedAt,
  });
  if (!normalized.accepted || normalized.rewardEvent === null) {
    return permanent(normalized.decision);
  }

  const event = normalized.rewardEvent;
  const configuredAdslot = (deps.rewardedAdslotId ?? '').trim();
  if (configuredAdslot) {
    const reportedAdslot = String(context.parameters['adslot_id'] ?? '').trim();
    if (reportedAdslot !== configuredAdslot) {
      // A callback from an adslot B64 did not ask for is not B64's rewarded
      // video, and the row is not written for it.
      return permanent('REJECT_AD_SLOT_MISMATCH');
    }
  }

  const memberId = await readB64RewardSubject(event.externalUserId, deps.signingSecret);
  if (memberId === null) return permanent('REJECT_UNVERIFIED_SUBJECT');

  const existing = await deps.rewardEvents.load(event.providerId, event.providerTransactionId);
  if (existing !== null && existing.memberId !== memberId) {
    // The same provider transaction reported for a different B64 member. The
    // row keeps its owner and nothing moves; this needs a human, not a retry.
    return permanent('REJECT_SUBJECT_MEMBER_MISMATCH');
  }

  const transition = applyProviderRewardEvent(existing === null ? null : asStateRecord(existing), event);

  if (transition.decision === 'IGNORE_IDEMPOTENT_DUPLICATE') {
    return outcome(200, transition.decision, AYET_S2S_ACK_BODY);
  }
  if (transition.decision === 'REJECT_ORPHAN_REVERSAL') {
    return retryLater(503, transition.decision);
  }
  if (transition.next === null) {
    return permanent(transition.decision);
  }
  if (transition.decision === 'REVIEW_IDENTITY_OR_VALUE_MISMATCH'
    || transition.decision === 'REVIEW_REOPEN_AFTER_REVERSAL') {
    return permanent(transition.decision);
  }

  const record = buildStoredRewardEvent(transition.next, memberId);
  if (transition.decision === 'CREATE_PENDING' || transition.decision === 'CREATE_CONFIRMED') {
    const written = await deps.rewardEvents.insert(record);
    if (written === 'CONFLICT') return retryLater(503, 'CONFLICT_CONCURRENT_CREATE');
    return outcome(200, transition.decision, AYET_S2S_ACK_BODY);
  }

  if (existing === null) return retryLater(503, 'REJECT_ORPHAN_TRANSITION');
  const written = await deps.rewardEvents.transition(record, existing.state);
  if (written === 'CONFLICT') return retryLater(503, 'CONFLICT_CONCURRENT_TRANSITION');
  return outcome(200, transition.decision, AYET_S2S_ACK_BODY);
}

export class AyetCallbackDisabled extends Error {
  constructor() { super('ayet callback is disabled on this deployment'); this.name = 'AyetCallbackDisabled'; }
}

export class AyetCallbackUnconfigured extends Error {
  constructor() { super('ayet callback needs a publisher api key and a signing secret'); this.name = 'AyetCallbackUnconfigured'; }
}
