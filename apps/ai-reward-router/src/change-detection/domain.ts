import type {
  OpportunityChange,
  OpportunityVersion,
  ReviewQueueItem,
} from '../persistence/domain.js';
import type {
  CandidateOpportunity,
  CandidateReviewRequest,
  ExtractionRunProvenance,
} from '../extraction/domain.js';

export type ChangeDisposition =
  | 'NO_CHANGE'
  | 'NON_MATERIAL_CHANGE'
  | 'MATERIAL_CHANGE_REVIEW_REQUIRED';

export type ChangeSemanticGroup =
  | 'CONTENT'
  | 'CLASSIFICATION'
  | 'COMPENSATION'
  | 'EFFORT'
  | 'PAYOUT'
  | 'AVAILABILITY'
  | 'ELIGIBILITY'
  | 'DESTINATION';

export const MATERIAL_TERM_FIELDS = [
  'title',
  'opportunityCategory',
  'incomeLadderLevel',
  'compensationType',
  'advertisedCompensationValue',
  'expectedPayoutValue',
  'compensationCurrency',
  'estimatedActiveMinutes',
  'estimatedTotalEffortMinutes',
  'applicationMinutes',
  'qualificationScreeningMinutes',
  'preparationMinutes',
  'startLatencyMinutes',
  'payoutMethod',
  'payoutDelay',
  'providerFees',
  'repeatability',
  'supplyAvailabilityState',
  'applicationRequired',
  'qualificationRequired',
  'qualificationProbability',
  'acceptanceProbability',
  'eligibleCountriesOrRegions',
  'languageRequirements',
  'skillRequirements',
  'deviceOsRequirements',
  'identityKycRequirements',
  'ageRequirements',
  'taxContractorRequirements',
  'schedulingRequirements',
  'canonicalDestinationUrl',
] as const;

export const NON_MATERIAL_TERM_FIELDS = [
  'shortSummary',
  'originalLanguage',
] as const;

export type MaterialTermField = (typeof MATERIAL_TERM_FIELDS)[number];
export type NonMaterialTermField = (typeof NON_MATERIAL_TERM_FIELDS)[number];
export type ComparableTermField = MaterialTermField | NonMaterialTermField;

export interface NormalizedTermChange {
  readonly field: ComparableTermField;
  readonly group: ChangeSemanticGroup;
  readonly material: boolean;
  readonly previousValue: unknown;
  readonly nextValue: unknown;
}

export interface MaterialChangeDetectionResult {
  readonly previousVersionId: string;
  readonly nextSourceSnapshotId: string;
  readonly changes: readonly NormalizedTermChange[];
  readonly materialChanges: readonly NormalizedTermChange[];
  readonly nonMaterialChanges: readonly NormalizedTermChange[];
  readonly disposition: ChangeDisposition;
  readonly newVersionRequired: boolean;
  readonly reviewRequired: boolean;
  readonly currentVersionReplacementAllowed: false;
}

export interface NextVersionProposalInput {
  readonly previousVersion: OpportunityVersion;
  readonly candidate: CandidateOpportunity;
  readonly provenance: ExtractionRunProvenance;
  readonly w5Review: CandidateReviewRequest;
  readonly nextVersionId: string;
  readonly changeId: string;
  readonly reviewQueueId: string;
  readonly detectedAt: string;
  readonly createdAt: string;
}

export interface NextVersionProposal {
  readonly detection: MaterialChangeDetectionResult;
  readonly proposedVersion: OpportunityVersion | null;
  readonly change: OpportunityChange | null;
  readonly reviewQueueItem: ReviewQueueItem | null;
  readonly currentVersionReplacementAllowed: false;
}
