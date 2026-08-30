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
import type { SourceCollectionGate } from '../source-policy/domain.js';
import { sourceById } from '../source-policy/registry.js';
import type { Verified20Record } from './domain.js';
import { CROWDGEN_FINAL_GATES, CROWDGEN_W8_POLICY } from './crowdgen.js';
import { stableEvidenceHash } from './hash.js';

export const CROWDGEN_MORAVA_OBSERVED_AT = '2026-08-30T08:21:00.000Z';
const roleUrl = 'https://jobs.lever.co/appen/b5a3495f-c569-4b54-a5b7-e18e67024e1a';

export const CROWDGEN_MORAVA_FINAL_GATES: readonly SourceCollectionGate[] = Object.freeze(
  CROWDGEN_FINAL_GATES.map((item, index) => {
    if (index === 1) return Object.freeze({ ...item, evidence: roleUrl, notes: 'Exact public CrowdGen/Lever Project Morava Korean role page is recorded; no private contributor dashboard is used.' });
    if (index === 5) return Object.freeze({ ...item, evidence: 'W8_CROWDGEN_MORAVA_FIELD_LEVEL_EVIDENCE', notes: 'Final record binds role, Korea residence, Korean language, age, device, task volume, effort and conditional payment to the public role page.' });
    if (index === 7) return Object.freeze({ ...item, evidence: 'review-w8-crowdgen-morava-v1', notes: 'CENTRAL independently reviewed Project Morava before VERIFIED status.' });
    return item;
  }),
);

const rawPayload = Object.freeze({
  provider: 'CrowdGen by Appen',
  project: 'Project Morava',
  publicRole: '[Korean] - Voice Recording Specialist',
  location: 'Korea, Republic of',
  relationship: 'Independent Contractor - Project Based',
  remote: true,
  task: 'read and record 150 short scripted Korean voice prompts using the Appen Mobile app',
  estimatedTaskHours: 2,
  compensationUsdOneTime: 20,
  paymentCondition: 'full session of 150 prompts; proportional payment if assigned fewer prompts',
  assignmentConstraint: 'first-come first-served with demographic quotas; some applicants may receive no task assignment',
  requirements: Object.freeze(['native Korean speaker', 'currently residing in Korea', 'age 18 or above', 'compatible smartphone with Appen Mobile app']),
  acceptanceProbability: null,
  guaranteedAssignment: false,
  futureProjectSupply: null,
  reference: roleUrl,
});
const snapshotHash = stableEvidenceHash(rawPayload);

export const CROWDGEN_MORAVA_SNAPSHOT: SourceSnapshot = Object.freeze({
  id: 'snapshot-w8-crowdgen-morava-20260830',
  sourceId: 'SRC-CROWDGEN',
  endpointId: null,
  acquiredAt: CROWDGEN_MORAVA_OBSERVED_AT,
  acquisitionModeUsed: sourceById('SRC-CROWDGEN').acquisitionMode,
  canonicalUrl: roleUrl,
  contentType: 'application/json',
  rawLocation: null,
  rawPayload,
  contentHash: snapshotHash,
  fetchMetadata: Object.freeze({ acquisition: 'CENTRAL_MANUAL_CURATED_OFFICIAL_SOURCE', productTransportCallCount: 0, centralResearchNetworkUsed: true, privateAccountAccess: false, loggedInProjectInventoryObserved: false }),
  actorProvenance: Object.freeze({ actorId: 'CENTRAL', mode: 'MANUAL_CURATED_OFFICIAL_SOURCE' }),
  httpStatus: null,
});

export const CROWDGEN_MORAVA_OPPORTUNITY: EarningOpportunity = Object.freeze({
  id: 'opp-w8-crowdgen-morava-korean-voice-recording',
  sourceId: 'SRC-CROWDGEN',
  merchantId: null,
  canonicalKey: 'SRC-CROWDGEN:project-morava:korean-voice-recording',
  providerExternalKey: 'b5a3495f-c569-4b54-a5b7-e18e67024e1a',
  lifecycleState: 'VERIFIED',
  currentVersionId: 'opp-w8-crowdgen-morava-korean-voice-recording-v1',
  firstSeenAt: CROWDGEN_MORAVA_OBSERVED_AT,
  lastSeenAt: CROWDGEN_MORAVA_OBSERVED_AT,
});

