import type {
  AcquisitionContext,
  DiscoveryReference,
  DiscoveryResult,
  HealthCheckResult,
  HealthStatus,
  RawFetchResult,
  SnapshotCandidate,
  SourceAdapter,
  SourceAdapterCapabilities,
} from './domain.js';
import { SourceAdapterError } from './domain.js';
import { deterministicContentHash, sanitizeTransportMetadata } from './runtime.js';

const ACQUIRED_AT = '2026-08-30T00:00:00.000Z';

export class FakeSourceAdapter implements SourceAdapter {
  readonly #sourceKey: string;
  #healthStatus: HealthStatus;
  #transportCalls = 0;
  readonly #referenceCalls = new Map<string, number>();

  constructor(sourceKey = 'SRC-CPX', healthStatus: HealthStatus = 'HEALTHY') {
    this.#sourceKey = sourceKey;
    this.#healthStatus = healthStatus;
  }

  sourceKey(): string {
    return this.#sourceKey;
  }

  capabilities(): SourceAdapterCapabilities {
    return Object.freeze({
      sourceKey: this.#sourceKey,
      supportsDiscovery: true,
      supportsList: false,
      supportsDetail: false,
      supportsDirectApiOrFeed: true,
      supportsManualCuratedInput: true,
      requiresAuth: false,
      requiresPartnerCredentials: false,
      transportMode: 'FAKE_OFFLINE',
      expectedContentTypes: Object.freeze(['application/json']),
      rateLimitHint: null,
      idempotencySupport: true,
    });
  }

  get transportCallCount(): number {
    return this.#transportCalls;
  }

  setHealthStatus(status: HealthStatus): void {
    this.#healthStatus = status;
  }

  async discover(context: AcquisitionContext): Promise<DiscoveryResult> {
    this.assertAutomatedAllowed(context);
    this.#transportCalls += 1;
    return Object.freeze({
      sourceKey: this.#sourceKey,
      references: Object.freeze([
        Object.freeze({ referenceId: 'stable-a', requestedUrlOrReference: 'fake://stable-a', providerExternalId: 'A' }),
        Object.freeze({ referenceId: 'changed-b', requestedUrlOrReference: 'fake://changed-b', providerExternalId: 'B' }),
      ]),
    });
  }

  async fetchDirect(request: DiscoveryReference, context: AcquisitionContext): Promise<RawFetchResult> {
    this.assertAutomatedAllowed(context);
    this.#transportCalls += 1;
    const count = (this.#referenceCalls.get(request.referenceId) ?? 0) + 1;
    this.#referenceCalls.set(request.referenceId, count);

    if (request.referenceId === 'transient-then-success' && count === 1) {
      throw new SourceAdapterError('RATE_LIMITED', 'synthetic transient rate limit', true);
    }
    if (request.referenceId === 'permanent-failure') {
      throw new SourceAdapterError('INVALID_CONTENT', 'synthetic permanent failure', false);
    }
    if (request.referenceId === 'unsupported') {
      return this.rawResult(request, 'UNSUPPORTED', null, 'UNSUPPORTED_MODE', 'synthetic unsupported reference', context.attemptNumber);
    }

    const payload = request.referenceId === 'changed-b'
      ? { fixture: 'B', revision: 2, value: 'changed' }
      : { fixture: 'A', revision: 1, value: 'stable' };
    return this.rawResult(request, 'SUCCESS', payload, null, null, context.attemptNumber);
  }

  async normalizeFetchResult(raw: RawFetchResult, context: AcquisitionContext): Promise<SnapshotCandidate> {
    if (raw.sourceKey !== this.#sourceKey || context.source.sourceId !== this.#sourceKey) {
      throw new SourceAdapterError('NORMALIZATION_ERROR', 'source mismatch during normalization');
    }
    if (raw.transportStatus !== 'SUCCESS' && raw.transportStatus !== 'NOT_MODIFIED') {
      throw new SourceAdapterError('NORMALIZATION_ERROR', 'only successful raw results can become snapshot candidates');
    }
    const rawPayload = raw.rawJson ?? raw.rawText ?? raw.rawBytesBase64;
    if (rawPayload === null && raw.rawLocation === null) {
      throw new SourceAdapterError('INVALID_CONTENT', 'synthetic raw result has no content');
    }
    return Object.freeze({
      sourceId: this.#sourceKey,
      endpointId: raw.endpointOrReferenceId,
      acquiredAt: raw.acquiredAt,
      acquisitionModeUsed: context.source.acquisitionMode,
      canonicalUrl: raw.finalUrl ?? raw.requestedUrlOrReference,
      contentType: raw.contentType,
      rawLocation: raw.rawLocation,
      rawPayload,
      contentHash: deterministicContentHash(raw),
      fetchMetadata: sanitizeTransportMetadata(raw.transportMetadata),
      actorProvenance: null,
      httpStatus: raw.httpStatus,
    });
  }

  async healthCheck(_context: AcquisitionContext): Promise<HealthCheckResult> {
    return Object.freeze({
      sourceKey: this.#sourceKey,
      status: this.#healthStatus,
      checkedAt: ACQUIRED_AT,
      message: 'synthetic offline health state',
    });
  }

  private assertAutomatedAllowed(context: AcquisitionContext): void {
    if (context.w1Decision !== 'AUTOMATED_ALLOWED') {
      throw new SourceAdapterError('POLICY_BLOCKED', 'fake transport refused incompatible W1 decision');
    }
  }

  private rawResult(
    request: DiscoveryReference,
    transportStatus: RawFetchResult['transportStatus'],
    rawJson: unknown | null,
    errorCode: RawFetchResult['errorCode'],
    errorMessageSanitized: string | null,
    attemptCount: number,
  ): RawFetchResult {
    return Object.freeze({
      sourceKey: this.#sourceKey,
      endpointOrReferenceId: request.referenceId,
      requestedUrlOrReference: request.requestedUrlOrReference,
      finalUrl: request.requestedUrlOrReference,
      acquiredAt: ACQUIRED_AT,
      transportStatus,
      httpStatus: transportStatus === 'SUCCESS' ? 200 : null,
      contentType: rawJson === null ? null : 'application/json',
      rawText: null,
      rawJson,
      rawBytesBase64: null,
      rawLocation: null,
      providerExternalId: request.providerExternalId,
      transportMetadata: Object.freeze({
        requestId: `transient-${attemptCount}`,
        retryCounter: attemptCount,
        authorization: 'MUST_NOT_PERSIST',
        cookie: 'MUST_NOT_PERSIST',
        nested: { apiKey: 'MUST_NOT_PERSIST', safe: 'kept' },
      }),
      errorCode,
      errorMessageSanitized,
      attemptCount,
      durationMs: 1,
    });
  }
}
