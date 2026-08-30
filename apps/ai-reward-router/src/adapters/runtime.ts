import { createHash } from 'node:crypto';
import { effectiveAcquisitionDecision } from '../source-policy/decision.js';
import type { EffectiveAcquisitionInput } from '../source-policy/domain.js';
import type { SourceSnapshot } from '../persistence/domain.js';
import type {
  AcquisitionContext,
  AcquisitionRunResult,
  AdapterErrorCode,
  DiscoveryReference,
  DiscoveryResult,
  ManualCuratedInput,
  RawFetchResult,
  SnapshotCandidate,
  SnapshotRepository,
  SourceAdapter,
} from './domain.js';
import { SourceAdapterError } from './domain.js';

const SECRET_KEY_PATTERN = /(authorization|cookie|token|secret|password|api[-_]?key|credential)/i;

function sanitizeValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sanitizeValue);
  if (value !== null && typeof value === 'object') {
    const output: Record<string, unknown> = {};
    for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
      if (SECRET_KEY_PATTERN.test(key)) continue;
      output[key] = sanitizeValue(child);
    }
    return output;
  }
  return value;
}

export function sanitizeTransportMetadata(metadata: Readonly<Record<string, unknown>>): Readonly<Record<string, unknown>> {
  return Object.freeze(sanitizeValue(metadata) as Record<string, unknown>);
}

