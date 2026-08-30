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
import type { Verified20Record } from './domain.js';
import { stableEvidenceHash } from './hash.js';
import { ONEFORMA_FINAL_GATES, ONEFORMA_W8_POLICY } from './oneforma.js';

export const ONEFORMA_EXTRA_OBSERVED_AT = '2026-08-30T08:48:00.000Z';

const termsUrl = 'https://www.oneforma.com/terms-and-conditions/';

type ExtraConfig = Readonly<{
  slot: 11 | 12;
  slug: string;
  title: string;
  url: string;
  category: 'SEARCH_OR_QUALITY_EVALUATION';
  compensationType: 'HOURLY' | 'PER_UNIT';
  componentType: 'HOURLY_RATE' | 'PER_UNIT';
  rateUnit: 'HOUR' | 'APPROVED_ASSET';
  taskSummary: string;
  requirements: readonly Readonly<{ type: OpportunityRequirement['requirementType']; value: unknown; text: string }>[];
  schedule: string | null;
}>;

const CONFIGS: readonly ExtraConfig[] = Object.freeze([
  Object.freeze({
    slot: 11,
    slug: 'local-search-quality-evaluator-ko-kr',
    title: 'Local Search Quality Evaluator — South Korea',
    url: 'https://www.oneforma.com/projects/local-search-quality-evaluator/',
    category: 'SEARCH_OR_QUALITY_EVALUATION', compensationType: 'HOURLY', componentType: 'HOURLY_RATE', rateUnit: 'HOUR',
    taskSummary: 'Evaluate search tasks for user intent, factual accuracy and local relevance to improve map and geolocation search quality.',
    requirements: Object.freeze([
      Object.freeze({ type: 'COUNTRY_REGION' as const, value: Object.freeze(['KOREA']), text: 'South Korea is an eligible location and the evaluator must have lived in the eligible location for at least five years.' }),
      Object.freeze({ type: 'LANGUAGE' as const, value: Object.freeze(['LOCAL_LANGUAGE','ENGLISH']), text: 'Native/fluent local-language ability and very fluent English are required.' }),
      Object.freeze({ type: 'QUALIFICATION' as const, value: Object.freeze({ certificationRequired: true, cvRequired: true }), text: 'Project certifications and a CV are required.' }),
    ]),
    schedule: 'At least 10 hours per week; long-term remote work.',
  }),
  Object.freeze({
    slot: 12,
    slug: 'app-store-music-search-evaluator-ko-kr',
    title: 'App Store and Music Search Evaluator — Korean (Korea)',
    url: 'https://www.oneforma.com/projects/app-store-and-music-search-evaluator/',
    category: 'SEARCH_OR_QUALITY_EVALUATION', compensationType: 'PER_UNIT', componentType: 'PER_UNIT', rateUnit: 'APPROVED_ASSET',
    taskSummary: 'Evaluate app-store listings and music search results for usefulness, intent and user experience.',
    requirements: Object.freeze([
      Object.freeze({ type: 'COUNTRY_REGION' as const, value: Object.freeze(['KOREA']), text: 'Korean (Korea) is explicitly available and applicants must use the locale App Store.' }),
      Object.freeze({ type: 'LANGUAGE' as const, value: Object.freeze(['KOREAN','ENGLISH']), text: 'Native/fluent Korean and a very high level of English are required.' }),
      Object.freeze({ type: 'OTHER' as const, value: Object.freeze({ appleId: true, iosDevice: true }), text: 'A valid Apple ID and iOS device are required.' }),
      Object.freeze({ type: 'QUALIFICATION' as const, value: Object.freeze({ certificationRequired: true }), text: 'Required OneForma certification must be passed.' }),
    ]),
    schedule: null,
  }),
]);

