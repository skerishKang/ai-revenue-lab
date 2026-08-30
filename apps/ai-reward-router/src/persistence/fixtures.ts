import type {
  EarningOpportunity,
  OpportunityChange,
  OpportunityCompensationComponent,
  OpportunityEvidence,
  OpportunityRequirement,
  OpportunityVersion,
  OpportunityWindow,
  ReviewQueueItem,
  SourceSnapshot,
} from './domain.js';
import { ACQUISITION_MODES } from '../source-policy/domain.js';

const T0 = '2026-08-30T00:00:00.000Z';

export interface OpportunityFixtureBundle {
  readonly snapshot: SourceSnapshot;
  readonly opportunity: EarningOpportunity;
  readonly versions: readonly OpportunityVersion[];
  readonly evidence: readonly OpportunityEvidence[];
  readonly requirements: readonly OpportunityRequirement[];
  readonly compensation: readonly OpportunityCompensationComponent[];
  readonly windows: readonly OpportunityWindow[];
  readonly change: OpportunityChange | null;
  readonly reviewQueue: readonly ReviewQueueItem[];
}

const baseVersion = (
  value: Partial<OpportunityVersion> & Pick<OpportunityVersion, 'id' | 'offerId' | 'sourceSnapshotId' | 'title' | 'opportunityCategory' | 'incomeLadderLevel' | 'compensationType'>,
): OpportunityVersion => ({
  versionNumber: 1,
  shortSummary: null,
  originalLanguage: 'en',
  verificationState: 'REVIEW_REQUIRED',
  sourceSnapshotHash: `hash:${value.sourceSnapshotId}`,
  modelId: null,
  promptVersion: null,
  inputHash: null,
  advertisedCompensationValue: null,
  expectedPayoutValue: null,
  compensationCurrency: null,
  estimatedActiveMinutes: null,
  estimatedTotalEffortMinutes: null,
  applicationMinutes: null,
  qualificationScreeningMinutes: null,
  preparationMinutes: null,
  startLatencyMinutes: null,
  payoutMethod: null,
  payoutDelay: null,
  providerFees: null,
  repeatability: null,
  supplyAvailabilityState: null,
  supplyObservedAt: null,
  applicationRequired: null,
  qualificationRequired: null,
  qualificationProbability: null,
  acceptanceProbability: null,
  rejectionOrReversalRisk: null,
  payoutReliability: null,
  eligibleCountriesOrRegions: null,
  languageRequirements: null,
  skillRequirements: null,
  deviceOsRequirements: null,
  identityKycRequirements: null,
  ageRequirements: null,
  taxContractorRequirements: null,
  schedulingRequirements: null,
  canonicalDestinationUrl: null,
  createdAt: T0,
  ...value,
});

