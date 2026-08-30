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

export const CERTAINTY_TYPES = ['GUARANTEED', 'CONDITIONAL', 'DRAW'] as const;
export type CertaintyType = (typeof CERTAINTY_TYPES)[number];

export type SupplyClaimMode = 'PROVIDER_PROGRAM_ONLY' | 'PUBLIC_CURRENT_INVENTORY';

/** Shared trust contract used by W8 and later verified expansion gates. */
export interface VerifiedOpportunityTrustRecord {
  readonly realEvidence: true;
  readonly syntheticFixture: false;
  readonly sourcePolicy: SourcePolicyReview;
  readonly sourceGates: readonly SourceCollectionGate[];
  readonly snapshot: SourceSnapshot;
  readonly opportunity: EarningOpportunity;
  readonly version: OpportunityVersion;
  readonly certaintyType: CertaintyType;
  readonly requirements: readonly OpportunityRequirement[];
  readonly compensationComponents: readonly OpportunityCompensationComponent[];
  readonly windows: readonly OpportunityWindow[];
  readonly evidence: readonly OpportunityEvidence[];
  readonly reviewQueue: ReviewQueueItem;
  readonly reviewDecision: ReviewDecisionRecord;
  readonly criticalEvidenceIds: readonly string[];
  readonly lastCheckedAt: string;
  readonly supplyClaimMode: SupplyClaimMode;
}

export interface Verified20Record extends VerifiedOpportunityTrustRecord {
  readonly slot: number;
}

export interface VerifiedOpportunityValidation {
  readonly countable: boolean;
  readonly errors: readonly string[];
}

export type Verified20Validation = VerifiedOpportunityValidation;

export function validateVerifiedOpportunityTrustRecord(record: VerifiedOpportunityTrustRecord): VerifiedOpportunityValidation {
  const errors: string[] = [];
  if (record.sourcePolicy.decision !== 'PASS' && record.sourcePolicy.decision !== 'PASS_WITH_LIMITS') errors.push('source policy must be explicitly cleared');
  if (record.sourcePolicy.sourceId !== record.snapshot.sourceId) errors.push('source policy must belong to the snapshot source');
  if (record.sourceGates.some((gate) => gate.sourceId !== record.snapshot.sourceId)) errors.push('all source gates must belong to the snapshot source');
  if (record.sourceGates.some((gate) => gate.required && gate.status !== 'PASS' && gate.status !== 'WAIVED')) errors.push('all required source gates must be PASS or WAIVED');
  if (record.snapshot.sourceId !== record.opportunity.sourceId) errors.push('snapshot/opportunity source mismatch');
  if (record.version.offerId !== record.opportunity.id) errors.push('version must belong to opportunity');
  if (record.version.sourceSnapshotId !== record.snapshot.id) errors.push('version must bind the real source snapshot');
  if (record.version.verificationState !== 'VERIFIED') errors.push('version must be human-reviewed VERIFIED');
  if (record.opportunity.currentVersionId !== record.version.id) errors.push('opportunity current version must be the verified version');
  if (record.reviewQueue.offerVersionId !== record.version.id || record.reviewQueue.state !== 'RESOLVED') errors.push('review queue must be resolved for the verified version');
  if (record.reviewDecision.reviewQueueId !== record.reviewQueue.id || record.reviewDecision.offerVersionId !== record.version.id || record.reviewDecision.decision === 'REJECT') errors.push('accepted review decision must bind the resolved queue and verified version');
  if (record.evidence.length === 0) errors.push('field-level evidence is required');
  if (record.criticalEvidenceIds.length === 0) errors.push('critical evidence list is required');
  for (const id of record.criticalEvidenceIds) {
    if (!record.evidence.some((item) => item.id === id)) errors.push(`missing critical evidence: ${id}`);
  }
  if (Number.isNaN(Date.parse(record.lastCheckedAt))) errors.push('lastCheckedAt must be an ISO-like timestamp');
  if (record.supplyClaimMode === 'PROVIDER_PROGRAM_ONLY' && record.version.supplyAvailabilityState === 'AVAILABLE') {
    errors.push('provider-level evidence must not fabricate current inventory');
  }
  if (record.version.supplyAvailabilityState === 'PUBLIC_JOB_POSTING_AVAILABLE') {
    errors.push('general job postings belong to external job-search assist, not verified core supply');
  }
  if (record.realEvidence !== true || record.syntheticFixture !== false) errors.push('synthetic fixtures never count toward verified opportunity gates');
  return Object.freeze({ countable: errors.length === 0, errors: Object.freeze(errors) });
}

export function validateVerified20Record(record: Verified20Record): Verified20Validation {
  const core = validateVerifiedOpportunityTrustRecord(record);
  const errors = [...core.errors];
  if (!Number.isInteger(record.slot) || record.slot < 1 || record.slot > 20) errors.unshift('slot must be an integer from 1 to 20');
  return Object.freeze({ countable: errors.length === 0, errors: Object.freeze(errors) });
}

export function verified20Progress(records: readonly Verified20Record[]) {
  const validations = records.map((record) => validateVerified20Record(record));
  const seenSlots = new Set<number>();
  const seenOpportunityIds = new Set<string>();
  let count = 0;

  records.forEach((record, index) => {
    const validation = validations[index];
    if (!validation?.countable) return;
    if (seenSlots.has(record.slot) || seenOpportunityIds.has(record.opportunity.id)) return;
    seenSlots.add(record.slot);
    seenOpportunityIds.add(record.opportunity.id);
    count += 1;
  });

  const expectedSlotsPresent = count === 20 && Array.from({ length: 20 }, (_, index) => index + 1).every((slot) => seenSlots.has(slot));
  return Object.freeze({
    verifiedCount: count,
    targetCount: 20,
    remainingCount: 20 - count,
    gatePassed: count === 20 && expectedSlotsPresent,
    duplicateSlotDetected: new Set(records.map((record) => record.slot)).size !== records.length,
    duplicateOpportunityDetected: new Set(records.map((record) => record.opportunity.id)).size !== records.length,
    validations: Object.freeze(validations),
  });
}
