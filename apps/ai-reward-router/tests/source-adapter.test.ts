import test from 'node:test';
import assert from 'node:assert/strict';
import type { AcquisitionContext } from '../src/adapters/domain.js';
import { FakeSourceAdapter } from '../src/adapters/fake-source-adapter.js';
import {
  InMemorySnapshotRepository,
  deterministicContentHash,
  ingestManualCurated,
  runAutomatedDirect,
  runDiscovery,
} from '../src/adapters/runtime.js';
import type { EffectiveAcquisitionInput } from '../src/source-policy/domain.js';
import {
  gatesBySourceId,
  policyBySourceId,
  sourceById,
} from '../src/source-policy/registry.js';

function allowedAutomatedInput(sourceId = 'SRC-CPX'): EffectiveAcquisitionInput {
  const source = sourceById(sourceId);
  return {
    source,
    policy: {
      ...policyBySourceId(sourceId),
      decision: 'PASS',
      automationPermission: 'ALLOWED',
    },
    gates: gatesBySourceId(sourceId).map((gate) => ({ ...gate, status: 'PASS' as const })),
    attempt: 'AUTOMATED',
    credentialsAvailable: true,
    limitsSatisfied: true,
  };
}

function blockedAutomatedInput(sourceId = 'SRC-CPX'): EffectiveAcquisitionInput {
  return {
    source: sourceById(sourceId),
    policy: policyBySourceId(sourceId),
    gates: gatesBySourceId(sourceId),
    attempt: 'AUTOMATED',
    credentialsAvailable: false,
  };
}

const ref = (referenceId: string) => ({
  referenceId,
  requestedUrlOrReference: `fake://${referenceId}`,
  providerExternalId: referenceId,
});

test('fake adapter satisfies discovery contract with two stable references', async () => {
  const adapter = new FakeSourceAdapter('SRC-CPX');
  const result = await runDiscovery(adapter, allowedAutomatedInput(), 'run-discovery');
  assert.equal('references' in result, true);
  if (!('references' in result)) return;
  assert.deepEqual(result.references.map((item) => item.referenceId), ['stable-a', 'changed-b']);
  assert.equal(adapter.transportCallCount, 1);
});

test('W1 BLOCK prevents transport invocation even when adapter capability is true', async () => {
  const adapter = new FakeSourceAdapter('SRC-CPX');
  assert.equal(adapter.capabilities().supportsDirectApiOrFeed, true);
  const result = await runAutomatedDirect(
    adapter,
    ref('stable-a'),
    blockedAutomatedInput(),
    new InMemorySnapshotRepository(),
    { runId: 'run-blocked' },
  );
  assert.equal(result.status, 'BLOCKED');
  assert.equal(result.errorCode, 'POLICY_BLOCKED');
  assert.equal(result.attempts, 0);
  assert.equal(adapter.transportCallCount, 0);
});

test('MANUAL_ONLY accepts explicit curated input with zero automated transport calls', async () => {
  const sourceId = 'SRC-TOSS';
  const adapter = new FakeSourceAdapter(sourceId);
  const policyInput: EffectiveAcquisitionInput = {
    source: sourceById(sourceId),
    policy: policyBySourceId(sourceId),
    gates: gatesBySourceId(sourceId),
    attempt: 'MANUAL_CURATED',
  };
  const repository = new InMemorySnapshotRepository();
  const result = await ingestManualCurated(adapter, {
    sourceId,
    canonicalUrlOrReference: 'https://example.invalid/manual-fixture',
    contentType: 'application/json',
    rawText: null,
    rawJson: { fixture: 'manual', synthetic: true },
    rawLocation: null,
    acquiredAt: '2026-08-30T00:00:00.000Z',
    actorProvenance: { actor: 'CENTRAL_FIXTURE', secretToken: 'MUST_NOT_PERSIST' },
  }, policyInput, repository, 'run-manual');
  assert.equal(result.decision, 'MANUAL_ONLY');
  assert.equal(result.status, 'PERSISTED');
  assert.equal(result.attempts, 0);
  assert.equal(adapter.transportCallCount, 0);
  assert.equal(JSON.stringify(result.snapshot?.actorProvenance).includes('MUST_NOT_PERSIST'), false);
});

test('identical raw content hashes identically and duplicate snapshot persistence is suppressed', async () => {
  const adapter = new FakeSourceAdapter('SRC-CPX');
  const repository = new InMemorySnapshotRepository();
  const policyInput = allowedAutomatedInput();
  const first = await runAutomatedDirect(adapter, ref('stable-a'), policyInput, repository, { runId: 'run-a1' });
  const second = await runAutomatedDirect(adapter, ref('stable-a'), policyInput, repository, { runId: 'run-a2' });
  assert.equal(first.status, 'PERSISTED');
  assert.equal(second.status, 'DUPLICATE');
  assert.equal(first.snapshot?.contentHash, second.snapshot?.contentHash);
  assert.equal(repository.all().length, 1);
});

