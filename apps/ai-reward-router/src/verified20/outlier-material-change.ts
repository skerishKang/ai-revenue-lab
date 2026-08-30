import type {
  EarningOpportunity,
  OpportunityChange,
  OpportunityCompensationComponent,
  OpportunityEvidence,
  OpportunityRequirement,
  OpportunityVersion,
  OpportunityWindow,
  ReviewDecisionRecord,
  ReviewQueueItem,
  SourceSnapshot,
} from '../persistence/domain.js';
import { sourceById } from '../source-policy/registry.js';
import type { Verified20Record } from './domain.js';
import { stableEvidenceHash } from './hash.js';
import {
  OUTLIER_PRE_CURATION_GATES,
  OUTLIER_W8_OPPORTUNITY,
  OUTLIER_W8_POLICY,
  OUTLIER_W8_VERSION,
} from './outlier.js';
import type { W8RealNegativeEvidenceCase } from './real-negative-evidence.js';

export const OUTLIER_W8_V2_OBSERVED_AT = '2026-08-30T09:02:00.000Z';
const roleUrl = 'https://outlier.ai/languages/ko-kr';

const rawPayloadV2 = Object.freeze({
  provider: 'Outlier AI',
  publicRole: 'Korean Voice AI Evaluator',
  language: 'Korean',
  location: 'South Korea (Remote)',
  advertisedRateCeilingUsdPerHour: 31,
  compensationQualifier: 'up to; varies by expertise, assessment, location and project; lower non-core rates may apply',
  publicPaymentMethods: Object.freeze(['PayPal', 'Airtm']),
  schedule: Object.freeze({ typicalHoursPerWeek: '5-10', maximumReferencedHoursPerWeek: 40, flexible: true }),
  onboarding: Object.freeze(['create account', 'verify identity and phone', 'pass skill assessment', 'complete tasks']),
  taskExamples: Object.freeze([
    'participate in live scenario-based Korean conversations with an AI voice model',
    'review recorded Korean speaker/AI conversations',
    'score naturalness helpfulness and audio quality',
  ]),
  idealExperience: Object.freeze(['conversational Korean', 'improvisation or voice work', 'customer-facing unscripted conversation', 'conversation or audio quality review']),
  acceptanceProbability: null,
  guaranteedWeeklyHours: null,
  futureTaskSupply: null,
  canonicalUrl: roleUrl,
});

const snapshotHashV2 = stableEvidenceHash(rawPayloadV2);

export const OUTLIER_W8_SNAPSHOT_V2: SourceSnapshot = Object.freeze({
  id: 'snapshot-w8-outlier-ko-voice-20260830', sourceId: 'SRC-OUTLIER', endpointId: null,
  acquiredAt: OUTLIER_W8_V2_OBSERVED_AT, acquisitionModeUsed: sourceById('SRC-OUTLIER').acquisitionMode,
  canonicalUrl: roleUrl, contentType: 'application/json', rawLocation: null, rawPayload: rawPayloadV2, contentHash: snapshotHashV2,
  fetchMetadata: Object.freeze({ acquisition: 'CENTRAL_MANUAL_CURATED_OFFICIAL_SOURCE', productTransportCallCount: 0, centralResearchNetworkUsed: true, privateAccountAccess: false, loggedInTaskInventoryObserved: false }),
  actorProvenance: Object.freeze({ actorId: 'CENTRAL', mode: 'MANUAL_CURATED_OFFICIAL_SOURCE' }), httpStatus: null,
});

