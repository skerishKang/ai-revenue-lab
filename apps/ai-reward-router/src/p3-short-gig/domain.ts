import type { OpportunityCategory } from '../persistence/domain.js';
import type { VerifiedOpportunityTrustRecord } from '../verified20/domain.js';
import { validateVerifiedOpportunityTrustRecord } from '../verified20/domain.js';

export const P3_OPPORTUNITY_KINDS = [
  'AI_SKILLED_GIG',
  'LANGUAGE_GIG',
  'REVIEW_GIG',
  'REMOTE_PROJECT',
  'OTHER_SHORT_GIG',
] as const;
export type P3OpportunityKind = (typeof P3_OPPORTUNITY_KINDS)[number];

export type P3SupplyMode =
  | 'CURRENT_GIG_INVENTORY'
  | 'PUBLIC_PROJECT_APPLICATION'
  | 'PROGRAM_REFERENCE'
  | 'UNKNOWN_SUPPLY';

export type P3CommitmentMode =
  | 'BOUNDED_PROJECT_OR_TASK'
  | 'OPEN_ENDED_OR_RECURRING'
  | 'UNKNOWN_COMMITMENT';

export type P3PreparationState =
  | 'RANKABLE'
  | 'PROJECT_APPLICATION_REFERENCE_ONLY'
  | 'PROGRAM_REFERENCE_ONLY'
  | 'UNRANKABLE_UNKNOWN_COMMITMENT'
  | 'UNRANKABLE_MISSING_CURRENT_GIG_SUPPLY'
  | 'UNRANKABLE_MISSING_CRITICAL_DATA'
  | 'BLOCKED_MONETARY_PREREQUISITE'
  | 'BLOCKED_TRUST'
  | 'BLOCKED_INACTIVE';

export type P3PayModel =
  | 'HOURLY'
  | 'FIXED_PROJECT'
  | 'PER_TASK'
  | 'PER_UNIT'
  | 'VARIABLE_OR_OTHER';

export interface P3PreparedOpportunity {
  readonly opportunityId: string;
  readonly canonicalKey: string;
  readonly sourceId: string;
  readonly title: string;
  readonly kind: P3OpportunityKind;
  readonly preparationState: P3PreparationState;
  readonly supplyMode: P3SupplyMode;
  readonly commitmentMode: P3CommitmentMode;
  readonly payModel: P3PayModel;
  readonly rewardAmount: number | null;
  readonly rewardCurrency: string | null;
  readonly estimatedActiveMinutes: number | null;
  readonly estimatedTotalEffortMinutes: number | null;
  readonly normalizedHourlyValue: number | null;
  readonly certainty: VerifiedOpportunityTrustRecord['certaintyType'];
  readonly applicationRequired: boolean | null;
  readonly qualificationRequired: boolean | null;
  readonly acceptanceProbabilityKnown: boolean;
  readonly identityKycKnown: boolean;
  readonly languageRequirementsKnown: boolean;
  readonly skillRequirementsKnown: boolean;
  readonly deviceRequirementsKnown: boolean;
  readonly scheduleRequirementKnown: boolean;
  readonly payoutDelayKnown: boolean;
  readonly repeatabilityKnown: boolean;
  readonly purchaseOrSpendRequired: boolean;
  readonly requiredEligibilityCount: number;
  readonly unresolvedFrictionFields: readonly string[];
  readonly knownFrictionScore: number;
  readonly canonicalDestinationUrl: string | null;
  readonly lastCheckedAt: string;
  readonly supplyClaimMode: VerifiedOpportunityTrustRecord['supplyClaimMode'];
  readonly supplyAvailabilityState: string | null;
}

export const P3_VISIBILITY_LOCK = Object.freeze({
  issueNumber: 1135 as const,
  consumerVisible: false as const,
  primaryNavigationVisible: false as const,
  homeSectionVisible: false as const,
  todayRouteVisible: false as const,
  automaticUnlockAllowed: false as const,
  unlockAuthority: 'SEPARATE_OWNER_CENTRAL_DECISION_AFTER_P0_P1_P2_SEQUENCE' as const,
});

const P3_CATEGORIES = new Set<OpportunityCategory>([
  'USER_TESTING',
  'AI_EVALUATION',
  'DATA_ANNOTATION',
  'DATA_REVIEW',
  'TRANSLATION',
  'TRANSCRIPTION',
  'CONTENT_MODERATION',
  'SEARCH_OR_QUALITY_EVALUATION',
  'REMOTE_FREELANCE',
  'REMOTE_PROJECT',
  'OTHER_VERIFIED_ONLINE_INCOME',
]);
const INACTIVE_LIFECYCLES = new Set(['ENDED', 'STALE', 'ARCHIVED', 'REJECTED']);
const CURRENT_GIG_SUPPLY_STATES = new Set([
  'AVAILABLE',
  'LIVE',
  'CURRENT_GIG_AVAILABLE',
  'CURRENT_PROJECT_AVAILABLE',
  'PUBLIC_PROJECT_WORK_AVAILABLE',
]);

