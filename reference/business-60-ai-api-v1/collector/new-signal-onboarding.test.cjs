'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { STATES } = require('./intake-core.cjs');
const {
  ONBOARDING_TYPES, candidateId, buildReviewPacket, renderReviewMarkdown,
  applyReviewDecisions, buildSnapshotProposal, buildChangeLedger, generatePromotionArtifacts
} = require('./review-promotion.cjs');

function baseSnapshot() {
  return {
    capturedAt: '2026-08-23T00:00:00Z',
    date: '2026-08-23',
    verification: 'OFFICIAL_SOURCE_SNAPSHOT',
    records: [
      { id: 'signal-1', provider: 'Existing', freeLabel: '10/day', price: '$0', access: ['API'] }
    ]
  };
}

function newCandidate(overrides = {}) {
  return {
    state: STATES.NEEDS_REVIEW,
    sourceId: 'new-provider-pricing',
    signalId: 'new-signal',
    provider: 'New Provider',
    authority: 'PRIMARY_OFFICIAL',
    observedAt: '2026-08-25T01:00:00.000Z',
    evidence: {
      requestedUrl: 'https://provider.example/pricing',
      finalUrl: 'https://provider.example/pricing',
      observedAt: '2026-08-25T01:00:00.000Z',
      httpStatus: 200,
      sha256: 'new-hash'
    },
    observations: [
      { field: 'freeLabel', value: 'Free tier', status: 'OBSERVED_PRIMARY_SOURCE', evidenceSha256: 'new-hash' },
      { field: 'price', value: '$0 trial', status: 'OBSERVED_PRIMARY_SOURCE', evidenceSha256: 'new-hash' },
      { field: 'access', value: ['API'], status: 'OBSERVED_PRIMARY_SOURCE', evidenceSha256: 'new-hash' }
    ],
    missingRequired: [],
    review: null,
    ...overrides
  };
}

function decisionsFor(packet, decision = 'approve') {
  return {
    packetId: packet.packetId,
    reviewer: 'owner',
    reviewedAt: '2026-08-25T02:00:00.000Z',
    decisions: packet.candidates.filter(x => x.reviewRequired).map(x => ({ candidateId: x.candidateId, decision }))
  };
}

test('NEW signal is explicit in review packet and has NONE previous value semantics', () => {
  const packet = buildReviewPacket([newCandidate()], baseSnapshot(), { generatedAt: '2026-08-25T01:10:00Z' });
  const entry = packet.candidates[0];
  assert.equal(entry.onboardingType, ONBOARDING_TYPES.NEW_SIGNAL);
  assert.equal(entry.canApprove, true);
  assert.equal(entry.fields[0].previousValue, null);
  assert.equal(entry.fields[0].previousValueState, 'NONE');
  assert.equal(packet.summary.newSignals, 1);
  assert.match(renderReviewMarkdown(packet), /NEW_SIGNAL/);
  assert.match(renderReviewMarkdown(packet), /NONE/);
});

test('NEW signal without explicit human review cannot reach snapshot proposal', () => {
  const c = newCandidate({
    state: STATES.APPROVED_FOR_SNAPSHOT,
    onboardingType: ONBOARDING_TYPES.NEW_SIGNAL,
    review: null
  });
  assert.throws(() => buildSnapshotProposal(baseSnapshot(), [c], {
    snapshotDate: '2026-08-25', capturedAt: '2026-08-25T02:10:00Z'
  }), /explicit human review/);
});

test('NEW signal missing required evidence cannot be approved', () => {
  const c = newCandidate({ missingRequired: ['freeLabel'] });
  const packet = buildReviewPacket([c], baseSnapshot());
  assert.equal(packet.candidates[0].canApprove, false);
  assert.throws(() => applyReviewDecisions([c], packet, decisionsFor(packet)), /candidate approval blocked/);
});

test('NEW signal requires PRIMARY_OFFICIAL evidence and source identity', () => {
  const c = newCandidate({ authority: 'SECONDARY', evidence: { sha256: null } });
  const packet = buildReviewPacket([c], baseSnapshot());
  assert.equal(packet.candidates[0].canApprove, false);
  assert.ok(packet.candidates[0].blockers.includes('PRIMARY_OFFICIAL_REQUIRED'));
  assert.ok(packet.candidates[0].blockers.includes('EVIDENCE_SHA256_REQUIRED'));
  assert.ok(packet.candidates[0].blockers.includes('OFFICIAL_SOURCE_URL_REQUIRED'));
});