function createExtra(config: ExtraConfig): Verified20Record {
  const rawPayload = Object.freeze({
    provider: 'OneForma by Centific', publicProject: config.title, statusObserved: 'OPEN_ACCEPTING_APPLICATIONS',
    eligibleRegion: 'South Korea', compensationBasis: config.rateUnit, advertisedCompensationAmount: null, advertisedCurrency: null,
    taskSummary: config.taskSummary, schedule: config.schedule, requirements: config.requirements,
    acceptanceProbability: null, guaranteedTaskSupply: null, references: Object.freeze([config.url, termsUrl]),
  });
  const snapshotId = `snapshot-w8-oneforma-${config.slug}-20260830`;
  const opportunityId = `opp-w8-oneforma-${config.slug}`;
  const versionId = `${opportunityId}-v1`;
  const snapshot: SourceSnapshot = Object.freeze({
    id: snapshotId, sourceId: 'SRC-ONEFORMA', endpointId: null, acquiredAt: ONEFORMA_EXTRA_OBSERVED_AT,
    acquisitionModeUsed: sourceById('SRC-ONEFORMA').acquisitionMode, canonicalUrl: config.url, contentType: 'application/json',
    rawLocation: null, rawPayload, contentHash: stableEvidenceHash(rawPayload),
    fetchMetadata: Object.freeze({ acquisition: 'CENTRAL_MANUAL_CURATED_OFFICIAL_SOURCE', productTransportCallCount: 0, centralResearchNetworkUsed: true, privateAccountAccess: false, securedProjectDocumentsAccessed: false }),
    actorProvenance: Object.freeze({ actorId: 'CENTRAL', mode: 'MANUAL_CURATED_OFFICIAL_SOURCE' }), httpStatus: null,
  });
  const opportunity: EarningOpportunity = Object.freeze({
    id: opportunityId, sourceId: 'SRC-ONEFORMA', merchantId: null, canonicalKey: `SRC-ONEFORMA:${config.slug}`,
    providerExternalKey: config.slug, lifecycleState: 'VERIFIED', currentVersionId: versionId,
    firstSeenAt: ONEFORMA_EXTRA_OBSERVED_AT, lastSeenAt: ONEFORMA_EXTRA_OBSERVED_AT,
  });
  const version: OpportunityVersion = Object.freeze({
    id: versionId, offerId: opportunityId, versionNumber: 1, sourceSnapshotId: snapshotId, title: config.title,
    shortSummary: `${config.taskSummary} The public page is open to applications for South Korea. Numeric compensation, currency, acceptance probability and guaranteed future task supply remain NULL/UNKNOWN.`,
    originalLanguage: 'en', verificationState: 'VERIFIED', sourceSnapshotHash: snapshot.contentHash,
    modelId: null, promptVersion: null, inputHash: null, opportunityCategory: config.category, incomeLadderLevel: 'TASK_WORK', compensationType: config.compensationType,
    advertisedCompensationValue: null, expectedPayoutValue: null, compensationCurrency: null,
    estimatedActiveMinutes: null, estimatedTotalEffortMinutes: null, applicationMinutes: null, qualificationScreeningMinutes: null, preparationMinutes: null, startLatencyMinutes: null,
    payoutMethod: null, payoutDelay: Object.freeze({ cadence: 'TWICE_MONTHLY_PUBLIC_PROJECT_LABEL' }), providerFees: null, repeatability: null,
    supplyAvailabilityState: 'PUBLIC_PROJECT_APPLICATION_OPEN', supplyObservedAt: ONEFORMA_EXTRA_OBSERVED_AT,
    applicationRequired: true, qualificationRequired: true, qualificationProbability: null, acceptanceProbability: null,
    rejectionOrReversalRisk: null, payoutReliability: null, eligibleCountriesOrRegions: Object.freeze(['KOREA']),
    languageRequirements: Object.freeze(config.slot === 12 ? ['KOREAN','ENGLISH'] : ['LOCAL_LANGUAGE','ENGLISH']), skillRequirements: null,
    deviceOsRequirements: config.slot === 12 ? Object.freeze(['IOS_DEVICE']) : null, identityKycRequirements: null,
    ageRequirements: Object.freeze({ minimumAge: 18, source: 'OneForma platform terms' }), taxContractorRequirements: Object.freeze({ relationship: 'INDEPENDENT_CONTRACTOR' }),
    schedulingRequirements: config.schedule === null ? null : Object.freeze({ publicRule: config.schedule, guaranteedHours: null }),
    canonicalDestinationUrl: config.url, createdAt: ONEFORMA_EXTRA_OBSERVED_AT,
  });
  const makeEvidence = (suffix: string, fieldPath: string, text: string, url = config.url): OpportunityEvidence => {
    const locator = Object.freeze({ url, observationMode: 'OFFICIAL_PUBLIC_PAGE' });
    return Object.freeze({ id: `ev-w8-oneforma-${config.slot}-${suffix}`, offerVersionId: versionId, sourceSnapshotId: snapshotId, fieldPath, evidenceText: text, evidenceLocator: locator, evidenceHash: stableEvidenceHash({ fieldPath, text, locator }), confidence: 1, createdAt: ONEFORMA_EXTRA_OBSERVED_AT });
  };
  const evidence: readonly OpportunityEvidence[] = Object.freeze([
    makeEvidence('project', 'title', 'Official OneForma project page identifies this project and marks it open to applications.'),
    makeEvidence('country', 'eligibleCountriesOrRegions', 'South Korea/Korean is explicitly listed as an eligible locale.'),
    makeEvidence('compensation', 'compensationType', `Public compensation is stated as ${config.rateUnit === 'HOUR' ? 'fixed rate per hour' : 'fixed rate per approved asset'}; no public Korea numeric amount is asserted.`),
    makeEvidence('task', 'opportunityCategory', config.taskSummary),
    makeEvidence('requirements', 'requirements', config.requirements.map((item) => item.text).join(' ')),
    makeEvidence('age', 'ageRequirements', 'OneForma public terms require users to be at least 18 years old.', termsUrl),
    makeEvidence('contractor', 'taxContractorRequirements', 'OneForma public terms define project workers as independent contractors.', termsUrl),
  ]);
  const idFor = (suffix: string) => evidence.find((item) => item.id.endsWith(`-${suffix}`))?.id ?? null;
  const requirements: readonly OpportunityRequirement[] = Object.freeze([
    ...config.requirements.map((item, index) => Object.freeze({ id: `req-w8-oneforma-${config.slot}-${index + 1}`, offerVersionId: versionId, requirementType: item.type, operator: 'REQUIRED', normalizedValue: item.value, displayText: item.text, required: true, confidence: 1, evidenceId: idFor('requirements') })),
    Object.freeze({ id: `req-w8-oneforma-${config.slot}-age`, offerVersionId: versionId, requirementType: 'AGE' as const, operator: 'GTE', normalizedValue: 18, displayText: 'OneForma platform terms require users to be at least 18.', required: true, confidence: 1, evidenceId: idFor('age') }),
  ]);
  const compensationComponents: readonly OpportunityCompensationComponent[] = Object.freeze([
    Object.freeze({ id: `comp-w8-oneforma-${config.slot}`, offerVersionId: versionId, componentType: config.componentType, amount: null, currency: null, rateUnit: config.rateUnit, percent: null, capAmount: null, conditionText: 'Public page states compensation basis but not the Korea numeric rate/currency; no amount is inferred.', evidenceId: idFor('compensation') }),
  ]);
  const windows: readonly OpportunityWindow[] = Object.freeze([
    Object.freeze({ id: `window-w8-oneforma-${config.slot}-application`, offerVersionId: versionId, windowType: 'APPLICATION', startAt: null, endAt: null, relativeRule: 'OPEN_WHILE_OFFICIAL_PROJECT_PAGE_ACCEPTS_APPLICATIONS', displayText: 'Official public project page is open and accepting applications; no closing date is inferred.', evidenceId: idFor('project') }),
  ]);
  const reviewQueue: ReviewQueueItem = Object.freeze({ id: `rq-w8-oneforma-${config.slot}-v1`, offerVersionId: versionId, reasonCodes: Object.freeze(['REAL_PUBLIC_PROJECT','PUBLIC_NUMERIC_PAY_UNKNOWN','QUALIFICATION_REQUIRED']), priority: 'HIGH', state: 'RESOLVED', assignedTo: 'CENTRAL', createdAt: ONEFORMA_EXTRA_OBSERVED_AT, resolvedAt: ONEFORMA_EXTRA_OBSERVED_AT });
  const reviewDecision: ReviewDecisionRecord = Object.freeze({ id: `review-w8-oneforma-${config.slot}-v1`, reviewQueueId: reviewQueue.id, offerVersionId: versionId, decision: 'APPROVE', reviewerId: 'CENTRAL', approvalReason: 'Official public OneForma evidence supports the exact project identity, South Korea eligibility, task semantics, requirements and compensation basis. Numeric pay, currency, acceptance probability and guaranteed future supply remain NULL/UNKNOWN.', rejectionReason: null, patch: null, createdAt: ONEFORMA_EXTRA_OBSERVED_AT });
  return Object.freeze({ slot: config.slot, realEvidence: true, syntheticFixture: false, sourcePolicy: ONEFORMA_W8_POLICY, sourceGates: ONEFORMA_FINAL_GATES, snapshot, opportunity, version, certaintyType: 'CONDITIONAL', requirements, compensationComponents, windows, evidence, reviewQueue, reviewDecision, criticalEvidenceIds: Object.freeze([idFor('project'),idFor('country'),idFor('compensation'),idFor('task'),idFor('requirements'),idFor('age')].filter((value): value is string => value !== null)), lastCheckedAt: ONEFORMA_EXTRA_OBSERVED_AT, supplyClaimMode: 'PUBLIC_CURRENT_INVENTORY' });
}

export const ONEFORMA_EXTRA_VERIFIED20_RECORDS: readonly Verified20Record[] = Object.freeze(CONFIGS.map(createExtra));
export const ONEFORMA_LOCAL_SEARCH_RECORD = ONEFORMA_EXTRA_VERIFIED20_RECORDS[0]!;
export const ONEFORMA_APP_MUSIC_SEARCH_RECORD = ONEFORMA_EXTRA_VERIFIED20_RECORDS[1]!;
