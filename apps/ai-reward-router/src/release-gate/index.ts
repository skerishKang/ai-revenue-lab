import { CURRENT_AD_CLICK_FIRST_READINESS } from '../ad-click-first/gate-readiness.js';
import { P1_VISIBILITY_LOCK } from '../p1-survey/domain.js';
import { P2_VISIBILITY_LOCK } from '../p2-microtask/domain.js';
import { P3_VISIBILITY_LOCK } from '../p3-short-gig/domain.js';
import { P4_VISIBILITY_LOCK } from '../job-search-assist/domain.js';

export const B64_RELEASE_TIERS = ['P0', 'P1', 'P2', 'P3', 'P4'] as const;
export type B64ReleaseTier = (typeof B64_RELEASE_TIERS)[number];
export type B64LaterTier = Exclude<B64ReleaseTier, 'P0'>;

export type ReleaseDecision = 'NOT_APPROVED' | 'APPROVED' | 'REVOKED';
export type TierVisibilityState =
  | 'VISIBLE'
  | 'HIDDEN_AWAITING_P0_LIVE'
  | 'HIDDEN_AWAITING_APPROVAL'
  | 'HIDDEN_UPSTREAM_LOCK'
  | 'HIDDEN_TECHNICAL_NOT_READY'
  | 'HIDDEN_REVOKED';

export interface ProgressiveReleaseInput {
  readonly p0TechnicalComplete: boolean;
  readonly p0LiveActivationComplete: boolean;
  readonly technicalPrepared: Readonly<Record<B64LaterTier, boolean>>;
  readonly releaseDecisions: Readonly<Record<B64LaterTier, ReleaseDecision>>;
}

export interface LaterTierReleaseState {
  readonly tier: B64LaterTier;
  readonly technicalPrepared: boolean;
  readonly releaseDecision: ReleaseDecision;
  readonly consumerVisible: boolean;
  readonly state: TierVisibilityState;
  readonly automaticUnlockAllowed: false;
  readonly perOpportunityTrustPolicyStillRequired: true;
}

const LATER_TIER_SEQUENCE: readonly B64LaterTier[] = Object.freeze(['P1', 'P2', 'P3', 'P4']);

export const RELEASE_GATE_INVARIANTS = Object.freeze({
  issueNumber: 1141 as const,
  sequentialUnlockRequired: true as const,
  explicitOwnerCentralDecisionRequiredPerTier: true as const,
  automaticUnlockAllowed: false as const,
  technicalPreparationDoesNotGrantVisibility: true as const,
  releaseDecisionDoesNotFabricateSupply: true as const,
  perOpportunityTrustPolicyGatesRemainRequired: true as const,
  p1AutomaticUnlockAllowed: P1_VISIBILITY_LOCK.automaticUnlockAllowed,
  p2AutomaticUnlockAllowed: P2_VISIBILITY_LOCK.automaticUnlockAllowed,
  p3AutomaticUnlockAllowed: P3_VISIBILITY_LOCK.automaticUnlockAllowed,
  p4AutomaticUnlockAllowed: P4_VISIBILITY_LOCK.automaticUnlockAllowed,
});

function hiddenStateFor(
  tier: B64LaterTier,
  input: ProgressiveReleaseInput,
  upstreamVisible: boolean,
): TierVisibilityState {
  if (!input.technicalPrepared[tier]) return 'HIDDEN_TECHNICAL_NOT_READY';
  if (input.releaseDecisions[tier] === 'REVOKED') return 'HIDDEN_REVOKED';
  if (tier === 'P1' && !input.p0LiveActivationComplete) return 'HIDDEN_AWAITING_P0_LIVE';
  if (!upstreamVisible) return 'HIDDEN_UPSTREAM_LOCK';
  if (input.releaseDecisions[tier] !== 'APPROVED') return 'HIDDEN_AWAITING_APPROVAL';
  return 'VISIBLE';
}

export function evaluateProgressiveRelease(input: ProgressiveReleaseInput) {
  const p0ConsumerLaneVisible = input.p0TechnicalComplete;
  let upstreamVisible = input.p0TechnicalComplete && input.p0LiveActivationComplete;
  const laterTierStates: LaterTierReleaseState[] = [];

  for (const tier of LATER_TIER_SEQUENCE) {
    const state = hiddenStateFor(tier, input, upstreamVisible);
    const consumerVisible = state === 'VISIBLE';
    laterTierStates.push(Object.freeze({
      tier,
      technicalPrepared: input.technicalPrepared[tier],
      releaseDecision: input.releaseDecisions[tier],
      consumerVisible,
      state,
      automaticUnlockAllowed: false as const,
      perOpportunityTrustPolicyStillRequired: true as const,
    }));
    upstreamVisible = upstreamVisible && consumerVisible;
  }

  const visibleLaterTiers = Object.freeze(
    laterTierStates.filter((tier) => tier.consumerVisible).map((tier) => tier.tier),
  );
  const visibleTiers = Object.freeze([
    ...(p0ConsumerLaneVisible ? ['P0' as const] : []),
    ...visibleLaterTiers,
  ]);

  return Object.freeze({
    issueNumber: 1141 as const,
    p0: Object.freeze({
      technicalComplete: input.p0TechnicalComplete,
      liveActivationComplete: input.p0LiveActivationComplete,
      consumerLaneVisible: p0ConsumerLaneVisible,
      realSupplyMayStillBeZero: true as const,
    }),
    laterTierStates: Object.freeze(laterTierStates),
    visibleTiers,
    highestVisibleTier: visibleTiers.length > 0 ? visibleTiers[visibleTiers.length - 1] : null,
    allLaterTiersHidden: visibleLaterTiers.length === 0,
    automaticUnlockAllowed: false as const,
    releaseAuthority: 'EXPLICIT_OWNER_CENTRAL_DECISION_PER_TIER' as const,
    perOpportunityTrustPolicyStillRequired: true as const,
  });
}

export const CURRENT_PROGRESSIVE_RELEASE_INPUT: ProgressiveReleaseInput = Object.freeze({
  p0TechnicalComplete: CURRENT_AD_CLICK_FIRST_READINESS.centralTechnicalComplete,
  p0LiveActivationComplete: CURRENT_AD_CLICK_FIRST_READINESS.liveActivationComplete,
  technicalPrepared: Object.freeze({
    P1: true,
    P2: true,
    P3: true,
    P4: true,
  }),
  releaseDecisions: Object.freeze({
    P1: 'NOT_APPROVED',
    P2: 'NOT_APPROVED',
    P3: 'NOT_APPROVED',
    P4: 'NOT_APPROVED',
  }),
});

export const CURRENT_PROGRESSIVE_RELEASE_STATE = evaluateProgressiveRelease(CURRENT_PROGRESSIVE_RELEASE_INPUT);
