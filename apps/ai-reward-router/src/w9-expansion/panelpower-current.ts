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
import { KOREAN_POCKET_MONEY_OBSERVED_AT, PANELPOWER_PROGRAM_RECORD } from '../verified20/korean-pocket-money.js';
import { stableEvidenceHash } from '../verified20/hash.js';
import type { W9ExpansionRecord } from './domain.js';

const PANELPOWER_HOME = 'https://www.panel.co.kr/';

interface Config {
  readonly ordinal: number;
  readonly slug: string;
  readonly title: string;
  readonly compensationKrw: number;
  readonly target: string;
  readonly targetNormalized: unknown;
}

const CONFIGS: readonly Config[] = Object.freeze([
  Object.freeze({
    ordinal: 21,
    slug: 'tertiary-hospital-outpatient-research',
    title: 'PanelPower — tertiary-hospital outpatient research',
    compensationKrw: 200000,
    target: 'Public current listing targets people scheduled for an outpatient visit to a tertiary hospital.',
    targetNormalized: Object.freeze({ tertiaryHospitalOutpatientVisitPlanned: true }),
  }),
  Object.freeze({
    ordinal: 22,
    slug: 'pr-advertising-professional-workshop',
    title: 'PanelPower — advertising/PR professional workshop',
    compensationKrw: 200000,
    target: 'Public current listing targets advertising/PR professionals.',
    targetNormalized: Object.freeze({ advertisingOrPrProfessional: true }),
  }),
  Object.freeze({
    ordinal: 23,
    slug: 'university-graduate-student-workshop',
    title: 'PanelPower — university/graduate-student workshop',
    compensationKrw: 150000,
    target: 'Public current listing targets university or graduate students.',
    targetNormalized: Object.freeze({ universityOrGraduateStudent: true }),
  }),
]);

