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

export interface Verified20Record {
  readonly slot: number;
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

export interface Verified20Validation {
  readonly countable: boolean;
  readonly errors: readonly string[];
}

export function validateVerified20Record(record: Verified20Record): Verified20Validation {
  const errors: string[] = [];
  if (!Number.isInteger(record.slot) || record.slot < 1 || record.slot > 20) errors.push('slot must be an integer from 1 to 20');
  if (record.sourcePolicy.decision !== 'PASS' && record.sourcePolicy.decision !== 'PASS_WITH_LIMITS') errors.push('source policy must be explicitly cleared');
  if (record.snapshot.sourceId !== record.opportunity.sourceId) errors.push('snapshot/opportunity source mismatch');
  if (record.version.offerId !== record.opportunity.id) errors.push('version must belong to opportunity');
  if (record.version.sourceSnapshotId !== record.snapshot.id) errors.push('version must bind the real source snapshot');
  if (record.version.verificationState !== 'VERIFIED') errors.push('version must be human-reviewed VERIFIED');
  if (record.opportunity.currentVersionId !== record.version.id) errors.push('opportunity current version must be the verified version');
  if (record.reviewQueue.offerVersionId !== record.version.id || record.reviewQueue.state !== 'RESOLVED') errors.push('review queue must be resolved for the verified version');
  if (record.reviewDecision.offerVersionId !== record.version.id || record.reviewDecision.decision === 'REJECT') errors.push('accepted review decision is required');
  if (record.evidence.length === 0) errors.push('field-level evidence is required');
  if (record.criticalEvidenceIds.length === 0) errors.push('critical evidence list is required');
  for (const id of record.criticalEvidenceIds) {
    if (!record.evidence.some((item) => item.id === id)) errors.push(`missing critical evidence: ${id}`);
  }
  if (Number.isNaN(Date.parse(record.lastCheckedAt))) errors.push('lastCheckedAt must be an ISO-like timestamp');
  if (record.supplyClaimMode === 'PROVIDER_PROGRAM_ONLY' && record.version.supplyAvailabilityState === 'AVAILABLE') {
    errors.push('provider-level evidence must not fabricate current inventory');
  }
  if (record.realEvidence !== true || record.syntheticFixture !== false) errors.push('synthetic fixtures never count toward VERIFIED 20');
  return Object.freeze({ countable: errors.length === 0, errors: Object.freeze(errors) });
}

export function verified20Progress(records: readonly Verified20Record[]) {
  const validations = records.map((record) => validateVerified20Record(record));
  const count = validations.filter((item) => item.countable).length;
  return Object.freeze({
    verifiedCount: count,
    targetCount: 20,
    remainingCount: 20 - count,
    gatePassed: count === 20,
    validations: Object.freeze(validations),
  });
}
