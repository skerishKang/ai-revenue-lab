import test from 'node:test';
import assert from 'node:assert/strict';
import type { SourceSnapshot } from '../src/persistence/domain.js';
import type { OpportunityExtractor } from '../src/extraction/domain.js';
import { FakeOpportunityExtractor } from '../src/extraction/fake-extractor.js';
import { runExtractionPipeline } from '../src/extraction/runtime.js';

function snapshot(): SourceSnapshot {
  return Object.freeze({
    id: 'snapshot-w5-fixture',
    sourceId: 'SRC-CPX',
    endpointId: null,
    acquiredAt: '2026-08-30T00:00:00.000Z',
    acquisitionModeUsed: 'PARTNER_API',
    canonicalUrl: 'https://example.invalid/source',
    contentType: 'application/json',
    rawLocation: null,
    rawPayload: { synthetic: true },
    contentHash: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    fetchMetadata: null,
    actorProvenance: { fixture: true },
    httpStatus: null,
  });
}

function input(runId: string) {
  return Object.freeze({
    snapshot: snapshot(),
    schemaVersion: 'W5-v1',
    runId,
    startedAt: '2026-08-30T00:00:00.000Z',
  });
}

test('fixed research fixture becomes evidence-bound CandidateOpportunity but remains review-required', async () => {
  const result = await runExtractionPipeline(new FakeOpportunityExtractor('FIXED_SURVEY'), input('fixed-survey'));
  assert.ok(result.candidate);
  assert.equal(result.candidate.opportunityCategory, 'MARKET_RESEARCH');
  assert.equal(result.candidate.expectedPayoutValue, 12);
  assert.equal(result.candidate.compensationCurrency, 'USD');
  assert.equal(result.candidate.qualificationProbability, null);
  assert.equal(result.provenance.status, 'SUCCESS');
  assert.equal(result.review.structuralErrors.length, 0);
  assert.equal(result.review.semanticErrors.length, 0);
  assert.equal(result.review.evidenceErrors.length, 0);
  assert.equal(result.review.state, 'REVIEW_REQUIRED');
  assert.equal(result.review.verificationAllowed, false);
  assert.equal(result.review.publicationAllowed, false);
});

test('unknown compensation stays null instead of receiving a plausible default', async () => {
  const result = await runExtractionPipeline(new FakeOpportunityExtractor('UNKNOWN_COMPENSATION'), input('unknown-comp'));
  assert.ok(result.candidate);
  assert.equal(result.candidate.advertisedCompensationValue, null);
  assert.equal(result.candidate.expectedPayoutValue, null);
  assert.equal(result.candidate.compensationCurrency, null);
  assert.equal(result.candidate.qualificationProbability, null);
  assert.equal(result.candidate.supplyAvailabilityState, null);
  assert.equal(result.review.evidenceErrors.length, 0);
});

test('draw maximum wording does not become guaranteed expected payout', async () => {
  const result = await runExtractionPipeline(new FakeOpportunityExtractor('DRAW_MAXIMUM'), input('draw-max'));
  assert.ok(result.candidate);
  assert.equal(result.candidate.compensationType, 'DRAW');
  assert.equal(result.candidate.advertisedCompensationValue, 500);
  assert.equal(result.candidate.expectedPayoutValue, null);
  assert.equal(result.review.semanticErrors.some((item) => item.includes('guaranteed expected payout')), false);
});

test('qualification-dependent AI work keeps application, screening and active work time distinct', async () => {
  const result = await runExtractionPipeline(new FakeOpportunityExtractor('AI_WORK_QUALIFIED'), input('ai-work'));
  assert.ok(result.candidate);
  assert.equal(result.candidate.applicationMinutes, 10);
  assert.equal(result.candidate.qualificationScreeningMinutes, 15);
  assert.equal(result.candidate.estimatedActiveMinutes, 30);
  assert.equal(result.candidate.qualificationRequired, true);
  assert.equal(result.candidate.immediateTodayRouteClaim, false);
  assert.equal(result.review.semanticErrors.length, 0);
});