test('human-approved NEW signal appends with full field-level provenance but no publication authority', () => {
  const c = newCandidate();
  const packet = buildReviewPacket([c], baseSnapshot());
  const reviewed = applyReviewDecisions([c], packet, decisionsFor(packet));
  assert.equal(reviewed[0].onboardingType, ONBOARDING_TYPES.NEW_SIGNAL);
  const proposal = buildSnapshotProposal(baseSnapshot(), reviewed, {
    snapshotDate: '2026-08-25', capturedAt: '2026-08-25T02:10:00Z'
  });
  assert.equal(proposal.publicationAuthority, 'HUMAN_EXPLICIT_PUBLISH_REQUIRED');
  assert.equal(proposal.publishAuthorized, false);
  assert.equal(proposal.snapshot.records.length, 2);
  const added = proposal.snapshot.records.find(r => r.id === 'new-signal');
  assert.ok(added);
  assert.equal(added.verification, 'VERIFIED_OFFICIAL_WEB');
  assert.equal(added.verificationScope, 'FULL_RECORD');
  assert.deepEqual(added.carriedForwardFields, []);
  for (const field of ['id', 'provider', 'freeLabel', 'price', 'access']) {
    assert.equal(added.fieldVerification[field].status, 'VERIFIED_OFFICIAL_WEB');
    assert.equal(added.fieldVerification[field].sourceId, 'new-provider-pricing');
  }
});

test('scheduler-like NEEDS_REVIEW output cannot create a NEW snapshot record', () => {
  const c = newCandidate();
  assert.throws(() => buildSnapshotProposal(baseSnapshot(), [c], {
    snapshotDate: '2026-08-25', capturedAt: '2026-08-25T02:10:00Z'
  }), /no approved candidates/);
});

test('duplicate NEW signal id against base snapshot is rejected', () => {
  const c = newCandidate({
    signalId: 'signal-1',
    state: STATES.APPROVED_FOR_SNAPSHOT,
    onboardingType: ONBOARDING_TYPES.NEW_SIGNAL,
    review: { decision: 'approve', reviewer: 'owner', reviewedAt: '2026-08-25T02:00:00Z' }
  });
  assert.throws(() => buildSnapshotProposal(baseSnapshot(), [c], {
    snapshotDate: '2026-08-25', capturedAt: '2026-08-25T02:10:00Z'
  }), /duplicate signal id/);
});

test('existing signal update and carried-forward behavior remain unchanged', () => {
  const c = newCandidate({
    signalId: 'signal-1', provider: 'Existing', sourceId: 'existing-official',
    observations: [{ field: 'freeLabel', value: '50/day', status: 'OBSERVED_PRIMARY_SOURCE', evidenceSha256: 'new-hash' }]
  });
  const packet = buildReviewPacket([c], baseSnapshot());
  assert.equal(packet.candidates[0].onboardingType, ONBOARDING_TYPES.EXISTING_SIGNAL);
  assert.deepEqual(packet.candidates[0].carriedForwardPreview, ['access', 'price']);
  const reviewed = applyReviewDecisions([c], packet, decisionsFor(packet));
  const proposal = buildSnapshotProposal(baseSnapshot(), reviewed, {
    snapshotDate: '2026-08-25', capturedAt: '2026-08-25T02:10:00Z'
  });
  const updated = proposal.snapshot.records[0];
  assert.equal(updated.freeLabel, '50/day');
  assert.equal(updated.price, '$0');
  assert.deepEqual(updated.carriedForwardFields, ['access', 'price']);
  assert.equal(updated.fieldVerification.price, undefined);
});

test('Change Ledger separates FIRST_SEEN from VERIFIED_CHANGE', () => {
  const newC = newCandidate();
  const updateC = newCandidate({
    signalId: 'signal-1', provider: 'Existing', sourceId: 'existing-official',
    observations: [{ field: 'freeLabel', value: '50/day', status: 'OBSERVED_PRIMARY_SOURCE', evidenceSha256: 'new-hash' }]
  });
  const packet = buildReviewPacket([newC, updateC], baseSnapshot());
  const { proposal, changeLedger } = generatePromotionArtifacts([newC, updateC], baseSnapshot(), decisionsFor(packet), {
    generatedAt: '2026-08-25T02:05:00Z', snapshotDate: '2026-08-25', capturedAt: '2026-08-25T02:10:00Z'
  });
  assert.equal(proposal.publishAuthorized, false);
  assert.equal(changeLedger.publishAuthorized, false);
  assert.equal(changeLedger.changes.length, 1);
  assert.equal(changeLedger.changes[0].status, 'VERIFIED_CHANGE');
  assert.ok(changeLedger.firstSeen.length >= 5);
  assert.ok(changeLedger.firstSeen.every(x => x.status === 'FIRST_SEEN'));
  assert.equal(changeLedger.summary.firstSeen, changeLedger.firstSeen.length);
});

test('duplicate review candidates are rejected deterministically', () => {
  const c = newCandidate();
  assert.throws(() => buildReviewPacket([c, { ...c }], baseSnapshot()), /duplicate review candidate id/);
});
