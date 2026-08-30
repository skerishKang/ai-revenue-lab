import test from 'node:test';
import assert from 'node:assert/strict';
import type { OpportunityVersion } from '../src/persistence/domain.js';
import type {
  CandidateOpportunity,
  CandidateReviewRequest,
  ExtractionRunProvenance,
} from '../src/extraction/domain.js';
import { detectMaterialNormalizedTermChanges } from '../src/change-detection/detector.js';
import { proposeNextOpportunityVersion } from '../src/change-detection/proposal.js';

function previous(overrides: Record<string, unknown> = {}): OpportunityVersion {
  return Object.freeze({
    id: 'version-1',
    offerId: 'offer-1',
    versionNumber: 1,
    sourceSnapshotId: 'snapshot-old',
    title: 'AI evaluation task',
    advertisedCompensationValue: 20,
    ...overrides,
  }) as unknown as OpportunityVersion;
}

function candidate(overrides: Record<string, unknown> = {}): CandidateOpportunity {
  return Object.freeze({
    candidateId: 'candidate-new',
    sourceSnapshotId: 'snapshot-new',
    sourceId: 'SRC-CPX',
    title: 'AI evaluation task',
    advertisedCompensationValue: 20,
    ...overrides,
  }) as unknown as CandidateOpportunity;
}

function provenance(overrides: Record<string, unknown> = {}): ExtractionRunProvenance {
  return Object.freeze({
    extractionRunId: 'run-new',
    sourceSnapshotId: 'snapshot-new',
    inputSnapshotSha256: 'new-hash',
    extractorKind: 'RULE',
    providerId: null,
    modelId: null,
    promptVersion: null,
    schemaVersion: 'W5-v1',
    startedAt: '2026-08-30T01:00:00.000Z',
    completedAt: '2026-08-30T01:00:00.000Z',
    rawStructuredOutputHash: 'structured-hash',
    status: 'SUCCESS',
    validationErrors: Object.freeze([]),
    humanCorrectionLineage: null,
    ...overrides,
  }) as ExtractionRunProvenance;
}

function review(overrides: Record<string, unknown> = {}): CandidateReviewRequest {
  return Object.freeze({
    candidateId: 'candidate-new',
    state: 'REVIEW_REQUIRED',
    riskCodes: Object.freeze(['NONE']),
    structuralErrors: Object.freeze([]),
    semanticErrors: Object.freeze([]),
    evidenceErrors: Object.freeze([]),
    publicationAllowed: false,
    verificationAllowed: false,
    ...overrides,
  }) as CandidateReviewRequest;
}

function proposalInput(overrides: Record<string, unknown> = {}) {
  return {
    previousVersion: previous(),
    candidate: candidate({ advertisedCompensationValue: 25 }),
    provenance: provenance(),
    w5Review: review(),
    nextVersionId: 'version-2',
    changeId: 'change-1',
    reviewQueueId: 'review-1',
    detectedAt: '2026-08-30T02:00:00.000Z',
    createdAt: '2026-08-30T02:00:00.000Z',
    ...overrides,
  } as Parameters<typeof proposeNextOpportunityVersion>[0];
}

test('duplicate-only list differences are canonicalized away', () => {
  const result = detectMaterialNormalizedTermChanges(
    previous({ eligibleCountriesOrRegions: ['KR', 'US', 'US'] }),
    candidate({ eligibleCountriesOrRegions: ['US', 'KR'] }),
  );
  assert.equal(result.disposition, 'NO_CHANGE');
});

test('title formatting and case changes do not imply semantic material change', () => {
  const result = detectMaterialNormalizedTermChanges(
    previous({ title: 'AI   Evaluation Task' }),
    candidate({ title: 'ai evaluation task' }),
  );
  assert.equal(result.disposition, 'NO_CHANGE');
});

test('W6 fails closed when the candidate reuses the previous immutable source snapshot', () => {
  assert.throws(
    () => proposeNextOpportunityVersion(proposalInput({
      previousVersion: previous({ sourceSnapshotId: 'snapshot-new' }),
    })),
    /later immutable SourceSnapshot distinct/,
  );
});

test('W6 rejects reuse of the previous immutable version id', () => {
  assert.throws(
    () => proposeNextOpportunityVersion(proposalInput({ nextVersionId: 'version-1' })),
    /must differ from the previous immutable version id/,
  );
});

test('material proposals require stable non-empty version/change/review identities', () => {
  assert.throws(
    () => proposeNextOpportunityVersion(proposalInput({ nextVersionId: '   ' })),
    /nextVersionId is required/,
  );
  assert.throws(
    () => proposeNextOpportunityVersion(proposalInput({ changeId: '   ' })),
    /changeId is required/,
  );
  assert.throws(
    () => proposeNextOpportunityVersion(proposalInput({ reviewQueueId: '   ' })),
    /reviewQueueId is required/,
  );
});