export const CROWDGEN_MORAVA_VERSION: OpportunityVersion = Object.freeze({
  id: 'opp-w8-crowdgen-morava-korean-voice-recording-v1',
  offerId: CROWDGEN_MORAVA_OPPORTUNITY.id,
  versionNumber: 1,
  sourceSnapshotId: CROWDGEN_MORAVA_SNAPSHOT.id,
  title: 'Project Morava — Korean Voice Recording Specialist',
  shortSummary: 'CrowdGen publicly lists a South Korea remote Project Morava voice-recording role: 150 scripted Korean prompts, approximately two hours, with USD 20 one-time advertised compensation for a full assigned session. Assignment is not guaranteed because demographic quotas and first-come allocation apply.',
  originalLanguage: 'en',
  verificationState: 'VERIFIED',
  sourceSnapshotHash: snapshotHash,
  modelId: null,
  promptVersion: null,
  inputHash: null,
  opportunityCategory: 'DATA_ANNOTATION',
  incomeLadderLevel: 'TASK_WORK',
  compensationType: 'FIXED',
  advertisedCompensationValue: 20,
  expectedPayoutValue: null,
  compensationCurrency: 'USD',
  estimatedActiveMinutes: 120,
  estimatedTotalEffortMinutes: 120,
  applicationMinutes: null,
  qualificationScreeningMinutes: null,
  preparationMinutes: null,
  startLatencyMinutes: null,
  payoutMethod: null,
  payoutDelay: null,
  providerFees: null,
  repeatability: null,
  supplyAvailabilityState: 'PUBLIC_ROLE_PAGE_AVAILABLE_QUOTA_LIMITED',
  supplyObservedAt: CROWDGEN_MORAVA_OBSERVED_AT,
  applicationRequired: true,
  qualificationRequired: true,
  qualificationProbability: null,
  acceptanceProbability: null,
  rejectionOrReversalRisk: Object.freeze({ assignmentRisk: 'DEMOGRAPHIC_QUOTA_AND_FIRST_COME' }),
  payoutReliability: null,
  eligibleCountriesOrRegions: Object.freeze(['KOREA']),
  languageRequirements: Object.freeze(['NATIVE_KOREAN']),
  skillRequirements: null,
  deviceOsRequirements: Object.freeze(['SMARTPHONE_COMPATIBLE_WITH_APPEN_MOBILE']),
  identityKycRequirements: null,
  ageRequirements: Object.freeze({ minimumAge: 18 }),
  taxContractorRequirements: Object.freeze({ relationship: 'INDEPENDENT_CONTRACTOR_PROJECT_BASED' }),
  schedulingRequirements: Object.freeze({ selfScheduled: true, estimatedTaskHours: 2, guaranteedAssignment: false }),
  canonicalDestinationUrl: roleUrl,
  createdAt: CROWDGEN_MORAVA_OBSERVED_AT,
});

function evidence(id: string, fieldPath: string, evidenceText: string): OpportunityEvidence {
  const locator = Object.freeze({ url: roleUrl, observationMode: 'OFFICIAL_PUBLIC_JOB_PAGE' });
  return Object.freeze({
    id,
    offerVersionId: CROWDGEN_MORAVA_VERSION.id,
    sourceSnapshotId: CROWDGEN_MORAVA_SNAPSHOT.id,
    fieldPath,
    evidenceText,
    evidenceLocator: locator,
    evidenceHash: stableEvidenceHash({ fieldPath, evidenceText, locator }),
    confidence: 1,
    createdAt: CROWDGEN_MORAVA_OBSERVED_AT,
  });
}