test('changed raw content creates a different hash and a second immutable snapshot', async () => {
  const adapter = new FakeSourceAdapter('SRC-CPX');
  const repository = new InMemorySnapshotRepository();
  const policyInput = allowedAutomatedInput();
  const first = await runAutomatedDirect(adapter, ref('stable-a'), policyInput, repository, { runId: 'run-change-a' });
  const second = await runAutomatedDirect(adapter, ref('changed-b'), policyInput, repository, { runId: 'run-change-b' });
  assert.equal(first.status, 'PERSISTED');
  assert.equal(second.status, 'PERSISTED');
  assert.notEqual(first.snapshot?.contentHash, second.snapshot?.contentHash);
  assert.equal(repository.all().length, 2);
});

test('transient failure retries once and succeeds while permanent failure stops immediately', async () => {
  const transientAdapter = new FakeSourceAdapter('SRC-CPX');
  const transient = await runAutomatedDirect(
    transientAdapter,
    ref('transient-then-success'),
    allowedAutomatedInput(),
    new InMemorySnapshotRepository(),
    { runId: 'run-transient', maxAttempts: 3 },
  );
  assert.equal(transient.status, 'PERSISTED');
  assert.equal(transient.attempts, 2);
  assert.equal(transientAdapter.transportCallCount, 2);

  const permanentAdapter = new FakeSourceAdapter('SRC-CPX');
  const permanent = await runAutomatedDirect(
    permanentAdapter,
    ref('permanent-failure'),
    allowedAutomatedInput(),
    new InMemorySnapshotRepository(),
    { runId: 'run-permanent', maxAttempts: 5 },
  );
  assert.equal(permanent.status, 'FAILED');
  assert.equal(permanent.errorCode, 'INVALID_CONTENT');
  assert.equal(permanent.attempts, 1);
  assert.equal(permanentAdapter.transportCallCount, 1);
});

test('unsupported direct reference fails explicitly instead of returning fake inventory', async () => {
  const adapter = new FakeSourceAdapter('SRC-CPX');
  const result = await runAutomatedDirect(
    adapter,
    ref('unsupported'),
    allowedAutomatedInput(),
    new InMemorySnapshotRepository(),
    { runId: 'run-unsupported' },
  );
  assert.equal(result.status, 'UNSUPPORTED');
  assert.equal(result.errorCode, 'UNSUPPORTED_MODE');
  assert.equal(result.snapshot, null);
});

test('snapshot metadata is secret-safe and output stops at raw snapshot fields', async () => {
  const adapter = new FakeSourceAdapter('SRC-CPX');
  const result = await runAutomatedDirect(
    adapter,
    ref('stable-a'),
    allowedAutomatedInput(),
    new InMemorySnapshotRepository(),
    { runId: 'run-sanitize' },
  );
  assert.equal(result.status, 'PERSISTED');
  const serialized = JSON.stringify(result.snapshot);
  assert.equal(serialized.includes('MUST_NOT_PERSIST'), false);
  assert.equal(serialized.includes('authorization'), false);
  assert.equal(serialized.includes('cookie'), false);
  assert.equal(serialized.includes('apiKey'), false);
  assert.equal(serialized.includes('"safe":"kept"'), true);
  assert.equal(Object.hasOwn(result.snapshot ?? {}, 'opportunityCategory'), false);
  assert.equal(Object.hasOwn(result.snapshot ?? {}, 'expectedPayoutValue'), false);
  assert.equal(Object.hasOwn(result.snapshot ?? {}, 'eligibility'), false);
});

test('health is diagnostic only and does not grant policy permission', async () => {
  const adapter = new FakeSourceAdapter('SRC-CPX', 'HEALTHY');
  const blocked = blockedAutomatedInput();
  const context: AcquisitionContext = {
    source: blocked.source,
    intendedAttempt: blocked.attempt,
    w1Decision: 'BLOCK',
    operation: 'HEALTH',
    endpointId: null,
    runId: 'run-health',
    attemptNumber: 0,
    timeoutMs: 0,
    secretReferenceHandles: [],
  };
  const health = await adapter.healthCheck(context);
  assert.equal(health.status, 'HEALTHY');
  const result = await runAutomatedDirect(
    adapter,
    ref('stable-a'),
    blocked,
    new InMemorySnapshotRepository(),
    { runId: 'run-health-still-blocked' },
  );
  assert.equal(result.status, 'BLOCKED');
  assert.equal(adapter.transportCallCount, 0);
});

test('deterministic content hash excludes transient request metadata', () => {
  const base = {
    sourceKey: 'SRC-CPX', endpointOrReferenceId: 'stable-a', requestedUrlOrReference: 'fake://stable-a', finalUrl: 'fake://stable-a',
    acquiredAt: '2026-08-30T00:00:00.000Z', transportStatus: 'SUCCESS' as const, httpStatus: 200,
    contentType: 'application/json', rawText: null, rawJson: { b: 2, a: 1 }, rawBytesBase64: null, rawLocation: null,
    providerExternalId: 'A', transportMetadata: { requestId: 'one' }, errorCode: null, errorMessageSanitized: null,
    attemptCount: 1, durationMs: 1,
  };
  const changedTransientMetadata = {
    ...base,
    acquiredAt: '2026-08-31T00:00:00.000Z',
    transportMetadata: { requestId: 'two', retryCounter: 99 },
    attemptCount: 99,
    durationMs: 999,
  };
  assert.equal(deterministicContentHash(base), deterministicContentHash(changedTransientMetadata));
});
