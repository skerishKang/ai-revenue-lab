import type {
  EarningOpportunity,
  IncomeLadderLevel,
  OpportunityCategory,
  OpportunityCompensationComponent,
  OpportunityEvidence,
  OpportunityRequirement,
  OpportunityVersion,
  OpportunityWindow,
  ReviewDecisionRecord,
  ReviewQueueItem,
  SourceSnapshot,
} from '../persistence/domain.js';
import type { Source, SourceCollectionGate, SourcePolicyReview } from '../source-policy/domain.js';
import type { Verified20Record } from './domain.js';
import { stableEvidenceHash } from './hash.js';

export const WELO_W8_OBSERVED_AT = '2026-08-30T08:21:00.000Z';
const jobsUrl = 'https://jobs.lever.co/weloglobal?location=South+Korea';
const privacyUrl = 'https://www.weloglobal.com/privacy-notice/';
const leverPublicPostingDoc = 'https://hire.lever.co/developer/documentation';

export const WELO_W8_SOURCE: Source = Object.freeze({
  sourceId: 'SRC-WELO',
  sourceName: 'Welo Data / Welo Global',
  sourceType: 'GLOBAL_AI_WORK',
  lane: 'BUILD',
  launchPriority: 'P1',
  country: 'GLOBAL/KR',
  accessMode: 'PUBLIC_JOB_BOARD',
  loginRequired: false,
  jsRendered: false,
  monetizationRole: 'NONE',
  verificationState: 'RESEARCH_SUPPORTED',
  riskTier: 'MEDIUM',
  updateCadence: 'DAILY',
  officialBaseUrl: 'https://www.weloglobal.com/',
  listUrl: jobsUrl,
  nextAction: 'Track published South Korea job postings and suppress closed/changed postings; no applicant/private project data.',
  notes: 'W8 extension source. Public employer job postings are manually curated as factual summaries only; not added to the frozen W1 22-source baseline registry in this slice.',
  acquisitionMode: 'DEEP_LINK_OR_DIRECTORY',
  opportunityClassHint: Object.freeze(['AI_EVALUATION','DATA_ANNOTATION','DATA_REVIEW','TRANSLATION']),
});

export const WELO_W8_POLICY: SourcePolicyReview = Object.freeze({
  sourceId: 'SRC-WELO',
  robotsStatus: 'WAIVED_MANUAL_ZERO_PRODUCT_TRANSPORT',
  termsStatus: 'REVIEWED_PUBLIC_LEVER_DISTRIBUTION_AND_WELO_PRIVACY_2026-08-30',
  commercialReuse: 'LIMITED',
  textReuse: 'LIMITED',
  imageLogoReuse: 'BLOCKED',
  automationPermission: 'BLOCKED',
  affiliateIncentive: 'UNKNOWN',
  policyEvidenceUrl: leverPublicPostingDoc,
  reviewedAt: WELO_W8_OBSERVED_AT,
  reviewer: 'CENTRAL',
  decision: 'PASS_WITH_LIMITS',
  notes: 'Manual/deep-link curation of employer-published public job facts only. Lever documentation distinguishes published public postings from internal/closed/draft postings. B64 stores short factual paraphrases and canonical job links only; no bulk job-description reproduction, logos, applicant data, private project content, automated crawling, or Opal/service content is collected. This bounded decision is not a blanket content license.',
});

function gate(index: number, name: string, status: SourceCollectionGate['status'], evidence: string, notes: string): SourceCollectionGate {
  return Object.freeze({
    gateId: `SRC-WELO-G${index}`,
    sourceId: 'SRC-WELO',
    gate: name,
    required: true,
    status,
    failureAction: index <= 4 ? 'BLOCK' : 'SHADOW',
    evidence,
    notes,
  });
}

