import type {
  CompensationType,
  IncomeLadderLevel,
  OpportunityCategory,
  SourceSnapshot,
} from '../persistence/domain.js';

export type ExtractorKind = 'RULE' | 'MODEL' | 'HYBRID';
export type ExtractionRunStatus = 'SUCCESS' | 'SCHEMA_REJECTED' | 'FAILED';
export type CandidateFreshness = 'CURRENT' | 'STALE' | 'BROKEN' | 'UNKNOWN';
export type ConflictRiskCode =
  | 'NONE'
  | 'MISSING_CRITICAL_EVIDENCE'
  | 'SOURCE_CONFLICT'
  | 'AMBIGUOUS_COMPENSATION'
  | 'AMBIGUOUS_ELIGIBILITY'
  | 'AMBIGUOUS_TIMING'
  | 'STALE_OR_BROKEN_SOURCE'
  | 'HIGH_RISK_HUMAN_REVIEW'
  | 'MODEL_SCHEMA_FAILURE';

export interface ExtractionInput {
  readonly snapshot: SourceSnapshot;
  readonly schemaVersion: string;
  readonly runId: string;
  readonly startedAt: string;
}

export interface CandidateOpportunity {
  readonly candidateId: string;
  readonly sourceSnapshotId: string;
  readonly sourceId: string;
  readonly title: string;
  readonly shortSummary: string | null;
  readonly originalLanguage: string | null;
  readonly opportunityCategory: OpportunityCategory;
  readonly incomeLadderLevel: IncomeLadderLevel;
  readonly compensationType: CompensationType;
  readonly advertisedCompensationValue: number | null;
  readonly expectedPayoutValue: number | null;
  readonly compensationCurrency: string | null;
  readonly estimatedActiveMinutes: number | null;
  readonly estimatedTotalEffortMinutes: number | null;
  readonly applicationMinutes: number | null;
  readonly qualificationScreeningMinutes: number | null;
  readonly preparationMinutes: number | null;
  readonly startLatencyMinutes: number | null;
  readonly payoutMethod: unknown | null;
  readonly payoutDelay: unknown | null;
  readonly providerFees: unknown | null;
  readonly repeatability: unknown | null;
  readonly supplyAvailabilityState: string | null;
  readonly supplyObservedAt: string | null;
  readonly applicationRequired: boolean | null;
  readonly qualificationRequired: boolean | null;
  readonly qualificationProbability: number | null;
  readonly acceptanceProbability: number | null;
  readonly eligibleCountriesOrRegions: readonly string[] | null;
  readonly languageRequirements: readonly string[] | null;
  readonly skillRequirements: readonly string[] | null;
  readonly deviceOsRequirements: readonly string[] | null;
  readonly identityKycRequirements: readonly string[] | null;
  readonly ageRequirements: unknown | null;
  readonly taxContractorRequirements: unknown | null;
  readonly schedulingRequirements: unknown | null;
  readonly canonicalDestinationUrl: string | null;
  readonly sourceFreshness: CandidateFreshness;
  readonly immediateTodayRouteClaim: boolean | null;
}

export interface EvidenceBinding {
  readonly candidateField: string;
  readonly sourceSnapshotId: string;
  readonly sourceLocator: string | null;
  readonly evidenceTextHash: string;
  readonly evidenceType: 'SOURCE_TEXT' | 'STRUCTURED_SOURCE' | 'CURATOR_CAPTURE';
  readonly extractedValue: unknown;
  readonly confidence: number | null;
  readonly conflict: boolean;
}

export interface ExtractorOutput {
  readonly candidate: CandidateOpportunity;
  readonly evidence: readonly EvidenceBinding[];
  readonly rawStructuredOutputHash: string;
}

export interface OpportunityExtractor {
  readonly kind: ExtractorKind;
  readonly providerId: string | null;
  readonly modelId: string | null;
  readonly promptVersion: string | null;
  extract(input: ExtractionInput): Promise<ExtractorOutput>;
}

export interface ExtractionRunProvenance {
  readonly extractionRunId: string;
  readonly sourceSnapshotId: string;
  readonly inputSnapshotSha256: string;
  readonly extractorKind: ExtractorKind;
  readonly providerId: string | null;
  readonly modelId: string | null;
  readonly promptVersion: string | null;
  readonly schemaVersion: string;
  readonly startedAt: string;
  readonly completedAt: string;
  readonly rawStructuredOutputHash: string | null;
  readonly status: ExtractionRunStatus;
  readonly validationErrors: readonly string[];
  readonly humanCorrectionLineage: null;
}

export interface CandidateReviewRequest {
  readonly candidateId: string;
  readonly state: 'REVIEW_REQUIRED';
  readonly riskCodes: readonly ConflictRiskCode[];
  readonly structuralErrors: readonly string[];
  readonly semanticErrors: readonly string[];
  readonly evidenceErrors: readonly string[];
  readonly publicationAllowed: false;
  readonly verificationAllowed: false;
}

export interface ExtractionPipelineResult {
  readonly candidate: CandidateOpportunity | null;
  readonly evidence: readonly EvidenceBinding[];
  readonly provenance: ExtractionRunProvenance;
  readonly review: CandidateReviewRequest;
}