export const OUTLIER_W8_VERSION_V2: OpportunityVersion = Object.freeze({
  id: 'opp-w8-outlier-korean-freelance-writer-v2',
  offerId: OUTLIER_W8_OPPORTUNITY.id,
  versionNumber: 2,
  sourceSnapshotId: OUTLIER_W8_SNAPSHOT_V2.id,
  title: 'Korean Voice AI Evaluator — Outlier AI training',
  shortSummary: 'The same official ko-kr route now publicly presents a Korean Voice AI Evaluator role focused on live Korean voice conversations and recorded-conversation evaluation. It advertises up to USD 31/hour. Acceptance probability, guaranteed hours and future task supply remain NULL/UNKNOWN.',
  originalLanguage: 'en', verificationState: 'VERIFIED', sourceSnapshotHash: snapshotHashV2,
  modelId: null, promptVersion: null, inputHash: null,
  opportunityCategory: 'AI_EVALUATION', incomeLadderLevel: 'SKILLED_DIGITAL_GIG', compensationType: 'HOURLY',
  advertisedCompensationValue: 31, expectedPayoutValue: null, compensationCurrency: 'USD',
  estimatedActiveMinutes: null, estimatedTotalEffortMinutes: null, applicationMinutes: null, qualificationScreeningMinutes: null, preparationMinutes: null, startLatencyMinutes: null,
  payoutMethod: Object.freeze({ methods: Object.freeze(['PayPal','Airtm']) }), payoutDelay: Object.freeze({ cadence: 'WEEKLY' }), providerFees: null, repeatability: null,
  supplyAvailabilityState: 'PUBLIC_ROLE_PAGE_AVAILABLE', supplyObservedAt: OUTLIER_W8_V2_OBSERVED_AT,
  applicationRequired: true, qualificationRequired: true, qualificationProbability: null, acceptanceProbability: null,
  rejectionOrReversalRisk: null, payoutReliability: null, eligibleCountriesOrRegions: Object.freeze(['KOREA']),
  languageRequirements: Object.freeze(['KOREAN']), skillRequirements: Object.freeze(['CONVERSATIONAL_KOREAN','VOICE_OR_CONVERSATION_EVALUATION']),
  deviceOsRequirements: null, identityKycRequirements: Object.freeze(['IDENTITY_VERIFICATION','PHONE_VERIFICATION']), ageRequirements: null,
  taxContractorRequirements: Object.freeze({ relationship: 'INDEPENDENT_CONTRACTOR', localWorkAuthorizationRequired: true }),
  schedulingRequirements: Object.freeze({ flexibleSchedule: true, typicalHoursPerWeek: '5-10', publicMaximumReferenceHoursPerWeek: 40, guaranteedHours: null }),
  canonicalDestinationUrl: roleUrl, createdAt: OUTLIER_W8_V2_OBSERVED_AT,
});

export const OUTLIER_W8_OPPORTUNITY_V2: EarningOpportunity = Object.freeze({
  ...OUTLIER_W8_OPPORTUNITY,
  currentVersionId: OUTLIER_W8_VERSION_V2.id,
  lastSeenAt: OUTLIER_W8_V2_OBSERVED_AT,
});

function evidence(id: string, fieldPath: string, evidenceText: string): OpportunityEvidence {
  const locator = Object.freeze({ url: roleUrl, observationMode: 'OFFICIAL_PUBLIC_PAGE' });
  return Object.freeze({ id, offerVersionId: OUTLIER_W8_VERSION_V2.id, sourceSnapshotId: OUTLIER_W8_SNAPSHOT_V2.id, fieldPath, evidenceText, evidenceLocator: locator, evidenceHash: stableEvidenceHash({ fieldPath, evidenceText, locator }), confidence: 1, createdAt: OUTLIER_W8_V2_OBSERVED_AT });
}

export const OUTLIER_W8_EVIDENCE_V2: readonly OpportunityEvidence[] = Object.freeze([
  evidence('ev-w8-outlier-v2-role', 'title', 'Official ko-kr page now identifies a Korean Voice AI Evaluator role.'),
  evidence('ev-w8-outlier-v2-location', 'eligibleCountriesOrRegions', 'Role remains South Korea remote.'),
  evidence('ev-w8-outlier-v2-rate', 'advertisedCompensationValue', 'Current public role advertises up to USD 31/hour with rate variability disclaimers.'),
  evidence('ev-w8-outlier-v2-task-live', 'opportunityCategory', 'Current tasks include live scenario-based Korean conversations with an AI voice model.'),
  evidence('ev-w8-outlier-v2-task-review', 'skillRequirements', 'Current tasks include reviewing recorded Korean AI conversations and scoring naturalness, helpfulness and audio quality.'),
  evidence('ev-w8-outlier-v2-onboarding', 'qualificationRequired', 'Account creation, identity/phone verification and skill assessment remain part of onboarding.'),
  evidence('ev-w8-outlier-v2-schedule', 'schedulingRequirements', 'Page describes flexible work; most experts contribute 5–10 hours/week with a public reference up to 40, without guaranteeing hours.'),
]);
const ev = (id: string) => OUTLIER_W8_EVIDENCE_V2.find((item) => item.id === id)?.id ?? null;

