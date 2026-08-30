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

export const PROLIFIC_W8_OBSERVED_AT = '2026-08-30T08:00:00.000Z';

const participantUrl = 'https://www.prolific.com/participants';
const eligibilityUrl = 'https://participant-help.prolific.com/en/article/628d72';
const howItWorksUrl = 'https://participant-help.prolific.com/en/article/36141a';
const legalUrl = 'https://www.prolific.com/privacy-and-legal';

export const PROLIFIC_W8_POLICY: SourcePolicyReview = Object.freeze({
  sourceId: 'SRC-PROLIFIC',
  robotsStatus: 'WAIVED_MANUAL_ZERO_TRANSPORT',
  termsStatus: 'REVIEWED_PUBLIC_LEGAL_AND_PARTICIPANT_MATERIAL_2026-08-30',
  commercialReuse: 'LIMITED',
  textReuse: 'LIMITED',
  imageLogoReuse: 'BLOCKED',
  automationPermission: 'BLOCKED',
  affiliateIncentive: 'UNKNOWN',
  policyEvidenceUrl: legalUrl,
  reviewedAt: PROLIFIC_W8_OBSERVED_AT,
  reviewer: 'CENTRAL',
  decision: 'PASS_WITH_LIMITS',
  notes: 'Manual/deep-link curation only. Factual paraphrase, canonical links, and minimal evidence snippets are allowed for B64 trust review. No automated feed/crawl, no logged-in study inventory, no page/logo reproduction, and no implication that VERIFIED means consumer LIVE publication.',
});

function gate(
  index: number,
  name: string,
  status: SourceCollectionGate['status'],
  evidence: string,
  notes: string,
): SourceCollectionGate {
  return Object.freeze({
    gateId: `SRC-PROLIFIC-G${index}`,
    sourceId: 'SRC-PROLIFIC',
    gate: name,
    required: true,
    status,
    failureAction: index <= 4 ? 'BLOCK' : 'SHADOW',
    evidence,
    notes,
  });
}

/**
 * Bootstrap clearance before manual curation. Downstream evidence extraction,
 * baseline change detection, and human review are deliberately WAIVED only as
 * acquisition preconditions; the final W8 record separately proves them.
 */
export const PROLIFIC_PRE_CURATION_GATES: readonly SourceCollectionGate[] = Object.freeze([
  gate(1, 'Source identity verified', 'PASS', participantUrl, 'Official Prolific participant surface identifies the provider and participant program.'),
  gate(2, 'Official endpoint identified', 'PASS', participantUrl, 'Canonical public participant and help references are recorded; no private endpoint is used.'),
  gate(3, 'robots reviewed', 'WAIVED', 'MANUAL_ZERO_TRANSPORT', 'No automated HTTP collector is authorized or used by this manual-curation path.'),
  gate(4, 'terms/commercial reuse reviewed', 'PASS', legalUrl, 'Bounded internal factual curation only; this is not a blanket reuse or automation grant.'),
  gate(5, 'collector stability test', 'WAIVED', 'NO_AUTOMATED_COLLECTOR', 'Not applicable to manual/deep-link curation.'),
  gate(6, 'evidence extraction works', 'WAIVED', 'BOOTSTRAP_PRECONDITION_ONLY', 'Waived only before first manual seed; final record contains field-level evidence.'),
  gate(7, 'change detection works', 'WAIVED', 'FIRST_BASELINE_W6_AVAILABLE', 'First real baseline has no predecessor; W6 material-change machinery exists and W8 negative demonstration is tracked separately.'),
  gate(8, 'human review accepted sample', 'WAIVED', 'BOOTSTRAP_PRECONDITION_ONLY', 'Waived only to permit acquisition; final record contains a resolved CENTRAL approval.'),
]);

export const PROLIFIC_FINAL_GATES: readonly SourceCollectionGate[] = Object.freeze(
  PROLIFIC_PRE_CURATION_GATES.map((item, index) => {
    if (index === 5) return Object.freeze({ ...item, status: 'PASS' as const, evidence: 'W8_PROLIFIC_FIELD_LEVEL_EVIDENCE', notes: 'Final record binds critical normalized fields to official public source evidence.' });
    if (index === 7) return Object.freeze({ ...item, status: 'PASS' as const, evidence: 'review-w8-prolific-v1', notes: 'CENTRAL reviewed and approved the provider-level representation with private/current inventory kept UNKNOWN.' });
    return item;
  }),
);

const rawPayload = Object.freeze({
  provider: 'Prolific',
  program: 'paid online studies',
  minimumAge: 18,
  supportedCountryObserved: 'KOREA',
  accountVerificationRequired: true,
  waitlistPossible: true,
  payoutMethod: 'PayPal',
  publicCashoutThreshold: '$6/£6',
  individualStudyInventoryPubliclyObserved: false,
  individualStudyPayAmount: null,
  selectionProbability: null,
  references: Object.freeze([participantUrl, eligibilityUrl, howItWorksUrl, legalUrl]),
});

