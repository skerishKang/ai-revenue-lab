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

export const OUTLIER_W8_OBSERVED_AT = '2026-08-30T08:21:00.000Z';

const roleUrl = 'https://outlier.ai/languages/ko-kr';
const faqUrl = 'https://outlier.ai/faq';
const termsUrl = 'https://outlier.ai/legal/terms-of-use';
const privacyUrl = 'https://outlier.ai/legal/privacy-policy';

export const OUTLIER_W8_POLICY: SourcePolicyReview = Object.freeze({
  sourceId: 'SRC-OUTLIER',
  robotsStatus: 'WAIVED_MANUAL_ZERO_PRODUCT_TRANSPORT',
  termsStatus: 'REVIEWED_PUBLIC_TERMS_ROLE_AND_FAQ_2026-08-30',
  commercialReuse: 'LIMITED',
  textReuse: 'LIMITED',
  imageLogoReuse: 'BLOCKED',
  automationPermission: 'BLOCKED',
  affiliateIncentive: 'UNKNOWN',
  policyEvidenceUrl: termsUrl,
  reviewedAt: OUTLIER_W8_OBSERVED_AT,
  reviewer: 'CENTRAL',
  decision: 'PASS_WITH_LIMITS',
  notes: 'Manual/deep-link factual curation only. Store B64-authored factual paraphrases and canonical links; do not reproduce Company Materials, logos, private task content, or confidential account/project information. No automated feed/crawl and no implication that a public role page guarantees acceptance, task supply, hours, or earnings.',
});

function gate(
  index: number,
  name: string,
  status: SourceCollectionGate['status'],
  evidence: string,
  notes: string,
): SourceCollectionGate {
  return Object.freeze({
    gateId: `SRC-OUTLIER-G${index}`,
    sourceId: 'SRC-OUTLIER',
    gate: name,
    required: true,
    status,
    failureAction: index <= 4 ? 'BLOCK' : 'SHADOW',
    evidence,
    notes,
  });
}

export const OUTLIER_PRE_CURATION_GATES: readonly SourceCollectionGate[] = Object.freeze([
  gate(1, 'Source identity verified', 'PASS', roleUrl, 'Official Outlier role page and legal terms identify Outlier/Scale AI contributor services.'),
  gate(2, 'Official endpoint identified', 'PASS', roleUrl, 'Exact public Korean role page, FAQ, terms and privacy references are recorded; no private endpoint is used.'),
  gate(3, 'robots reviewed', 'WAIVED', 'MANUAL_ZERO_PRODUCT_TRANSPORT', 'No B64 automated collector is authorized or used for this record.'),
  gate(4, 'terms/commercial reuse reviewed', 'PASS', termsUrl, 'Internal factual paraphrase and canonical-link curation only; no blanket content-license or automation grant is asserted.'),
  gate(5, 'collector stability test', 'WAIVED', 'NO_AUTOMATED_COLLECTOR', 'Not applicable to the manual/deep-link path.'),
  gate(6, 'evidence extraction works', 'WAIVED', 'BOOTSTRAP_PRECONDITION_ONLY', 'Waived only before seed construction; the final record carries field-level evidence.'),
  gate(7, 'change detection works', 'WAIVED', 'FIRST_BASELINE_W6_AVAILABLE', 'This is the first real Outlier baseline; later material changes must use W6 versioning.'),
  gate(8, 'human review accepted sample', 'WAIVED', 'BOOTSTRAP_PRECONDITION_ONLY', 'Waived only to permit record construction; final record carries a resolved CENTRAL review.'),
]);

export const OUTLIER_FINAL_GATES: readonly SourceCollectionGate[] = Object.freeze(
  OUTLIER_PRE_CURATION_GATES.map((item, index) => {
    if (index === 5) return Object.freeze({ ...item, status: 'PASS' as const, evidence: 'W8_OUTLIER_FIELD_LEVEL_EVIDENCE', notes: 'Final record binds compensation, location, language, onboarding and task claims to official public Outlier evidence.' });
    if (index === 7) return Object.freeze({ ...item, status: 'PASS' as const, evidence: 'review-w8-outlier-ko-v1', notes: 'CENTRAL approved the exact public Korean role representation with acceptance probability and future task supply kept UNKNOWN.' });
    return item;
  }),
);

