import type {
  Source,
  SourceCollectionGate,
  SourcePolicyReview,
} from '../source-policy/domain.js';

export const OPPORTUNITY_CATEGORIES = [
  'REWARDED_AD', 'OFFERWALL', 'SURVEY', 'MARKET_RESEARCH', 'USER_TESTING',
  'AI_EVALUATION', 'DATA_ANNOTATION', 'DATA_REVIEW', 'TRANSLATION', 'TRANSCRIPTION',
  'CONTENT_MODERATION', 'SEARCH_OR_QUALITY_EVALUATION', 'MICROTASK', 'AFFILIATE_ACTION',
  'CASHBACK', 'PROMOTION', 'REMOTE_FREELANCE', 'REMOTE_PROJECT',
  'RECURRING_DIGITAL_WORK', 'OTHER_VERIFIED_ONLINE_INCOME',
] as const;
export type OpportunityCategory = (typeof OPPORTUNITY_CATEGORIES)[number];

export const INCOME_LADDER_LEVELS = [
  'MICRO_REWARD', 'TASK_WORK', 'SKILLED_DIGITAL_GIG', 'PROJECT_WORK', 'RECURRING_SIDE_JOB',
] as const;
export type IncomeLadderLevel = (typeof INCOME_LADDER_LEVELS)[number];

export const COMPENSATION_TYPES = [
  'FIXED', 'HOURLY', 'PER_TASK', 'PER_UNIT', 'VARIABLE', 'COMMISSION', 'BENEFIT', 'DRAW', 'OTHER',
] as const;
export type CompensationType = (typeof COMPENSATION_TYPES)[number];

export const OPPORTUNITY_LIFECYCLE_STATES = [
  'DISCOVERED', 'PARSED', 'REVIEW_REQUIRED', 'VERIFIED', 'LIVE', 'EXPIRING', 'ENDED', 'STALE', 'ARCHIVED', 'REJECTED',
] as const;
export type OpportunityLifecycleState = (typeof OPPORTUNITY_LIFECYCLE_STATES)[number];

export type OpportunityVerificationState = 'UNVERIFIED' | 'REVIEW_REQUIRED' | 'VERIFIED' | 'REJECTED';
export type RequirementType =
  | 'LANGUAGE' | 'SKILL' | 'QUALIFICATION' | 'IDENTITY_KYC' | 'AGE' | 'SCHEDULE'
  | 'COUNTRY_REGION' | 'PAYMENT_METHOD' | 'TAX_CONTRACTOR' | 'OTHER';
export type CompensationComponentType =
  | 'FIXED_PAY' | 'HOURLY_RATE' | 'PER_TASK' | 'PER_UNIT' | 'BONUS' | 'CASHBACK'
  | 'POINT' | 'DISCOUNT' | 'COUPON' | 'PRIZE' | 'BENEFIT' | 'COMMISSION' | 'OTHER';
export type OpportunityWindowType =
  | 'PARTICIPATION' | 'APPLICATION' | 'SCREENING' | 'QUALIFICATION' | 'WORK' | 'SUBMISSION'
  | 'REVIEW' | 'PURCHASE' | 'DRAW' | 'PAYOUT' | 'CLAIM';
export type ReviewPriority = 'LOW' | 'NORMAL' | 'HIGH' | 'CRITICAL';
export type ReviewState = 'OPEN' | 'IN_REVIEW' | 'RESOLVED';
export type ReviewDecision = 'APPROVE' | 'MODIFY_APPROVE' | 'REJECT';

export interface PersistedSourceRecord {
  readonly sourceId: string;
  readonly sourceName: string;
  readonly sourceType: string;
  readonly lane: Source['lane'];
  readonly launchPriority: Source['launchPriority'];
  readonly countryScope: string;
  readonly accessMode: string;
  readonly loginRequired: boolean;
  readonly jsRendered: boolean | 'UNKNOWN';
  readonly monetizationRole: Source['monetizationRole'];
  readonly verificationState: Source['verificationState'];
  readonly riskTier: Source['riskTier'];
  readonly updateCadence: string;
  readonly officialBaseUrl: string | null;
  readonly listUrl: string | null;
  readonly nextAction: string | null;
  readonly notes: string | null;
  readonly acquisitionMode: Source['acquisitionMode'];
  readonly opportunityClassHint: readonly string[];
}

