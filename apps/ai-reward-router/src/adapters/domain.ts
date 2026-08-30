import type {
  AcquisitionAttempt,
  AcquisitionMode,
  EffectiveAcquisitionDecision,
  Source,
} from '../source-policy/domain.js';
import type { SourceSnapshot } from '../persistence/domain.js';

export type AdapterOperation = 'DISCOVER' | 'LIST' | 'DETAIL' | 'DIRECT' | 'MANUAL_CURATED' | 'HEALTH';
export type TransportStatus =
  | 'SUCCESS'
  | 'NOT_MODIFIED'
  | 'RETRYABLE_ERROR'
  | 'PERMANENT_ERROR'
  | 'UNSUPPORTED'
  | 'BLOCKED';
export type HealthStatus = 'HEALTHY' | 'DEGRADED' | 'UNAVAILABLE' | 'BLOCKED' | 'NOT_CONFIGURED' | 'UNSUPPORTED';

export const ADAPTER_ERROR_CODES = [
  'POLICY_BLOCKED',
  'UNSUPPORTED_MODE',
  'CONFIG_MISSING',
  'AUTH_REQUIRED',
  'AUTH_FAILED',
  'RATE_LIMITED',
  'TIMEOUT',
  'NETWORK_ERROR',
  'HTTP_ERROR',
  'INVALID_CONTENT',
  'NORMALIZATION_ERROR',
  'SNAPSHOT_PERSIST_ERROR',
  'UNKNOWN_TRANSPORT_ERROR',
] as const;
export type AdapterErrorCode = (typeof ADAPTER_ERROR_CODES)[number];

export interface SourceAdapterCapabilities {
  readonly sourceKey: string;
  readonly supportsDiscovery: boolean;
  readonly supportsList: boolean;
  readonly supportsDetail: boolean;
  readonly supportsDirectApiOrFeed: boolean;
  readonly supportsManualCuratedInput: boolean;
  readonly requiresAuth: boolean;
  readonly requiresPartnerCredentials: boolean;
  readonly transportMode: string;
  readonly expectedContentTypes: readonly string[];
  readonly rateLimitHint: string | null;
  readonly idempotencySupport: boolean | null;
}

export interface AcquisitionContext {
  readonly source: Source;
  readonly intendedAttempt: AcquisitionAttempt;
  readonly w1Decision: EffectiveAcquisitionDecision;
  readonly operation: AdapterOperation;
  readonly endpointId: string | null;
  readonly runId: string;
  readonly attemptNumber: number;
  readonly timeoutMs: number;
  /** Names/handles only. Secret values must never be put here. */
  readonly secretReferenceHandles: readonly string[];
}

export interface DiscoveryReference {
  readonly referenceId: string;
  readonly requestedUrlOrReference: string | null;
  readonly providerExternalId: string | null;
}

export interface DiscoveryResult {
  readonly sourceKey: string;
  readonly references: readonly DiscoveryReference[];
}

export interface RawFetchResult {
  readonly sourceKey: string;
  readonly endpointOrReferenceId: string | null;
  readonly requestedUrlOrReference: string | null;
  readonly finalUrl: string | null;
  readonly acquiredAt: string;
  readonly transportStatus: TransportStatus;
  readonly httpStatus: number | null;
  readonly contentType: string | null;
  readonly rawText: string | null;
  readonly rawJson: unknown | null;
  readonly rawBytesBase64: string | null;
  readonly rawLocation: string | null;
  readonly providerExternalId: string | null;
  readonly transportMetadata: Readonly<Record<string, unknown>>;
  readonly errorCode: AdapterErrorCode | null;
  readonly errorMessageSanitized: string | null;
  readonly attemptCount: number;
  readonly durationMs: number | null;
}

export type SnapshotCandidate = Omit<SourceSnapshot, 'id'>;

export interface HealthCheckResult {
  readonly sourceKey: string;
  readonly status: HealthStatus;
  readonly checkedAt: string;
  readonly message: string | null;
}

export interface SourceAdapter {
  sourceKey(): string;
  capabilities(): SourceAdapterCapabilities;
  discover(context: AcquisitionContext): Promise<DiscoveryResult>;
  fetchList?(request: DiscoveryReference, context: AcquisitionContext): Promise<RawFetchResult>;
  fetchDetail?(request: DiscoveryReference, context: AcquisitionContext): Promise<RawFetchResult>;
  fetchDirect?(request: DiscoveryReference, context: AcquisitionContext): Promise<RawFetchResult>;
  normalizeFetchResult(raw: RawFetchResult, context: AcquisitionContext): Promise<SnapshotCandidate>;
  healthCheck(context: AcquisitionContext): Promise<HealthCheckResult>;
}

export class SourceAdapterError extends Error {
  readonly code: AdapterErrorCode;
  readonly retryable: boolean;

  constructor(code: AdapterErrorCode, messageSanitized: string, retryable = false) {
    super(messageSanitized);
    this.name = 'SourceAdapterError';
    this.code = code;
    this.retryable = retryable;
  }
}

export interface SnapshotAppendResult {
  readonly created: boolean;
  readonly snapshot: SourceSnapshot;
}

export interface SnapshotRepository {
  findEquivalentSnapshot(candidate: SnapshotCandidate): Promise<SourceSnapshot | null>;
  appendSnapshot(candidate: SnapshotCandidate): Promise<SourceSnapshot>;
}

export interface AcquisitionRunResult {
  readonly runId: string;
  readonly sourceKey: string;
  readonly decision: EffectiveAcquisitionDecision;
  readonly status: 'PERSISTED' | 'DUPLICATE' | 'BLOCKED' | 'UNSUPPORTED' | 'FAILED';
  readonly attempts: number;
  readonly snapshot: SourceSnapshot | null;
  readonly errorCode: AdapterErrorCode | null;
  readonly errorMessageSanitized: string | null;
}

export interface ManualCuratedInput {
  readonly sourceId: string;
  readonly canonicalUrlOrReference: string | null;
  readonly contentType: string | null;
  readonly rawText: string | null;
  readonly rawJson: unknown | null;
  readonly rawLocation: string | null;
  readonly acquiredAt: string;
  readonly actorProvenance: Readonly<Record<string, unknown>>;
}

export interface PartnerAdapterConfig {
  readonly sourceKey: string;
  readonly accountOrAppIdReference: string | null;
  readonly approvedApiBaseUrl: string | null;
  readonly secretReferenceNames: readonly string[];
  readonly callbackConfigurationReference: string | null;
}

export interface AdapterPolicyInput {
  readonly source: Source;
  readonly acquisitionMode: AcquisitionMode;
  readonly intendedAttempt: AcquisitionAttempt;
}
