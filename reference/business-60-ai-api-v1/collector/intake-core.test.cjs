'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const manifest = require('./source-manifest.cjs');
const { STATES, sha256, fetchEvidence, extractCandidate, reviewCandidate, promoteApprovedCandidates } = require('./intake-core.cjs');

function mockResponse(body, options = {}) {
  return {
    ok: options.ok ?? true,
    status: options.status ?? 200,
    url: options.url || 'https://official.example/final',
    headers: { get: name => name === 'content-type' ? 'text/html; charset=utf-8' : null },
    text: async () => body
  };
}

test('fetch envelope records immutable evidence metadata and sha256', async () => {
  const source = manifest.find(x => x.id === 'google-gemini-pricing');
  const body = '<html>Gemini API Free tier</html>';
  const envelope = await fetchEvidence(source, { observedAt: '2026-08-23T05:30:00.000Z', fetchImpl: async () => mockResponse(body) });
  assert.equal(envelope.state, STATES.FETCHED);
  assert.equal(envelope.httpStatus, 200);
  assert.equal(envelope.evidenceSha256, sha256(body));
  assert.equal(envelope.observedAt, '2026-08-23T05:30:00.000Z');
});

test('extraction never auto-verifies a primary-source candidate', async () => {
  const source = manifest.find(x => x.id === 'vercel-glm52-model');
  const body = 'zai/glm-5.2 context 1M. Route requests across multiple providers. Z.AI $1.40 input and $4.40 output; DeepInfra $0.95 input and $3 output. Free accounts receive $5 credits every 30 days.';
  const envelope = await fetchEvidence(source, { fetchImpl: async () => mockResponse(body) });
  const candidate = extractCandidate(source, envelope);
  assert.equal(candidate.state, STATES.NEEDS_REVIEW);
  assert.equal(candidate.review, null);
  assert.equal(candidate.missingRequired.length, 0);
  assert.ok(candidate.observations.length >= 4);
  assert.equal(candidate.observations.find(x => x.field === 'price')?.value, 'Varies by routed provider');
  assert.notEqual(candidate.observations.find(x => x.field === 'price')?.value, '$1.40/M input · $4.40/M output');
  assert.equal(candidate.verification, undefined);
});

test('approval is explicit and only approved candidates can become snapshot records', async () => {
  const source = manifest.find(x => x.id === 'cloudflare-workers-ai-pricing');
  const body = 'Workers AI includes 10,000 neurons per day free. Above that allocation pricing is $0.011 per 1,000 neurons.';
  const envelope = await fetchEvidence(source, { fetchImpl: async () => mockResponse(body) });
  const candidate = extractCandidate(source, envelope);
  assert.throws(() => promoteApprovedCandidates({ id: source.signalId }, [candidate]), /no approved candidates/);

  const approved = reviewCandidate(candidate, { decision: 'approve', reviewer: 'human-reviewer', reviewedAt: '2026-08-23T05:35:00.000Z' });
  assert.equal(approved.state, STATES.APPROVED_FOR_SNAPSHOT);
  const record = promoteApprovedCandidates({ id: source.signalId, provider: source.provider }, [approved], { snapshotDate: '2026-08-23' });
  assert.equal(record.verification, 'VERIFIED_OFFICIAL_WEB');
  assert.equal(record.verificationScope, 'FULL_RECORD');
  assert.equal(record.freeLabel, '10,000 neurons / day');
  assert.equal(record.fieldVerification.freeLabel.status, 'VERIFIED_OFFICIAL_WEB');
  assert.deepEqual(record.carriedForwardFields, []);
  assert.equal(record.evidence[0].sha256, envelope.evidenceSha256);
});

test('unobserved historical fields are carried forward without becoming freshly verified', () => {
  const approved = {
    state: STATES.APPROVED_FOR_SNAPSHOT,
    sourceId: 'official-free-plan',
    signalId: 'signal-1',
    observedAt: '2026-08-24T01:00:00.000Z',
    evidence: {
      requestedUrl: 'https://official.example/free',
      finalUrl: 'https://official.example/free',
      observedAt: '2026-08-24T01:00:00.000Z',
      httpStatus: 200,
      contentType: 'text/html',
      contentLength: 100,
      sha256: 'evidence-hash'
    },
    observations: [
      {
        field: 'freeLabel',
        value: '50 requests / day',
        status: 'OBSERVED_PRIMARY_SOURCE',
        evidenceSha256: 'evidence-hash',
        excerpt: '50 requests per day'
      }
    ],
    missingRequired: [],
    review: {
      decision: 'approve',
      reviewer: 'human-reviewer',
      reviewedAt: '2026-08-24T01:05:00.000Z',
      reason: null
    }
  };

  const record = promoteApprovedCandidates({
    id: 'signal-1',
    provider: 'Example',
    price: '$0 historical price',
    freeLabel: '10 requests / day'
  }, [approved], { snapshotDate: '2026-08-24' });

  assert.equal(record.freeLabel, '50 requests / day');
  assert.equal(record.price, '$0 historical price');
  assert.equal(record.verification, 'PARTIALLY_VERIFIED_OFFICIAL_WEB');
  assert.equal(record.verificationScope, 'OBSERVED_FIELDS_ONLY');
  assert.deepEqual(record.carriedForwardFields, ['price']);
  assert.equal(record.fieldVerification.freeLabel.status, 'VERIFIED_OFFICIAL_WEB');
  assert.equal(record.fieldVerification.freeLabel.evidenceSha256, 'evidence-hash');
  assert.equal(record.fieldVerification.price, undefined);
});

test('required missing evidence blocks approval', async () => {
  const source = manifest.find(x => x.id === 'openrouter-pricing');
  const envelope = await fetchEvidence(source, { fetchImpl: async () => mockResponse('pricing page without the daily free-plan allowance') });
  const candidate = extractCandidate(source, envelope);
  assert.deepEqual(candidate.missingRequired, ['freeLabel']);
  assert.throws(() => reviewCandidate(candidate, { decision: 'approve', reviewer: 'reviewer' }), /required evidence missing/);
});

test('failed HTTP evidence becomes rejected candidate, not a verified record', async () => {
  const source = manifest.find(x => x.id === 'groq-free-rate-limits');
  const envelope = await fetchEvidence(source, { fetchImpl: async () => mockResponse('server error', { ok:false, status:503 }) });
  const candidate = extractCandidate(source, envelope);
  assert.equal(candidate.state, STATES.REJECTED);
  assert.equal(candidate.reason, 'HTTP_503');
  assert.equal(candidate.observations.length, 0);
});