function isP3Candidate(record: VerifiedOpportunityTrustRecord): boolean {
  if (!P3_CATEGORIES.has(record.version.opportunityCategory)) return false;
  return record.version.incomeLadderLevel === 'SKILLED_DIGITAL_GIG' || record.version.incomeLadderLevel === 'PROJECT_WORK';
}

function kindFor(record: VerifiedOpportunityTrustRecord): P3OpportunityKind {
  switch (record.version.opportunityCategory) {
    case 'AI_EVALUATION':
    case 'DATA_ANNOTATION':
      return 'AI_SKILLED_GIG';
    case 'TRANSLATION':
    case 'TRANSCRIPTION':
      return 'LANGUAGE_GIG';
    case 'DATA_REVIEW':
    case 'CONTENT_MODERATION':
    case 'SEARCH_OR_QUALITY_EVALUATION':
    case 'USER_TESTING':
      return 'REVIEW_GIG';
    case 'REMOTE_FREELANCE':
    case 'REMOTE_PROJECT':
      return 'REMOTE_PROJECT';
    default:
      return 'OTHER_SHORT_GIG';
  }
}

function supplyModeFor(record: VerifiedOpportunityTrustRecord): P3SupplyMode {
  if (record.supplyClaimMode === 'PROVIDER_PROGRAM_ONLY') return 'PROGRAM_REFERENCE';
  const state = record.version.supplyAvailabilityState ?? '';
  if (CURRENT_GIG_SUPPLY_STATES.has(state)) return 'CURRENT_GIG_INVENTORY';
  if (record.version.applicationRequired === true && (state.includes('PROJECT') || state.includes('APPLICATION') || state.includes('ROLE_PAGE'))) {
    return 'PUBLIC_PROJECT_APPLICATION';
  }
  return 'UNKNOWN_SUPPLY';
}

function commitmentModeFor(record: VerifiedOpportunityTrustRecord): P3CommitmentMode {
  if (record.version.incomeLadderLevel === 'RECURRING_SIDE_JOB' || record.version.opportunityCategory === 'RECURRING_DIGITAL_WORK') {
    return 'OPEN_ENDED_OR_RECURRING';
  }
  if ((record.version.estimatedTotalEffortMinutes ?? 0) > 0 || (record.version.estimatedActiveMinutes ?? 0) > 0) {
    return 'BOUNDED_PROJECT_OR_TASK';
  }
  if (record.version.opportunityCategory === 'REMOTE_PROJECT' || ['FIXED', 'PER_TASK', 'PER_UNIT'].includes(record.version.compensationType)) {
    return 'BOUNDED_PROJECT_OR_TASK';
  }
  return 'UNKNOWN_COMMITMENT';
}

function payModelFor(record: VerifiedOpportunityTrustRecord): P3PayModel {
  switch (record.version.compensationType) {
    case 'HOURLY': return 'HOURLY';
    case 'FIXED': return 'FIXED_PROJECT';
    case 'PER_TASK': return 'PER_TASK';
    case 'PER_UNIT': return 'PER_UNIT';
    default: return 'VARIABLE_OR_OTHER';
  }
}

function rewardAmountFor(record: VerifiedOpportunityTrustRecord): number | null {
  return record.version.expectedPayoutValue ?? record.version.advertisedCompensationValue;
}

function normalizedHourlyValueFor(record: VerifiedOpportunityTrustRecord): number | null {
  const amount = rewardAmountFor(record);
  if (amount === null || record.version.compensationCurrency === null) return null;
  if (record.version.compensationType === 'HOURLY') return amount;
  const minutes = record.version.estimatedActiveMinutes ?? record.version.estimatedTotalEffortMinutes;
  if (minutes === null || minutes <= 0) return null;
  return amount * 60 / minutes;
}

function purchaseOrSpendRequired(record: VerifiedOpportunityTrustRecord): boolean {
  return record.windows.some((window) => window.windowType === 'PURCHASE');
}

function unresolvedFriction(record: VerifiedOpportunityTrustRecord): readonly string[] {
  const fields: string[] = [];
  if (record.version.applicationRequired === null) fields.push('applicationRequired');
  if (record.version.qualificationRequired === null) fields.push('qualificationRequired');
  if (record.version.acceptanceProbability === null) fields.push('acceptanceProbability');
  if (record.version.identityKycRequirements === null) fields.push('identityKycRequirements');
  if (record.version.languageRequirements === null) fields.push('languageRequirements');
  if (record.version.skillRequirements === null) fields.push('skillRequirements');
  if (record.version.deviceOsRequirements === null) fields.push('deviceOsRequirements');
  if (record.version.schedulingRequirements === null) fields.push('schedulingRequirements');
  if (record.version.repeatability === null) fields.push('repeatability');
  if (record.version.payoutDelay === null) fields.push('payoutDelay');
  if (record.version.startLatencyMinutes === null) fields.push('startLatencyMinutes');
  if (record.version.estimatedTotalEffortMinutes === null) fields.push('estimatedTotalEffortMinutes');
  return Object.freeze(fields);
}

