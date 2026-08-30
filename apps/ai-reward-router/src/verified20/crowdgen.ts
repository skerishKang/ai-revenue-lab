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
import type { SourceCollectionGate, SourcePolicyReview } from '../source-policy/domain.js';
import { sourceById } from '../source-policy/registry.js';
import type { Verified20Record } from './domain.js';
import { stableEvidenceHash } from './hash.js';

export const CROWDGEN_W8_OBSERVED_AT = '2026-08-30T08:29:00.000Z';

const homeUrl = 'https://crowdgen.com/';
const termsUrl = 'https://crowdgen.com/terms-of-service/';
const standardsUrl = 'https://crowdgen.com/docs/general-onboarding/getting-started/crowdgen-contributor-standards-what-crowdgen-expects-from-you/';
const moogerahUrl = 'https://crowdgen.com/moogerah-en-kr/';
const plumeriaUrl = 'https://crowdgen.com/plumeria-korean-remote/';

export const CROWDGEN_W8_POLICY: SourcePolicyReview = Object.freeze({
  sourceId: 'SRC-CROWDGEN',
  robotsStatus: 'WAIVED_MANUAL_ZERO_PRODUCT_TRANSPORT',
  termsStatus: 'REVIEWED_PUBLIC_TERMS_PROJECTS_AND_STANDARDS_2026-08-30',
  commercialReuse: 'LIMITED',
  textReuse: 'LIMITED',
  imageLogoReuse: 'BLOCKED',
  automationPermission: 'BLOCKED',
  affiliateIncentive: 'UNKNOWN',
  policyEvidenceUrl: termsUrl,
  reviewedAt: CROWDGEN_W8_OBSERVED_AT,
  reviewer: 'CENTRAL',
  decision: 'PASS_WITH_LIMITS',
  notes: 'Manual/deep-link factual curation only. Store B64-authored factual paraphrases plus canonical CrowdGen links. Do not reproduce protected platform/project content beyond minimal evidence, do not use logos, do not access contributor accounts, and do not automate project discovery or private task access.',
});

function gate(index: number, name: string, status: SourceCollectionGate['status'], evidence: string, notes: string): SourceCollectionGate {
  return Object.freeze({
    gateId: `SRC-CROWDGEN-G${index}`,
    sourceId: 'SRC-CROWDGEN',
    gate: name,
    required: true,
    status,
    failureAction: index <= 4 ? 'BLOCK' : 'SHADOW',
    evidence,
    notes,
  });
}

export const CROWDGEN_FINAL_GATES: readonly SourceCollectionGate[] = Object.freeze([
  gate(1, 'Source identity verified', 'PASS', homeUrl, 'Official CrowdGen by Appen public site identifies the contributor platform.'),
  gate(2, 'Official endpoint identified', 'PASS', `${moogerahUrl} | ${plumeriaUrl}`, 'Two distinct public Korean project pages are recorded; no private dashboard endpoint is used.'),
  gate(3, 'robots reviewed', 'WAIVED', 'MANUAL_ZERO_PRODUCT_TRANSPORT', 'No B64 automated collector is authorized or used for these records.'),
  gate(4, 'terms/commercial reuse reviewed', 'PASS', termsUrl, 'Internal factual paraphrase and canonical-link curation only; no blanket content-license or automation grant is asserted.'),
  gate(5, 'collector stability test', 'WAIVED', 'NO_AUTOMATED_COLLECTOR', 'Not applicable to manual/deep-link curation.'),
  gate(6, 'evidence extraction works', 'PASS', 'W8_CROWDGEN_FIELD_LEVEL_EVIDENCE', 'Both real records bind critical normalized fields to official public CrowdGen project evidence.'),
  gate(7, 'change detection works', 'WAIVED', 'FIRST_BASELINE_W6_AVAILABLE', 'These are first real baselines; later material changes must use W6 immutable versioning.'),
  gate(8, 'human review accepted sample', 'PASS', 'review-w8-crowdgen-moogerah-v1 | review-w8-crowdgen-plumeria-v1', 'CENTRAL independently reviewed both distinct project representations.'),
]);