const rawPayload = Object.freeze({
  provider: 'Outlier AI',
  publicRole: 'Korean Freelance Writer',
  language: 'Korean',
  location: 'South Korea (Remote)',
  advertisedRateCeilingUsdPerHour: 31,
  compensationQualifier: 'up to; varies by expertise and project requirements; lower non-core rates may apply',
  publicPaymentMethods: Object.freeze(['PayPal', 'Airtm']),
  onboarding: Object.freeze(['create account', 'verify identity and phone', 'pass skill assessment', 'complete tasks']),
  taskExamples: Object.freeze(['rank Korean AI responses', 'write Korean text', 'assess factual accuracy']),
  currentPublicRolePageObserved: true,
  acceptanceProbability: null,
  guaranteedWeeklyHours: null,
  futureTaskSupply: null,
  references: Object.freeze([roleUrl, faqUrl, termsUrl, privacyUrl]),
});

const snapshotHash = stableEvidenceHash(rawPayload);

export const OUTLIER_W8_SNAPSHOT: SourceSnapshot = Object.freeze({
  id: 'snapshot-w8-outlier-ko-20260830',
  sourceId: 'SRC-OUTLIER',
  endpointId: null,
  acquiredAt: OUTLIER_W8_OBSERVED_AT,
  acquisitionModeUsed: sourceById('SRC-OUTLIER').acquisitionMode,
  canonicalUrl: roleUrl,
  contentType: 'application/json',
  rawLocation: null,
  rawPayload,
  contentHash: snapshotHash,
  fetchMetadata: Object.freeze({
    acquisition: 'CENTRAL_MANUAL_CURATED_OFFICIAL_SOURCE',
    productTransportCallCount: 0,
    centralResearchNetworkUsed: true,
    privateAccountAccess: false,
    loggedInTaskInventoryObserved: false,
  }),
  actorProvenance: Object.freeze({ actorId: 'CENTRAL', mode: 'MANUAL_CURATED_OFFICIAL_SOURCE' }),
  httpStatus: null,
});

export const OUTLIER_W8_OPPORTUNITY: EarningOpportunity = Object.freeze({
  id: 'opp-w8-outlier-korean-freelance-writer',
  sourceId: 'SRC-OUTLIER',
  merchantId: null,
  canonicalKey: 'SRC-OUTLIER:korean-freelance-writer:ko-kr',
  providerExternalKey: 'languages/ko-kr',
  lifecycleState: 'VERIFIED',
  currentVersionId: 'opp-w8-outlier-korean-freelance-writer-v1',
  firstSeenAt: OUTLIER_W8_OBSERVED_AT,
  lastSeenAt: OUTLIER_W8_OBSERVED_AT,
});

export const OUTLIER_W8_VERSION: OpportunityVersion = Object.freeze({
  id: 'opp-w8-outlier-korean-freelance-writer-v1',
  offerId: OUTLIER_W8_OPPORTUNITY.id,
  versionNumber: 1,
  sourceSnapshotId: OUTLIER_W8_SNAPSHOT.id,
  title: 'Korean Freelance Writer — Outlier AI training',
  shortSummary: 'Outlier publicly lists a remote South Korea Korean-language freelance AI-training role with an advertised rate ceiling of USD 31/hour. Acceptance, future project matching, guaranteed hours, and future task supply are not asserted.',
  originalLanguage: 'en',
  verificationState: 'VERIFIED',
  sourceSnapshotHash: snapshotHash,
  modelId: null,
  promptVersion: null,
  inputHash: null,
  opportunityCategory: 'AI_EVALUATION',
  incomeLadderLevel: 'SKILLED_DIGITAL_GIG',
  compensationType: 'HOURLY',
  advertisedCompensationValue: 31,
  expectedPayoutValue: null,
  compensationCurrency: 'USD',
  estimatedActiveMinutes: null,
  estimatedTotalEffortMinutes: null,
  applicationMinutes: null,
  qualificationScreeningMinutes: null,
  preparationMinutes: null,
  startLatencyMinutes: null,
  payoutMethod: Object.freeze({ methods: Object.freeze(['PayPal', 'Airtm']) }),
  payoutDelay: Object.freeze({ cadence: 'WEEKLY', exactRolePageDay: null }),
  providerFees: null,
  repeatability: null,
  supplyAvailabilityState: 'PUBLIC_ROLE_PAGE_AVAILABLE',
  supplyObservedAt: OUTLIER_W8_OBSERVED_AT,
  applicationRequired: true,
  qualificationRequired: true,
  qualificationProbability: null,
  acceptanceProbability: null,
  rejectionOrReversalRisk: null,
  payoutReliability: null,
  eligibleCountriesOrRegions: Object.freeze(['KOREA']),
  languageRequirements: Object.freeze(['KOREAN']),
  skillRequirements: null,
  deviceOsRequirements: null,
  identityKycRequirements: Object.freeze(['IDENTITY_VERIFICATION', 'PHONE_VERIFICATION']),
  ageRequirements: null,
  taxContractorRequirements: Object.freeze({ relationship: 'INDEPENDENT_CONTRACTOR', jurisdictionSpecificTaxTreatment: 'UNKNOWN' }),
  schedulingRequirements: Object.freeze({ flexibleSchedule: true, guaranteedHours: null }),
  canonicalDestinationUrl: roleUrl,
  createdAt: OUTLIER_W8_OBSERVED_AT,
});

