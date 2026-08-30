import type {
  CompensationType,
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
import type { SourceCollectionGate, SourcePolicyReview } from '../source-policy/domain.js';
import { sourceById } from '../source-policy/registry.js';
import type { Verified20Record } from './domain.js';
import { stableEvidenceHash } from './hash.js';

export const ONEFORMA_W8_OBSERVED_AT = '2026-08-30T08:37:00.000Z';

const termsUrl = 'https://www.oneforma.com/terms-and-conditions/';
const privacyUrl = 'https://www.oneforma.com/privacy-policy/';
const conductUrl = 'https://www.oneforma.com/code-of-conduct/';

export const ONEFORMA_W8_POLICY: SourcePolicyReview = Object.freeze({
  sourceId: 'SRC-ONEFORMA',
  robotsStatus: 'WAIVED_MANUAL_ZERO_PRODUCT_TRANSPORT',
  termsStatus: 'REVIEWED_PUBLIC_TERMS_PRIVACY_AND_CONDUCT_2026-08-30',
  commercialReuse: 'LIMITED',
  textReuse: 'LIMITED',
  imageLogoReuse: 'BLOCKED',
  automationPermission: 'BLOCKED',
  affiliateIncentive: 'UNKNOWN',
  policyEvidenceUrl: termsUrl,
  reviewedAt: ONEFORMA_W8_OBSERVED_AT,
  reviewer: 'CENTRAL',
  decision: 'PASS_WITH_LIMITS',
  notes: 'Manual/deep-link curation of publicly visible project facts only. B64 stores its own factual paraphrases and canonical project links. No account/private project library, secured SOW/NDA content, Company Materials, logos, credentials, automated discovery, project execution, or AI-assisted contributor work is collected or performed.',
});

function gate(index: number, name: string, status: SourceCollectionGate['status'], evidence: string, notes: string): SourceCollectionGate {
  return Object.freeze({
    gateId: `SRC-ONEFORMA-G${index}`,
    sourceId: 'SRC-ONEFORMA',
    gate: name,
    required: true,
    status,
    failureAction: index <= 4 ? 'BLOCK' : 'SHADOW',
    evidence,
    notes,
  });
}

export const ONEFORMA_FINAL_GATES: readonly SourceCollectionGate[] = Object.freeze([
  gate(1, 'Source identity verified', 'PASS', 'https://www.oneforma.com/', 'Official OneForma/Centific public site identifies the freelance platform.'),
  gate(2, 'Official endpoint identified', 'PASS', 'https://www.oneforma.com/projects/', 'Only exact public project pages and public policy pages are used.'),
  gate(3, 'robots reviewed', 'WAIVED', 'MANUAL_ZERO_PRODUCT_TRANSPORT', 'No B64 automated collector is authorized or used.'),
  gate(4, 'terms/commercial reuse reviewed', 'PASS', termsUrl, 'Public factual paraphrase and canonical links only; protected project documents and Company Materials remain excluded.'),
  gate(5, 'collector stability test', 'WAIVED', 'NO_AUTOMATED_COLLECTOR', 'Not applicable to manual/deep-link curation.'),
  gate(6, 'evidence extraction works', 'PASS', 'W8_ONEFORMA_FIELD_LEVEL_EVIDENCE', 'Each counted public project carries field-level official evidence.'),
  gate(7, 'change detection works', 'WAIVED', 'FIRST_BASELINES_W6_AVAILABLE', 'These are first real baselines; later material changes must use W6 versioning.'),
  gate(8, 'human review accepted sample', 'PASS', 'W8_ONEFORMA_CENTRAL_REVIEWS', 'CENTRAL reviewed each public project independently before VERIFIED status.'),
]);

type ProjectConfig = Readonly<{
  slot: number;
  slug: string;
  title: string;
  url: string;
  category: OpportunityCategory;
  ladder: IncomeLadderLevel;
  compensationType: CompensationType;
  compensationBasis: 'HOUR' | 'APPROVED_ASSET';
  hoursRule: string | null;
  payoutCadence: string | null;
  languageRequirements: readonly string[];
  skillRequirements: readonly string[] | null;
  qualificationRequired: boolean | null;
  taskSummary: string;
  requirementsSummary: string;
}>;

const PROJECTS: readonly ProjectConfig[] = Object.freeze([
  Object.freeze({
    slot: 5,
    slug: 'audio-transcription-quality-reviewer-ko-kr',
    title: 'Audio Transcription Quality Reviewer — Korean (South Korea)',
    url: 'https://www.oneforma.com/projects/audio-transcription-quality-reviewer/',
    category: 'TRANSCRIPTION', ladder: 'TASK_WORK', compensationType: 'HOURLY', compensationBasis: 'HOUR',
    hoursRule: 'Flexible; tasks are released weekly and volume may vary by locale; up to 10 billable hours per day.', payoutCadence: null,
    languageRequirements: Object.freeze(['KOREAN']), skillRequirements: Object.freeze(['TRANSCRIPTION_REVIEW','SPEAKER_LABELING','TIMESTAMP_REVIEW']), qualificationRequired: true,
    taskSummary: 'Review long-form audio transcriptions for accuracy, speaker labels, timestamps, segmentation and audio issues.',
    requirementsSummary: 'Korean/South Korea is an eligible locale; detailed transcription guidelines, computer/internet/microphone and required practice tasks apply.',
  }),
  Object.freeze({
    slot: 6,
    slug: 'multilingual-intent-response-annotator-ko-kr',
    title: 'Multilingual Intent and Response Annotator — Korean (Korea)',
    url: 'https://www.oneforma.com/projects/multilingual-intent-and-response-annotator/',
    category: 'DATA_ANNOTATION', ladder: 'TASK_WORK', compensationType: 'HOURLY', compensationBasis: 'HOUR',
    hoursRule: '30–50 hours per month.', payoutCadence: 'TWICE_MONTHLY',
    languageRequirements: Object.freeze(['KOREAN']), skillRequirements: Object.freeze(['INTENT_ANNOTATION','AI_RESPONSE_ANNOTATION']), qualificationRequired: true,
    taskSummary: 'Label user requests and AI responses to improve multilingual intent interpretation.',
    requirementsSummary: 'Korean (Korea) is explicitly offered; onboarding is required before project contribution.',
  }),
  Object.freeze({
    slot: 7,
    slug: 'bilingual-translation-quality-rater-es-ko',
    title: 'Bilingual Translation Quality Rater — Spanish (Spain) to Korean (Korea)',
    url: 'https://www.oneforma.com/projects/bilingual-translation-quality-rater/',
    category: 'TRANSLATION', ladder: 'SKILLED_DIGITAL_GIG', compensationType: 'PER_UNIT', compensationBasis: 'APPROVED_ASSET',
    hoursRule: null, payoutCadence: null,
    languageRequirements: Object.freeze(['KOREAN','SPANISH']), skillRequirements: Object.freeze(['TRANSLATION_QUALITY_RATING']), qualificationRequired: true,
    taskSummary: 'Compare source sentences with translations and score translation quality using a defined rating scale.',
    requirementsSummary: 'The public project lists Spanish (Spain) to Korean (Korea); native target-language ability, strong source-language proficiency and required certifications apply.',
  }),
  Object.freeze({
    slot: 8,
    slug: 'paragraph-translation-quality-rater-ko-es',
    title: 'Paragraph-Level Translation Quality Rater — Korean (Korea) to Spanish (Spain)',
    url: 'https://www.oneforma.com/projects/paragraph-level-translation-quality-rater/',
    category: 'TRANSLATION', ladder: 'SKILLED_DIGITAL_GIG', compensationType: 'PER_UNIT', compensationBasis: 'APPROVED_ASSET',
    hoursRule: 'At least 2 hours per day; remote and flexible.', payoutCadence: null,
    languageRequirements: Object.freeze(['KOREAN','SPANISH']), skillRequirements: Object.freeze(['TRANSLATION_QUALITY_RATING','TEXT_ALIGNMENT']), qualificationRequired: true,
    taskSummary: 'Evaluate translated paragraphs and match translated text to source text to improve AI translation systems.',
    requirementsSummary: 'The public project lists Korean (Korea) to Spanish (Spain); language certification is required before starting.',
  }),
  Object.freeze({
    slot: 9,
    slug: 'multilingual-ai-qa-reviewer-ko-kr',
    title: 'Multilingual AI Quality Assurance Reviewer — Korean (South Korea)',
    url: 'https://www.oneforma.com/projects/multilingual-ai-quality-assurance-reviewer/',
    category: 'AI_EVALUATION', ladder: 'SKILLED_DIGITAL_GIG', compensationType: 'HOURLY', compensationBasis: 'HOUR',
    hoursRule: '20–30 hours per week; ongoing.', payoutCadence: 'TWICE_MONTHLY',
    languageRequirements: Object.freeze(['KOREAN']), skillRequirements: Object.freeze(['AI_OUTPUT_REVIEW','QUALITY_ASSURANCE']), qualificationRequired: null,
    taskSummary: 'Review multilingual AI outputs across summarization, text composition and visual content generation and provide structured quality feedback.',
    requirementsSummary: 'Korean — South Korea is explicitly listed among the project locales.',
  }),
  Object.freeze({
    slot: 10,
    slug: 'podcast-transcription-speech-annotator-ko-kr',
    title: 'Multilingual Podcast Transcription and Speech Annotator — Korean (South Korea)',
    url: 'https://www.oneforma.com/projects/multilingual-podcast-transcription-and-speech-annotator/',
    category: 'TRANSCRIPTION', ladder: 'TASK_WORK', compensationType: 'HOURLY', compensationBasis: 'HOUR',
    hoursRule: 'Flexible; weekly task releases; task volume may vary by location and batch.', payoutCadence: 'TWICE_MONTHLY',
    languageRequirements: Object.freeze(['KOREAN']), skillRequirements: Object.freeze(['TRANSCRIPTION','SPEAKER_LABELING','TIMESTAMP_ANNOTATION']), qualificationRequired: null,
    taskSummary: 'Transcribe podcast audio, label speakers, add timestamps and review recording quality for multilingual speech models.',
    requirementsSummary: 'Korean — South Korea is an eligible locale; native or near-native fluency, listening skill, transcription/speech-annotation experience, computer and stable internet are listed.',
  }),
]);

function createRecord(config: ProjectConfig): Verified20Record {
  const rawPayload = Object.freeze({
    provider: 'OneForma by Centific',
    publicProject: config.title,
    statusObserved: 'OPEN_ACCEPTING_APPLICATIONS',
    eligibleRegion: 'South Korea',
    compensationBasis: config.compensationBasis,
    advertisedCompensationAmount: null,
    advertisedCurrency: null,
    hoursRule: config.hoursRule,
    payoutCadence: config.payoutCadence,
    languageRequirements: config.languageRequirements,
    skillRequirements: config.skillRequirements,
    qualificationRequired: config.qualificationRequired,
    taskSummary: config.taskSummary,
    requirementsSummary: config.requirementsSummary,
    acceptanceProbability: null,
    guaranteedTaskSupply: null,
    references: Object.freeze([config.url, termsUrl, privacyUrl, conductUrl]),
  });
  const snapshotId = `snapshot-w8-oneforma-${config.slug}-20260830`;
  const versionId = `opp-w8-oneforma-${config.slug}-v1`;
  const opportunityId = `opp-w8-oneforma-${config.slug}`;
  const snapshot: SourceSnapshot = Object.freeze({
    id: snapshotId,
    sourceId: 'SRC-ONEFORMA',
    endpointId: null,
    acquiredAt: ONEFORMA_W8_OBSERVED_AT,
    acquisitionModeUsed: sourceById('SRC-ONEFORMA').acquisitionMode,
    canonicalUrl: config.url,
    contentType: 'application/json',
    rawLocation: null,
    rawPayload,
    contentHash: stableEvidenceHash(rawPayload),
    fetchMetadata: Object.freeze({ acquisition: 'CENTRAL_MANUAL_CURATED_OFFICIAL_SOURCE', productTransportCallCount: 0, centralResearchNetworkUsed: true, privateAccountAccess: false, securedProjectDocumentsAccessed: false }),
    actorProvenance: Object.freeze({ actorId: 'CENTRAL', mode: 'MANUAL_CURATED_OFFICIAL_SOURCE' }),
    httpStatus: null,
  });
  const opportunity: EarningOpportunity = Object.freeze({
    id: opportunityId,
    sourceId: 'SRC-ONEFORMA',
    merchantId: null,
    canonicalKey: `SRC-ONEFORMA:${config.slug}`,
    providerExternalKey: config.slug,
    lifecycleState: 'VERIFIED',
    currentVersionId: versionId,
    firstSeenAt: ONEFORMA_W8_OBSERVED_AT,
    lastSeenAt: ONEFORMA_W8_OBSERVED_AT,
  });
  const version: OpportunityVersion = Object.freeze({
    id: versionId,
    offerId: opportunityId,
    versionNumber: 1,
    sourceSnapshotId: snapshotId,
    title: config.title,
    shortSummary: `${config.taskSummary} The public page is open to applications for a South Korea/Korean option. The numeric rate, currency, acceptance probability and guaranteed future task supply are not publicly asserted and remain NULL/UNKNOWN.`,
    originalLanguage: 'en',
    verificationState: 'VERIFIED',
    sourceSnapshotHash: snapshot.contentHash,
    modelId: null, promptVersion: null, inputHash: null,
    opportunityCategory: config.category,
    incomeLadderLevel: config.ladder,
    compensationType: config.compensationType,
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
    payoutDelay: config.payoutCadence === null ? null : Object.freeze({ cadence: config.payoutCadence }),
    providerFees: null,
    repeatability: null,
    supplyAvailabilityState: 'PUBLIC_PROJECT_APPLICATION_OPEN',
    supplyObservedAt: ONEFORMA_W8_OBSERVED_AT,
    applicationRequired: true,
    qualificationRequired: config.qualificationRequired,
    qualificationProbability: null,
    acceptanceProbability: null,
    rejectionOrReversalRisk: null,
    payoutReliability: null,
    eligibleCountriesOrRegions: Object.freeze(['KOREA']),
    languageRequirements: config.languageRequirements,
    skillRequirements: config.skillRequirements,
    deviceOsRequirements: null,
    identityKycRequirements: null,
    ageRequirements: Object.freeze({ minimumAge: 18, source: 'OneForma platform terms' }),
    taxContractorRequirements: Object.freeze({ relationship: 'INDEPENDENT_CONTRACTOR', localTaxTreatment: 'SELF_RESPONSIBILITY_SUBJECT_TO_LOCAL_LAW' }),
    schedulingRequirements: config.hoursRule === null ? null : Object.freeze({ publicRule: config.hoursRule, guaranteedHours: null }),
    canonicalDestinationUrl: config.url,
    createdAt: ONEFORMA_W8_OBSERVED_AT,
  });
  const evidence = (suffix: string, fieldPath: string, text: string, url = config.url): OpportunityEvidence => {
    const locator = Object.freeze({ url, observationMode: 'OFFICIAL_PUBLIC_PAGE' });
    return Object.freeze({ id: `ev-w8-oneforma-${config.slot}-${suffix}`, offerVersionId: versionId, sourceSnapshotId: snapshotId, fieldPath, evidenceText: text, evidenceLocator: locator, evidenceHash: stableEvidenceHash({ fieldPath, text, locator }), confidence: 1, createdAt: ONEFORMA_W8_OBSERVED_AT });
  };
  const evidenceRows: readonly OpportunityEvidence[] = Object.freeze([
    evidence('project', 'title', 'Official OneForma project page identifies this distinct public project and shows it as open to applications.'),
    evidence('country', 'eligibleCountriesOrRegions', 'South Korea/Korean is explicitly listed as an eligible project locale.'),
    evidence('compensation', 'compensationType', `The public project states compensation by ${config.compensationBasis === 'HOUR' ? 'hour' : 'approved asset'} but does not expose a numeric Korea rate in the public evidence.`),
    evidence('task', 'opportunityCategory', config.taskSummary),
    evidence('requirements', 'languageRequirements', config.requirementsSummary),
    evidence('contractor', 'taxContractorRequirements', 'OneForma public terms define registered project workers as independent contractors.', termsUrl),
  ]);
  const evId = (suffix: string) => evidenceRows.find((item) => item.id.endsWith(`-${suffix}`))?.id ?? null;
  const requirements: readonly OpportunityRequirement[] = Object.freeze([
    Object.freeze({ id: `req-w8-oneforma-${config.slot}-country`, offerVersionId: versionId, requirementType: 'COUNTRY_REGION', operator: 'IN', normalizedValue: Object.freeze(['KOREA']), displayText: 'South Korea/Korean is an eligible option on the public project page.', required: true, confidence: 1, evidenceId: evId('country') }),
    Object.freeze({ id: `req-w8-oneforma-${config.slot}-language`, offerVersionId: versionId, requirementType: 'LANGUAGE', operator: 'REQUIRED', normalizedValue: config.languageRequirements, displayText: config.requirementsSummary, required: true, confidence: 1, evidenceId: evId('requirements') }),
    Object.freeze({ id: `req-w8-oneforma-${config.slot}-age`, offerVersionId: versionId, requirementType: 'AGE', operator: 'GTE', normalizedValue: 18, displayText: 'OneForma platform terms require users to be at least 18.', required: true, confidence: 1, evidenceId: evId('contractor') }),
  ]);
  const compensationComponents: readonly OpportunityCompensationComponent[] = Object.freeze([
    Object.freeze({ id: `comp-w8-oneforma-${config.slot}`, offerVersionId: versionId, componentType: config.compensationBasis === 'HOUR' ? 'HOURLY_RATE' : 'PER_UNIT', amount: null, currency: null, rateUnit: config.compensationBasis, percent: null, capAmount: null, conditionText: 'Public project page states the compensation basis, but the Korea-specific numeric rate/currency is not exposed publicly; no amount is inferred.', evidenceId: evId('compensation') }),
  ]);
  const windows: readonly OpportunityWindow[] = Object.freeze([
    Object.freeze({ id: `window-w8-oneforma-${config.slot}-application`, offerVersionId: versionId, windowType: 'APPLICATION', startAt: null, endAt: null, relativeRule: 'OPEN_WHILE_OFFICIAL_PROJECT_PAGE_ACCEPTS_APPLICATIONS', displayText: 'Official public project page is currently open and accepting applications; no closing date is inferred.', evidenceId: evId('project') }),
  ]);
  const reviewQueue: ReviewQueueItem = Object.freeze({ id: `rq-w8-oneforma-${config.slot}-v1`, offerVersionId: versionId, reasonCodes: Object.freeze(['REAL_PUBLIC_PROJECT','PUBLIC_NUMERIC_PAY_UNKNOWN','APPLICATION_OR_QUALIFICATION_REQUIRED']), priority: 'HIGH', state: 'RESOLVED', assignedTo: 'CENTRAL', createdAt: ONEFORMA_W8_OBSERVED_AT, resolvedAt: ONEFORMA_W8_OBSERVED_AT });
  const reviewDecision: ReviewDecisionRecord = Object.freeze({ id: `review-w8-oneforma-${config.slot}-v1`, reviewQueueId: reviewQueue.id, offerVersionId: versionId, decision: 'APPROVE', reviewerId: 'CENTRAL', approvalReason: 'Official public OneForma project evidence supports the exact project identity, Korea/Korean eligibility, task semantics and compensation basis. The public evidence does not establish a Korea-specific numeric rate, currency, acceptance probability or guaranteed task supply, so those fields remain NULL/UNKNOWN.', rejectionReason: null, patch: null, createdAt: ONEFORMA_W8_OBSERVED_AT });
  return Object.freeze({
    slot: config.slot,
    realEvidence: true,
    syntheticFixture: false,
    sourcePolicy: ONEFORMA_W8_POLICY,
    sourceGates: ONEFORMA_FINAL_GATES,
    snapshot,
    opportunity,
    version,
    certaintyType: 'CONDITIONAL',
    requirements,
    compensationComponents,
    windows,
    evidence: evidenceRows,
    reviewQueue,
    reviewDecision,
    criticalEvidenceIds: Object.freeze([evId('project'), evId('country'), evId('compensation'), evId('task'), evId('requirements')].filter((value): value is string => value !== null)),
    lastCheckedAt: ONEFORMA_W8_OBSERVED_AT,
    supplyClaimMode: 'PUBLIC_CURRENT_INVENTORY',
  });
}

export const ONEFORMA_VERIFIED20_RECORDS: readonly Verified20Record[] = Object.freeze(PROJECTS.map(createRecord));
export const ONEFORMA_AUDIO_QA_RECORD = ONEFORMA_VERIFIED20_RECORDS[0]!;
export const ONEFORMA_INTENT_ANNOTATOR_RECORD = ONEFORMA_VERIFIED20_RECORDS[1]!;
export const ONEFORMA_BILINGUAL_TRANSLATION_RECORD = ONEFORMA_VERIFIED20_RECORDS[2]!;
export const ONEFORMA_PARAGRAPH_TRANSLATION_RECORD = ONEFORMA_VERIFIED20_RECORDS[3]!;
export const ONEFORMA_AI_QA_RECORD = ONEFORMA_VERIFIED20_RECORDS[4]!;
export const ONEFORMA_PODCAST_TRANSCRIPTION_RECORD = ONEFORMA_VERIFIED20_RECORDS[5]!;