function sourceSnapshot(id: string, canonicalUrl: string, rawPayload: unknown): SourceSnapshot {
  return Object.freeze({
    id,
    sourceId: 'SRC-CROWDGEN',
    endpointId: null,
    acquiredAt: CROWDGEN_W8_OBSERVED_AT,
    acquisitionModeUsed: sourceById('SRC-CROWDGEN').acquisitionMode,
    canonicalUrl,
    contentType: 'application/json',
    rawLocation: null,
    rawPayload,
    contentHash: stableEvidenceHash(rawPayload),
    fetchMetadata: Object.freeze({
      acquisition: 'CENTRAL_MANUAL_CURATED_OFFICIAL_SOURCE',
      productTransportCallCount: 0,
      centralResearchNetworkUsed: true,
      privateAccountAccess: false,
      loggedInProjectInventoryObserved: false,
    }),
    actorProvenance: Object.freeze({ actorId: 'CENTRAL', mode: 'MANUAL_CURATED_OFFICIAL_SOURCE' }),
    httpStatus: null,
  });
}

function evidence(
  id: string,
  versionId: string,
  snapshotId: string,
  fieldPath: string,
  evidenceText: string,
  url: string,
  confidence = 1,
): OpportunityEvidence {
  const locator = Object.freeze({ url, observationMode: 'OFFICIAL_PUBLIC_PAGE' });
  return Object.freeze({
    id,
    offerVersionId: versionId,
    sourceSnapshotId: snapshotId,
    fieldPath,
    evidenceText,
    evidenceLocator: locator,
    evidenceHash: stableEvidenceHash({ fieldPath, evidenceText, locator }),
    confidence,
    createdAt: CROWDGEN_W8_OBSERVED_AT,
  });
}

// Slot 3 — Project Moogerah
const MOOGERAH_RAW = Object.freeze({
  provider: 'CrowdGen by Appen',
  project: 'Project Moogerah',
  task: 'record 500 scripted Korean and English commands',
  qualityCondition: 'at least 450 of 500 recordings pass quality review',
  compensationUsd: 85,
  compensationBasis: 'one-time payment after completion under project conditions',
  language: 'native Korean',
  residence: 'South Korea',
  minimumAge: 18,
  mobileAppRequired: true,
  acceptanceProbability: null,
  futureProjectSupply: null,
  references: Object.freeze([moogerahUrl, termsUrl, standardsUrl]),
});

export const CROWDGEN_MOOGERAH_SNAPSHOT = sourceSnapshot('snapshot-w8-crowdgen-moogerah-20260830', moogerahUrl, MOOGERAH_RAW);

export const CROWDGEN_MOOGERAH_OPPORTUNITY: EarningOpportunity = Object.freeze({
  id: 'opp-w8-crowdgen-moogerah',
  sourceId: 'SRC-CROWDGEN',
  merchantId: null,
  canonicalKey: 'SRC-CROWDGEN:project-moogerah:en-kr',
  providerExternalKey: 'moogerah-en-kr',
  lifecycleState: 'VERIFIED',
  currentVersionId: 'opp-w8-crowdgen-moogerah-v1',
  firstSeenAt: CROWDGEN_W8_OBSERVED_AT,
  lastSeenAt: CROWDGEN_W8_OBSERVED_AT,
});

export const CROWDGEN_MOOGERAH_VERSION: OpportunityVersion = Object.freeze({
  id: 'opp-w8-crowdgen-moogerah-v1',
  offerId: CROWDGEN_MOOGERAH_OPPORTUNITY.id,
  versionNumber: 1,
  sourceSnapshotId: CROWDGEN_MOOGERAH_SNAPSHOT.id,
  title: 'Project Moogerah — Korean speech recording',
  shortSummary: 'CrowdGen publicly lists a South Korea Korean-language speech-recording project with USD 85 one-time compensation subject to completion and recording-quality conditions. Acceptance probability and future project supply are not asserted.',
  originalLanguage: 'en',
  verificationState: 'VERIFIED',
  sourceSnapshotHash: CROWDGEN_MOOGERAH_SNAPSHOT.contentHash,
  modelId: null,
  promptVersion: null,
  inputHash: null,
  opportunityCategory: 'DATA_ANNOTATION',
  incomeLadderLevel: 'TASK_WORK',
  compensationType: 'FIXED',
  advertisedCompensationValue: 85,
  expectedPayoutValue: null,
  compensationCurrency: 'USD',
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
  supplyAvailabilityState: 'PUBLIC_PROJECT_PAGE_AVAILABLE',
  supplyObservedAt: CROWDGEN_W8_OBSERVED_AT,
  applicationRequired: true,
  qualificationRequired: true,
  qualificationProbability: null,
  acceptanceProbability: null,
  rejectionOrReversalRisk: null,
  payoutReliability: null,
  eligibleCountriesOrRegions: Object.freeze(['KOREA']),
  languageRequirements: Object.freeze(['NATIVE_KOREAN']),
  skillRequirements: null,
  deviceOsRequirements: null,
  identityKycRequirements: null,
  ageRequirements: Object.freeze({ minimumAge: 18 }),
  taxContractorRequirements: null,
  schedulingRequirements: null,
  canonicalDestinationUrl: moogerahUrl,
  createdAt: CROWDGEN_W8_OBSERVED_AT,
});