function evidence(
  id: string,
  fieldPath: string,
  evidenceText: string,
  url: string,
  confidence = 1,
): OpportunityEvidence {
  const locator = Object.freeze({ url, observationMode: 'OFFICIAL_PUBLIC_PAGE' });
  return Object.freeze({
    id,
    offerVersionId: OUTLIER_W8_VERSION.id,
    sourceSnapshotId: OUTLIER_W8_SNAPSHOT.id,
    fieldPath,
    evidenceText,
    evidenceLocator: locator,
    evidenceHash: stableEvidenceHash({ fieldPath, evidenceText, locator }),
    confidence,
    createdAt: OUTLIER_W8_OBSERVED_AT,
  });
}

export const OUTLIER_W8_EVIDENCE: readonly OpportunityEvidence[] = Object.freeze([
  evidence('ev-w8-outlier-role', 'title', 'Official page lists a Korean freelance writing role for AI training.', roleUrl),
  evidence('ev-w8-outlier-location', 'eligibleCountriesOrRegions', 'Role is remote and explicitly located in South Korea.', roleUrl),
  evidence('ev-w8-outlier-language', 'languageRequirements', 'Fluent Korean reading, writing and text evaluation are required.', roleUrl),
  evidence('ev-w8-outlier-rate', 'advertisedCompensationValue', 'Advertised core-work ceiling is USD 31 per hour; actual rates vary.', roleUrl),
  evidence('ev-w8-outlier-payment', 'payoutMethod', 'Public role materials identify PayPal and Airtm as payment methods.', roleUrl),
  evidence('ev-w8-outlier-onboarding', 'qualificationRequired', 'Public onboarding includes identity and phone verification plus a skill assessment.', roleUrl),
  evidence('ev-w8-outlier-tasking', 'opportunityCategory', 'Tasks include evaluating Korean AI responses, Korean writing, and factual-accuracy review.', roleUrl),
  evidence('ev-w8-outlier-contractor', 'taxContractorRequirements', 'Terms describe contributors as independent contractors paid for completed accepted tasks.', termsUrl),
]);

const ev = (id: string) => OUTLIER_W8_EVIDENCE.find((item) => item.id === id)?.id ?? null;

export const OUTLIER_W8_REQUIREMENTS: readonly OpportunityRequirement[] = Object.freeze([
  Object.freeze({
    id: 'req-w8-outlier-language', offerVersionId: OUTLIER_W8_VERSION.id, requirementType: 'LANGUAGE', operator: 'REQUIRED',
    normalizedValue: Object.freeze(['KOREAN']), displayText: 'Fluent Korean reading, writing and text evaluation are required.', required: true, confidence: 1,
    evidenceId: ev('ev-w8-outlier-language'),
  }),
  Object.freeze({
    id: 'req-w8-outlier-country', offerVersionId: OUTLIER_W8_VERSION.id, requirementType: 'COUNTRY_REGION', operator: 'IN',
    normalizedValue: Object.freeze(['KOREA']), displayText: 'The public role is listed for South Korea and is remote.', required: true, confidence: 1,
    evidenceId: ev('ev-w8-outlier-location'),
  }),
  Object.freeze({
    id: 'req-w8-outlier-identity', offerVersionId: OUTLIER_W8_VERSION.id, requirementType: 'IDENTITY_KYC', operator: 'REQUIRED',
    normalizedValue: Object.freeze({ identityVerification: true, phoneVerification: true }), displayText: 'Identity and phone verification are part of onboarding.', required: true, confidence: 1,
    evidenceId: ev('ev-w8-outlier-onboarding'),
  }),
  Object.freeze({
    id: 'req-w8-outlier-assessment', offerVersionId: OUTLIER_W8_VERSION.id, requirementType: 'QUALIFICATION', operator: 'REQUIRED',
    normalizedValue: Object.freeze({ skillAssessment: true }), displayText: 'A skill assessment is part of the public onboarding flow.', required: true, confidence: 1,
    evidenceId: ev('ev-w8-outlier-onboarding'),
  }),
]);