export const MICRO_REWARD_FIXTURE: OpportunityFixtureBundle = Object.freeze({
  snapshot: Object.freeze({
    id: 'snap-fixture-promo-1', sourceId: 'SRC-TOSS', endpointId: null, acquiredAt: T0,
    acquisitionModeUsed: ACQUISITION_MODES.MANUAL_CURATED_OFFICIAL_SOURCE,
    canonicalUrl: 'https://example.invalid/fixture/promo', contentType: 'text/html',
    rawLocation: null, rawPayload: { fixture: true }, contentHash: 'sha256:fixture-promo-v1',
    fetchMetadata: null, actorProvenance: { actor: 'CENTRAL_FIXTURE' }, httpStatus: null,
  }),
  opportunity: Object.freeze({
    id: 'offer-fixture-promo', sourceId: 'SRC-TOSS', merchantId: null,
    canonicalKey: 'fixture-promo', providerExternalKey: null, lifecycleState: 'REVIEW_REQUIRED',
    currentVersionId: null, firstSeenAt: T0, lastSeenAt: T0,
  }),
  versions: Object.freeze([baseVersion({
    id: 'offer-fixture-promo-v1', offerId: 'offer-fixture-promo', sourceSnapshotId: 'snap-fixture-promo-1',
    title: 'Synthetic promotion fixture', opportunityCategory: 'PROMOTION', incomeLadderLevel: 'MICRO_REWARD',
    compensationType: 'FIXED', advertisedCompensationValue: 1000, expectedPayoutValue: 1000,
    compensationCurrency: 'KRW', estimatedActiveMinutes: 3,
  })]),
  evidence: Object.freeze([{
    id: 'ev-promo-value', offerVersionId: 'offer-fixture-promo-v1', sourceSnapshotId: 'snap-fixture-promo-1',
    fieldPath: 'advertisedCompensationValue', evidenceText: 'SYNTHETIC FIXTURE: 1000 KRW', evidenceLocator: null,
    evidenceHash: 'sha256:ev-promo-value', confidence: 1, createdAt: T0,
  }]),
  requirements: Object.freeze([]),
  compensation: Object.freeze([{
    id: 'comp-promo', offerVersionId: 'offer-fixture-promo-v1', componentType: 'FIXED_PAY' as const, amount: 1000,
    currency: 'KRW', rateUnit: null, percent: null, capAmount: null, conditionText: 'Synthetic fixture only', evidenceId: 'ev-promo-value',
  }]),
  windows: Object.freeze([]), change: null,
  reviewQueue: Object.freeze([{
    id: 'rq-promo', offerVersionId: 'offer-fixture-promo-v1', reasonCodes: ['NEW_OPPORTUNITY'], priority: 'NORMAL' as const,
    state: 'OPEN' as const, assignedTo: null, createdAt: T0, resolvedAt: null,
  }]),
});

export const PAID_RESEARCH_FIXTURE: OpportunityFixtureBundle = Object.freeze({
  snapshot: Object.freeze({
    id: 'snap-fixture-research-1', sourceId: 'SRC-PROLIFIC', endpointId: null, acquiredAt: T0,
    acquisitionModeUsed: ACQUISITION_MODES.DEEP_LINK_OR_DIRECTORY, canonicalUrl: 'https://example.invalid/fixture/research',
    contentType: 'text/html', rawLocation: null, rawPayload: { fixture: true }, contentHash: 'sha256:fixture-research-v1',
    fetchMetadata: null, actorProvenance: { actor: 'CENTRAL_FIXTURE' }, httpStatus: null,
  }),
  opportunity: Object.freeze({
    id: 'offer-fixture-research', sourceId: 'SRC-PROLIFIC', merchantId: null, canonicalKey: 'fixture-research',
    providerExternalKey: null, lifecycleState: 'REVIEW_REQUIRED', currentVersionId: null, firstSeenAt: T0, lastSeenAt: T0,
  }),
  versions: Object.freeze([baseVersion({
    id: 'offer-fixture-research-v1', offerId: 'offer-fixture-research', sourceSnapshotId: 'snap-fixture-research-1',
    title: 'Synthetic paid research fixture', opportunityCategory: 'MARKET_RESEARCH', incomeLadderLevel: 'TASK_WORK',
    compensationType: 'FIXED', applicationRequired: true, qualificationRequired: true,
    qualificationScreeningMinutes: 5, estimatedActiveMinutes: 30, payoutDelay: { days: 7 },
    qualificationProbability: null,
  })]),
  evidence: Object.freeze([]),
  requirements: Object.freeze([{
    id: 'req-research-qualification', offerVersionId: 'offer-fixture-research-v1', requirementType: 'QUALIFICATION' as const,
    operator: 'REQUIRED', normalizedValue: null, displayText: 'Synthetic screener required', required: true,
    confidence: 1, evidenceId: null,
  }]),
  compensation: Object.freeze([]),
  windows: Object.freeze([{ id: 'win-research-screen', offerVersionId: 'offer-fixture-research-v1', windowType: 'SCREENING' as const, startAt: null, endAt: null, relativeRule: null, displayText: 'Synthetic screening window', evidenceId: null }]),
  change: null,
  reviewQueue: Object.freeze([{ id: 'rq-research', offerVersionId: 'offer-fixture-research-v1', reasonCodes: ['QUALIFICATION_REQUIRED'], priority: 'NORMAL' as const, state: 'OPEN' as const, assignedTo: null, createdAt: T0, resolvedAt: null }]),
});