function createRecord(config: Config): W9ExpansionRecord {
  const snapshotId = `snapshot-w9-panelpower-${config.slug}-20260830`;
  const opportunityId = `opp-w9-panelpower-${config.slug}`;
  const versionId = `${opportunityId}-v1`;
  const reviewId = `review-w9-panelpower-${config.slug}-v1`;
  const rawPayload = Object.freeze({
    provider: 'Embrain PanelPower',
    publicCurrentResearch: config.title,
    advertisedCompensationKrw: config.compensationKrw,
    participantTarget: config.target,
    duration: null,
    deadline: null,
    selectionProbability: null,
    guaranteedPayment: null,
  });
  const contentHash = stableEvidenceHash(rawPayload);
  const sourceGates: readonly SourceCollectionGate[] = Object.freeze(
    PANELPOWER_PROGRAM_RECORD.sourceGates.map((gate) => gate.gateId.endsWith('-G8')
      ? Object.freeze({ ...gate, evidence: reviewId, notes: 'CENTRAL reviewed this exact current PanelPower public research listing before W9 verification.' })
      : gate),
  );

  const snapshot: SourceSnapshot = Object.freeze({
    id: snapshotId,
    sourceId: PANELPOWER_PROGRAM_RECORD.snapshot.sourceId,
    endpointId: null,
    acquiredAt: KOREAN_POCKET_MONEY_OBSERVED_AT,
    acquisitionModeUsed: PANELPOWER_PROGRAM_RECORD.snapshot.acquisitionModeUsed,
    canonicalUrl: PANELPOWER_HOME,
    contentType: 'application/json',
    rawLocation: null,
    rawPayload,
    contentHash,
    fetchMetadata: Object.freeze({
      acquisition: 'CENTRAL_MANUAL_CURATED_OFFICIAL_SOURCE',
      productTransportCallCount: 0,
      privateAccountAccess: false,
      privateSurveyInventoryAccessed: false,
    }),
    actorProvenance: Object.freeze({ actorId: 'CENTRAL', mode: 'MANUAL_CURATED_OFFICIAL_SOURCE' }),
    httpStatus: null,
  });

  const opportunity: EarningOpportunity = Object.freeze({
    id: opportunityId,
    sourceId: snapshot.sourceId,
    merchantId: null,
    canonicalKey: `SRC-PANELPOWER:${config.slug}:20260830`,
    providerExternalKey: `public-homepage-${config.slug}-20260830`,
    lifecycleState: 'VERIFIED',
    currentVersionId: versionId,
    firstSeenAt: KOREAN_POCKET_MONEY_OBSERVED_AT,
    lastSeenAt: KOREAN_POCKET_MONEY_OBSERVED_AT,
  });

  const version: OpportunityVersion = Object.freeze({
    id: versionId,
    offerId: opportunityId,
    versionNumber: 1,
    sourceSnapshotId: snapshotId,
    title: config.title,
    shortSummary: `${config.target} The current public PanelPower listing advertises KRW ${config.compensationKrw.toLocaleString('en-US')}. Duration, exact deadline, selection probability and guaranteed payment are not asserted.`,
    originalLanguage: 'ko',
    verificationState: 'VERIFIED',
    sourceSnapshotHash: contentHash,
    modelId: null,
    promptVersion: null,
    inputHash: null,
    opportunityCategory: 'MARKET_RESEARCH',
    incomeLadderLevel: 'PROJECT_WORK',
    compensationType: 'FIXED',
    advertisedCompensationValue: config.compensationKrw,
    expectedPayoutValue: null,
    compensationCurrency: 'KRW',
    estimatedActiveMinutes: null,
    estimatedTotalEffortMinutes: null,
    applicationMinutes: null,
    qualificationScreeningMinutes: null,
    preparationMinutes: null,
    startLatencyMinutes: null,
    payoutMethod: null,
    payoutDelay: null,
    providerFees: null,
    repeatability: Object.freeze({ oneOffStudy: true }),
    supplyAvailabilityState: 'PUBLIC_RESEARCH_STUDY_AVAILABLE',
    supplyObservedAt: KOREAN_POCKET_MONEY_OBSERVED_AT,
    applicationRequired: true,
    qualificationRequired: true,
    qualificationProbability: null,
    acceptanceProbability: null,
    rejectionOrReversalRisk: null,
    payoutReliability: null,
    eligibleCountriesOrRegions: Object.freeze(['KOREA']),
    languageRequirements: null,
    skillRequirements: null,
    deviceOsRequirements: null,
    identityKycRequirements: null,
    ageRequirements: null,
    taxContractorRequirements: null,
    schedulingRequirements: null,
    canonicalDestinationUrl: PANELPOWER_HOME,
    createdAt: KOREAN_POCKET_MONEY_OBSERVED_AT,
  });

  const evidence = (suffix: string, fieldPath: string, text: string): OpportunityEvidence => {
    const locator = Object.freeze({ url: PANELPOWER_HOME, observationMode: 'OFFICIAL_PUBLIC_HOMEPAGE_CURRENT_RESEARCH_LIST' });
    return Object.freeze({
      id: `ev-w9-panelpower-${config.slug}-${suffix}`,
      offerVersionId: versionId,
      sourceSnapshotId: snapshotId,
      fieldPath,
      evidenceText: text,
      evidenceLocator: locator,
      evidenceHash: stableEvidenceHash({ fieldPath, text, locator }),
      confidence: 1,
      createdAt: KOREAN_POCKET_MONEY_OBSERVED_AT,
    });
  };

  const evidenceRows = Object.freeze([
    evidence('study', 'title', `Official PanelPower homepage currently lists ${config.title.replace('PanelPower — ', '')}.`),
    evidence('reward', 'advertisedCompensationValue', `Current public listing advertises KRW ${config.compensationKrw.toLocaleString('en-US')}.`),
    evidence('target', 'qualificationRequired', config.target),
  ]);

  const requirement: OpportunityRequirement = Object.freeze({
    id: `req-w9-panelpower-${config.slug}-target`,
    offerVersionId: versionId,
    requirementType: 'QUALIFICATION',
    operator: 'REQUIRED',
    normalizedValue: config.targetNormalized,
    displayText: config.target,
    required: true,
    confidence: 1,
    evidenceId: evidenceRows[2]!.id,
  });

  const compensation: OpportunityCompensationComponent = Object.freeze({
    id: `comp-w9-panelpower-${config.slug}-fixed`,
    offerVersionId: versionId,
    componentType: 'FIXED_PAY',
    amount: config.compensationKrw,
    currency: 'KRW',
    rateUnit: null,
    percent: null,
    capAmount: null,
    conditionText: 'Advertised study/workshop compensation; payment remains conditional on selection and participation requirements.',
    evidenceId: evidenceRows[1]!.id,
  });

  const window: OpportunityWindow = Object.freeze({
    id: `window-w9-panelpower-${config.slug}-application`,
    offerVersionId: versionId,
    windowType: 'APPLICATION',
    startAt: null,
    endAt: null,
    relativeRule: 'WHILE_CURRENT_PUBLIC_RESEARCH_LISTING_REMAINS_OPEN',
    displayText: 'Current PanelPower homepage listing is present; no exact public closing date is asserted.',
    evidenceId: evidenceRows[0]!.id,
  });

  const queue: ReviewQueueItem = Object.freeze({
    id: `rq-w9-panelpower-${config.slug}-v1`,
    offerVersionId: versionId,
    reasonCodes: Object.freeze(['REAL_CURRENT_SHORT_RESEARCH','TARGETED_REQUIREMENT','FIXED_ADVERTISED_COMPENSATION']),
    priority: 'HIGH',
    state: 'RESOLVED',
    assignedTo: 'CENTRAL',
    createdAt: KOREAN_POCKET_MONEY_OBSERVED_AT,
    resolvedAt: KOREAN_POCKET_MONEY_OBSERVED_AT,
  });

  const review: ReviewDecisionRecord = Object.freeze({
    id: reviewId,
    reviewQueueId: queue.id,
    offerVersionId: versionId,
    decision: 'APPROVE',
    reviewerId: 'CENTRAL',
    approvalReason: 'Current official PanelPower homepage supports the exact bounded research/workshop target and advertised KRW compensation. Duration, deadline, selection probability and guaranteed payment remain NULL/UNKNOWN.',
    rejectionReason: null,
    patch: null,
    createdAt: KOREAN_POCKET_MONEY_OBSERVED_AT,
  });

  return Object.freeze({
    ordinal: config.ordinal,
    realEvidence: true,
    syntheticFixture: false,
    sourcePolicy: PANELPOWER_PROGRAM_RECORD.sourcePolicy,
    sourceGates,
    snapshot,
    opportunity,
    version,
    certaintyType: 'CONDITIONAL',
    requirements: Object.freeze([requirement]),
    compensationComponents: Object.freeze([compensation]),
    windows: Object.freeze([window]),
    evidence: evidenceRows,
    reviewQueue: queue,
    reviewDecision: review,
    criticalEvidenceIds: Object.freeze(evidenceRows.map((item) => item.id)),
    lastCheckedAt: KOREAN_POCKET_MONEY_OBSERVED_AT,
    supplyClaimMode: 'PUBLIC_CURRENT_INVENTORY',
  });
}

export const PANELPOWER_HOSPITAL_RESEARCH_W9 = createRecord(CONFIGS[0]!);
export const PANELPOWER_PR_WORKSHOP_W9 = createRecord(CONFIGS[1]!);
export const PANELPOWER_STUDENT_WORKSHOP_W9 = createRecord(CONFIGS[2]!);

export const PANELPOWER_CURRENT_W9_RECORDS: readonly W9ExpansionRecord[] = Object.freeze([
  PANELPOWER_HOSPITAL_RESEARCH_W9,
  PANELPOWER_PR_WORKSHOP_W9,
  PANELPOWER_STUDENT_WORKSHOP_W9,
]);