export const WELO_FINAL_GATES: readonly SourceCollectionGate[] = Object.freeze([
  gate(1, 'Source identity verified', 'PASS', `${jobsUrl} | ${privacyUrl}`, 'Welo Global public jobs surface and current privacy notice identify the employer/data-controller context.'),
  gate(2, 'Official public posting channel identified', 'PASS', `${jobsUrl} | ${leverPublicPostingDoc}`, 'Only Welo employer postings distributed through the public Lever job site are eligible for this manual W8 slice.'),
  gate(3, 'robots reviewed', 'WAIVED', 'MANUAL_ZERO_PRODUCT_TRANSPORT', 'No B64 automated collector is authorized or used for Welo records.'),
  gate(4, 'terms/commercial-use boundary reviewed', 'PASS', `${leverPublicPostingDoc} | ${privacyUrl}`, 'Bounded factual job curation only; public posting status is not treated as permission to reproduce protected content.'),
  gate(5, 'collector stability test', 'WAIVED', 'NO_AUTOMATED_COLLECTOR', 'Not applicable to manual/deep-link curation.'),
  gate(6, 'evidence extraction works', 'PASS', 'W8_WELO_FIELD_LEVEL_EVIDENCE', 'Each counted Welo record binds title, South Korea location, task, compensation and requirements to its exact public job page.'),
  gate(7, 'change detection works', 'WAIVED', 'FIRST_BASELINES_W6_AVAILABLE', 'These are first baselines; closed or materially changed postings must use suppression/versioning on later observations.'),
  gate(8, 'human review accepted sample', 'PASS', 'W8_WELO_CENTRAL_REVIEWS', 'CENTRAL independently reviewed each of the six exact public South Korea job postings.'),
]);

type WeloConfig = Readonly<{
  slot: number;
  slug: string;
  providerExternalKey: string;
  title: string;
  url: string;
  category: OpportunityCategory;
  ladder: IncomeLadderLevel;
  rate: number;
  rateQualifier: string;
  hoursRule: string | null;
  durationRule: string | null;
  taskSummary: string;
  languageRequirements: readonly string[];
  skillRequirements: readonly string[] | null;
  degreeRequirement: string | null;
  qualificationRequired: boolean | null;
  specialRisk: string | null;
}>;

