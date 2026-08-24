'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { STATES } = require('./intake-core.cjs');
const {
  candidateId, buildReviewPacket, renderReviewMarkdown, applyReviewDecisions,
  buildSnapshotProposal, buildChangeLedger, generatePromotionArtifacts
} = require('./review-promotion.cjs');

function candidate(overrides = {}) {
  return {
    state: STATES.NEEDS_REVIEW,
    sourceId: 'official-source',
    signalId: 'signal-1',
    provider: 'Example',
    authority: 'PRIMARY_OFFICIAL',
    observedAt: '2026-08-24T01:00:00.000Z',
    evidence: {
      requestedUrl: 'https://example.com',
      finalUrl: 'https://example.com',
      observedAt: '2026-08-24T01:00:00.000Z',
      httpStatus: 200,
      sha256: 'hash-1'
    },
    observations: [{
      field: 'freeLabel',
      value: '50 requests / day',
      status: 'OBSERVED_PRIMARY_SOURCE',
      evidenceSha256: 'hash-1',
      excerpt: '50 requests per day'
    }],
    missingRequired: [],
    review: null,
    ...overrides
  };
}

function snapshot() {
  return {
    capturedAt: '2026-08-23T00:00:00Z',
    date: '2026-08-23',
    verification: 'OFFICIAL_SOURCE_SNAPSHOT',
    records: [
      { id: 'signal-1', provider: 'Example', freeLabel: '10 requests / day', price: '$0 historical', access: ['API'] },
      { id: 'signal-2', provider: 'Other', freeLabel: 'Free tier', price: 'Free' }
    ]
  };
}

test('review packet is deterministic and exposes old/new values plus carried-forward preview', () => {
  const c = candidate();
  const a = buildReviewPacket([c], snapshot(), { generatedAt: '2026-08-24T02:00:00Z' });
  const b = buildReviewPacket([c], snapshot(), { generatedAt: 'later' });
  assert.equal(a.packetId, b.packetId);
  assert.equal(a.candidates[0].canApprove, true);
  assert.equal(a.candidates[0].fields[0].previousValue, '10 requests / day');
  assert.equal(a.candidates[0].fields[0].changed, true);
  assert.deepEqual(a.candidates[0].carriedForwardPreview, ['access', 'price']);
  const md = renderReviewMarkdown(a);
  assert.match(md, /공식 소스 검토 패킷/);
  assert.match(md, /50 requests \/ day/);
  assert.match(md, /게시 권한이 없습니다/);
});

test('promotion requires one explicit decision for every reviewable candidate', () => {
  const cs = [
    candidate(),
    candidate({
      sourceId: 'official-source-2',
      evidence: { requestedUrl: 'https://e2', finalUrl: 'https://e2', observedAt: '2026-08-24T01:02:00Z', httpStatus: 200, sha256: 'hash-2' },
      observations: [{ field: 'price', value: 'Provider dependent', status: 'OBSERVED_PRIMARY_SOURCE', evidenceSha256: 'hash-2' }]
    })
  ];
  const packet = buildReviewPacket(cs, snapshot());
  const doc = {
    packetId: packet.packetId,
    reviewer: 'owner',
    reviewedAt: '2026-08-24T02:00:00Z',
    decisions: [{ candidateId: packet.candidates[0].candidateId, decision: 'approve' }]
  };
  assert.throws(() => applyReviewDecisions(cs, packet, doc), /every reviewable candidate requires exactly one explicit decision/);
});

test('rejected candidate cannot change snapshot record', () => {
  const c = candidate();
  const packet = buildReviewPacket([c], snapshot());
  const reviewed = applyReviewDecisions([c], packet, {
    packetId: packet.packetId,
    reviewer: 'owner',
    reviewedAt: '2026-08-24T02:00:00Z',
    decisions: [{ candidateId: candidateId(c), decision: 'reject', reason: 'not enough context' }]
  });
  assert.equal(reviewed[0].state, STATES.REJECTED);
  assert.throws(
    () => buildSnapshotProposal(snapshot(), reviewed, { snapshotDate: '2026-08-24', capturedAt: '2026-08-24T02:10:00Z' }),
    /no approved candidates/
  );
});

