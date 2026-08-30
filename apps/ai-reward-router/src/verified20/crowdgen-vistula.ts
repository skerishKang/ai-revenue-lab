import type {
  EarningOpportunity,
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
import { CROWDGEN_FINAL_GATES, CROWDGEN_W8_POLICY } from './crowdgen.js';
import type { Verified20Record } from './domain.js';
import { stableEvidenceHash } from './hash.js';

export const CROWDGEN_VISTULA_OBSERVED_AT = '2026-08-30T08:55:00.000Z';
const vistulaUrl = 'https://crowdgen.com/vistula-ko-us-a/';

const rawPayload = Object.freeze({
  provider: 'CrowdGen by Appen',
  project: 'Project Vistula',
  role: 'Machine Translation Evaluation — English to Korean',
  task: Object.freeze(['review English-to-Korean AI translations', 'check fluency grammar and meaning', 'flag mistranslations offensive language or poor tone adaptation']),
  compensationUsdPerHour: 18,
  languageRequirements: Object.freeze(['ENGLISH','KOREAN']),
  deviceRequirement: 'LAPTOP_OR_COMPUTER',
  remote: true,
  qualificationRequired: true,
  identityVerificationRequired: true,
  acceptanceProbability: null,
  guaranteedHours: null,
  futureTaskSupply: null,
  canonicalUrl: vistulaUrl,
});

const snapshotHash = stableEvidenceHash(rawPayload);

export const CROWDGEN_VISTULA_SNAPSHOT: SourceSnapshot = Object.freeze({
  id: 'snapshot-w8-crowdgen-vistula-20260830', sourceId: 'SRC-CROWDGEN', endpointId: null,
  acquiredAt: CROWDGEN_VISTULA_OBSERVED_AT, acquisitionModeUsed: sourceById('SRC-CROWDGEN').acquisitionMode,
  canonicalUrl: vistulaUrl, contentType: 'application/json', rawLocation: null, rawPayload, contentHash: snapshotHash,
  fetchMetadata: Object.freeze({ acquisition: 'CENTRAL_MANUAL_CURATED_OFFICIAL_SOURCE', productTransportCallCount: 0, centralResearchNetworkUsed: true, privateAccountAccess: false, loggedInProjectInventoryObserved: false }),
  actorProvenance: Object.freeze({ actorId: 'CENTRAL', mode: 'MANUAL_CURATED_OFFICIAL_SOURCE' }), httpStatus: null,
});

export const CROWDGEN_VISTULA_OPPORTUNITY: EarningOpportunity = Object.freeze({
  id: 'opp-w8-crowdgen-vistula', sourceId: 'SRC-CROWDGEN', merchantId: null,
  canonicalKey: 'SRC-CROWDGEN:project-vistula:english-to-korean', providerExternalKey: 'vistula-ko-us-a',
  lifecycleState: 'VERIFIED', currentVersionId: 'opp-w8-crowdgen-vistula-v1',
  firstSeenAt: CROWDGEN_VISTULA_OBSERVED_AT, lastSeenAt: CROWDGEN_VISTULA_OBSERVED_AT,
});

export const CROWDGEN_VISTULA_VERSION: OpportunityVersion = Object.freeze({
  id: 'opp-w8-crowdgen-vistula-v1', offerId: CROWDGEN_VISTULA_OPPORTUNITY.id, versionNumber: 1,
  sourceSnapshotId: CROWDGEN_VISTULA_SNAPSHOT.id, title: 'Project Vistula — English to Korean Machine Translation Evaluation',
  shortSummary: 'CrowdGen publicly lists an English-to-Korean AI translation evaluation project advertising USD 18/hour. Qualification and identity verification are required; acceptance probability, guaranteed hours and future task supply are not asserted.',
  originalLanguage: 'en', verificationState: 'VERIFIED', sourceSnapshotHash: snapshotHash,
  modelId: null, promptVersion: null, inputHash: null, opportunityCategory: 'TRANSLATION', incomeLadderLevel: 'SKILLED_DIGITAL_GIG', compensationType: 'HOURLY',
  advertisedCompensationValue: 18, expectedPayoutValue: null, compensationCurrency: 'USD',
  estimatedActiveMinutes: null, estimatedTotalEffortMinutes: null, applicationMinutes: null, qualificationScreeningMinutes: null, preparationMinutes: null, startLatencyMinutes: null,
  payoutMethod: null, payoutDelay: null, providerFees: null, repeatability: null,
  supplyAvailabilityState: 'PUBLIC_PROJECT_PAGE_AVAILABLE', supplyObservedAt: CROWDGEN_VISTULA_OBSERVED_AT,
  applicationRequired: true, qualificationRequired: true, qualificationProbability: null, acceptanceProbability: null,
  rejectionOrReversalRisk: null, payoutReliability: null, eligibleCountriesOrRegions: null,
  languageRequirements: Object.freeze(['ENGLISH','KOREAN']), skillRequirements: Object.freeze(['TRANSLATION_QUALITY_EVALUATION']),
  deviceOsRequirements: Object.freeze(['LAPTOP_OR_COMPUTER']), identityKycRequirements: Object.freeze(['IDENTITY_VERIFICATION']),
  ageRequirements: null, taxContractorRequirements: null, schedulingRequirements: Object.freeze({ flexibleSchedule: true, guaranteedHours: null }),
  canonicalDestinationUrl: vistulaUrl, createdAt: CROWDGEN_VISTULA_OBSERVED_AT,
});

function evidence(id: string, fieldPath: string, evidenceText: string): OpportunityEvidence {
  const locator = Object.freeze({ url: vistulaUrl, observationMode: 'OFFICIAL_PUBLIC_PAGE' });
  return Object.freeze({ id, offerVersionId: CROWDGEN_VISTULA_VERSION.id, sourceSnapshotId: CROWDGEN_VISTULA_SNAPSHOT.id, fieldPath, evidenceText, evidenceLocator: locator, evidenceHash: stableEvidenceHash({ fieldPath, evidenceText, locator }), confidence: 1, createdAt: CROWDGEN_VISTULA_OBSERVED_AT });
}

export const CROWDGEN_VISTULA_EVIDENCE: readonly OpportunityEvidence[] = Object.freeze([
  evidence('ev-w8-cg-vistula-project', 'title', 'Official CrowdGen page identifies Project Vistula as English-to-Korean machine translation evaluation.'),
  evidence('ev-w8-cg-vistula-pay', 'advertisedCompensationValue', 'Official public project page advertises USD 18 per hour.'),
  evidence('ev-w8-cg-vistula-language', 'languageRequirements', 'Public requirements call for bilingual English and Korean speakers.'),
  evidence('ev-w8-cg-vistula-task', 'opportunityCategory', 'Tasks review English-to-Korean AI translations for fluency, grammar, meaning and translation errors.'),
  evidence('ev-w8-cg-vistula-qualification', 'qualificationRequired', 'Public onboarding requires qualification tests and identity verification before work.'),
  evidence('ev-w8-cg-vistula-device', 'deviceOsRequirements', 'Laptop or computer and remote-work capability are required.'),
]);
const ev = (id: string) => CROWDGEN_VISTULA_EVIDENCE.find((item) => item.id === id)?.id ?? null;

export const CROWDGEN_VISTULA_REQUIREMENTS: readonly OpportunityRequirement[] = Object.freeze([
  Object.freeze({ id: 'req-w8-cg-vistula-language', offerVersionId: CROWDGEN_VISTULA_VERSION.id, requirementType: 'LANGUAGE', operator: 'REQUIRED', normalizedValue: Object.freeze(['ENGLISH','KOREAN']), displayText: 'Bilingual English and Korean ability is required.', required: true, confidence: 1, evidenceId: ev('ev-w8-cg-vistula-language') }),
  Object.freeze({ id: 'req-w8-cg-vistula-qualification', offerVersionId: CROWDGEN_VISTULA_VERSION.id, requirementType: 'QUALIFICATION', operator: 'REQUIRED', normalizedValue: Object.freeze({ qualificationTest: true }), displayText: 'Project qualification tests must be passed.', required: true, confidence: 1, evidenceId: ev('ev-w8-cg-vistula-qualification') }),
  Object.freeze({ id: 'req-w8-cg-vistula-identity', offerVersionId: CROWDGEN_VISTULA_VERSION.id, requirementType: 'IDENTITY_KYC', operator: 'REQUIRED', normalizedValue: Object.freeze({ identityVerification: true }), displayText: 'Identity verification is part of onboarding.', required: true, confidence: 1, evidenceId: ev('ev-w8-cg-vistula-qualification') }),
]);

export const CROWDGEN_VISTULA_COMPENSATION: readonly OpportunityCompensationComponent[] = Object.freeze([
  Object.freeze({ id: 'comp-w8-cg-vistula-hourly', offerVersionId: CROWDGEN_VISTULA_VERSION.id, componentType: 'HOURLY_RATE', amount: 18, currency: 'USD', rateUnit: 'HOUR', percent: null, capAmount: null, conditionText: 'Public project page advertises USD 18/hour; acceptance and guaranteed hours are not inferred.', evidenceId: ev('ev-w8-cg-vistula-pay') }),
]);

export const CROWDGEN_VISTULA_WINDOWS: readonly OpportunityWindow[] = Object.freeze([
  Object.freeze({ id: 'window-w8-cg-vistula-application', offerVersionId: CROWDGEN_VISTULA_VERSION.id, windowType: 'APPLICATION', startAt: null, endAt: null, relativeRule: 'OPEN_WHILE_OFFICIAL_PROJECT_PAGE_ACCEPTS_APPLICATIONS', displayText: 'Official project page exposes the project application path; no closing date is inferred.', evidenceId: ev('ev-w8-cg-vistula-project') }),
]);

export const CROWDGEN_VISTULA_REVIEW_QUEUE: ReviewQueueItem = Object.freeze({ id: 'rq-w8-cg-vistula-v1', offerVersionId: CROWDGEN_VISTULA_VERSION.id, reasonCodes: Object.freeze(['REAL_PUBLIC_PROJECT','HOURLY_PAY','QUALIFICATION_REQUIRED']), priority: 'HIGH', state: 'RESOLVED', assignedTo: 'CENTRAL', createdAt: CROWDGEN_VISTULA_OBSERVED_AT, resolvedAt: CROWDGEN_VISTULA_OBSERVED_AT });
export const CROWDGEN_VISTULA_REVIEW: ReviewDecisionRecord = Object.freeze({ id: 'review-w8-crowdgen-vistula-v1', reviewQueueId: CROWDGEN_VISTULA_REVIEW_QUEUE.id, offerVersionId: CROWDGEN_VISTULA_VERSION.id, decision: 'APPROVE', reviewerId: 'CENTRAL', approvalReason: 'Official CrowdGen public project evidence supports the distinct Vistula English-to-Korean translation evaluation task and USD 18/hour advertised rate. Qualification and identity verification are required; acceptance probability, guaranteed hours and future task supply remain NULL/UNKNOWN.', rejectionReason: null, patch: null, createdAt: CROWDGEN_VISTULA_OBSERVED_AT });

export const CROWDGEN_VISTULA_RECORD: Verified20Record = Object.freeze({
  slot: 13, realEvidence: true, syntheticFixture: false, sourcePolicy: CROWDGEN_W8_POLICY, sourceGates: CROWDGEN_FINAL_GATES,
  snapshot: CROWDGEN_VISTULA_SNAPSHOT, opportunity: CROWDGEN_VISTULA_OPPORTUNITY, version: CROWDGEN_VISTULA_VERSION,
  certaintyType: 'CONDITIONAL', requirements: CROWDGEN_VISTULA_REQUIREMENTS, compensationComponents: CROWDGEN_VISTULA_COMPENSATION,
  windows: CROWDGEN_VISTULA_WINDOWS, evidence: CROWDGEN_VISTULA_EVIDENCE, reviewQueue: CROWDGEN_VISTULA_REVIEW_QUEUE,
  reviewDecision: CROWDGEN_VISTULA_REVIEW, criticalEvidenceIds: Object.freeze(['ev-w8-cg-vistula-project','ev-w8-cg-vistula-pay','ev-w8-cg-vistula-language','ev-w8-cg-vistula-task','ev-w8-cg-vistula-qualification']),
  lastCheckedAt: CROWDGEN_VISTULA_OBSERVED_AT, supplyClaimMode: 'PUBLIC_CURRENT_INVENTORY',
});
