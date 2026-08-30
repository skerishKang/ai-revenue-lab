export const CENTRAL_AD_CLICK_TECHNICAL_CRITERIA = [
  'REWARD_CONDITION_ACTION_FRESHNESS_MODELED',
  'LOW_FRICTION_CONSUMER_CARD_WORKS',
  'CLICK_INCENTIVE_AUTHORITY_FAILS_CLOSED',
  'STALE_BROKEN_ENDED_SUPPRESSION_WORKS',
  'DUPLICATE_SUPPRESSION_WORKS',
  'PROVIDER_TRACKING_IS_CONTRACT_BOUND',
  'DEFAULT_UI_IS_AD_CLICK_ONLY',
  'LATER_TIERS_ARE_HIDDEN',
  'ACCOUNT_OPTIONAL_RUNTIME_CONFIG_WORKS',
  'EXTERNAL_FULFILLMENT_AND_PAYOUT_GATES_MODELED',
  'OWNER_ACTIVATION_RUNBOOK_EXISTS',
] as const;

export const OWNER_LIVE_ACTIVATION_CRITERIA = [
  'POLICY_CLEARED_REAL_SUPPLY',
  'CANONICAL_EVIDENCE_BOUND_OPPORTUNITY',
  'OUTBOUND_OR_PROVIDER_LAUNCH_WORKS',
  'LIVE_PROVIDER_FILL_OBSERVED',
  'SIGNED_REWARD_CALLBACK_OBSERVED',
  'LIVE_EXTERNAL_REWARD_FULFILLMENT_OBSERVED',
] as const;

export const AD_CLICK_FIRST_REQUIRED_CRITERIA = [
  ...CENTRAL_AD_CLICK_TECHNICAL_CRITERIA,
  ...OWNER_LIVE_ACTIVATION_CRITERIA,
] as const;

export type AdClickFirstCriterion = (typeof AD_CLICK_FIRST_REQUIRED_CRITERIA)[number];
export type AdClickFirstCriterionState =
  | 'PASS'
  | 'IMPLEMENTED_NOT_RUNTIME_VERIFIED'
  | 'NOT_RUN'
  | 'BLOCKED'
  | 'OWNER_ACTION';

export type AdClickFirstEvidenceState = Readonly<Record<AdClickFirstCriterion, AdClickFirstCriterionState>>;

function missingFrom(
  criteria: readonly AdClickFirstCriterion[],
  evidence: AdClickFirstEvidenceState,
): readonly AdClickFirstCriterion[] {
  return Object.freeze(criteria.filter((criterion) => evidence[criterion] !== 'PASS'));
}

export function evaluateAdClickFirstReadiness(evidence: AdClickFirstEvidenceState) {
  const centralTechnicalMissing = missingFrom(CENTRAL_AD_CLICK_TECHNICAL_CRITERIA, evidence);
  const ownerLiveActivationPending = missingFrom(OWNER_LIVE_ACTIVATION_CRITERIA, evidence);
  const missing = Object.freeze([...centralTechnicalMissing, ...ownerLiveActivationPending]);
  const blocked = Object.freeze(
    AD_CLICK_FIRST_REQUIRED_CRITERIA.filter((criterion) => evidence[criterion] === 'BLOCKED'),
  );
  const ownerActions = Object.freeze(
    OWNER_LIVE_ACTIVATION_CRITERIA.filter((criterion) => evidence[criterion] === 'OWNER_ACTION'),
  );

  const centralTechnicalComplete = centralTechnicalMissing.length === 0;
  const liveActivationComplete = ownerLiveActivationPending.length === 0;

  return Object.freeze({
    issueNumber: 1112,
    criteriaComplete: centralTechnicalComplete && liveActivationComplete,
    centralTechnicalComplete,
    liveActivationComplete,
    centralTechnicalReadiness: centralTechnicalComplete
      ? 'READY_FOR_CENTRAL_TECHNICAL_ACCEPTANCE' as const
      : 'IN_PROGRESS' as const,
    liveActivationReadiness: liveActivationComplete
      ? 'READY_FOR_LIVE_ACTIVATION_REVIEW' as const
      : 'OWNER_ACTION_PENDING' as const,
    readiness: centralTechnicalComplete && liveActivationComplete
      ? 'READY_FOR_CENTRAL_ACCEPTANCE' as const
      : centralTechnicalComplete
        ? 'TECHNICAL_COMPLETE_OWNER_ACTIVATION_PENDING' as const
        : 'IN_PROGRESS' as const,
    centralAcceptance: 'REQUIRED_SEPARATELY' as const,
    missing,
    centralTechnicalMissing,
    ownerLiveActivationPending,
    ownerActions,
    blocked,
  });
}

/**
 * CENTRAL runtime evidence checkpoint.
 *
 * Exact-head CI on b418e21349e80239350da59949ba9cdc25046b01 executed the locked
 * Node 22 build, typecheck and full test suite: 194/194 tests passed. The
 * next exact-head CI must re-verify these PASS declarations together with
 * the runbook-content test before CENTRAL acceptance is recorded.
 *
 * Provider account, real-fill and real-payout criteria remain OWNER_ACTION;
 * technical completion must never be interpreted as live consumer supply.
 */
export const CURRENT_AD_CLICK_FIRST_EVIDENCE: AdClickFirstEvidenceState = Object.freeze({
  REWARD_CONDITION_ACTION_FRESHNESS_MODELED: 'PASS',
  LOW_FRICTION_CONSUMER_CARD_WORKS: 'PASS',
  CLICK_INCENTIVE_AUTHORITY_FAILS_CLOSED: 'PASS',
  STALE_BROKEN_ENDED_SUPPRESSION_WORKS: 'PASS',
  DUPLICATE_SUPPRESSION_WORKS: 'PASS',
  PROVIDER_TRACKING_IS_CONTRACT_BOUND: 'PASS',
  DEFAULT_UI_IS_AD_CLICK_ONLY: 'PASS',
  LATER_TIERS_ARE_HIDDEN: 'PASS',
  ACCOUNT_OPTIONAL_RUNTIME_CONFIG_WORKS: 'PASS',
  EXTERNAL_FULFILLMENT_AND_PAYOUT_GATES_MODELED: 'PASS',
  OWNER_ACTIVATION_RUNBOOK_EXISTS: 'PASS',
  POLICY_CLEARED_REAL_SUPPLY: 'OWNER_ACTION',
  CANONICAL_EVIDENCE_BOUND_OPPORTUNITY: 'OWNER_ACTION',
  OUTBOUND_OR_PROVIDER_LAUNCH_WORKS: 'OWNER_ACTION',
  LIVE_PROVIDER_FILL_OBSERVED: 'OWNER_ACTION',
  SIGNED_REWARD_CALLBACK_OBSERVED: 'OWNER_ACTION',
  LIVE_EXTERNAL_REWARD_FULFILLMENT_OBSERVED: 'OWNER_ACTION',
});

export const CURRENT_AD_CLICK_FIRST_READINESS = evaluateAdClickFirstReadiness(CURRENT_AD_CLICK_FIRST_EVIDENCE);