function canonicalize(value: unknown): string {
  if (value === null) return 'null';
  if (typeof value === 'string') return JSON.stringify(value);
  if (typeof value === 'number' || typeof value === 'boolean') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalize).join(',')}]`;
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, child]) => `${JSON.stringify(key)}:${canonicalize(child)}`);
    return `{${entries.join(',')}}`;
  }
  return JSON.stringify(String(value));
}

export function canonicalRawContent(raw: RawFetchResult): string {
  if (raw.rawJson !== null) return canonicalize(raw.rawJson);
  if (raw.rawText !== null) return raw.rawText;
  if (raw.rawBytesBase64 !== null) return raw.rawBytesBase64;
  if (raw.rawLocation !== null) return raw.rawLocation;
  throw new SourceAdapterError('INVALID_CONTENT', 'raw acquisition result contains no source content');
}

export function deterministicContentHash(raw: RawFetchResult): string {
  return createHash('sha256').update(canonicalRawContent(raw), 'utf8').digest('hex');
}

function candidateDedupKey(candidate: SnapshotCandidate): string {
  return `${candidate.sourceId}\u0000${candidate.canonicalUrl ?? ''}\u0000${candidate.contentHash}`;
}

export class InMemorySnapshotRepository implements SnapshotRepository {
  readonly #snapshots: SourceSnapshot[] = [];

  async findEquivalentSnapshot(candidate: SnapshotCandidate): Promise<SourceSnapshot | null> {
    const key = candidateDedupKey(candidate);
    return this.#snapshots.find((snapshot) =>
      `${snapshot.sourceId}\u0000${snapshot.canonicalUrl ?? ''}\u0000${snapshot.contentHash}` === key,
    ) ?? null;
  }

  async appendSnapshot(candidate: SnapshotCandidate): Promise<SourceSnapshot> {
    const snapshot: SourceSnapshot = Object.freeze({
      ...candidate,
      id: `snapshot-${this.#snapshots.length + 1}`,
    });
    this.#snapshots.push(snapshot);
    return snapshot;
  }

  all(): readonly SourceSnapshot[] {
    return Object.freeze([...this.#snapshots]);
  }
}

async function persistCandidate(repository: SnapshotRepository, candidate: SnapshotCandidate) {
  const existing = await repository.findEquivalentSnapshot(candidate);
  if (existing) return { created: false, snapshot: existing } as const;
  return { created: true, snapshot: await repository.appendSnapshot(candidate) } as const;
}

function contextFor(
  input: EffectiveAcquisitionInput,
  decision: ReturnType<typeof effectiveAcquisitionDecision>,
  operation: AcquisitionContext['operation'],
  runId: string,
  attemptNumber: number,
  timeoutMs: number,
): AcquisitionContext {
  return Object.freeze({
    source: input.source,
    intendedAttempt: input.attempt,
    w1Decision: decision,
    operation,
    endpointId: null,
    runId,
    attemptNumber,
    timeoutMs,
    secretReferenceHandles: Object.freeze([]),
  });
}

function failureResult(
  runId: string,
  sourceKey: string,
  decision: ReturnType<typeof effectiveAcquisitionDecision>,
  status: AcquisitionRunResult['status'],
  attempts: number,
  errorCode: AdapterErrorCode,
  message: string,
): AcquisitionRunResult {
  return Object.freeze({
    runId,
    sourceKey,
    decision,
    status,
    attempts,
    snapshot: null,
    errorCode,
    errorMessageSanitized: message,
  });
}

export async function runDiscovery(
  adapter: SourceAdapter,
  policyInput: EffectiveAcquisitionInput,
  runId: string,
  timeoutMs = 5_000,
): Promise<DiscoveryResult | AcquisitionRunResult> {
  const decision = effectiveAcquisitionDecision(policyInput);
  if (adapter.sourceKey() !== policyInput.source.sourceId) {
    return failureResult(runId, adapter.sourceKey(), decision, 'FAILED', 0, 'CONFIG_MISSING', 'adapter source key does not match policy source');
  }
  if (decision !== 'AUTOMATED_ALLOWED') {
    return failureResult(runId, adapter.sourceKey(), decision, 'BLOCKED', 0, 'POLICY_BLOCKED', 'W1 decision does not authorize automated discovery');
  }
  if (!adapter.capabilities().supportsDiscovery) {
    return failureResult(runId, adapter.sourceKey(), decision, 'UNSUPPORTED', 0, 'UNSUPPORTED_MODE', 'adapter does not support discovery');
  }
  return adapter.discover(contextFor(policyInput, decision, 'DISCOVER', runId, 1, timeoutMs));
}

export async function runAutomatedDirect(
  adapter: SourceAdapter,
  request: DiscoveryReference,
  policyInput: EffectiveAcquisitionInput,
  repository: SnapshotRepository,
  options: { readonly runId: string; readonly maxAttempts?: number; readonly timeoutMs?: number },
): Promise<AcquisitionRunResult> {
  const decision = effectiveAcquisitionDecision(policyInput);
  const maxAttempts = Math.max(1, Math.min(options.maxAttempts ?? 3, 5));
  const timeoutMs = options.timeoutMs ?? 5_000;

  if (adapter.sourceKey() !== policyInput.source.sourceId) {
    return failureResult(options.runId, adapter.sourceKey(), decision, 'FAILED', 0, 'CONFIG_MISSING', 'adapter source key does not match policy source');
  }
  if (decision !== 'AUTOMATED_ALLOWED') {
    return failureResult(options.runId, adapter.sourceKey(), decision, 'BLOCKED', 0, 'POLICY_BLOCKED', 'W1 decision does not authorize automated transport');
  }
  if (!adapter.capabilities().supportsDirectApiOrFeed || !adapter.fetchDirect) {
    return failureResult(options.runId, adapter.sourceKey(), decision, 'UNSUPPORTED', 0, 'UNSUPPORTED_MODE', 'adapter does not support direct acquisition');
  }

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const context = contextFor(policyInput, decision, 'DIRECT', options.runId, attempt, timeoutMs);
    try {
      const raw = await adapter.fetchDirect(request, context);
      if (raw.transportStatus === 'RETRYABLE_ERROR') {
        if (attempt < maxAttempts) continue;
        return failureResult(options.runId, adapter.sourceKey(), decision, 'FAILED', attempt, raw.errorCode ?? 'UNKNOWN_TRANSPORT_ERROR', raw.errorMessageSanitized ?? 'retryable transport error exhausted');
      }
      if (raw.transportStatus !== 'SUCCESS' && raw.transportStatus !== 'NOT_MODIFIED') {
        return failureResult(options.runId, adapter.sourceKey(), decision, raw.transportStatus === 'UNSUPPORTED' ? 'UNSUPPORTED' : 'FAILED', attempt, raw.errorCode ?? 'UNKNOWN_TRANSPORT_ERROR', raw.errorMessageSanitized ?? 'transport failed');
      }

      const candidate = await adapter.normalizeFetchResult(raw, context);
      const persisted = await persistCandidate(repository, candidate);
      return Object.freeze({
        runId: options.runId,
        sourceKey: adapter.sourceKey(),
        decision,
        status: persisted.created ? 'PERSISTED' : 'DUPLICATE',
        attempts: attempt,
        snapshot: persisted.snapshot,
        errorCode: null,
        errorMessageSanitized: null,
      });
    } catch (error) {
      const typed = error instanceof SourceAdapterError
        ? error
        : new SourceAdapterError('UNKNOWN_TRANSPORT_ERROR', 'unknown transport error');
      if (typed.retryable && attempt < maxAttempts) continue;
      return failureResult(options.runId, adapter.sourceKey(), decision, 'FAILED', attempt, typed.code, typed.message);
    }
  }

  return failureResult(options.runId, adapter.sourceKey(), decision, 'FAILED', maxAttempts, 'UNKNOWN_TRANSPORT_ERROR', 'bounded retry loop exhausted');
}