const CONFIGS: readonly WeloConfig[] = Object.freeze([
  Object.freeze({
    slot: 15,
    slug: 'alpheratz-korean-translation-quality-rater',
    providerExternalKey: '0aa00a3e-df19-4b35-8873-eca10a8b7791',
    title: 'Alpheratz — Korean Translation Quality Rater',
    url: 'https://jobs.lever.co/weloglobal/0aa00a3e-df19-4b35-8873-eca10a8b7791',
    category: 'TRANSLATION', ladder: 'SKILLED_DIGITAL_GIG', rate: 30,
    rateQualifier: 'Public posting states USD 30/hour.', hoursRule: null, durationRule: 'ONGOING',
    taskSummary: 'Review and refine machine-translated Korean customer-service content, rate MT quality and produce high-quality reference translations.',
    languageRequirements: Object.freeze(['NATIVE_KOREAN','STRONG_ENGLISH']), skillRequirements: Object.freeze(['TRANSLATION','LOCALIZATION','MT_POST_EDITING_OR_QUALITY_EVALUATION']), degreeRequirement: null, qualificationRequired: null, specialRisk: null,
  }),
  Object.freeze({
    slot: 16,
    slug: 'alpheratz-korean-translation-quality-reviewer',
    providerExternalKey: 'a73f4f10-c90d-4b33-b62e-0a6948f4dc5a',
    title: 'Alpheratz — Korean Translation Quality Reviewer',
    url: 'https://jobs.lever.co/weloglobal/a73f4f10-c90d-4b33-b62e-0a6948f4dc5a',
    category: 'DATA_REVIEW', ladder: 'SKILLED_DIGITAL_GIG', rate: 37.5,
    rateQualifier: 'Public posting states USD 37.50/hour.', hoursRule: null, durationRule: 'ONGOING',
    taskSummary: 'Conduct second-pass Korean linguistic quality review, validate severity assessments, identify systemic MT issues and provide qualitative feedback.',
    languageRequirements: Object.freeze(['NATIVE_KOREAN','STRONG_ENGLISH']), skillRequirements: Object.freeze(['LINGUISTIC_QA','MT_EVALUATION','LOCALIZATION_QA']), degreeRequirement: null, qualificationRequired: null, specialRisk: null,
  }),
  Object.freeze({
    slot: 17,
    slug: 'circinus-audio-contributor-korean',
    providerExternalKey: '21bed87c-777f-4336-8d6a-eb120e09c2fd',
    title: 'Circinus — Audio Contributor Korean',
    url: 'https://jobs.lever.co/weloglobal/21bed87c-777f-4336-8d6a-eb120e09c2fd',
    category: 'DATA_ANNOTATION', ladder: 'TASK_WORK', rate: 18,
    rateQualifier: 'Public posting states USD 18/hour.', hoursRule: 'Estimated task duration 1 hour.', durationRule: 'UP_TO_2_HOURS_WITH_POSSIBLE_EXTENSION',
    taskSummary: 'Record short scripted Korean audio prompts on the project platform using a laptop in a remote South Korea data-collection project.',
    languageRequirements: Object.freeze(['NATIVE_OR_NEAR_NATIVE_KOREAN','ENGLISH_FOR_GUIDELINES']), skillRequirements: null, degreeRequirement: null, qualificationRequired: null, specialRisk: null,
  }),
  Object.freeze({
    slot: 18,
    slug: 'epsilon-korean-data-trainer',
    providerExternalKey: '62d41823-519a-43e9-afa4-765e194a2bd7',
    title: 'Project Epsilon — Korean Data Trainer',
    url: 'https://jobs.lever.co/weloglobal/62d41823-519a-43e9-afa4-765e194a2bd7',
    category: 'DATA_ANNOTATION', ladder: 'SKILLED_DIGITAL_GIG', rate: 42,
    rateQualifier: 'Public posting states USD 42/hour.', hoursRule: '10 hours per week.', durationRule: 'LONG_TERM',
    taskSummary: 'Review image-question pairs and provide accurate golden answers based on visible image content, flagging unclear or corrupted inputs.',
    languageRequirements: Object.freeze(['STRONG_KOREAN','FLUENT_ENGLISH']), skillRequirements: Object.freeze(['VISUAL_DATA_ANNOTATION','GUIDELINE_FOLLOWING']), degreeRequirement: 'BACHELORS_REQUIRED', qualificationRequired: null, specialRisk: null,
  }),
  Object.freeze({
    slot: 19,
    slug: 'epsilon-korean-quality-control-specialist',
    providerExternalKey: '06ad9ffd-d945-456d-b822-0d1a1bb488ed',
    title: 'Project Epsilon — Korean Quality Control Specialist',
    url: 'https://jobs.lever.co/weloglobal/06ad9ffd-d945-456d-b822-0d1a1bb488ed',
    category: 'DATA_REVIEW', ladder: 'SKILLED_DIGITAL_GIG', rate: 46.2,
    rateQualifier: 'Public posting states USD 46.20/hour.', hoursRule: '10 hours per week.', durationRule: 'LONG_TERM',
    taskSummary: 'Review Trainer image/question/golden-answer submissions for accuracy and consistency, flag ambiguity and provide corrections before sign-off.',
    languageRequirements: Object.freeze(['STRONG_KOREAN','STRONG_WRITTEN_ENGLISH']), skillRequirements: Object.freeze(['QUALITY_CONTROL','VISUAL_REVIEW','ERROR_DETECTION']), degreeRequirement: 'BACHELORS_REQUIRED', qualificationRequired: null, specialRisk: null,
  }),
  Object.freeze({
    slot: 20,
    slug: 'ara-zeta-ai-safety-evaluator-korean',
    providerExternalKey: '494c384e-9ecc-4d0d-9e63-5b8a4257b66e',
    title: 'Ara Zeta — AI Safety Evaluator Korean',
    url: 'https://jobs.lever.co/weloglobal/494c384e-9ecc-4d0d-9e63-5b8a4257b66e',
    category: 'AI_EVALUATION', ladder: 'SKILLED_DIGITAL_GIG', rate: 22,
    rateQualifier: 'Public posting states USD 22/hour.', hoursRule: '20–40 hours per week with stated schedule options.', durationRule: '2_TO_3_WEEKS',
    taskSummary: 'Evaluate AI-generated responses against a structured safety rubric for Korean cultural context, provide English rationales and support calibration/arbitration.',
    languageRequirements: Object.freeze(['KOREAN','ENGLISH']), skillRequirements: Object.freeze(['AI_SAFETY_EVALUATION','RUBRIC_BASED_ASSESSMENT','CULTURAL_CONTEXT']), degreeRequirement: null, qualificationRequired: null, specialRisk: 'EXPLICIT_AND_SENSITIVE_CONTENT',
  }),
]);