test('missing required evidence cannot be approved', () => {
  const c = candidate({ missingRequired: ['freeLabel'] });
  const packet = buildReviewPacket([c], snapshot());
  assert.equal(packet.candidates[0].canApprove, false);
  assert.throws(() => applyReviewDecisions([c], packet, {
    packetId: packet.packetId,
    reviewer: 'owner',
    reviewedAt: '2026-08-24T02:00:00Z',
    decisions: [{ candidateId: candidateId(c), decision: 'approve' }]
  }), /candidate approval blocked/);
});

test('snapshot proposal changes only approved fields and never grants publication authority', () => {
  const c = candidate();
  const packet = buildReviewPacket([c], snapshot());
  const reviewed = applyReviewDecisions([c], packet, {
    packetId: packet.packetId,
    reviewer: 'owner',
    reviewedAt: '2026-08-24T02:00:00Z',
    decisions: [{ candidateId: candidateId(c), decision: 'approve' }]
  });
  const proposal = buildSnapshotProposal(snapshot(), reviewed, {
    snapshotDate: '2026-08-24',
    capturedAt: '2026-08-24T02:10:00Z'
  });
  const r = proposal.snapshot.records[0];
  assert.equal(proposal.publishAuthorized, false);
  assert.equal(proposal.publicationAuthority, 'HUMAN_EXPLICIT_PUBLISH_REQUIRED');
  assert.equal(r.freeLabel, '50 requests / day');
  assert.equal(r.price, '$0 historical');
  assert.deepEqual(r.carriedForwardFields, ['access', 'price']);
  assert.equal(r.fieldVerification.price, undefined);
  assert.deepEqual(proposal.snapshot.records[1], snapshot().records[1]);
});

test('change ledger contains only freshly verified field changes, never carried-forward fields', () => {
  const c = candidate();
  const packet = buildReviewPacket([c], snapshot());
  const decisions = {
    packetId: packet.packetId,
    reviewer: 'owner',
    reviewedAt: '2026-08-24T02:00:00Z',
    decisions: [{ candidateId: candidateId(c), decision: 'approve' }]
  };
  const { proposal, changeLedger } = generatePromotionArtifacts([c], snapshot(), decisions, {
    generatedAt: '2026-08-24T02:05:00Z',
    snapshotDate: '2026-08-24',
    capturedAt: '2026-08-24T02:10:00Z'
  });
  assert.equal(proposal.publishAuthorized, false);
  assert.equal(changeLedger.publishAuthorized, false);
  assert.equal(changeLedger.changes.length, 1);
  assert.equal(changeLedger.changes[0].field, 'freeLabel');
  assert.equal(changeLedger.changes[0].before, '10 requests / day');
  assert.equal(changeLedger.changes[0].after, '50 requests / day');
  assert.equal(changeLedger.changes.some(x => x.field === 'price'), false);
});

test('reverified unchanged fields are separated from actual changes', () => {
  const c = candidate({ observations: [{ field: 'freeLabel', value: '10 requests / day', status: 'OBSERVED_PRIMARY_SOURCE', evidenceSha256: 'hash-1' }] });
  const packet = buildReviewPacket([c], snapshot());
  const reviewed = applyReviewDecisions([c], packet, {
    packetId: packet.packetId,
    reviewer: 'owner',
    reviewedAt: '2026-08-24T02:00:00Z',
    decisions: [{ candidateId: candidateId(c), decision: 'approve' }]
  });
  const proposal = buildSnapshotProposal(snapshot(), reviewed, {
    snapshotDate: '2026-08-24',
    capturedAt: '2026-08-24T02:10:00Z'
  });
  const ledger = buildChangeLedger(snapshot(), proposal);
  assert.equal(ledger.changes.length, 0);
  assert.equal(ledger.reverifiedUnchanged.length, 1);
  assert.equal(ledger.reverifiedUnchanged[0].field, 'freeLabel');
});
