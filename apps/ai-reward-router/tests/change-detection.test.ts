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

function previousVersion(overrides: Partial<OpportunityVersion> = {}): OpportunityVersion {
  const base: OpportunityVersion = {
    id: 'version-1',
    offerId: 'offer-1',
    versionNumber: 1,
    sourceSnapshotId: 'snapshot-old',
    title: 'AI evaluation task',
    shortSummary: 'Evaluate model responses',
    originalLanguage: 'en',
    verificationState: 'VERIFIED',
    sourceSnapshotHash: 'old-hash',
    modelId: null,
    promptVersion: null,
    inputHash: 'old-hash',
    opportunityCategory: 'AI_EVALUATION',
    incomeLadderLevel: 'TASK_WORK',
    compensationType: 'PER_TASK',
    advertisedCompensationValue: 20,
    expectedPayoutValue: 20,
    compensationCurrency: 'USD',
    estimatedActiveMinutes: 30,
    estimatedTotalEffortMinutes: null,
    applicationMinutes: 10,
    qualificationScreeningMinutes: 15,
    preparationMinutes: null,
    startLatencyMinutes: null,
    payoutMethod: { kind: 'bank', currency: 'USD' },
    payoutDelay: { days: 7 },
    providerFees: null,
    repeatability: { kind: 'VARIABLE' },
    supplyAvailabilityState: null,
    supplyObservedAt: null,
    applicationRequired: true,
    qualificationRequired: true,
    qualificationProbability: null,
    acceptanceProbability: null,
    rejectionOrReversalRisk: null,
    payoutReliability: null,
    eligibleCountriesOrRegions: ['KR', 'US'],
    languageRequirements: ['en', 'ko'],
    skillRequirements: ['reasoning'],
    deviceOsRequirements: null,
    identityKycRequirements: null,
    ageRequirements: null,
    taxContractorRequirements: null,
    schedulingRequirements: null,
    canonicalDestinationUrl: 'https://example.invalid/task',
    createdAt: '2026-08-30T00:00:00.000Z',
  };
  return Object.freeze({ ...base, ...overrides });
}

function candidate(overrides: Partial<CandidateOpportunity> = {}): CandidateOpportunity {
  const base: CandidateOpportunity = {
    candidateId: 'candidate-new',
    sourceSnapshotId: 'snapshot-new',
    sourceId: 'SRC-CPX',
    title: 'AI evaluation task',
    shortSummary: 'Evaluate model responses',
    originalLanguage: 'en',
    opportunityCategory: 'AI_EVALUATION',
    incomeLadderLevel: 'TASK_WORK',
    compensationType: 'PER_TASK',
    advertisedCompensationValue: 20,
    expectedPayoutValue: 20,
    compensationCurrency: 'USD',
    estimatedActiveMinutes: 30,
    estimatedTotalEffortMinutes: null,
    applicationMinutes: 10,
    qualificationScreeningMinutes: 15,
    preparationMinutes: null,
    startLatencyMinutes: null,
    payoutMethod: { currency: 'USD', kind: 'bank' },
    payoutDelay: { days: 7 },
    providerFees: null,
    repeatability: { kind: 'VARIABLE' },
    supplyAvailabilityState: null,
    supplyObservedAt: null,
    applicationRequired: true,
    qualificationRequired: true,
    qualificationProbability: null,
    acceptanceProbability: null,
    eligibleCountriesOrRegions: ['KR', 'US'],
    languageRequirements: ['en', 'ko'],
    skillRequirements: ['reasoning'],
    deviceOsRequirements: null,
    identityKycRequirements: null,
    ageRequirements: null,
    taxContractorRequirements: null,
    schedulingRequirements: null,
    canonicalDestinationUrl: 'https://example.invalid/task',
    sourceFreshness: 'CURRENT',
    immediateTodayRouteClaim: false,
  };
  return Object.freeze({ ...base, ...overrides });
}