export const AI_DATA_WORK_FIXTURE: OpportunityFixtureBundle = Object.freeze({
  snapshot: Object.freeze({ id: 'snap-fixture-ai-1', sourceId: 'SRC-OUTLIER', endpointId: null, acquiredAt: T0, acquisitionModeUsed: ACQUISITION_MODES.DEEP_LINK_OR_DIRECTORY, canonicalUrl: 'https://example.invalid/fixture/ai-work', contentType: 'text/html', rawLocation: null, rawPayload: { fixture: true }, contentHash: 'sha256:fixture-ai-v1', fetchMetadata: null, actorProvenance: { actor: 'CENTRAL_FIXTURE' }, httpStatus: null }),
  opportunity: Object.freeze({ id: 'offer-fixture-ai', sourceId: 'SRC-OUTLIER', merchantId: null, canonicalKey: 'fixture-ai-work', providerExternalKey: null, lifecycleState: 'REVIEW_REQUIRED', currentVersionId: null, firstSeenAt: T0, lastSeenAt: T0 }),
  versions: Object.freeze([baseVersion({ id: 'offer-fixture-ai-v1', offerId: 'offer-fixture-ai', sourceSnapshotId: 'snap-fixture-ai-1', title: 'Synthetic AI evaluation fixture', opportunityCategory: 'AI_EVALUATION', incomeLadderLevel: 'SKILLED_DIGITAL_GIG', compensationType: 'HOURLY', advertisedCompensationValue: 25, compensationCurrency: 'USD', applicationRequired: true, qualificationRequired: true, languageRequirements: ['ko', 'en'], skillRequirements: ['evaluation'] })]),
  evidence: Object.freeze([]),
  requirements: Object.freeze([
    { id: 'req-ai-language', offerVersionId: 'offer-fixture-ai-v1', requirementType: 'LANGUAGE' as const, operator: 'IN', normalizedValue: ['ko', 'en'], displayText: 'Synthetic language requirement', required: true, confidence: 1, evidenceId: null },
    { id: 'req-ai-skill', offerVersionId: 'offer-fixture-ai-v1', requirementType: 'SKILL' as const, operator: 'CONTAINS', normalizedValue: ['evaluation'], displayText: 'Synthetic skill requirement', required: true, confidence: 1, evidenceId: null },
  ]),
  compensation: Object.freeze([{ id: 'comp-ai-hourly', offerVersionId: 'offer-fixture-ai-v1', componentType: 'HOURLY_RATE' as const, amount: 25, currency: 'USD', rateUnit: 'HOUR', percent: null, capAmount: null, conditionText: 'Synthetic fixture only', evidenceId: null }]),
  windows: Object.freeze([]), change: null,
  reviewQueue: Object.freeze([{ id: 'rq-ai', offerVersionId: 'offer-fixture-ai-v1', reasonCodes: ['QUALIFICATION_REQUIRED'], priority: 'NORMAL' as const, state: 'OPEN' as const, assignedTo: null, createdAt: T0, resolvedAt: null }]),
});

