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
import type { Verified20Record } from './domain.js';
import { stableEvidenceHash } from './hash.js';
import { KOREAN_POCKET_MONEY_OBSERVED_AT, PANELPOWER_PROGRAM_RECORD } from './korean-pocket-money.js';

const url = 'https://www.panel.co.kr/';
const snapshotId = 'snapshot-w8-panelpower-realtor-focus-group-20260830';
const opportunityId = 'opp-w8-panelpower-realtor-focus-group';
const versionId = `${opportunityId}-v1`;

const rawPayload = Object.freeze({
  publicResearch: 'Licensed real-estate-agent focus group',
  advertisedCompensationKrw: 100000,
  qualification: 'licensed real-estate agent',
  duration: null,
  deadline: null,
  acceptanceProbability: null,
});
const contentHash = stableEvidenceHash(rawPayload);

const sourceGates: readonly SourceCollectionGate[] = Object.freeze(
  PANELPOWER_PROGRAM_RECORD.sourceGates.map((gate) => gate.gateId.endsWith('-G8')
    ? Object.freeze({ ...gate, evidence: 'review-w8-panelpower-realtor-v1', notes: 'CENTRAL reviewed the current public realtor focus-group representation.' })
    : gate),
);

const snapshot: SourceSnapshot = Object.freeze({
  id: snapshotId,
  sourceId: PANELPOWER_PROGRAM_RECORD.snapshot.sourceId,
  endpointId: null,
  acquiredAt: KOREAN_POCKET_MONEY_OBSERVED_AT,
  acquisitionModeUsed: PANELPOWER_PROGRAM_RECORD.snapshot.acquisitionModeUsed,
  canonicalUrl: url,
  contentType: 'application/json',
  rawLocation: null,
  rawPayload,
  contentHash,
  fetchMetadata: Object.freeze({ acquisition: 'CENTRAL_MANUAL_CURATED_OFFICIAL_SOURCE', productTransportCallCount: 0, privateAccountAccess: false }),
  actorProvenance: Object.freeze({ actorId: 'CENTRAL', mode: 'MANUAL_CURATED_OFFICIAL_SOURCE' }),
  httpStatus: null,
});

const opportunity: EarningOpportunity = Object.freeze({
  id: opportunityId,
  sourceId: snapshot.sourceId,
  merchantId: null,
  canonicalKey: 'SRC-PANELPOWER:realtor-focus-group-20260830',
  providerExternalKey: 'public-homepage-realtor-focus-group-20260830',
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
  title: 'PanelPower — licensed real-estate-agent focus group',
  shortSummary: 'PanelPower currently lists a focus group targeted to licensed real-estate agents with advertised compensation of KRW 100,000. Duration, deadline and selection probability are not publicly asserted.',
  originalLanguage: 'ko',
  verificationState: 'VERIFIED',
  sourceSnapshotHash: contentHash,
  modelId: null,
  promptVersion: null,
  inputHash: null,
  opportunityCategory: 'MARKET_RESEARCH',
  incomeLadderLevel: 'PROJECT_WORK',
  compensationType: 'FIXED',
  advertisedCompensationValue: 100000,
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
  skillRequirements: Object.freeze(['LICENSED_REAL_ESTATE_AGENT']),
  deviceOsRequirements: null,
  identityKycRequirements: null,
  ageRequirements: null,
  taxContractorRequirements: null,
  schedulingRequirements: null,
  canonicalDestinationUrl: url,
  createdAt: KOREAN_POCKET_MONEY_OBSERVED_AT,
});

function evidence(suffix: string, fieldPath: string, evidenceText: string): OpportunityEvidence {
  const locator = Object.freeze({ url, observationMode: 'OFFICIAL_PUBLIC_HOMEPAGE_CURRENT_RESEARCH_LIST' });
  return Object.freeze({ id: `ev-w8-panelpower-realtor-${suffix}`, offerVersionId: versionId, sourceSnapshotId: snapshotId, fieldPath, evidenceText, evidenceLocator: locator, evidenceHash: stableEvidenceHash({ fieldPath, evidenceText, locator }), confidence: 1, createdAt: KOREAN_POCKET_MONEY_OBSERVED_AT });
}
const evidenceRows = Object.freeze([
  evidence('study', 'title', 'Official PanelPower homepage currently lists a focus group for licensed real-estate agents.'),
  evidence('reward', 'advertisedCompensationValue', 'Current public listing advertises KRW 100,000.'),
  evidence('requirement', 'qualificationRequired', 'The public study title targets licensed real-estate agents.'),
]);

const requirement: OpportunityRequirement = Object.freeze({ id: 'req-w8-panelpower-realtor-license', offerVersionId: versionId, requirementType: 'QUALIFICATION', operator: 'REQUIRED', normalizedValue: Object.freeze({ licensedRealEstateAgent: true }), displayText: 'Applicant must match the public licensed-real-estate-agent target.', required: true, confidence: 1, evidenceId: evidenceRows[2]!.id });
const compensation: OpportunityCompensationComponent = Object.freeze({ id: 'comp-w8-panelpower-realtor-fixed', offerVersionId: versionId, componentType: 'FIXED_PAY', amount: 100000, currency: 'KRW', rateUnit: null, percent: null, capAmount: null, conditionText: 'Advertised focus-group compensation; payment remains conditional on study selection/participation requirements.', evidenceId: evidenceRows[1]!.id });
const window: OpportunityWindow = Object.freeze({ id: 'window-w8-panelpower-realtor-application', offerVersionId: versionId, windowType: 'APPLICATION', startAt: null, endAt: null, relativeRule: 'WHILE_CURRENT_PUBLIC_RESEARCH_LISTING_REMAINS_OPEN', displayText: 'Current homepage listing is present; no exact public deadline is asserted.', evidenceId: evidenceRows[0]!.id });
const queue: ReviewQueueItem = Object.freeze({ id: 'rq-w8-panelpower-realtor-v1', offerVersionId: versionId, reasonCodes: Object.freeze(['REAL_CURRENT_SHORT_RESEARCH','TARGETED_PROFESSIONAL_REQUIREMENT','FIXED_ADVERTISED_COMPENSATION']), priority: 'HIGH', state: 'RESOLVED', assignedTo: 'CENTRAL', createdAt: KOREAN_POCKET_MONEY_OBSERVED_AT, resolvedAt: KOREAN_POCKET_MONEY_OBSERVED_AT });
const review: ReviewDecisionRecord = Object.freeze({ id: 'review-w8-panelpower-realtor-v1', reviewQueueId: queue.id, offerVersionId: versionId, decision: 'APPROVE', reviewerId: 'CENTRAL', approvalReason: 'Official current PanelPower homepage supports the exact focus-group target and KRW 100,000 advertised compensation. Duration, deadline, selection probability and guaranteed payment remain unasserted.', rejectionReason: null, patch: null, createdAt: KOREAN_POCKET_MONEY_OBSERVED_AT });

export const PANELPOWER_REALTOR_FOCUS_GROUP_RECORD: Verified20Record = Object.freeze({
  slot: 18,
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