export const CROWDGEN_MOOGERAH_EVIDENCE: readonly OpportunityEvidence[] = Object.freeze([
  evidence('ev-w8-cg-moogerah-task', CROWDGEN_MOOGERAH_VERSION.id, CROWDGEN_MOOGERAH_SNAPSHOT.id, 'title', 'Public project page describes a Korean speech-recording AI-data task.', moogerahUrl),
  evidence('ev-w8-cg-moogerah-pay', CROWDGEN_MOOGERAH_VERSION.id, CROWDGEN_MOOGERAH_SNAPSHOT.id, 'advertisedCompensationValue', 'Project advertises a one-time USD 85 payment under completion conditions.', moogerahUrl),
  evidence('ev-w8-cg-moogerah-quality', CROWDGEN_MOOGERAH_VERSION.id, CROWDGEN_MOOGERAH_SNAPSHOT.id, 'qualificationRequired', 'At least 450 of 500 submitted recordings must pass quality review.', moogerahUrl),
  evidence('ev-w8-cg-moogerah-language', CROWDGEN_MOOGERAH_VERSION.id, CROWDGEN_MOOGERAH_SNAPSHOT.id, 'languageRequirements', 'Project requires native Korean language ability.', moogerahUrl),
  evidence('ev-w8-cg-moogerah-country', CROWDGEN_MOOGERAH_VERSION.id, CROWDGEN_MOOGERAH_SNAPSHOT.id, 'eligibleCountriesOrRegions', 'Project requires current residence in South Korea.', moogerahUrl),
  evidence('ev-w8-cg-moogerah-age', CROWDGEN_MOOGERAH_VERSION.id, CROWDGEN_MOOGERAH_SNAPSHOT.id, 'ageRequirements', 'Public requirements specify a minimum age of 18.', moogerahUrl),
  evidence('ev-w8-cg-moogerah-app', CROWDGEN_MOOGERAH_VERSION.id, CROWDGEN_MOOGERAH_SNAPSHOT.id, 'deviceOsRequirements', 'Project requires use of the Appen Mobile app.', moogerahUrl),
]);
const me = (id: string) => CROWDGEN_MOOGERAH_EVIDENCE.find((item) => item.id === id)?.id ?? null;

export const CROWDGEN_MOOGERAH_REQUIREMENTS: readonly OpportunityRequirement[] = Object.freeze([
  Object.freeze({ id: 'req-w8-cg-moogerah-language', offerVersionId: CROWDGEN_MOOGERAH_VERSION.id, requirementType: 'LANGUAGE', operator: 'REQUIRED', normalizedValue: Object.freeze(['NATIVE_KOREAN']), displayText: 'Native Korean language ability is required.', required: true, confidence: 1, evidenceId: me('ev-w8-cg-moogerah-language') }),
  Object.freeze({ id: 'req-w8-cg-moogerah-country', offerVersionId: CROWDGEN_MOOGERAH_VERSION.id, requirementType: 'COUNTRY_REGION', operator: 'IN', normalizedValue: Object.freeze(['KOREA']), displayText: 'Current residence in South Korea is required.', required: true, confidence: 1, evidenceId: me('ev-w8-cg-moogerah-country') }),
  Object.freeze({ id: 'req-w8-cg-moogerah-age', offerVersionId: CROWDGEN_MOOGERAH_VERSION.id, requirementType: 'AGE', operator: 'GTE', normalizedValue: 18, displayText: 'Minimum age is 18.', required: true, confidence: 1, evidenceId: me('ev-w8-cg-moogerah-age') }),
  Object.freeze({ id: 'req-w8-cg-moogerah-app', offerVersionId: CROWDGEN_MOOGERAH_VERSION.id, requirementType: 'OTHER', operator: 'REQUIRED', normalizedValue: Object.freeze({ appenMobileApp: true }), displayText: 'Appen Mobile app is required for the recording task.', required: true, confidence: 1, evidenceId: me('ev-w8-cg-moogerah-app') }),
]);

