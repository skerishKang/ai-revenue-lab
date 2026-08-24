'use strict';

const crypto = require('node:crypto');

const STATES = Object.freeze({
  FETCHED: 'FETCHED',
  EXTRACTED: 'EXTRACTED',
  NEEDS_REVIEW: 'NEEDS_REVIEW',
  APPROVED_FOR_SNAPSHOT: 'APPROVED_FOR_SNAPSHOT',
  REJECTED: 'REJECTED'
});

const RECORD_META_FIELDS = new Set([
  'id',
  'provider',
  'verification',
  'verifiedAt',
  'verificationScope',
  'evidence',
  'fieldVerification',
  'carriedForwardFields'
]);

function sha256(text) {
  return crypto.createHash('sha256').update(String(text)).digest('hex');
}

function excerpt(body, index, length) {
  const start = Math.max(0, index - 90);
  const end = Math.min(body.length, index + Math.max(length, 1) + 140);
  return body.slice(start, end).replace(/\s+/g, ' ').trim();
}

async function fetchEvidence(source, options = {}) {
  const fetchImpl = options.fetchImpl || globalThis.fetch;
  if (typeof fetchImpl !== 'function') throw new TypeError('fetchImpl is required');
  const observedAt = options.observedAt || new Date().toISOString();
  const response = await fetchImpl(source.url, {
    method: 'GET', redirect: 'follow',
    headers: { 'user-agent': options.userAgent || 'ai-api-b60-intake/0.1' }
  });
  const body = await response.text();
  return {
    state: STATES.FETCHED,
    sourceId: source.id,
    signalId: source.signalId,
    provider: source.provider,
    authority: source.authority,
    requestedUrl: source.url,
    finalUrl: response.url || source.url,
    observedAt,
    httpStatus: response.status,
    ok: Boolean(response.ok),
    contentType: response.headers?.get?.('content-type') || '',
    contentLength: Buffer.byteLength(body),
    evidenceSha256: sha256(body),
    body
  };
}

function evidenceRef(envelope) {
  return {
    requestedUrl: envelope.requestedUrl,
    finalUrl: envelope.finalUrl,
    observedAt: envelope.observedAt,
    httpStatus: envelope.httpStatus,
    contentType: envelope.contentType,
    contentLength: envelope.contentLength,
    sha256: envelope.evidenceSha256
  };
}

function extractCandidate(source, envelope) {
  if (!envelope || envelope.sourceId !== source.id) throw new Error('source/envelope mismatch');
  if (!envelope.ok) {
    return {
      state: STATES.REJECTED,
      sourceId: source.id,
      signalId: source.signalId,
      reason: `HTTP_${envelope.httpStatus}`,
      evidence: evidenceRef(envelope),
      observations: []
    };
  }

  const observations = [];
  const missingRequired = [];
  for (const claim of source.claims || []) {
    const re = new RegExp(claim.pattern, claim.flags || 'i');
    const match = re.exec(envelope.body);
    if (!match) {
      if (claim.required) missingRequired.push(claim.field);
      continue;
    }
    observations.push({
      field: claim.field,
      value: claim.value,
      status: 'OBSERVED_PRIMARY_SOURCE',
      evidenceSha256: envelope.evidenceSha256,
      excerpt: excerpt(envelope.body, match.index, match[0].length)
    });
  }

  return {
    state: STATES.NEEDS_REVIEW,
    extractedState: STATES.EXTRACTED,
    sourceId: source.id,
    signalId: source.signalId,
    provider: source.provider,
    authority: source.authority,
    observedAt: envelope.observedAt,
    evidence: evidenceRef(envelope),
    observations,
    missingRequired,
    review: null
  };
}

function reviewCandidate(candidate, review) {
  if (!candidate || candidate.state !== STATES.NEEDS_REVIEW) throw new Error('candidate is not reviewable');
  if (!review || !['approve', 'reject'].includes(review.decision)) throw new Error('review decision must be approve or reject');
  if (!review.reviewer) throw new Error('reviewer is required');
  const reviewedAt = review.reviewedAt || new Date().toISOString();

  if (review.decision === 'reject') {
    return { ...candidate, state: STATES.REJECTED, review: { decision: 'reject', reviewer: review.reviewer, reviewedAt, reason: review.reason || null } };
  }
  if (candidate.missingRequired.length) throw new Error(`required evidence missing: ${candidate.missingRequired.join(', ')}`);
  if (!candidate.observations.length) throw new Error('cannot approve empty candidate');

  return { ...candidate, state: STATES.APPROVED_FOR_SNAPSHOT, review: { decision: 'approve', reviewer: review.reviewer, reviewedAt, reason: review.reason || null } };
}

function promoteApprovedCandidates(baseRecord, candidates, snapshotMeta = {}) {
  const approved = (candidates || []).filter(c => c?.state === STATES.APPROVED_FOR_SNAPSHOT);
  if (!approved.length) throw new Error('no approved candidates');
  const signalIds = new Set(approved.map(c => c.signalId));
  if (signalIds.size !== 1 || !signalIds.has(baseRecord.id)) throw new Error('candidate signal mismatch');

  const next = { ...baseRecord };
  const evidence = [];
  const fieldVerification = {};
  const verifiedFields = new Set();

  for (const candidate of approved) {
    for (const observation of candidate.observations) {
      if (!observation?.field) throw new Error('approved observation field is required');
      next[observation.field] = observation.value;
      verifiedFields.add(observation.field);
      fieldVerification[observation.field] = {
        status: 'VERIFIED_OFFICIAL_WEB',
        sourceId: candidate.sourceId,
        observedAt: candidate.observedAt || candidate.evidence?.observedAt || null,
        reviewedAt: candidate.review?.reviewedAt || null,
        evidenceSha256: observation.evidenceSha256 || candidate.evidence?.sha256 || null
      };
    }
    evidence.push({ sourceId: candidate.sourceId, ...candidate.evidence, review: candidate.review });
  }

  const carriedForwardFields = Object.keys(baseRecord)
    .filter(field => !RECORD_META_FIELDS.has(field) && !verifiedFields.has(field))
    .sort();

  next.verification = carriedForwardFields.length
    ? 'PARTIALLY_VERIFIED_OFFICIAL_WEB'
    : 'VERIFIED_OFFICIAL_WEB';
  next.verificationScope = carriedForwardFields.length
    ? 'OBSERVED_FIELDS_ONLY'
    : 'FULL_RECORD';
  next.verifiedAt = snapshotMeta.snapshotDate || approved.map(c => c.review.reviewedAt.slice(0, 10)).sort().at(-1);
  next.fieldVerification = fieldVerification;
  next.carriedForwardFields = carriedForwardFields;
  next.evidence = evidence;
  return next;
}

async function collectSource(source, options = {}) {
  const envelope = await fetchEvidence(source, options);
  return extractCandidate(source, envelope);
}

module.exports = { STATES, sha256, fetchEvidence, extractCandidate, reviewCandidate, promoteApprovedCandidates, collectSource };