test('qualification-dependent work claiming immediate TODAY_ROUTE is deterministically rejected for review', async () => {
  const inner = new FakeOpportunityExtractor('AI_WORK_QUALIFIED');
  const wrapper: OpportunityExtractor = {
    kind: 'RULE', providerId: null, modelId: null, promptVersion: null,
    async extract(extractionInput) {
      const output = await inner.extract(extractionInput);
      return { ...output, candidate: { ...output.candidate, immediateTodayRouteClaim: true } };
    },
  };
  const result = await runExtractionPipeline(wrapper, input('ai-work-bad-route'));
  assert.equal(result.review.semanticErrors.some((item) => item.includes('TODAY_ROUTE')), true);
  assert.equal(result.review.verificationAllowed, false);
});

test('conflicting compensation evidence routes to conflict review', async () => {
  const result = await runExtractionPipeline(new FakeOpportunityExtractor('CONFLICTING_COMPENSATION'), input('conflict'));
  assert.equal(result.review.riskCodes.includes('SOURCE_CONFLICT'), true);
  assert.equal(result.review.riskCodes.includes('AMBIGUOUS_COMPENSATION'), true);
  assert.equal(result.review.publicationAllowed, false);
});

test('stale source evidence blocks publication and is explicitly classified', async () => {
  const result = await runExtractionPipeline(new FakeOpportunityExtractor('STALE_SOURCE'), input('stale'));
  assert.equal(result.review.riskCodes.includes('STALE_OR_BROKEN_SOURCE'), true);
  assert.equal(result.review.semanticErrors.some((item) => item.includes('blocks publication')), true);
  assert.equal(result.review.publicationAllowed, false);
});

test('malformed numeric output is schema-rejected before verification', async () => {
  const result = await runExtractionPipeline(new FakeOpportunityExtractor('MALFORMED_NEGATIVE'), input('malformed'));
  assert.equal(result.provenance.status, 'SCHEMA_REJECTED');
  assert.equal(result.review.riskCodes.includes('MODEL_SCHEMA_FAILURE'), true);
  assert.equal(result.review.structuralErrors.some((item) => item.includes('advertisedCompensationValue')), true);
  assert.equal(result.review.verificationAllowed, false);
});

test('material fields without evidence are fail-closed into review', async () => {
  const result = await runExtractionPipeline(new FakeOpportunityExtractor('MISSING_EVIDENCE'), input('missing-evidence'));
  assert.equal(result.review.riskCodes.includes('MISSING_CRITICAL_EVIDENCE'), true);
  assert.equal(result.review.evidenceErrors.some((item) => item.includes('opportunityCategory')), true);
  assert.equal(result.review.evidenceErrors.some((item) => item.includes('advertisedCompensationValue')), true);
});

test('extractor provider/model identity is swappable and provenance records only the actually supplied identity', async () => {
  const extractor = new FakeOpportunityExtractor('UNKNOWN_COMPENSATION', {
    kind: 'MODEL', providerId: 'fixture-provider', modelId: 'fixture-model-v1', promptVersion: 'prompt-v7',
  });
  const result = await runExtractionPipeline(extractor, input('provider-swap'));
  assert.equal(result.provenance.extractorKind, 'MODEL');
  assert.equal(result.provenance.providerId, 'fixture-provider');
  assert.equal(result.provenance.modelId, 'fixture-model-v1');
  assert.equal(result.provenance.promptVersion, 'prompt-v7');
  assert.equal(result.provenance.inputSnapshotSha256, snapshot().contentHash);
});

test('extractor failure is captured as MODEL_SCHEMA_FAILURE without candidate verification or publication', async () => {
  const failing: OpportunityExtractor = {
    kind: 'MODEL', providerId: 'fixture-provider', modelId: 'fixture-fail', promptVersion: 'prompt-v1',
    async extract() { throw new Error('synthetic extractor failure'); },
  };
  const result = await runExtractionPipeline(failing, input('extract-fail'));
  assert.equal(result.candidate, null);
  assert.equal(result.provenance.status, 'FAILED');
  assert.equal(result.review.riskCodes.includes('MODEL_SCHEMA_FAILURE'), true);
  assert.equal(result.review.verificationAllowed, false);
  assert.equal(result.review.publicationAllowed, false);
});