export const CROWDGEN_MORAVA_EVIDENCE: readonly OpportunityEvidence[] = Object.freeze([
  evidence('ev-w8-cg-morava-role', 'title', 'Official CrowdGen/Lever page identifies Project Morava as a Korean Voice Recording Specialist project-based remote role in Korea.'),
  evidence('ev-w8-cg-morava-task', 'opportunityCategory', 'Participants record 150 short scripted Korean voice prompts using the Appen Mobile app.'),
  evidence('ev-w8-cg-morava-effort', 'estimatedTotalEffortMinutes', 'The public role states the entire task takes approximately two hours including guideline review.'),
  evidence('ev-w8-cg-morava-pay', 'advertisedCompensationValue', 'The public role advertises USD 20 one-time; payment is for a full 150-prompt session and is adjusted proportionally if fewer prompts are assigned.'),
  evidence('ev-w8-cg-morava-country', 'eligibleCountriesOrRegions', 'Participants must currently reside in Korea and may participate from anywhere within Korea.'),
  evidence('ev-w8-cg-morava-language', 'languageRequirements', 'Participants must be native Korean speakers.'),
  evidence('ev-w8-cg-morava-age', 'ageRequirements', 'Participants must be 18 years old or above.'),
  evidence('ev-w8-cg-morava-device', 'deviceOsRequirements', 'A smartphone compatible with the Appen Mobile app is required.'),
  evidence('ev-w8-cg-morava-quota', 'rejectionOrReversalRisk', 'The project is first-come first-served with demographic quotas, so some applicants may not receive a task assignment.'),
]);
const ev = (id: string) => CROWDGEN_MORAVA_EVIDENCE.find((item) => item.id === id)?.id ?? null;

export const CROWDGEN_MORAVA_REQUIREMENTS: readonly OpportunityRequirement[] = Object.freeze([
  Object.freeze({ id: 'req-w8-cg-morava-language', offerVersionId: CROWDGEN_MORAVA_VERSION.id, requirementType: 'LANGUAGE', operator: 'REQUIRED', normalizedValue: Object.freeze(['NATIVE_KOREAN']), displayText: 'Native Korean is required.', required: true, confidence: 1, evidenceId: ev('ev-w8-cg-morava-language') }),
  Object.freeze({ id: 'req-w8-cg-morava-country', offerVersionId: CROWDGEN_MORAVA_VERSION.id, requirementType: 'COUNTRY_REGION', operator: 'IN', normalizedValue: Object.freeze(['KOREA']), displayText: 'Current residence in Korea is required.', required: true, confidence: 1, evidenceId: ev('ev-w8-cg-morava-country') }),
  Object.freeze({ id: 'req-w8-cg-morava-age', offerVersionId: CROWDGEN_MORAVA_VERSION.id, requirementType: 'AGE', operator: 'GTE', normalizedValue: 18, displayText: 'Minimum age is 18.', required: true, confidence: 1, evidenceId: ev('ev-w8-cg-morava-age') }),
  Object.freeze({ id: 'req-w8-cg-morava-device', offerVersionId: CROWDGEN_MORAVA_VERSION.id, requirementType: 'OTHER', operator: 'REQUIRED', normalizedValue: Object.freeze({ smartphone: true, appenMobile: true }), displayText: 'Compatible smartphone and Appen Mobile app are required.', required: true, confidence: 1, evidenceId: ev('ev-w8-cg-morava-device') }),
]);

export const CROWDGEN_MORAVA_COMPENSATION: readonly OpportunityCompensationComponent[] = Object.freeze([
  Object.freeze({ id: 'comp-w8-cg-morava-fixed', offerVersionId: CROWDGEN_MORAVA_VERSION.id, componentType: 'FIXED_PAY', amount: 20, currency: 'USD', rateUnit: null, percent: null, capAmount: null, conditionText: 'USD 20 for a full assigned session of 150 prompts; proportional adjustment applies when fewer prompts are assigned. Assignment itself is not guaranteed.', evidenceId: ev('ev-w8-cg-morava-pay') }),
]);

