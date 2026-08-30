import type { OpportunityCategory } from '../persistence/domain.js';
import type { VerifiedOpportunityTrustRecord } from '../verified20/domain.js';
import { validateVerifiedOpportunityTrustRecord } from '../verified20/domain.js';

export const P1_OPPORTUNITY_KINDS = ['SURVEY', 'SHORT_REWARD'] as const;
export type P1OpportunityKind = (typeof P1_OPPORTUNITY_KINDS)[number];

export type P1PreparationState =
  | 'RANKABLE'
  | 'PROGRAM_REFERENCE_ONLY'
  | 'UNRANKABLE_MISSING_CRITICAL_DATA'
  | 'BLOCKED_TRUST'
  | 'BLOCKED_INACTIVE';

export interface P1PreparedOpportunity {
  readonly opportunityId: string;
  readonly sourceId: string;
  readonly title: string;
  readonly kind: P1OpportunityKind;
  readonly preparationState: P1PreparationState;
  readonly estimatedActiveMinutes: number | null;
  readonly rewardAmount: number | null;
  readonly rewardCurrency: string | null;
  readonly certainty: VerifiedOpportunityTrustRecord['certaintyType'];
  readonly effectiveHourlyValue: number | null;
  readonly qualificationRequired: boolean | null;
  readonly applicationRequired: boolean | null;
  readonly identityKycKnown: boolean;
  readonly purchaseRequirement: 'REQUIRED' | 'NOT_ESTABLISHED';
  readonly unresolvedFrictionFields: readonly string[];
  readonly knownFrictionScore: number;
  readonly canonicalDestinationUrl: string | null;
  readonly lastCheckedAt: string;
  readonly supplyClaimMode: VerifiedOpportunityTrustRecord['supplyClaimMode'];
  readonly supplyAvailabilityState: string | null;
}

export const P1_VISIBILITY_LOCK = Object.freeze({
  issueNumber: 1130 as const,
  consumerVisible: false as const,
  primaryNavigationVisible: false as const,
  homeSectionVisible: false as const,
  todayRouteVisible: false as const,
  automaticUnlockAllowed: false as const,
  unlockAuthority: 'SEPARATE_OWNER_CENTRAL_DECISION_AFTER_P0_LIVE_ACCEPTANCE' as const,
});

const INACTIVE_LIFECYCLES = new Set(['ENDED', 'STALE', 'ARCHIVED', 'REJECTED']);
const SHORT_REWARD_MAX_ACTIVE_MINUTES = 30;

function isP1Category(category: OpportunityCategory, record: VerifiedOpportunityTrustRecord): boolean {
  if (category === 'SURVEY') return true;
  if (category !== 'MARKET_RESEARCH') return false;
  if (record.supplyClaimMode === 'PROVIDER_PROGRAM_ONLY') return true;
  const minutes = record.version.estimatedActiveMinutes;
  return minutes !== null && minutes > 0 && minutes <= SHORT_REWARD_MAX_ACTIVE_MINUTES;
}

function kindFor(record: VerifiedOpportunityTrustRecord): P1OpportunityKind {
  return record.version.opportunityCategory === 'SURVEY' ? 'SURVEY' : 'SHORT_REWARD';
}

function rewardAmountFor(record: VerifiedOpportunityTrustRecord): number | null {
  return record.version.expectedPayoutValue ?? record.version.advertisedCompensationValue;
}

function calculateEffectiveHourlyValue(amount: number | null, minutes: number | null): number | null {
  if (amount === null || minutes === null || minutes <= 0) return null;
  return amount * 60 / minutes;
}

function unresolvedFriction(record: VerifiedOpportunityTrustRecord): readonly string[] {
  const fields: string[] = [];
  if (record.version.applicationRequired === null) fields.push('applicationRequired');
  if (record.version.qualificationRequired === null) fields.push('qualificationRequired');
  if (record.version.identityKycRequirements === null) fields.push('identityKycRequirements');
  if (record.version.payoutDelay === null) fields.push('payoutDelay');
  fields.push('accountLoginRequirement');
  fields.push('installRequirement');
  if (!record.windows.some((window) => window.windowType === 'PURCHASE')) fields.push('purchaseRequirement');
  return Object.freeze(fields);
}

function knownFrictionScore(record: VerifiedOpportunityTrustRecord): number {
  let score = 0;
  if (record.version.applicationRequired === true) score += 2;
  if (record.version.qualificationRequired === true) score += 2;
  if ((record.version.identityKycRequirements?.length ?? 0) > 0) score += 3;
  score += record.requirements.filter((requirement) => requirement.required).length;
  if (record.windows.some((window) => window.windowType === 'PURCHASE')) score += 5;
  return score;
}

function stateFor(record: VerifiedOpportunityTrustRecord): P1PreparationState {
  if (!validateVerifiedOpportunityTrustRecord(record).countable) return 'BLOCKED_TRUST';
  if (INACTIVE_LIFECYCLES.has(record.opportunity.lifecycleState)) return 'BLOCKED_INACTIVE';
  if (record.supplyClaimMode === 'PROVIDER_PROGRAM_ONLY') return 'PROGRAM_REFERENCE_ONLY';

  const amount = rewardAmountFor(record);
  const minutes = record.version.estimatedActiveMinutes;
  if (amount === null || record.version.compensationCurrency === null || minutes === null || minutes <= 0) {
    return 'UNRANKABLE_MISSING_CRITICAL_DATA';
  }
  return 'RANKABLE';
}

