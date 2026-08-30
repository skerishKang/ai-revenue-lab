export const AD_CLICK_FIRST_REQUIRED_CRITERIA = [
  'POLICY_CLEARED_REAL_SUPPLY',
  'CANONICAL_EVIDENCE_BOUND_OPPORTUNITY',
  'REWARD_CONDITION_ACTION_FRESHNESS_MODELED',
  'LOW_FRICTION_CONSUMER_CARD_WORKS',
  'OUTBOUND_OR_PROVIDER_LAUNCH_WORKS',
  'STALE_BROKEN_ENDED_SUPPRESSION_WORKS',
  'DUPLICATE_SUPPRESSION_WORKS',
  'PROVIDER_TRACKING_IS_CONTRACT_BOUND',
  'DEFAULT_UI_IS_AD_CLICK_ONLY',
  'LATER_TIERS_ARE_HIDDEN',
  'LIVE_PROVIDER_FILL_OBSERVED',
  'SIGNED_REWARD_CALLBACK_OBSERVED',
] as const;

export type AdClickFirstCriterion = (typeof AD_CLICK_FIRST_REQUIRED_CRITERIA)[number];
export type AdClickFirstCriterionState = 'PASS' | 'NOT_RUN' | 'BLOCKED';

export type AdClickFirstEvidenceState = Readonly<Record<AdClickFirstCriterion, AdClickFirstCriterionState>>;

export function evaluateAdClickFirstReadiness(evidence: AdClickFirstEvidenceState) {
  const missing = AD_CLICK_FIRST_REQUIRED_CRITERIA.filter((criterion) => evidence[criterion] !== 'PASS');
  const blocked = AD_CLICK_FIRST_REQUIRED_CRITERIA.filter((criterion) => evidence[criterion] === 'BLOCKED');
  return Object.freeze({
    issueNumber: 1112,
    criteriaComplete: missing.length === 0,
    readiness: missing.length === 0 ? 'READY_FOR_CENTRAL_ACCEPTANCE' as const : 'IN_PROGRESS' as const,
    centralAcceptance: 'REQUIRED_SEPARATELY' as const,
    missing: Object.freeze(missing),
    blocked: Object.freeze(blocked),
  });
}

/**
 * Current truthful checkpoint. Authored code/tests are not silently promoted to PASS,
 * and live provider evidence remains blocked until real publisher onboarding exists.
 */
export const CURRENT_AD_CLICK_FIRST_EVIDENCE: AdClickFirstEvidenceState = Object.freeze({
  POLICY_CLEARED_REAL_SUPPLY: 'BLOCKED',
  CANONICAL_EVIDENCE_BOUND_OPPORTUNITY: 'NOT_RUN',
  REWARD_CONDITION_ACTION_FRESHNESS_MODELED: 'NOT_RUN',
  LOW_FRICTION_CONSUMER_CARD_WORKS: 'NOT_RUN',
  OUTBOUND_OR_PROVIDER_LAUNCH_WORKS: 'BLOCKED',
  STALE_BROKEN_ENDED_SUPPRESSION_WORKS: 'NOT_RUN',
  DUPLICATE_SUPPRESSION_WORKS: 'NOT_RUN',
  PROVIDER_TRACKING_IS_CONTRACT_BOUND: 'NOT_RUN',
  DEFAULT_UI_IS_AD_CLICK_ONLY: 'NOT_RUN',
  LATER_TIERS_ARE_HIDDEN: 'NOT_RUN',
  LIVE_PROVIDER_FILL_OBSERVED: 'BLOCKED',
  SIGNED_REWARD_CALLBACK_OBSERVED: 'BLOCKED',
});

export const CURRENT_AD_CLICK_FIRST_READINESS = evaluateAdClickFirstReadiness(CURRENT_AD_CLICK_FIRST_EVIDENCE);