function provenance(overrides: Partial<ExtractionRunProvenance> = {}): ExtractionRunProvenance {
  const base: ExtractionRunProvenance = {
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
  };
  return Object.freeze({ ...base, ...overrides });
}

function review(overrides: Partial<CandidateReviewRequest> = {}): CandidateReviewRequest {
  const base: CandidateReviewRequest = {
    candidateId: 'candidate-new',
    state: 'REVIEW_REQUIRED',
    riskCodes: Object.freeze(['NONE']),
    structuralErrors: Object.freeze([]),
    semanticErrors: Object.freeze([]),
    evidenceErrors: Object.freeze([]),
    publicationAllowed: false,
    verificationAllowed: false,
  };
  return Object.freeze({ ...base, ...overrides });
}

function proposalInput(overrides: Partial<Parameters<typeof proposeNextOpportunityVersion>[0]> = {}) {
  return {
    previousVersion: previousVersion(),
    candidate: candidate(),
    provenance: provenance(),
    w5Review: review(),
    nextVersionId: 'version-2',
    changeId: 'change-1',
    reviewQueueId: 'review-1',
    detectedAt: '2026-08-30T02:00:00.000Z',
    createdAt: '2026-08-30T02:00:00.000Z',
    ...overrides,
  };
}

test('different raw snapshot identity with identical normalized terms does not create a material change', () => {
  const result = detectMaterialNormalizedTermChanges(previousVersion(), candidate());
  assert.equal(result.disposition, 'NO_CHANGE');
  assert.equal(result.changes.length, 0);
  assert.equal(result.newVersionRequired, false);
  assert.equal(result.reviewRequired, false);
  assert.equal(result.currentVersionReplacementAllowed, false);
});

test('compensation amount change is material and review-gated', () => {
  const result = detectMaterialNormalizedTermChanges(
    previousVersion(),
    candidate({ advertisedCompensationValue: 25, expectedPayoutValue: 25 }),
  );
  assert.equal(result.disposition, 'MATERIAL_CHANGE_REVIEW_REQUIRED');
  assert.equal(result.newVersionRequired, true);
  assert.equal(result.reviewRequired, true);
  assert.equal(result.materialChanges.some((change) => change.field === 'advertisedCompensationValue'), true);
  assert.equal(result.materialChanges.some((change) => change.field === 'expectedPayoutValue'), true);
});

test('certainty or compensation-basis change is material', () => {
  const result = detectMaterialNormalizedTermChanges(
    previousVersion({ compensationType: 'FIXED', expectedPayoutValue: null }),
    candidate({ compensationType: 'DRAW', expectedPayoutValue: null }),
  );
  assert.equal(result.materialChanges.some((change) => change.field === 'compensationType'), true);
});

test('application and qualification gate changes are material', () => {
  const result = detectMaterialNormalizedTermChanges(
    previousVersion(),
    candidate({ applicationRequired: false, qualificationRequired: false }),
  );
  assert.equal(result.materialChanges.some((change) => change.field === 'applicationRequired'), true);
  assert.equal(result.materialChanges.some((change) => change.field === 'qualificationRequired'), true);
});

test('country language and skill requirement changes are material', () => {
  const result = detectMaterialNormalizedTermChanges(
    previousVersion(),
    candidate({
      eligibleCountriesOrRegions: ['KR'],
      languageRequirements: ['ko'],
      skillRequirements: ['reasoning', 'coding'],
    }),
  );
  assert.equal(result.materialChanges.some((change) => change.field === 'eligibleCountriesOrRegions'), true);
  assert.equal(result.materialChanges.some((change) => change.field === 'languageRequirements'), true);
  assert.equal(result.materialChanges.some((change) => change.field === 'skillRequirements'), true);
});