export const CROWDGEN_MOOGERAH_COMPENSATION: readonly OpportunityCompensationComponent[] = Object.freeze([
  Object.freeze({ id: 'comp-w8-cg-moogerah-fixed', offerVersionId: CROWDGEN_MOOGERAH_VERSION.id, componentType: 'FIXED_PAY', amount: 85, currency: 'USD', rateUnit: null, percent: null, capAmount: null, conditionText: 'One-time project payment subject to completion and stated recording-quality conditions.', evidenceId: me('ev-w8-cg-moogerah-pay') }),
]);

export const CROWDGEN_MOOGERAH_WINDOWS: readonly OpportunityWindow[] = Object.freeze([
  Object.freeze({ id: 'window-w8-cg-moogerah-application', offerVersionId: CROWDGEN_MOOGERAH_VERSION.id, windowType: 'APPLICATION', startAt: null, endAt: null, relativeRule: 'OPEN_WHILE_OFFICIAL_PROJECT_PAGE_ACCEPTS_APPLICATIONS', displayText: 'Public project page remains available; no explicit closing date is asserted.', evidenceId: me('ev-w8-cg-moogerah-task') }),
]);

export const CROWDGEN_MOOGERAH_REVIEW_QUEUE: ReviewQueueItem = Object.freeze({ id: 'rq-w8-cg-moogerah-v1', offerVersionId: CROWDGEN_MOOGERAH_VERSION.id, reasonCodes: Object.freeze(['REAL_PUBLIC_PROJECT', 'QUALITY_CONDITIONAL_FIXED_PAY']), priority: 'HIGH', state: 'RESOLVED', assignedTo: 'CENTRAL', createdAt: CROWDGEN_W8_OBSERVED_AT, resolvedAt: CROWDGEN_W8_OBSERVED_AT });
export const CROWDGEN_MOOGERAH_REVIEW: ReviewDecisionRecord = Object.freeze({ id: 'review-w8-crowdgen-moogerah-v1', reviewQueueId: CROWDGEN_MOOGERAH_REVIEW_QUEUE.id, offerVersionId: CROWDGEN_MOOGERAH_VERSION.id, decision: 'APPROVE', reviewerId: 'CENTRAL', approvalReason: 'Official CrowdGen project evidence supports the exact Korean recording task, USD 85 advertised payment, quality condition, Korea residence, native Korean and age requirements. Acceptance probability and future project supply remain NULL/UNKNOWN.', rejectionReason: null, patch: null, createdAt: CROWDGEN_W8_OBSERVED_AT });

export const CROWDGEN_MOOGERAH_RECORD: Verified20Record = Object.freeze({
  slot: 3, realEvidence: true, syntheticFixture: false, sourcePolicy: CROWDGEN_W8_POLICY, sourceGates: CROWDGEN_FINAL_GATES,
  snapshot: CROWDGEN_MOOGERAH_SNAPSHOT, opportunity: CROWDGEN_MOOGERAH_OPPORTUNITY, version: CROWDGEN_MOOGERAH_VERSION,
  certaintyType: 'CONDITIONAL', requirements: CROWDGEN_MOOGERAH_REQUIREMENTS, compensationComponents: CROWDGEN_MOOGERAH_COMPENSATION,
  windows: CROWDGEN_MOOGERAH_WINDOWS, evidence: CROWDGEN_MOOGERAH_EVIDENCE, reviewQueue: CROWDGEN_MOOGERAH_REVIEW_QUEUE,
  reviewDecision: CROWDGEN_MOOGERAH_REVIEW, criticalEvidenceIds: Object.freeze(['ev-w8-cg-moogerah-task','ev-w8-cg-moogerah-pay','ev-w8-cg-moogerah-quality','ev-w8-cg-moogerah-language','ev-w8-cg-moogerah-country','ev-w8-cg-moogerah-age']),
  lastCheckedAt: CROWDGEN_W8_OBSERVED_AT, supplyClaimMode: 'PUBLIC_CURRENT_INVENTORY',
});