export function prepareP1Opportunity(record: VerifiedOpportunityTrustRecord): P1PreparedOpportunity | null {
  if (!isP1Category(record.version.opportunityCategory, record)) return null;
  const rewardAmount = rewardAmountFor(record);
  const estimatedActiveMinutes = record.version.estimatedActiveMinutes;
  return Object.freeze({
    opportunityId: record.opportunity.id,
    sourceId: record.snapshot.sourceId,
    title: record.version.title,
    kind: kindFor(record),
    preparationState: stateFor(record),
    estimatedActiveMinutes,
    rewardAmount,
    rewardCurrency: record.version.compensationCurrency,
    certainty: record.certaintyType,
    effectiveHourlyValue: calculateEffectiveHourlyValue(rewardAmount, estimatedActiveMinutes),
    qualificationRequired: record.version.qualificationRequired,
    applicationRequired: record.version.applicationRequired,
    identityKycKnown: record.version.identityKycRequirements !== null,
    purchaseRequirement: record.windows.some((window) => window.windowType === 'PURCHASE') ? 'REQUIRED' : 'NOT_ESTABLISHED',
    unresolvedFrictionFields: unresolvedFriction(record),
    knownFrictionScore: knownFrictionScore(record),
    canonicalDestinationUrl: record.version.canonicalDestinationUrl,
    lastCheckedAt: record.lastCheckedAt,
    supplyClaimMode: record.supplyClaimMode,
    supplyAvailabilityState: record.version.supplyAvailabilityState,
  });
}

const CERTAINTY_RANK: Record<P1PreparedOpportunity['certainty'], number> = {
  GUARANTEED: 0,
  CONDITIONAL: 1,
  DRAW: 2,
};

export function compareP1PreparedOpportunities(a: P1PreparedOpportunity, b: P1PreparedOpportunity): number {
  const stateRank: Record<P1PreparationState, number> = {
    RANKABLE: 0,
    PROGRAM_REFERENCE_ONLY: 1,
    UNRANKABLE_MISSING_CRITICAL_DATA: 2,
    BLOCKED_TRUST: 3,
    BLOCKED_INACTIVE: 4,
  };
  const stateDelta = stateRank[a.preparationState] - stateRank[b.preparationState];
  if (stateDelta !== 0) return stateDelta;

  const unknownDelta = a.unresolvedFrictionFields.length - b.unresolvedFrictionFields.length;
  if (unknownDelta !== 0) return unknownDelta;
  const frictionDelta = a.knownFrictionScore - b.knownFrictionScore;
  if (frictionDelta !== 0) return frictionDelta;
  const certaintyDelta = CERTAINTY_RANK[a.certainty] - CERTAINTY_RANK[b.certainty];
  if (certaintyDelta !== 0) return certaintyDelta;

  if (a.effectiveHourlyValue !== null && b.effectiveHourlyValue !== null && a.effectiveHourlyValue !== b.effectiveHourlyValue) {
    return b.effectiveHourlyValue - a.effectiveHourlyValue;
  }
  if (a.effectiveHourlyValue !== null && b.effectiveHourlyValue === null) return -1;
  if (a.effectiveHourlyValue === null && b.effectiveHourlyValue !== null) return 1;

  const aMinutes = a.estimatedActiveMinutes ?? Number.POSITIVE_INFINITY;
  const bMinutes = b.estimatedActiveMinutes ?? Number.POSITIVE_INFINITY;
  if (aMinutes !== bMinutes) return aMinutes - bMinutes;
  return a.opportunityId.localeCompare(b.opportunityId);
}

export interface P1PreparedBacklogViewModel {
  readonly mode: 'P1_PREPARATION_HIDDEN';
  readonly issueNumber: 1130;
  readonly consumerVisible: false;
  readonly visibilityLock: typeof P1_VISIBILITY_LOCK;
  readonly opportunities: readonly P1PreparedOpportunity[];
  readonly rankableCount: number;
  readonly programReferenceCount: number;
  readonly blockedOrUnrankableCount: number;
}

export function buildP1PreparedBacklog(records: readonly VerifiedOpportunityTrustRecord[]): P1PreparedBacklogViewModel {
  const opportunities = Object.freeze(
    records
      .map(prepareP1Opportunity)
      .filter((item): item is P1PreparedOpportunity => item !== null)
      .sort(compareP1PreparedOpportunities),
  );
  return Object.freeze({
    mode: 'P1_PREPARATION_HIDDEN' as const,
    issueNumber: 1130 as const,
    consumerVisible: false as const,
    visibilityLock: P1_VISIBILITY_LOCK,
    opportunities,
    rankableCount: opportunities.filter((item) => item.preparationState === 'RANKABLE').length,
    programReferenceCount: opportunities.filter((item) => item.preparationState === 'PROGRAM_REFERENCE_ONLY').length,
    blockedOrUnrankableCount: opportunities.filter((item) => item.preparationState !== 'RANKABLE' && item.preparationState !== 'PROGRAM_REFERENCE_ONLY').length,
  });
}