function knownFrictionScore(record: VerifiedOpportunityTrustRecord): number {
  let score = 0;
  if (record.version.applicationRequired === true) score += 4;
  if (record.version.qualificationRequired === true) score += 4;
  if ((record.version.identityKycRequirements?.length ?? 0) > 0) score += 3;
  if ((record.version.deviceOsRequirements?.length ?? 0) > 0) score += 2;
  if (record.version.schedulingRequirements !== null) score += 2;
  if (record.version.taxContractorRequirements !== null) score += 2;
  if (record.version.payoutDelay !== null) score += 1;
  if ((record.version.startLatencyMinutes ?? 0) > 0) score += 1;
  score += Math.min(6, record.requirements.filter((requirement) => requirement.required).length);
  return score;
}

function stateFor(record: VerifiedOpportunityTrustRecord): P3PreparationState {
  if (!validateVerifiedOpportunityTrustRecord(record).countable) return 'BLOCKED_TRUST';
  if (INACTIVE_LIFECYCLES.has(record.opportunity.lifecycleState)) return 'BLOCKED_INACTIVE';
  if (purchaseOrSpendRequired(record)) return 'BLOCKED_MONETARY_PREREQUISITE';

  const supplyMode = supplyModeFor(record);
  if (supplyMode === 'PROGRAM_REFERENCE') return 'PROGRAM_REFERENCE_ONLY';
  if (supplyMode === 'PUBLIC_PROJECT_APPLICATION') return 'PROJECT_APPLICATION_REFERENCE_ONLY';
  if (supplyMode !== 'CURRENT_GIG_INVENTORY') return 'UNRANKABLE_MISSING_CURRENT_GIG_SUPPLY';
  if (commitmentModeFor(record) !== 'BOUNDED_PROJECT_OR_TASK') return 'UNRANKABLE_UNKNOWN_COMMITMENT';

  const amount = rewardAmountFor(record);
  if (amount === null || record.version.compensationCurrency === null || normalizedHourlyValueFor(record) === null) {
    return 'UNRANKABLE_MISSING_CRITICAL_DATA';
  }
  return 'RANKABLE';
}

export function prepareP3Opportunity(record: VerifiedOpportunityTrustRecord): P3PreparedOpportunity | null {
  if (!isP3Candidate(record)) return null;
  return Object.freeze({
    opportunityId: record.opportunity.id,
    canonicalKey: record.opportunity.canonicalKey,
    sourceId: record.snapshot.sourceId,
    title: record.version.title,
    kind: kindFor(record),
    preparationState: stateFor(record),
    supplyMode: supplyModeFor(record),
    commitmentMode: commitmentModeFor(record),
    payModel: payModelFor(record),
    rewardAmount: rewardAmountFor(record),
    rewardCurrency: record.version.compensationCurrency,
    estimatedActiveMinutes: record.version.estimatedActiveMinutes,
    estimatedTotalEffortMinutes: record.version.estimatedTotalEffortMinutes,
    normalizedHourlyValue: normalizedHourlyValueFor(record),
    certainty: record.certaintyType,
    applicationRequired: record.version.applicationRequired,
    qualificationRequired: record.version.qualificationRequired,
    acceptanceProbabilityKnown: record.version.acceptanceProbability !== null,
    identityKycKnown: record.version.identityKycRequirements !== null,
    languageRequirementsKnown: record.version.languageRequirements !== null,
    skillRequirementsKnown: record.version.skillRequirements !== null,
    deviceRequirementsKnown: record.version.deviceOsRequirements !== null,
    scheduleRequirementKnown: record.version.schedulingRequirements !== null,
    payoutDelayKnown: record.version.payoutDelay !== null,
    repeatabilityKnown: record.version.repeatability !== null,
    purchaseOrSpendRequired: purchaseOrSpendRequired(record),
    requiredEligibilityCount: record.requirements.filter((requirement) => requirement.required).length,
    unresolvedFrictionFields: unresolvedFriction(record),
    knownFrictionScore: knownFrictionScore(record),
    canonicalDestinationUrl: record.version.canonicalDestinationUrl,
    lastCheckedAt: record.lastCheckedAt,
    supplyClaimMode: record.supplyClaimMode,
    supplyAvailabilityState: record.version.supplyAvailabilityState,
  });
}