const snapshotHash = stableEvidenceHash(rawPayload);

export const PROLIFIC_W8_SNAPSHOT: SourceSnapshot = Object.freeze({
  id: 'snapshot-w8-prolific-20260830',
  sourceId: 'SRC-PROLIFIC',
  endpointId: null,
  acquiredAt: PROLIFIC_W8_OBSERVED_AT,
  acquisitionModeUsed: sourceById('SRC-PROLIFIC').acquisitionMode,
  canonicalUrl: participantUrl,
  contentType: 'application/json',
  rawLocation: null,
  rawPayload,
  contentHash: snapshotHash,
  fetchMetadata: Object.freeze({
    acquisition: 'CENTRAL_MANUAL_CURATED_OFFICIAL_SOURCE',
    transportCallCount: 0,
    privateAccountAccess: false,
    loggedInInventoryObserved: false,
  }),
  actorProvenance: Object.freeze({ actorId: 'CENTRAL', mode: 'MANUAL_CURATED_OFFICIAL_SOURCE' }),
  httpStatus: null,
});

export const PROLIFIC_W8_OPPORTUNITY: EarningOpportunity = Object.freeze({
  id: 'opp-w8-prolific-paid-studies',
  sourceId: 'SRC-PROLIFIC',
  merchantId: null,
  canonicalKey: 'SRC-PROLIFIC:paid-online-studies',
  providerExternalKey: null,
  lifecycleState: 'VERIFIED',
  currentVersionId: 'opp-w8-prolific-paid-studies-v1',
  firstSeenAt: PROLIFIC_W8_OBSERVED_AT,
  lastSeenAt: PROLIFIC_W8_OBSERVED_AT,
});

export const PROLIFIC_W8_VERSION: OpportunityVersion = Object.freeze({
  id: 'opp-w8-prolific-paid-studies-v1',
  offerId: PROLIFIC_W8_OPPORTUNITY.id,
  versionNumber: 1,
  sourceSnapshotId: PROLIFIC_W8_SNAPSHOT.id,
  title: 'Paid online studies on Prolific',
  shortSummary: 'Prolific publicly offers paid online study participation. Individual study availability, study-specific reward amounts, and selection probability are account-specific and are not asserted from public evidence.',
  originalLanguage: 'en',
  verificationState: 'VERIFIED',
  sourceSnapshotHash: snapshotHash,
  modelId: null,
  promptVersion: null,
  inputHash: null,
  opportunityCategory: 'MARKET_RESEARCH',
  incomeLadderLevel: 'TASK_WORK',
  compensationType: 'VARIABLE',
  advertisedCompensationValue: null,
  expectedPayoutValue: null,
  compensationCurrency: null,
  estimatedActiveMinutes: null,
  estimatedTotalEffortMinutes: null,
  applicationMinutes: null,
  qualificationScreeningMinutes: null,
  preparationMinutes: null,
  startLatencyMinutes: null,
  payoutMethod: Object.freeze({ method: 'PayPal', cashoutThreshold: '$6/£6' }),
  payoutDelay: null,
  providerFees: null,
  repeatability: null,
  supplyAvailabilityState: 'ACCOUNT_SPECIFIC_UNKNOWN',
  supplyObservedAt: null,
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
  identityKycRequirements: Object.freeze(['ACCOUNT_VERIFICATION']),
  ageRequirements: Object.freeze({ minimumAge: 18 }),
  taxContractorRequirements: null,
  schedulingRequirements: null,
  canonicalDestinationUrl: participantUrl,
  createdAt: PROLIFIC_W8_OBSERVED_AT,
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
    offerVersionId: PROLIFIC_W8_VERSION.id,
    sourceSnapshotId: PROLIFIC_W8_SNAPSHOT.id,
    fieldPath,
    evidenceText,
    evidenceLocator: locator,
    evidenceHash: stableEvidenceHash({ fieldPath, evidenceText, locator }),
    confidence,
    createdAt: PROLIFIC_W8_OBSERVED_AT,
  });
}

export const PROLIFIC_W8_EVIDENCE: readonly OpportunityEvidence[] = Object.freeze([
  evidence('ev-w8-prolific-program', 'opportunityCategory', 'Get paid to take studies', participantUrl),
  evidence('ev-w8-prolific-age', 'ageRequirements.minimumAge', 'over 18', eligibilityUrl),
  evidence('ev-w8-prolific-country', 'eligibleCountriesOrRegions', 'KOREA', eligibilityUrl),
  evidence('ev-w8-prolific-verify', 'identityKycRequirements', 'Verify your account', howItWorksUrl),
  evidence('ev-w8-prolific-payout', 'payoutMethod', 'transferred to your PayPal', participantUrl),
]);

const ev = (id: string) => PROLIFIC_W8_EVIDENCE.find((item) => item.id === id)?.id ?? null;