// Slot 4 — Project Plumeria
const PLUMERIA_RAW = Object.freeze({
  provider: 'CrowdGen by Appen',
  project: 'Project Plumeria',
  role: 'Korean Language Comprehension Content Analyst',
  compensationUsdPerHour: 12,
  language: 'native Korean',
  location: 'Republic of Korea',
  taskExamples: Object.freeze(['review article relevance', 'create Korean questions and concise answers']),
  qualification: Object.freeze(['native Korean', 'attention to detail', 'strong analytical skills']),
  publicPaymentMethods: Object.freeze(['local bank transfer', 'PayPal']),
  acceptanceProbability: null,
  guaranteedHours: null,
  futureTaskSupply: null,
  references: Object.freeze([plumeriaUrl, termsUrl, standardsUrl]),
});

export const CROWDGEN_PLUMERIA_SNAPSHOT = sourceSnapshot('snapshot-w8-crowdgen-plumeria-20260830', plumeriaUrl, PLUMERIA_RAW);

export const CROWDGEN_PLUMERIA_OPPORTUNITY: EarningOpportunity = Object.freeze({
  id: 'opp-w8-crowdgen-plumeria', sourceId: 'SRC-CROWDGEN', merchantId: null,
  canonicalKey: 'SRC-CROWDGEN:project-plumeria:korean-remote', providerExternalKey: 'plumeria-korean-remote',
  lifecycleState: 'VERIFIED', currentVersionId: 'opp-w8-crowdgen-plumeria-v1', firstSeenAt: CROWDGEN_W8_OBSERVED_AT, lastSeenAt: CROWDGEN_W8_OBSERVED_AT,
});

export const CROWDGEN_PLUMERIA_VERSION: OpportunityVersion = Object.freeze({
  id: 'opp-w8-crowdgen-plumeria-v1', offerId: CROWDGEN_PLUMERIA_OPPORTUNITY.id, versionNumber: 1,
  sourceSnapshotId: CROWDGEN_PLUMERIA_SNAPSHOT.id, title: 'Project Plumeria — Korean Language Comprehension Content Analyst',
  shortSummary: 'CrowdGen publicly lists a remote Korea Korean-language AI content-analysis project advertising USD 12/hour after qualification. Acceptance probability, guaranteed hours and future task supply are not asserted.',
  originalLanguage: 'en', verificationState: 'VERIFIED', sourceSnapshotHash: CROWDGEN_PLUMERIA_SNAPSHOT.contentHash,
  modelId: null, promptVersion: null, inputHash: null, opportunityCategory: 'AI_EVALUATION', incomeLadderLevel: 'TASK_WORK', compensationType: 'HOURLY',
  advertisedCompensationValue: 12, expectedPayoutValue: null, compensationCurrency: 'USD', estimatedActiveMinutes: null, estimatedTotalEffortMinutes: null,
  applicationMinutes: null, qualificationScreeningMinutes: null, preparationMinutes: null, startLatencyMinutes: null,
  payoutMethod: Object.freeze({ methodsByLocation: Object.freeze(['LOCAL_BANK_TRANSFER', 'PAYPAL']) }), payoutDelay: null, providerFees: null, repeatability: null,
  supplyAvailabilityState: 'PUBLIC_PROJECT_PAGE_AVAILABLE', supplyObservedAt: CROWDGEN_W8_OBSERVED_AT, applicationRequired: true, qualificationRequired: true,
  qualificationProbability: null, acceptanceProbability: null, rejectionOrReversalRisk: null, payoutReliability: null,
  eligibleCountriesOrRegions: Object.freeze(['KOREA']), languageRequirements: Object.freeze(['NATIVE_KOREAN']), skillRequirements: Object.freeze(['ATTENTION_TO_DETAIL','ANALYTICAL_SKILLS']),
  deviceOsRequirements: null, identityKycRequirements: null, ageRequirements: null, taxContractorRequirements: null,
  schedulingRequirements: Object.freeze({ flexibleRemoteSchedule: true, guaranteedHours: null }), canonicalDestinationUrl: plumeriaUrl, createdAt: CROWDGEN_W8_OBSERVED_AT,
});