export const CROWDGEN_MORAVA_WINDOWS: readonly OpportunityWindow[] = Object.freeze([
  Object.freeze({ id: 'window-w8-cg-morava-application', offerVersionId: CROWDGEN_MORAVA_VERSION.id, windowType: 'APPLICATION', startAt: null, endAt: null, relativeRule: 'OPEN_WHILE_PUBLIC_ROLE_ACCEPTS_APPLICATIONS_AND_QUOTAS_REMAIN', displayText: 'Public role currently exposes an application action; no fixed closing date is asserted and assignment remains quota-limited.', evidenceId: ev('ev-w8-cg-morava-role') }),
]);

export const CROWDGEN_MORAVA_REVIEW_QUEUE: ReviewQueueItem = Object.freeze({
  id: 'rq-w8-cg-morava-v1',
  offerVersionId: CROWDGEN_MORAVA_VERSION.id,
  reasonCodes: Object.freeze(['REAL_PUBLIC_PROJECT', 'FIXED_PAY', 'DEMOGRAPHIC_QUOTA', 'ASSIGNMENT_NOT_GUARANTEED']),
  priority: 'HIGH',
  state: 'RESOLVED',
  assignedTo: 'CENTRAL',
  createdAt: CROWDGEN_MORAVA_OBSERVED_AT,
  resolvedAt: CROWDGEN_MORAVA_OBSERVED_AT,
});

export const CROWDGEN_MORAVA_REVIEW: ReviewDecisionRecord = Object.freeze({
  id: 'review-w8-crowdgen-morava-v1',
  reviewQueueId: CROWDGEN_MORAVA_REVIEW_QUEUE.id,
  offerVersionId: CROWDGEN_MORAVA_VERSION.id,
  decision: 'APPROVE',
  reviewerId: 'CENTRAL',
  approvalReason: 'Official public CrowdGen/Lever evidence supports the exact Project Morava Korean recording task, two-hour estimate, USD 20 one-time advertised compensation, Korea/native-Korean/age/device requirements and quota risk. Acceptance probability and guaranteed assignment remain NULL/false rather than inferred.',
  rejectionReason: null,
  patch: null,
  createdAt: CROWDGEN_MORAVA_OBSERVED_AT,
});

export const CROWDGEN_MORAVA_RECORD: Verified20Record = Object.freeze({
  slot: 14,
  realEvidence: true,
  syntheticFixture: false,
  sourcePolicy: CROWDGEN_W8_POLICY,
  sourceGates: CROWDGEN_MORAVA_FINAL_GATES,
  snapshot: CROWDGEN_MORAVA_SNAPSHOT,
  opportunity: CROWDGEN_MORAVA_OPPORTUNITY,
  version: CROWDGEN_MORAVA_VERSION,
  certaintyType: 'CONDITIONAL',
  requirements: CROWDGEN_MORAVA_REQUIREMENTS,
  compensationComponents: CROWDGEN_MORAVA_COMPENSATION,
  windows: CROWDGEN_MORAVA_WINDOWS,
  evidence: CROWDGEN_MORAVA_EVIDENCE,
  reviewQueue: CROWDGEN_MORAVA_REVIEW_QUEUE,
  reviewDecision: CROWDGEN_MORAVA_REVIEW,
  criticalEvidenceIds: Object.freeze(['ev-w8-cg-morava-role','ev-w8-cg-morava-task','ev-w8-cg-morava-effort','ev-w8-cg-morava-pay','ev-w8-cg-morava-country','ev-w8-cg-morava-language','ev-w8-cg-morava-age','ev-w8-cg-morava-device','ev-w8-cg-morava-quota']),
  lastCheckedAt: CROWDGEN_MORAVA_OBSERVED_AT,
  supplyClaimMode: 'PUBLIC_CURRENT_INVENTORY',
});