export const UNKNOWN_COMPENSATION_FIXTURE: OpportunityFixtureBundle = Object.freeze({
  snapshot: Object.freeze({ id: 'snap-fixture-unknown-1', sourceId: 'SRC-USERTESTING', endpointId: null, acquiredAt: T0, acquisitionModeUsed: ACQUISITION_MODES.DEEP_LINK_OR_DIRECTORY, canonicalUrl: 'https://example.invalid/fixture/unknown', contentType: 'text/html', rawLocation: null, rawPayload: { fixture: true }, contentHash: 'sha256:fixture-unknown-v1', fetchMetadata: null, actorProvenance: { actor: 'CENTRAL_FIXTURE' }, httpStatus: null }),
  opportunity: Object.freeze({ id: 'offer-fixture-unknown', sourceId: 'SRC-USERTESTING', merchantId: null, canonicalKey: 'fixture-unknown', providerExternalKey: null, lifecycleState: 'DISCOVERED', currentVersionId: null, firstSeenAt: T0, lastSeenAt: T0 }),
  versions: Object.freeze([baseVersion({ id: 'offer-fixture-unknown-v1', offerId: 'offer-fixture-unknown', sourceSnapshotId: 'snap-fixture-unknown-1', title: 'Synthetic unknown-compensation fixture', opportunityCategory: 'USER_TESTING', incomeLadderLevel: 'TASK_WORK', compensationType: 'OTHER', advertisedCompensationValue: null, expectedPayoutValue: null, compensationCurrency: null, qualificationProbability: null, supplyAvailabilityState: null })]),
  evidence: Object.freeze([]), requirements: Object.freeze([]), compensation: Object.freeze([]), windows: Object.freeze([]), change: null,
  reviewQueue: Object.freeze([{ id: 'rq-unknown', offerVersionId: 'offer-fixture-unknown-v1', reasonCodes: ['UNKNOWN_COMPENSATION'], priority: 'NORMAL' as const, state: 'OPEN' as const, assignedTo: null, createdAt: T0, resolvedAt: null }]),
});

const CHANGE_V1 = baseVersion({ id: 'offer-fixture-change-v1', offerId: 'offer-fixture-change', sourceSnapshotId: 'snap-fixture-change-1', title: 'Synthetic material-change fixture', opportunityCategory: 'REMOTE_PROJECT', incomeLadderLevel: 'PROJECT_WORK', compensationType: 'FIXED', advertisedCompensationValue: 100, compensationCurrency: 'USD', verificationState: 'VERIFIED', versionNumber: 1 });
const CHANGE_V2 = baseVersion({ id: 'offer-fixture-change-v2', offerId: 'offer-fixture-change', sourceSnapshotId: 'snap-fixture-change-2', title: 'Synthetic material-change fixture', opportunityCategory: 'REMOTE_PROJECT', incomeLadderLevel: 'PROJECT_WORK', compensationType: 'FIXED', advertisedCompensationValue: 150, compensationCurrency: 'USD', verificationState: 'REVIEW_REQUIRED', versionNumber: 2 });
export const MATERIAL_CHANGE_FIXTURE = Object.freeze({
  opportunity: Object.freeze({ id: 'offer-fixture-change', sourceId: 'SRC-RESPONDENT', merchantId: null, canonicalKey: 'fixture-change', providerExternalKey: null, lifecycleState: 'VERIFIED', currentVersionId: CHANGE_V1.id, firstSeenAt: T0, lastSeenAt: T0 }),
  versions: Object.freeze([CHANGE_V1, CHANGE_V2]),
  change: Object.freeze({ id: 'chg-fixture-1', offerId: 'offer-fixture-change', previousVersionId: CHANGE_V1.id, newVersionId: CHANGE_V2.id, material: true, changeType: 'COMPENSATION_AMOUNT', summary: 'Synthetic compensation changed from 100 to 150 USD', detectedAt: T0 }),
  reviewQueue: Object.freeze([{ id: 'rq-change-v2', offerVersionId: CHANGE_V2.id, reasonCodes: ['MATERIAL_CHANGE'], priority: 'HIGH' as const, state: 'OPEN' as const, assignedTo: null, createdAt: T0, resolvedAt: null }]),
});

export const SOURCE_HINT_INDEPENDENCE_FIXTURE = Object.freeze({
  sourceId: 'SRC-AYET',
  providerHints: Object.freeze(['OFFERWALL', 'SURVEY']),
  normalizedOpportunityCategory: 'MARKET_RESEARCH' as const,
  evidenceBacked: true,
});