export type PersistedSourcePolicyReviewRecord = Readonly<SourcePolicyReview & { id: string }>;
export type PersistedSourceCollectionGateRecord = Readonly<SourceCollectionGate>;

export interface SourceSnapshot {
  readonly id: string;
  readonly sourceId: string;
  readonly endpointId: string | null;
  readonly acquiredAt: string;
  readonly acquisitionModeUsed: Source['acquisitionMode'];
  readonly canonicalUrl: string | null;
  readonly contentType: string | null;
  readonly rawLocation: string | null;
  readonly rawPayload: unknown | null;
  readonly contentHash: string;
  readonly fetchMetadata: unknown | null;
  readonly actorProvenance: unknown | null;
  readonly httpStatus: number | null;
}

export interface EarningOpportunity {
  readonly id: string;
  readonly sourceId: string;
  readonly merchantId: string | null;
  readonly canonicalKey: string;
  readonly providerExternalKey: string | null;
  readonly lifecycleState: OpportunityLifecycleState;
  readonly currentVersionId: string | null;
  readonly firstSeenAt: string;
  readonly lastSeenAt: string;
}

export interface OpportunityVersion {
  readonly id: string;
  readonly offerId: string;
  readonly versionNumber: number;
  readonly sourceSnapshotId: string;
  readonly title: string;
  readonly shortSummary: string | null;
  readonly originalLanguage: string | null;
  readonly verificationState: OpportunityVerificationState;
  readonly sourceSnapshotHash: string;
  readonly modelId: string | null;
  readonly promptVersion: string | null;
  readonly inputHash: string | null;
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
  readonly rejectionOrReversalRisk: unknown | null;
  readonly payoutReliability: unknown | null;
  readonly eligibleCountriesOrRegions: readonly string[] | null;
  readonly languageRequirements: readonly string[] | null;
  readonly skillRequirements: readonly string[] | null;
  readonly deviceOsRequirements: readonly string[] | null;
  readonly identityKycRequirements: readonly string[] | null;
  readonly ageRequirements: unknown | null;
  readonly taxContractorRequirements: unknown | null;
  readonly schedulingRequirements: unknown | null;
  readonly canonicalDestinationUrl: string | null;
  readonly createdAt: string;
}

export interface OpportunityEvidence {
  readonly id: string;
  readonly offerVersionId: string;
  readonly sourceSnapshotId: string;
  readonly fieldPath: string;
  readonly evidenceText: string | null;
  readonly evidenceLocator: unknown | null;
  readonly evidenceHash: string;
  readonly confidence: number | null;
  readonly createdAt: string;
}

export interface OpportunityRequirement {
  readonly id: string;
  readonly offerVersionId: string;
  readonly requirementType: RequirementType;
  readonly operator: string;
  readonly normalizedValue: unknown | null;
  readonly displayText: string;
  readonly required: boolean;
  readonly confidence: number | null;
  readonly evidenceId: string | null;
}

export interface OpportunityCompensationComponent {
  readonly id: string;
  readonly offerVersionId: string;
  readonly componentType: CompensationComponentType;
  readonly amount: number | null;
  readonly currency: string | null;
  readonly rateUnit: string | null;
  readonly percent: number | null;
  readonly capAmount: number | null;
  readonly conditionText: string | null;
  readonly evidenceId: string | null;
}

export interface OpportunityWindow {
  readonly id: string;
  readonly offerVersionId: string;
  readonly windowType: OpportunityWindowType;
  readonly startAt: string | null;
  readonly endAt: string | null;
  readonly relativeRule: string | null;
  readonly displayText: string;
  readonly evidenceId: string | null;
}

export interface OpportunityChange {
  readonly id: string;
  readonly offerId: string;
  readonly previousVersionId: string;
  readonly newVersionId: string;
  readonly material: boolean;
  readonly changeType: string;
  readonly summary: string;
  readonly detectedAt: string;
}