function createWeloRecord(config: WeloConfig): Verified20Record {
  const rawPayload = Object.freeze({
    provider: 'Welo Data / Welo Global',
    title: config.title,
    publicPostingState: 'PUBLISHED_PUBLIC_OBSERVED',
    location: 'South Korea',
    workMode: 'REMOTE',
    compensationUsdPerHour: config.rate,
    compensationQualifier: config.rateQualifier,
    hoursRule: config.hoursRule,
    durationRule: config.durationRule,
    taskSummary: config.taskSummary,
    languageRequirements: config.languageRequirements,
    skillRequirements: config.skillRequirements,
    degreeRequirement: config.degreeRequirement,
    specialRisk: config.specialRisk,
    acceptanceProbability: null,
    guaranteedFutureSupply: null,
    reference: config.url,
  });
  const snapshotId = `snapshot-w8-welo-${config.slug}-20260830`;
  const opportunityId = `opp-w8-welo-${config.slug}`;
  const versionId = `${opportunityId}-v1`;
  const snapshotHash = stableEvidenceHash(rawPayload);
  const snapshot: SourceSnapshot = Object.freeze({
    id: snapshotId, sourceId: 'SRC-WELO', endpointId: null, acquiredAt: WELO_W8_OBSERVED_AT,
    acquisitionModeUsed: WELO_W8_SOURCE.acquisitionMode, canonicalUrl: config.url, contentType: 'application/json', rawLocation: null, rawPayload,
    contentHash: snapshotHash,
    fetchMetadata: Object.freeze({ acquisition: 'CENTRAL_MANUAL_CURATED_PUBLIC_EMPLOYER_POSTING', productTransportCallCount: 0, centralResearchNetworkUsed: true, privateApplicantDataAccessed: false, privateProjectContentAccessed: false }),
    actorProvenance: Object.freeze({ actorId: 'CENTRAL', mode: 'MANUAL_CURATED_PUBLIC_EMPLOYER_POSTING' }), httpStatus: null,
  });
  const opportunity: EarningOpportunity = Object.freeze({
    id: opportunityId, sourceId: 'SRC-WELO', merchantId: null, canonicalKey: `SRC-WELO:${config.slug}`, providerExternalKey: config.providerExternalKey,
    lifecycleState: 'VERIFIED', currentVersionId: versionId, firstSeenAt: WELO_W8_OBSERVED_AT, lastSeenAt: WELO_W8_OBSERVED_AT,
  });
  const version: OpportunityVersion = Object.freeze({
    id: versionId, offerId: opportunityId, versionNumber: 1, sourceSnapshotId: snapshotId, title: config.title,
    shortSummary: `${config.taskSummary} The public South Korea posting advertises ${config.rateQualifier} Acceptance probability and future task supply are not guaranteed or inferred.`,
    originalLanguage: 'en', verificationState: 'VERIFIED', sourceSnapshotHash: snapshotHash, modelId: null, promptVersion: null, inputHash: null,
    opportunityCategory: config.category, incomeLadderLevel: config.ladder, compensationType: 'HOURLY',
    advertisedCompensationValue: config.rate, expectedPayoutValue: null, compensationCurrency: 'USD',
    estimatedActiveMinutes: config.slug === 'circinus-audio-contributor-korean' ? 60 : null, estimatedTotalEffortMinutes: null,
    applicationMinutes: null, qualificationScreeningMinutes: null, preparationMinutes: null, startLatencyMinutes: null,
    payoutMethod: null, payoutDelay: null, providerFees: null, repeatability: null,
    supplyAvailabilityState: 'PUBLIC_JOB_POSTING_AVAILABLE', supplyObservedAt: WELO_W8_OBSERVED_AT,
    applicationRequired: true, qualificationRequired: config.qualificationRequired, qualificationProbability: null, acceptanceProbability: null,
    rejectionOrReversalRisk: config.specialRisk === null ? null : Object.freeze({ workContentRisk: config.specialRisk }), payoutReliability: null,
    eligibleCountriesOrRegions: Object.freeze(['KOREA']), languageRequirements: config.languageRequirements, skillRequirements: config.skillRequirements,
    deviceOsRequirements: null, identityKycRequirements: null, ageRequirements: null,
    taxContractorRequirements: Object.freeze({ relationship: 'FREELANCE_OR_REMOTE_PROJECT_AS_PUBLICLY_POSTED' }),
    schedulingRequirements: config.hoursRule === null ? null : Object.freeze({ publicRule: config.hoursRule, durationRule: config.durationRule, guaranteedHours: null }),
    canonicalDestinationUrl: config.url, createdAt: WELO_W8_OBSERVED_AT,
  });
  const ev = (suffix: string, fieldPath: string, evidenceText: string): OpportunityEvidence => {
    const locator = Object.freeze({ url: config.url, observationMode: 'EMPLOYER_PUBLISHED_PUBLIC_JOB_PAGE' });
    return Object.freeze({ id: `ev-w8-welo-${config.slot}-${suffix}`, offerVersionId: versionId, sourceSnapshotId: snapshotId, fieldPath, evidenceText, evidenceLocator: locator, evidenceHash: stableEvidenceHash({ fieldPath, evidenceText, locator }), confidence: 1, createdAt: WELO_W8_OBSERVED_AT });
  };
  const evidenceRows: readonly OpportunityEvidence[] = Object.freeze([
    ev('posting', 'title', `Employer-published public Welo posting identifies ${config.title} as a remote South Korea opportunity.`),
    ev('pay', 'advertisedCompensationValue', config.rateQualifier),
    ev('task', 'opportunityCategory', config.taskSummary),
    ev('language', 'languageRequirements', `Public language requirements: ${config.languageRequirements.join(', ')}.`),
    ev('schedule', 'schedulingRequirements', `Public schedule/duration: ${config.hoursRule ?? 'not numerically specified'} / ${config.durationRule ?? 'not numerically specified'}.`),
  ]);
  const evidenceId = (suffix: string) => evidenceRows.find((item) => item.id.endsWith(`-${suffix}`))?.id ?? null;
  const requirements: OpportunityRequirement[] = [
    Object.freeze({ id: `req-w8-welo-${config.slot}-country`, offerVersionId: versionId, requirementType: 'COUNTRY_REGION', operator: 'IN', normalizedValue: Object.freeze(['KOREA']), displayText: 'Public posting is for South Korea.', required: true, confidence: 1, evidenceId: evidenceId('posting') }),
    Object.freeze({ id: `req-w8-welo-${config.slot}-language`, offerVersionId: versionId, requirementType: 'LANGUAGE', operator: 'REQUIRED', normalizedValue: config.languageRequirements, displayText: `Language requirements: ${config.languageRequirements.join(', ')}.`, required: true, confidence: 1, evidenceId: evidenceId('language') }),
  ];
  if (config.degreeRequirement !== null) requirements.push(Object.freeze({ id: `req-w8-welo-${config.slot}-degree`, offerVersionId: versionId, requirementType: 'QUALIFICATION', operator: 'REQUIRED', normalizedValue: Object.freeze({ degree: config.degreeRequirement }), displayText: 'Public posting requires a bachelor’s degree.', required: true, confidence: 1, evidenceId: evidenceId('posting') }));
  if (config.specialRisk !== null) requirements.push(Object.freeze({ id: `req-w8-welo-${config.slot}-risk`, offerVersionId: versionId, requirementType: 'OTHER', operator: 'DISCLOSED', normalizedValue: Object.freeze({ workContentRisk: config.specialRisk }), displayText: 'Public posting discloses explicit/sensitive content exposure.', required: true, confidence: 1, evidenceId: evidenceId('task') }));
  const compensation: readonly OpportunityCompensationComponent[] = Object.freeze([
    Object.freeze({ id: `comp-w8-welo-${config.slot}-hourly`, offerVersionId: versionId, componentType: 'HOURLY_RATE', amount: config.rate, currency: 'USD', rateUnit: 'HOUR', percent: null, capAmount: null, conditionText: config.rateQualifier, evidenceId: evidenceId('pay') }),
  ]);
  const windows: readonly OpportunityWindow[] = Object.freeze([
    Object.freeze({ id: `window-w8-welo-${config.slot}-application`, offerVersionId: versionId, windowType: 'APPLICATION', startAt: null, endAt: null, relativeRule: 'OPEN_WHILE_EMPLOYER_PUBLIC_POSTING_ACCEPTS_APPLICATIONS', displayText: 'The employer-published public job page currently exposes an application action; no closing date is inferred.', evidenceId: evidenceId('posting') }),
  ]);
  const reviewQueue: ReviewQueueItem = Object.freeze({ id: `rq-w8-welo-${config.slot}-v1`, offerVersionId: versionId, reasonCodes: Object.freeze(['NEW_REAL_SOURCE','PUBLIC_EMPLOYER_POSTING','COMPENSATION_EXPLICIT','POLICY_LIMITED_MANUAL_ONLY']), priority: 'HIGH', state: 'RESOLVED', assignedTo: 'CENTRAL', createdAt: WELO_W8_OBSERVED_AT, resolvedAt: WELO_W8_OBSERVED_AT });
  const reviewDecision: ReviewDecisionRecord = Object.freeze({ id: `review-w8-welo-${config.slot}-v1`, reviewQueueId: reviewQueue.id, offerVersionId: versionId, decision: 'APPROVE', reviewerId: 'CENTRAL', approvalReason: 'CENTRAL reviewed the exact employer-published South Korea job posting under the bounded Welo public-posting policy. The role, task, public hourly rate and requirements are evidence-backed; acceptance probability and future supply remain NULL/UNKNOWN.', rejectionReason: null, patch: null, createdAt: WELO_W8_OBSERVED_AT });
  return Object.freeze({
    slot: config.slot, realEvidence: true, syntheticFixture: false, sourcePolicy: WELO_W8_POLICY, sourceGates: WELO_FINAL_GATES,
    snapshot, opportunity, version, certaintyType: 'CONDITIONAL', requirements: Object.freeze(requirements), compensationComponents: compensation,
    windows, evidence: evidenceRows, reviewQueue, reviewDecision,
    criticalEvidenceIds: Object.freeze(evidenceRows.map((item) => item.id)), lastCheckedAt: WELO_W8_OBSERVED_AT, supplyClaimMode: 'PUBLIC_CURRENT_INVENTORY',
  });
}

export const WELO_VERIFIED20_RECORDS: readonly Verified20Record[] = Object.freeze(CONFIGS.map(createWeloRecord));