export const PROLIFIC_W8_REQUIREMENTS: readonly OpportunityRequirement[] = Object.freeze([
  Object.freeze({
    id: 'req-w8-prolific-age', offerVersionId: PROLIFIC_W8_VERSION.id, requirementType: 'AGE', operator: 'GTE',
    normalizedValue: 18, displayText: 'Participant must be at least 18.', required: true, confidence: 1,
    evidenceId: ev('ev-w8-prolific-age'),
  }),
  Object.freeze({
    id: 'req-w8-prolific-country', offerVersionId: PROLIFIC_W8_VERSION.id, requirementType: 'COUNTRY_REGION', operator: 'IN',
    normalizedValue: Object.freeze(['KOREA']), displayText: 'Korea appears in Prolific’s supported-country list.', required: true, confidence: 1,
    evidenceId: ev('ev-w8-prolific-country'),
  }),
  Object.freeze({
    id: 'req-w8-prolific-account', offerVersionId: PROLIFIC_W8_VERSION.id, requirementType: 'IDENTITY_KYC', operator: 'REQUIRED',
    normalizedValue: Object.freeze({ accountVerification: true }), displayText: 'Account verification is required before participation.', required: true, confidence: 1,
    evidenceId: ev('ev-w8-prolific-verify'),
  }),
]);

export const PROLIFIC_W8_COMPENSATION: readonly OpportunityCompensationComponent[] = Object.freeze([
  Object.freeze({
    id: 'comp-w8-prolific-study-specific', offerVersionId: PROLIFIC_W8_VERSION.id, componentType: 'OTHER',
    amount: null, currency: null, rateUnit: null, percent: null, capAmount: null,
    conditionText: 'Study-specific compensation varies; no universal public study amount is asserted.',
    evidenceId: ev('ev-w8-prolific-program'),
  }),
]);

export const PROLIFIC_W8_WINDOWS: readonly OpportunityWindow[] = Object.freeze([
  Object.freeze({
    id: 'window-w8-prolific-application', offerVersionId: PROLIFIC_W8_VERSION.id, windowType: 'APPLICATION',
    startAt: null, endAt: null, relativeRule: 'WAITLIST_INVITE_THEN_ACCOUNT_VERIFICATION',
    displayText: 'Join the waitlist and complete account verification when invited; no public universal deadline is asserted.',
    evidenceId: ev('ev-w8-prolific-verify'),
  }),
]);

export const PROLIFIC_W8_REVIEW_QUEUE: ReviewQueueItem = Object.freeze({
  id: 'rq-w8-prolific-v1',
  offerVersionId: PROLIFIC_W8_VERSION.id,
  reasonCodes: Object.freeze(['FIRST_REAL_SOURCE', 'PROVIDER_LEVEL_PROGRAM', 'PRIVATE_INVENTORY_UNKNOWN']),
  priority: 'HIGH',
  state: 'RESOLVED',
  assignedTo: 'CENTRAL',
  createdAt: PROLIFIC_W8_OBSERVED_AT,
  resolvedAt: PROLIFIC_W8_OBSERVED_AT,
});

export const PROLIFIC_W8_REVIEW_DECISION: ReviewDecisionRecord = Object.freeze({
  id: 'review-w8-prolific-v1',
  reviewQueueId: PROLIFIC_W8_REVIEW_QUEUE.id,
  offerVersionId: PROLIFIC_W8_VERSION.id,
  decision: 'APPROVE',
  reviewerId: 'CENTRAL',
  approvalReason: 'Official public provider evidence supports a provider-level paid-study opportunity, Korea support, minimum age, account verification, and PayPal payout. Individual study inventory, amounts, and selection probability remain NULL/UNKNOWN because no private account inventory was accessed.',
  rejectionReason: null,
  patch: null,
  createdAt: PROLIFIC_W8_OBSERVED_AT,
});

export const PROLIFIC_VERIFIED20_RECORD: Verified20Record = Object.freeze({
  slot: 1,
  realEvidence: true,
  syntheticFixture: false,
  sourcePolicy: PROLIFIC_W8_POLICY,
  sourceGates: PROLIFIC_FINAL_GATES,
  snapshot: PROLIFIC_W8_SNAPSHOT,
  opportunity: PROLIFIC_W8_OPPORTUNITY,
  version: PROLIFIC_W8_VERSION,
  certaintyType: 'CONDITIONAL',
  requirements: PROLIFIC_W8_REQUIREMENTS,
  compensationComponents: PROLIFIC_W8_COMPENSATION,
  windows: PROLIFIC_W8_WINDOWS,
  evidence: PROLIFIC_W8_EVIDENCE,
  reviewQueue: PROLIFIC_W8_REVIEW_QUEUE,
  reviewDecision: PROLIFIC_W8_REVIEW_DECISION,
  criticalEvidenceIds: Object.freeze([
    'ev-w8-prolific-program',
    'ev-w8-prolific-age',
    'ev-w8-prolific-country',
    'ev-w8-prolific-verify',
    'ev-w8-prolific-payout',
  ]),
  lastCheckedAt: PROLIFIC_W8_OBSERVED_AT,
  supplyClaimMode: 'PROVIDER_PROGRAM_ONLY',
});