export interface ReviewQueueItem {
  readonly id: string;
  readonly offerVersionId: string;
  readonly reasonCodes: readonly string[];
  readonly priority: ReviewPriority;
  readonly state: ReviewState;
  readonly assignedTo: string | null;
  readonly createdAt: string;
  readonly resolvedAt: string | null;
}

export interface ReviewDecisionRecord {
  readonly id: string;
  readonly reviewQueueId: string;
  readonly offerVersionId: string;
  readonly decision: ReviewDecision;
  readonly reviewerId: string;
  readonly approvalReason: string | null;
  readonly rejectionReason: string | null;
  readonly patch: unknown | null;
  readonly createdAt: string;
}

export function persistSource(source: Source): PersistedSourceRecord {
  return Object.freeze({
    sourceId: source.sourceId,
    sourceName: source.sourceName,
    sourceType: source.sourceType,
    lane: source.lane,
    launchPriority: source.launchPriority,
    countryScope: source.country,
    accessMode: source.accessMode,
    loginRequired: source.loginRequired,
    jsRendered: source.jsRendered,
    monetizationRole: source.monetizationRole,
    verificationState: source.verificationState,
    riskTier: source.riskTier,
    updateCadence: source.updateCadence,
    officialBaseUrl: source.officialBaseUrl,
    listUrl: source.listUrl,
    nextAction: source.nextAction,
    notes: source.notes,
    acquisitionMode: source.acquisitionMode,
    opportunityClassHint: Object.freeze([...source.opportunityClassHint]),
  });
}

export function persistPolicyReview(policy: SourcePolicyReview): PersistedSourcePolicyReviewRecord {
  return Object.freeze({ id: `${policy.sourceId}:CURRENT`, ...policy });
}

export function persistCollectionGate(gate: SourceCollectionGate): PersistedSourceCollectionGateRecord {
  return Object.freeze({ ...gate });
}

const nonNegativeFields: readonly (keyof OpportunityVersion)[] = [
  'advertisedCompensationValue', 'expectedPayoutValue', 'estimatedActiveMinutes',
  'estimatedTotalEffortMinutes', 'applicationMinutes', 'qualificationScreeningMinutes',
  'preparationMinutes', 'startLatencyMinutes',
];
const probabilityFields: readonly (keyof OpportunityVersion)[] = [
  'qualificationProbability', 'acceptanceProbability',
];

export function sourceSnapshotDedupKey(snapshot: SourceSnapshot): string {
  return `${snapshot.sourceId}\u0000${snapshot.canonicalUrl ?? ''}\u0000${snapshot.contentHash}`;
}

export function validateOpportunityVersion(version: OpportunityVersion): readonly string[] {
  const errors: string[] = [];
  if (!Number.isInteger(version.versionNumber) || version.versionNumber <= 0) {
    errors.push('versionNumber must be a positive integer');
  }
  for (const field of nonNegativeFields) {
    const value = version[field];
    if (typeof value === 'number' && value < 0) errors.push(`${field} must be >= 0 when present`);
  }
  for (const field of probabilityFields) {
    const value = version[field];
    if (typeof value === 'number' && (value < 0 || value > 1)) errors.push(`${field} must be between 0 and 1 when present`);
  }
  return Object.freeze(errors);
}

export function validateOpportunityWindow(window: OpportunityWindow): readonly string[] {
  if (window.startAt !== null && window.endAt !== null && Date.parse(window.endAt) < Date.parse(window.startAt)) {
    return Object.freeze(['endAt must be >= startAt']);
  }
  return Object.freeze([]);
}

export function guaranteedCompensationTotal(components: readonly OpportunityCompensationComponent[]): number | null {
  let total = 0;
  let sawGuaranteedAmount = false;
  for (const component of components) {
    if (component.componentType === 'PRIZE') continue;
    if (component.amount === null) continue;
    total += component.amount;
    sawGuaranteedAmount = true;
  }
  return sawGuaranteedAmount ? total : null;
}

export function canMarkVerified(version: OpportunityVersion, humanApprovalRecorded: boolean): boolean {
  return humanApprovalRecorded && version.verificationState !== 'REJECTED';
}
