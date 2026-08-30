import type {
  EarningOpportunity,
  OpportunityChange,
  OpportunityEvidence,
  OpportunityVersion,
  ReviewDecisionRecord,
  ReviewQueueItem,
  SourceSnapshot,
} from '../persistence/domain.js';
import type {
  Source,
  SourceCollectionGate,
  SourcePolicyReview,
} from '../source-policy/domain.js';

export type AdminRole = 'ADMIN' | 'REVIEWER' | 'OPERATOR' | 'VIEWER';
export type AdminRoute =
  | 'DASHBOARD'
  | 'SOURCES'
  | 'OPPORTUNITIES'
  | 'REVIEW_QUEUE'
  | 'OPPORTUNITY_REVIEW'
  | 'CHANGES'
  | 'STALE_BROKEN'
  | 'AUDIT_LOG';

export type AdminReviewAction = 'APPROVE' | 'MODIFY_APPROVE' | 'REJECT' | 'RE_EXTRACT';
export type AdminHealthAction = 'RECHECK_NOW' | 'SUPPRESS_OFFER' | 'END_OFFER' | 'RETURN_TO_REVIEW' | 'MARK_SOURCE_INCIDENT';
export type StaleBrokenCause =
  | 'EXPECTED_SOURCE_CHECK_MISSED'
  | 'SOURCE_PAGE_UNAVAILABLE'
  | 'DESTINATION_BROKEN'
  | 'OFFER_DISAPPEARED'
  | 'CONFLICTING_TERMS'
  | 'LOGIN_ONLY_TERMS_UNVERIFIABLE';

export interface AdminAuditRecord {
  readonly id: string;
  readonly actorId: string;
  readonly actorRole: AdminRole;
  readonly action: string;
  readonly targetType: 'SOURCE' | 'OPPORTUNITY' | 'OPPORTUNITY_VERSION' | 'REVIEW_QUEUE' | 'STALE_BROKEN';
  readonly targetId: string;
  readonly beforeRef: string | null;
  readonly afterRef: string | null;
  readonly reason: string;
  readonly createdAt: string;
  readonly modelId: string | null;
  readonly promptVersion: string | null;
  readonly sourceSnapshotHash: string | null;
}

export interface ReviewPatchRecord {
  readonly id: string;
  readonly reviewQueueId: string;
  readonly fromVersionId: string;
  readonly resultingVersionId: string;
  readonly reviewerId: string;
  readonly patch: Readonly<Record<string, unknown>>;
  readonly reason: string;
  readonly createdAt: string;
}

export interface ReextractRequest {
  readonly id: string;
  readonly reviewQueueId: string;
  readonly offerVersionId: string;
  readonly requestedBy: string;
  readonly reason: string;
  readonly sourceSnapshotId: string;
  readonly createdAt: string;
}

export interface StaleBrokenRecord {
  readonly id: string;
  readonly sourceId: string;
  readonly offerId: string | null;
  readonly cause: StaleBrokenCause;
  readonly detail: string;
  readonly detectedAt: string;
  readonly state: 'OPEN' | 'RECHECK_REQUESTED' | 'SOURCE_INCIDENT' | 'RESOLVED';
}

export interface AdminConsoleState {
  readonly sources: readonly Source[];
  readonly policies: readonly SourcePolicyReview[];
  readonly gates: readonly SourceCollectionGate[];
  readonly snapshots: readonly SourceSnapshot[];
  readonly opportunities: readonly EarningOpportunity[];
  readonly versions: readonly OpportunityVersion[];
  readonly evidence: readonly OpportunityEvidence[];
  readonly reviewQueue: readonly ReviewQueueItem[];
  readonly changes: readonly OpportunityChange[];
  readonly reviewDecisions: readonly ReviewDecisionRecord[];
  readonly reviewPatches: readonly ReviewPatchRecord[];
  readonly reextractRequests: readonly ReextractRequest[];
  readonly staleBroken: readonly StaleBrokenRecord[];
  readonly auditLog: readonly AdminAuditRecord[];
}

export interface ReviewCommand {
  readonly action: AdminReviewAction;
  readonly role: AdminRole;
  readonly actorId: string;
  readonly reviewQueueId: string;
  readonly decisionId: string;
  readonly auditId: string;
  readonly reason: string;
  readonly at: string;
  readonly patchId?: string;
  readonly patch?: Readonly<Record<string, unknown>>;
  readonly resultingVersionId?: string;
  readonly reextractRequestId?: string;
}

export interface HealthCommand {
  readonly action: AdminHealthAction;
  readonly role: AdminRole;
  readonly actorId: string;
  readonly incidentId: string;
  readonly auditId: string;
  readonly reason: string;
  readonly at: string;
  readonly reviewQueueId?: string;
}

export const TRUST_STATUS_LABELS = Object.freeze([
  'SOURCE POLICY PASS',
  'DATA VERIFIED',
  'HUMAN REVIEWED',
  'LIVE',
  'PARTNER APPROVED',
] as const);