const CERTAINTY_RANK: Record<P3PreparedOpportunity['certainty'], number> = {
  GUARANTEED: 0,
  CONDITIONAL: 1,
  DRAW: 2,
};
const STATE_RANK: Record<P3PreparationState, number> = {
  RANKABLE: 0,
  PROJECT_APPLICATION_REFERENCE_ONLY: 1,
  PROGRAM_REFERENCE_ONLY: 2,
  UNRANKABLE_UNKNOWN_COMMITMENT: 3,
  UNRANKABLE_MISSING_CURRENT_GIG_SUPPLY: 4,
  UNRANKABLE_MISSING_CRITICAL_DATA: 5,
  BLOCKED_MONETARY_PREREQUISITE: 6,
  BLOCKED_TRUST: 7,
  BLOCKED_INACTIVE: 8,
};

export function compareP3PreparedOpportunities(a: P3PreparedOpportunity, b: P3PreparedOpportunity): number {
  const stateDelta = STATE_RANK[a.preparationState] - STATE_RANK[b.preparationState];
  if (stateDelta !== 0) return stateDelta;
  const unknownDelta = a.unresolvedFrictionFields.length - b.unresolvedFrictionFields.length;
  if (unknownDelta !== 0) return unknownDelta;
  const frictionDelta = a.knownFrictionScore - b.knownFrictionScore;
  if (frictionDelta !== 0) return frictionDelta;
  const certaintyDelta = CERTAINTY_RANK[a.certainty] - CERTAINTY_RANK[b.certainty];
  if (certaintyDelta !== 0) return certaintyDelta;
  if (a.normalizedHourlyValue !== null && b.normalizedHourlyValue !== null && a.normalizedHourlyValue !== b.normalizedHourlyValue) {
    return b.normalizedHourlyValue - a.normalizedHourlyValue;
  }
  if (a.normalizedHourlyValue !== null && b.normalizedHourlyValue === null) return -1;
  if (a.normalizedHourlyValue === null && b.normalizedHourlyValue !== null) return 1;
  const aMinutes = a.estimatedTotalEffortMinutes ?? a.estimatedActiveMinutes ?? Number.POSITIVE_INFINITY;
  const bMinutes = b.estimatedTotalEffortMinutes ?? b.estimatedActiveMinutes ?? Number.POSITIVE_INFINITY;
  if (aMinutes !== bMinutes) return aMinutes - bMinutes;
  return a.opportunityId.localeCompare(b.opportunityId);
}

export interface P3PreparedBacklogViewModel {
  readonly mode: 'P3_SHORT_GIG_PREPARATION_HIDDEN';
  readonly issueNumber: 1135;
  readonly consumerVisible: false;
  readonly visibilityLock: typeof P3_VISIBILITY_LOCK;
  readonly opportunities: readonly P3PreparedOpportunity[];
  readonly rankableCount: number;
  readonly projectReferenceCount: number;
  readonly programReferenceCount: number;
  readonly blockedOrUnrankableCount: number;
  readonly duplicateSuppressedCount: number;
}

export function buildP3PreparedBacklog(records: readonly VerifiedOpportunityTrustRecord[]): P3PreparedBacklogViewModel {
  const sorted = records
    .map(prepareP3Opportunity)
    .filter((item): item is P3PreparedOpportunity => item !== null)
    .sort(compareP3PreparedOpportunities);

  const deduped: P3PreparedOpportunity[] = [];
  const seen = new Set<string>();
  let duplicateSuppressedCount = 0;
  for (const item of sorted) {
    const key = `${item.sourceId}\u0000${item.canonicalKey}`;
    if (seen.has(key)) {
      duplicateSuppressedCount += 1;
      continue;
    }
    seen.add(key);
    deduped.push(item);
  }

  const opportunities = Object.freeze(deduped);
  return Object.freeze({
    mode: 'P3_SHORT_GIG_PREPARATION_HIDDEN' as const,
    issueNumber: 1135 as const,
    consumerVisible: false as const,
    visibilityLock: P3_VISIBILITY_LOCK,
    opportunities,
    rankableCount: opportunities.filter((item) => item.preparationState === 'RANKABLE').length,
    projectReferenceCount: opportunities.filter((item) => item.preparationState === 'PROJECT_APPLICATION_REFERENCE_ONLY').length,
    programReferenceCount: opportunities.filter((item) => item.preparationState === 'PROGRAM_REFERENCE_ONLY').length,
    blockedOrUnrankableCount: opportunities.filter((item) => !['RANKABLE', 'PROJECT_APPLICATION_REFERENCE_ONLY', 'PROGRAM_REFERENCE_ONLY'].includes(item.preparationState)).length,
    duplicateSuppressedCount,
  });
}