test('NULL to explicit payout timing is a real material change without default fabrication', () => {
  const result = detectMaterialNormalizedTermChanges(
    previousVersion({ payoutDelay: null }),
    candidate({ payoutDelay: { days: 7 } }),
  );
  const change = result.materialChanges.find((item) => item.field === 'payoutDelay');
  assert.ok(change);
  assert.equal(change.previousValue, null);
  assert.deepEqual(change.nextValue, { days: 7 });
});

test('ordering-only differences in list-set fields do not create false changes', () => {
  const result = detectMaterialNormalizedTermChanges(
    previousVersion({
      eligibleCountriesOrRegions: ['KR', 'US'],
      languageRequirements: ['en', 'ko'],
    }),
    candidate({
      eligibleCountriesOrRegions: ['US', 'KR'],
      languageRequirements: ['ko', 'en'],
    }),
  );
  assert.equal(result.disposition, 'NO_CHANGE');
});

test('structured object key ordering does not create false payout changes', () => {
  const result = detectMaterialNormalizedTermChanges(
    previousVersion({ payoutMethod: { kind: 'bank', currency: 'USD' } }),
    candidate({ payoutMethod: { currency: 'USD', kind: 'bank' } }),
  );
  assert.equal(result.disposition, 'NO_CHANGE');
});

test('short-summary-only edits are reported but non-material in bounded W6', () => {
  const result = detectMaterialNormalizedTermChanges(
    previousVersion(),
    candidate({ shortSummary: 'Editorial wording only' }),
  );
  assert.equal(result.disposition, 'NON_MATERIAL_CHANGE');
  assert.equal(result.materialChanges.length, 0);
  assert.equal(result.nonMaterialChanges.length, 1);
  assert.equal(result.newVersionRequired, false);
});

test('material change proposal creates version +1 in REVIEW_REQUIRED and never authorizes current replacement', () => {
  const input = proposalInput({
    candidate: candidate({ expectedPayoutValue: 25, advertisedCompensationValue: 25 }),
  });
  const result = proposeNextOpportunityVersion(input);
  assert.ok(result.proposedVersion);
  assert.equal(result.proposedVersion.versionNumber, 2);
  assert.equal(result.proposedVersion.verificationState, 'REVIEW_REQUIRED');
  assert.equal(result.proposedVersion.sourceSnapshotId, 'snapshot-new');
  assert.equal(result.proposedVersion.sourceSnapshotHash, 'new-hash');
  assert.equal(result.currentVersionReplacementAllowed, false);
  assert.ok(result.reviewQueueItem);
  assert.equal(result.reviewQueueItem.state, 'OPEN');
  assert.equal(result.reviewQueueItem.offerVersionId, 'version-2');
});

test('OpportunityChange links the previous immutable version to the proposed next version', () => {
  const result = proposeNextOpportunityVersion(proposalInput({
    candidate: candidate({ canonicalDestinationUrl: 'https://example.invalid/task-v2' }),
  }));
  assert.ok(result.change);
  assert.equal(result.change.previousVersionId, 'version-1');
  assert.equal(result.change.newVersionId, 'version-2');
  assert.equal(result.change.material, true);
  assert.match(result.change.summary, /canonicalDestinationUrl/);
});

test('proposal does not mutate the previous immutable version object', () => {
  const previous = previousVersion();
  const before = JSON.stringify(previous);
  proposeNextOpportunityVersion(proposalInput({
    previousVersion: previous,
    candidate: candidate({ qualificationRequired: false }),
  }));
  assert.equal(JSON.stringify(previous), before);
  assert.equal(previous.versionNumber, 1);
  assert.equal(previous.verificationState, 'VERIFIED');
});

test('W6 fails closed when W5 provenance does not match the candidate snapshot', () => {
  assert.throws(
    () => proposeNextOpportunityVersion(proposalInput({
      provenance: provenance({ sourceSnapshotId: 'different-snapshot' }),
      candidate: candidate({ expectedPayoutValue: 25 }),
    })),
    /sourceSnapshotId does not match/,
  );
});