export const OUTLIER_W8_REQUIREMENTS_V2: readonly OpportunityRequirement[] = Object.freeze([
  Object.freeze({ id: 'req-w8-outlier-v2-language', offerVersionId: OUTLIER_W8_VERSION_V2.id, requirementType: 'LANGUAGE', operator: 'REQUIRED', normalizedValue: Object.freeze(['KOREAN']), displayText: 'Fluent conversational Korean is required.', required: true, confidence: 1, evidenceId: ev('ev-w8-outlier-v2-role') }),
  Object.freeze({ id: 'req-w8-outlier-v2-qualification', offerVersionId: OUTLIER_W8_VERSION_V2.id, requirementType: 'QUALIFICATION', operator: 'REQUIRED', normalizedValue: Object.freeze({ skillAssessment: true }), displayText: 'A skill assessment is required before tasking.', required: true, confidence: 1, evidenceId: ev('ev-w8-outlier-v2-onboarding') }),
  Object.freeze({ id: 'req-w8-outlier-v2-identity', offerVersionId: OUTLIER_W8_VERSION_V2.id, requirementType: 'IDENTITY_KYC', operator: 'REQUIRED', normalizedValue: Object.freeze({ identityVerification: true, phoneVerification: true }), displayText: 'Identity and phone verification are part of onboarding.', required: true, confidence: 1, evidenceId: ev('ev-w8-outlier-v2-onboarding') }),
]);

export const OUTLIER_W8_COMPENSATION_V2: readonly OpportunityCompensationComponent[] = Object.freeze([
  Object.freeze({ id: 'comp-w8-outlier-v2-hourly', offerVersionId: OUTLIER_W8_VERSION_V2.id, componentType: 'HOURLY_RATE', amount: 31, currency: 'USD', rateUnit: 'HOUR', percent: null, capAmount: null, conditionText: 'Up to USD 31/hour; actual rate varies and lower non-core rates may apply. This is not an expected or guaranteed rate.', evidenceId: ev('ev-w8-outlier-v2-rate') }),
]);

export const OUTLIER_W8_WINDOWS_V2: readonly OpportunityWindow[] = Object.freeze([
  Object.freeze({ id: 'window-w8-outlier-v2-application', offerVersionId: OUTLIER_W8_VERSION_V2.id, windowType: 'APPLICATION', startAt: null, endAt: null, relativeRule: 'OPEN_WHILE_CURRENT_OFFICIAL_ROLE_PAGE_ACCEPTS_APPLICATIONS', displayText: 'Current official role page exposes an application action; no closing date is inferred.', evidenceId: ev('ev-w8-outlier-v2-role') }),
]);

export const OUTLIER_W8_CHANGE_V1_TO_V2: OpportunityChange = Object.freeze({
  id: 'change-w8-outlier-ko-v1-v2', offerId: OUTLIER_W8_OPPORTUNITY.id,
  previousVersionId: OUTLIER_W8_VERSION.id, newVersionId: OUTLIER_W8_VERSION_V2.id,
  material: true, changeType: 'ROLE_SCOPE_AND_TASK_SEMANTICS',
  summary: 'Same canonical ko-kr route changed from a Korean freelance text/writing AI-training role to a Korean Voice AI Evaluator role with live and recorded voice-conversation tasks; immutable v1 is retained and v2 required review before becoming current.',
  detectedAt: OUTLIER_W8_V2_OBSERVED_AT,
});

