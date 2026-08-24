'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const manifest = require('./source-manifest.cjs');
const { validatePayload, renderSummary } = require('./audit-intake-output.cjs');

function reviewable(source, overrides = {}) {
  return {
    state: 'NEEDS_REVIEW',
    sourceId: source.id,
    signalId: source.signalId,
    provider: source.provider,
    review: null,
    evidence: {
      requestedUrl: source.url,
      finalUrl: source.url,
      observedAt: '2026-08-24T12:00:00.000Z',
      httpStatus: 200,
      contentType: 'text/html',
      contentLength: 1234,
      sha256: 'a'.repeat(64)
    },
    observations: [],
    missingRequired: [],
    ...overrides
  };
}

function payload(candidates = manifest.map(source => reviewable(source))) {
  return {
    generatedAt: '2026-08-24T12:00:00.000Z',
    publicationAuthority: 'REVIEW_REQUIRED',
    candidates
  };
}

test('valid mixed review-only output passes and renders explicit no-publication summary', () => {
  const candidates = manifest.map(source => reviewable(source));
  candidates[0] = {
    state: 'REJECTED',
    sourceId: manifest[0].id,
    signalId: manifest[0].signalId,
    reason: 'HTTP_503'
  };
  const audit = validatePayload(payload(candidates));
  assert.equal(audit.manifestSources, manifest.length);
  assert.equal(audit.reviewable, manifest.length - 1);
  assert.equal(audit.rejected, 1);
  const summary = renderSummary(audit, 'b'.repeat(40));
  assert.match(summary, /Publication authority: `REVIEW_REQUIRED`/);
  assert.match(summary, /no candidate was approved, no snapshot was written, no publication occurred, and no deployment occurred/);
  assert.match(summary, /AUTO_APPROVAL=0/);
});

test('forbids any approved-for-snapshot state', () => {
  const candidates = manifest.map(source => reviewable(source));
  candidates[0].state = 'APPROVED_FOR_SNAPSHOT';
  assert.throws(() => validatePayload(payload(candidates)), /forbidden state APPROVED_FOR_SNAPSHOT/);
});

test('forbids embedded human review decisions on scheduled output', () => {
  const candidates = manifest.map(source => reviewable(source));
  candidates[0].review = { decision: 'approve', reviewer: 'scheduler' };
  assert.throws(() => validatePayload(payload(candidates)), /must not contain a human review/);
});

test('requires exact one-to-one manifest source coverage', () => {
  const candidates = manifest.map(source => reviewable(source));
  candidates[1].sourceId = candidates[0].sourceId;
  assert.throws(() => validatePayload(payload(candidates)), /duplicate candidate sourceId/);
});

test('rejects raw fetched page bodies in review artifacts', () => {
  const candidates = manifest.map(source => reviewable(source));
  candidates[0].body = '<html>raw source body</html>';
  assert.throws(() => validatePayload(payload(candidates)), /must not contain raw page body/);
});

test('requires reviewable evidence metadata and stable publication authority', () => {
  const candidates = manifest.map(source => reviewable(source));
  candidates[0].evidence.sha256 = 'bad';
  assert.throws(() => validatePayload(payload(candidates)), /missing evidence SHA-256/);
  assert.throws(() => validatePayload({ ...payload(), publicationAuthority: 'AUTO' }), /must be REVIEW_REQUIRED/);
});