export const OUTLIER_W8_COMPENSATION: readonly OpportunityCompensationComponent[] = Object.freeze([
  Object.freeze({
    id: 'comp-w8-outlier-hourly-ceiling', offerVersionId: OUTLIER_W8_VERSION.id, componentType: 'HOURLY_RATE',
    amount: 31, currency: 'USD', rateUnit: 'HOUR', percent: null, capAmount: null,
    conditionText: 'Up to USD 31/hour for core project work; rate varies by expertise/project requirements and lower non-core rates may apply.',
    evidenceId: ev('ev-w8-outlier-rate'),
  }),
]);

export const OUTLIER_W8_WINDOWS: readonly OpportunityWindow[] = Object.freeze([
  Object.freeze({
    id: 'window-w8-outlier-application', offerVersionId: OUTLIER_W8_VERSION.id, windowType: 'APPLICATION',
    startAt: null, endAt: null, relativeRule: 'OPEN_WHILE_OFFICIAL_ROLE_PAGE_ACCEPTS_APPLICATIONS',
    displayText: 'Official role page exposes an application action; no explicit public closing date is asserted.',
    evidenceId: ev('ev-w8-outlier-role'),
  }),
]);

export const OUTLIER_W8_REVIEW_QUEUE: ReviewQueueItem = Object.freeze({
  id: 'rq-w8-outlier-ko-v1',
  offerVersionId: OUTLIER_W8_VERSION.id,
  reasonCodes: Object.freeze(['REAL_PUBLIC_CURRENT_ROLE', 'VARIABLE_UP_TO_COMPENSATION', 'QUALIFICATION_REQUIRED']),
  priority: 'HIGH',
  state: 'RESOLVED',
  assignedTo: 'CENTRAL',
  createdAt: OUTLIER_W8_OBSERVED_AT,
  resolvedAt: OUTLIER_W8_OBSERVED_AT,
});

export const OUTLIER_W8_REVIEW_DECISION: ReviewDecisionRecord = Object.freeze({
  id: 'review-w8-outlier-ko-v1',
  reviewQueueId: OUTLIER_W8_REVIEW_QUEUE.id,
  offerVersionId: OUTLIER_W8_VERSION.id,
  decision: 'APPROVE',
  reviewerId: 'CENTRAL',
  approvalReason: 'Official public Outlier role material supports the exact Korean remote role, South Korea location, up-to USD 31/hour compensation ceiling, Korean proficiency, onboarding verification/assessment, and AI-training task semantics. Acceptance probability, guaranteed hours, and future task supply remain NULL/UNKNOWN.',
  rejectionReason: null,
  patch: null,
  createdAt: OUTLIER_W8_OBSERVED_AT,
});

export const OUTLIER_VERIFIED20_RECORD: Verified20Record = Object.freeze({
  slot: 2,
  realEvidence: true,
  syntheticFixture: false,
  sourcePolicy: OUTLIER_W8_POLICY,
  sourceGates: OUTLIER_FINAL_GATES,
  snapshot: OUTLIER_W8_SNAPSHOT,
  opportunity: OUTLIER_W8_OPPORTUNITY,
  version: OUTLIER_W8_VERSION,
  certaintyType: 'CONDITIONAL',
  requirements: OUTLIER_W8_REQUIREMENTS,
  compensationComponents: OUTLIER_W8_COMPENSATION,
  windows: OUTLIER_W8_WINDOWS,
  evidence: OUTLIER_W8_EVIDENCE,
  reviewQueue: OUTLIER_W8_REVIEW_QUEUE,
  reviewDecision: OUTLIER_W8_REVIEW_DECISION,
  criticalEvidenceIds: Object.freeze([
    'ev-w8-outlier-role',
    'ev-w8-outlier-location',
    'ev-w8-outlier-language',
    'ev-w8-outlier-rate',
    'ev-w8-outlier-onboarding',
    'ev-w8-outlier-tasking',
  ]),
  lastCheckedAt: OUTLIER_W8_OBSERVED_AT,
  supplyClaimMode: 'PUBLIC_CURRENT_INVENTORY',
});