export const OUTLIER_W8_V2_REVIEW_QUEUE: ReviewQueueItem = Object.freeze({ id: 'rq-w8-outlier-ko-v2', offerVersionId: OUTLIER_W8_VERSION_V2.id, reasonCodes: Object.freeze(['MATERIAL_CHANGE','ROLE_SCOPE_CHANGED','TASK_MODALITY_CHANGED']), priority: 'CRITICAL', state: 'RESOLVED', assignedTo: 'CENTRAL', createdAt: OUTLIER_W8_V2_OBSERVED_AT, resolvedAt: OUTLIER_W8_V2_OBSERVED_AT });
export const OUTLIER_W8_V2_REVIEW: ReviewDecisionRecord = Object.freeze({ id: 'review-w8-outlier-ko-v2', reviewQueueId: OUTLIER_W8_V2_REVIEW_QUEUE.id, offerVersionId: OUTLIER_W8_VERSION_V2.id, decision: 'APPROVE', reviewerId: 'CENTRAL', approvalReason: 'Fresh official same-route evidence materially changed the role/task semantics to Korean voice interaction and conversation evaluation. v1 remains immutable history; v2 is approved as the current evidence-backed representation. Up-to pay remains non-guaranteed and acceptance/future supply remain NULL/UNKNOWN.', rejectionReason: null, patch: null, createdAt: OUTLIER_W8_V2_OBSERVED_AT });

export const OUTLIER_REAL_MATERIAL_CHANGE_CASE: W8RealNegativeEvidenceCase = Object.freeze({
  evidenceId: 'w8-real-negative-outlier-material-change-20260830', demonstrationId: 'MATERIAL_VERSION_CHANGE',
  sourceId: 'SRC-OUTLIER', canonicalUrl: roleUrl, observedAt: OUTLIER_W8_V2_OBSERVED_AT, realEvidence: true,
  disposition: 'NEW_VERSION_REVIEW_REQUIRED', countableVerified20: false,
  reasonCodes: Object.freeze(['SAME_CANONICAL_ROUTE','ROLE_SCOPE_CHANGED','TASK_MODALITY_CHANGED','IMMUTABLE_V1_RETAINED','V2_REVIEW_REQUIRED']),
  evidenceSummary: 'Fresh official Outlier ko-kr evidence materially changed from the previously reviewed Korean freelance text role to a Korean Voice AI Evaluator role. B64 retained immutable v1, created v2, routed v2 through material-change review, then approved v2 as current rather than silently overwriting v1.',
});

export const OUTLIER_VERIFIED20_RECORD_V2: Verified20Record = Object.freeze({
  slot: 2, realEvidence: true, syntheticFixture: false, sourcePolicy: OUTLIER_W8_POLICY, sourceGates: OUTLIER_PRE_CURATION_GATES,
  snapshot: OUTLIER_W8_SNAPSHOT_V2, opportunity: OUTLIER_W8_OPPORTUNITY_V2, version: OUTLIER_W8_VERSION_V2,
  certaintyType: 'CONDITIONAL', requirements: OUTLIER_W8_REQUIREMENTS_V2, compensationComponents: OUTLIER_W8_COMPENSATION_V2,
  windows: OUTLIER_W8_WINDOWS_V2, evidence: OUTLIER_W8_EVIDENCE_V2, reviewQueue: OUTLIER_W8_V2_REVIEW_QUEUE,
  reviewDecision: OUTLIER_W8_V2_REVIEW, criticalEvidenceIds: Object.freeze(['ev-w8-outlier-v2-role','ev-w8-outlier-v2-location','ev-w8-outlier-v2-rate','ev-w8-outlier-v2-task-live','ev-w8-outlier-v2-task-review','ev-w8-outlier-v2-onboarding']),
  lastCheckedAt: OUTLIER_W8_V2_OBSERVED_AT, supplyClaimMode: 'PUBLIC_CURRENT_INVENTORY',
});