export const CROWDGEN_PLUMERIA_EVIDENCE: readonly OpportunityEvidence[] = Object.freeze([
  evidence('ev-w8-cg-plumeria-role', CROWDGEN_PLUMERIA_VERSION.id, CROWDGEN_PLUMERIA_SNAPSHOT.id, 'title', 'Official project page lists a Korean-language AI content-analysis role.', plumeriaUrl),
  evidence('ev-w8-cg-plumeria-pay', CROWDGEN_PLUMERIA_VERSION.id, CROWDGEN_PLUMERIA_SNAPSHOT.id, 'advertisedCompensationValue', 'Project advertises USD 12 per hour after qualification.', plumeriaUrl),
  evidence('ev-w8-cg-plumeria-language', CROWDGEN_PLUMERIA_VERSION.id, CROWDGEN_PLUMERIA_SNAPSHOT.id, 'languageRequirements', 'Native Korean fluency is listed as a requirement.', plumeriaUrl),
  evidence('ev-w8-cg-plumeria-country', CROWDGEN_PLUMERIA_VERSION.id, CROWDGEN_PLUMERIA_SNAPSHOT.id, 'eligibleCountriesOrRegions', 'Project requires location in the Republic of Korea.', plumeriaUrl),
  evidence('ev-w8-cg-plumeria-skills', CROWDGEN_PLUMERIA_VERSION.id, CROWDGEN_PLUMERIA_SNAPSHOT.id, 'skillRequirements', 'Attention to detail and strong analytical skills are required.', plumeriaUrl),
  evidence('ev-w8-cg-plumeria-tasking', CROWDGEN_PLUMERIA_VERSION.id, CROWDGEN_PLUMERIA_SNAPSHOT.id, 'opportunityCategory', 'Tasks involve reviewing content relevance and creating Korean questions and answers for AI improvement.', plumeriaUrl),
  evidence('ev-w8-cg-plumeria-payment', CROWDGEN_PLUMERIA_VERSION.id, CROWDGEN_PLUMERIA_SNAPSHOT.id, 'payoutMethod', 'Public project page identifies local bank transfer or PayPal depending on location.', plumeriaUrl),
]);
const pe = (id: string) => CROWDGEN_PLUMERIA_EVIDENCE.find((item) => item.id === id)?.id ?? null;

export const CROWDGEN_PLUMERIA_REQUIREMENTS: readonly OpportunityRequirement[] = Object.freeze([
  Object.freeze({ id: 'req-w8-cg-plumeria-language', offerVersionId: CROWDGEN_PLUMERIA_VERSION.id, requirementType: 'LANGUAGE', operator: 'REQUIRED', normalizedValue: Object.freeze(['NATIVE_KOREAN']), displayText: 'Native Korean fluency is required.', required: true, confidence: 1, evidenceId: pe('ev-w8-cg-plumeria-language') }),
  Object.freeze({ id: 'req-w8-cg-plumeria-country', offerVersionId: CROWDGEN_PLUMERIA_VERSION.id, requirementType: 'COUNTRY_REGION', operator: 'IN', normalizedValue: Object.freeze(['KOREA']), displayText: 'Applicant must be located in the Republic of Korea.', required: true, confidence: 1, evidenceId: pe('ev-w8-cg-plumeria-country') }),
  Object.freeze({ id: 'req-w8-cg-plumeria-skills', offerVersionId: CROWDGEN_PLUMERIA_VERSION.id, requirementType: 'SKILL', operator: 'REQUIRED', normalizedValue: Object.freeze(['ATTENTION_TO_DETAIL','ANALYTICAL_SKILLS']), displayText: 'Attention to detail and strong analytical skills are required.', required: true, confidence: 1, evidenceId: pe('ev-w8-cg-plumeria-skills') }),
  Object.freeze({ id: 'req-w8-cg-plumeria-qualification', offerVersionId: CROWDGEN_PLUMERIA_VERSION.id, requirementType: 'QUALIFICATION', operator: 'REQUIRED', normalizedValue: Object.freeze({ projectQualification: true }), displayText: 'The page states earning begins after project qualification.', required: true, confidence: 1, evidenceId: pe('ev-w8-cg-plumeria-pay') }),
]);