export async function ingestManualCurated(
  adapter: SourceAdapter,
  input: ManualCuratedInput,
  policyInput: EffectiveAcquisitionInput,
  repository: SnapshotRepository,
  runId: string,
): Promise<AcquisitionRunResult> {
  const decision = effectiveAcquisitionDecision(policyInput);
  if (adapter.sourceKey() !== input.sourceId || adapter.sourceKey() !== policyInput.source.sourceId) {
    return failureResult(runId, adapter.sourceKey(), decision, 'FAILED', 0, 'CONFIG_MISSING', 'manual input source does not match adapter/policy source');
  }
  if (decision !== 'MANUAL_ONLY' || !adapter.capabilities().supportsManualCuratedInput) {
    return failureResult(runId, adapter.sourceKey(), decision, 'BLOCKED', 0, 'POLICY_BLOCKED', 'W1 decision does not authorize manual curated input');
  }

  const context = contextFor(policyInput, decision, 'MANUAL_CURATED', runId, 0, 0);
  const raw: RawFetchResult = Object.freeze({
    sourceKey: input.sourceId,
    endpointOrReferenceId: null,
    requestedUrlOrReference: input.canonicalUrlOrReference,
    finalUrl: input.canonicalUrlOrReference,
    acquiredAt: input.acquiredAt,
    transportStatus: 'SUCCESS',
    httpStatus: null,
    contentType: input.contentType,
    rawText: input.rawText,
    rawJson: input.rawJson,
    rawBytesBase64: null,
    rawLocation: input.rawLocation,
    providerExternalId: null,
    transportMetadata: Object.freeze({ manualCurated: true }),
    errorCode: null,
    errorMessageSanitized: null,
    attemptCount: 0,
    durationMs: null,
  });
  const normalized = await adapter.normalizeFetchResult(raw, context);
  const candidate: SnapshotCandidate = Object.freeze({
    ...normalized,
    actorProvenance: sanitizeTransportMetadata(input.actorProvenance),
  });
  const persisted = await persistCandidate(repository, candidate);
  return Object.freeze({
    runId,
    sourceKey: adapter.sourceKey(),
    decision,
    status: persisted.created ? 'PERSISTED' : 'DUPLICATE',
    attempts: 0,
    snapshot: persisted.snapshot,
    errorCode: null,
    errorMessageSanitized: null,
  });
}
