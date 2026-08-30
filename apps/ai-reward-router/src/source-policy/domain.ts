export const ACQUISITION_MODES = {
  PARTNER_API: 'PARTNER_API',
  PARTNER_FEED: 'PARTNER_FEED',
  PARTNER_WIDGET_SDK: 'PARTNER_WIDGET_SDK',
  PUBLIC_WEB_ALLOWED: 'PUBLIC_WEB_ALLOWED',
  MANUAL_CURATED_OFFICIAL_SOURCE: 'MANUAL_CURATED_OFFICIAL_SOURCE',
  DEEP_LINK_OR_DIRECTORY: 'DEEP_LINK_OR_DIRECTORY',
  USER_SUBMITTED_DISCOVERY: 'USER_SUBMITTED_DISCOVERY',
  SHADOW_ONLY: 'SHADOW_ONLY',
  DIRECT_B2B_FUTURE: 'DIRECT_B2B_FUTURE',
} as const;

export type AcquisitionMode = (typeof ACQUISITION_MODES)[keyof typeof ACQUISITION_MODES];
export type SourceLane = 'BUILD' | 'SHADOW_ONLY' | 'NEGOTIATE' | 'INVENTORY_TEST' | 'HOLD' | 'REJECT';
export type VerificationState =
  | 'DISCOVERED'
  | 'RESEARCH_SUPPORTED'
  | 'LIVE_VERIFIED'
  | 'PARTNERSHIP_REQUIRED'
  | 'POLICY_BLOCKED'
  | 'REJECTED';
export type RiskTier = 'LOW' | 'MEDIUM' | 'HIGH';
export type MonetizationRole = 'TRAFFIC' | 'REVENUE' | 'BOTH' | 'NONE';
export type PolicyDecision = 'PENDING' | 'PASS' | 'PASS_WITH_LIMITS' | 'BLOCK';
export type GateStatus = 'NOT_STARTED' | 'IN_PROGRESS' | 'PASS' | 'FAIL' | 'WAIVED';
export type GateFailureAction = 'BLOCK' | 'SHADOW';
export type PermissionFact = 'UNKNOWN' | 'ALLOWED' | 'LIMITED' | 'BLOCKED';
export type AcquisitionAttempt = 'AUTOMATED' | 'MANUAL_CURATED' | 'DIRECTORY' | 'SHADOW';
export type EffectiveAcquisitionDecision = 'BLOCK' | 'MANUAL_ONLY' | 'SHADOW_ONLY' | 'AUTOMATED_ALLOWED';

export interface Source {
  readonly sourceId: string;
  readonly sourceName: string;
  readonly sourceType: string;
  readonly lane: SourceLane;
  readonly launchPriority: 'P0' | 'P1' | 'P2';
  readonly country: string;
  readonly accessMode: string;
  readonly loginRequired: boolean;
  readonly jsRendered: boolean | 'UNKNOWN';
  readonly monetizationRole: MonetizationRole;
  readonly verificationState: VerificationState;
  readonly riskTier: RiskTier;
  readonly updateCadence: string;
  readonly officialBaseUrl: string | null;
  readonly listUrl: string | null;
  readonly nextAction: string | null;
  readonly notes: string | null;
  readonly acquisitionMode: AcquisitionMode;
  /** Provider-level metadata only; never a verified opportunity classification. */
  readonly opportunityClassHint: readonly string[];
}

export interface SourceEndpoint {
  readonly endpointId: string;
  readonly sourceId: string;
  readonly endpointKind: string;
  readonly url: string | null;
  readonly requiresAuth: boolean | 'UNKNOWN';
  readonly renderMode: string;
  readonly intendedBehavior: string;
  readonly enabled: boolean;
  readonly evidenceNotes: string | null;
}

export interface SourcePolicyReview {
  readonly sourceId: string;
  readonly robotsStatus: string;
  readonly termsStatus: string;
  readonly commercialReuse: PermissionFact;
  readonly textReuse: PermissionFact;
  readonly imageLogoReuse: PermissionFact;
  readonly automationPermission: PermissionFact;
  readonly affiliateIncentive: PermissionFact;
  readonly policyEvidenceUrl: string | null;
  readonly reviewedAt: string | null;
  readonly reviewer: string | null;
  readonly decision: PolicyDecision;
  readonly notes: string | null;
}

export interface SourceCollectionGate {
  readonly gateId: string;
  readonly sourceId: string;
  readonly gate: string;
  readonly required: boolean;
  readonly status: GateStatus;
  readonly failureAction: GateFailureAction;
  readonly evidence: string | null;
  readonly notes: string | null;
}

export interface EffectiveAcquisitionInput {
  readonly source: Source;
  readonly policy: SourcePolicyReview;
  readonly gates: readonly SourceCollectionGate[];
  readonly attempt: AcquisitionAttempt;
  readonly credentialsAvailable?: boolean;
  readonly limitsSatisfied?: boolean;
}