export const CROWDGEN_PLUMERIA_COMPENSATION: readonly OpportunityCompensationComponent[] = Object.freeze([
  Object.freeze({ id: 'comp-w8-cg-plumeria-hourly', offerVersionId: CROWDGEN_PLUMERIA_VERSION.id, componentType: 'HOURLY_RATE', amount: 12, currency: 'USD', rateUnit: 'HOUR', percent: null, capAmount: null, conditionText: 'USD 12/hour after qualification; no guaranteed hours or acceptance probability are asserted.', evidenceId: pe('ev-w8-cg-plumeria-pay') }),
]);

export const CROWDGEN_PLUMERIA_WINDOWS: readonly OpportunityWindow[] = Object.freeze([
  Object.freeze({ id: 'window-w8-cg-plumeria-application', offerVersionId: CROWDGEN_PLUMERIA_VERSION.id, windowType: 'APPLICATION', startAt: null, endAt: null, relativeRule: 'OPEN_WHILE_OFFICIAL_PROJECT_PAGE_ACCEPTS_APPLICATIONS', displayText: 'Official project page exposes an application action; no explicit closing date is asserted.', evidenceId: pe('ev-w8-cg-plumeria-role') }),
]);

export const CROWDGEN_PLUMERIA_REVIEW_QUEUE: ReviewQueueItem = Object.freeze({ id: 'rq-w8-cg-plumeria-v1', offerVersionId: CROWDGEN_PLUMERIA_VERSION.id, reasonCodes: Object.freeze(['REAL_PUBLIC_PROJECT','QUALIFICATION_REQUIRED','HOURLY_PAY']), priority: 'HIGH', state: 'RESOLVED', assignedTo: 'CENTRAL', createdAt: CROWDGEN_W8_OBSERVED_AT, resolvedAt: CROWDGEN_W8_OBSERVED_AT });
export const CROWDGEN_PLUMERIA_REVIEW: ReviewDecisionRecord = Object.freeze({ id: 'review-w8-crowdgen-plumeria-v1', reviewQueueId: CROWDGEN_PLUMERIA_REVIEW_QUEUE.id, offerVersionId: CROWDGEN_PLUMERIA_VERSION.id, decision: 'APPROVE', reviewerId: 'CENTRAL', approvalReason: 'Official CrowdGen project evidence supports the exact Korean remote content-analysis project, USD 12/hour advertised rate, Korea/native-Korean requirements, qualification condition, core tasks and public payout methods. Acceptance probability, guaranteed hours and future task supply remain NULL/UNKNOWN.', rejectionReason: null, patch: null, createdAt: CROWDGEN_W8_OBSERVED_AT });

export const CROWDGEN_PLUMERIA_RECORD: Verified20Record = Object.freeze({
  slot: 4, realEvidence: true, syntheticFixture: false, sourcePolicy: CROWDGEN_W8_POLICY, sourceGates: CROWDGEN_FINAL_GATES,
  snapshot: CROWDGEN_PLUMERIA_SNAPSHOT, opportunity: CROWDGEN_PLUMERIA_OPPORTUNITY, version: CROWDGEN_PLUMERIA_VERSION,
  certaintyType: 'CONDITIONAL', requirements: CROWDGEN_PLUMERIA_REQUIREMENTS, compensationComponents: CROWDGEN_PLUMERIA_COMPENSATION,
  windows: CROWDGEN_PLUMERIA_WINDOWS, evidence: CROWDGEN_PLUMERIA_EVIDENCE, reviewQueue: CROWDGEN_PLUMERIA_REVIEW_QUEUE,
  reviewDecision: CROWDGEN_PLUMERIA_REVIEW, criticalEvidenceIds: Object.freeze(['ev-w8-cg-plumeria-role','ev-w8-cg-plumeria-pay','ev-w8-cg-plumeria-language','ev-w8-cg-plumeria-country','ev-w8-cg-plumeria-skills','ev-w8-cg-plumeria-tasking']),
  lastCheckedAt: CROWDGEN_W8_OBSERVED_AT, supplyClaimMode: 'PUBLIC_CURRENT_INVENTORY',
});
