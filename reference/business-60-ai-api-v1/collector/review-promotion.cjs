'use strict';

const { STATES, sha256, reviewCandidate, promoteApprovedCandidates } = require('./intake-core.cjs');

const RECORD_META_FIELDS = new Set([
  'id', 'provider', 'verification', 'verifiedAt', 'verificationScope',
  'evidence', 'fieldVerification', 'carriedForwardFields'
]);

function sameValue(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

function assertSnapshot(snapshot) {
  if (!snapshot || !Array.isArray(snapshot.records)) throw new Error('snapshot.records is required');
  const ids = snapshot.records.map(record => record?.id);
  if (ids.some(id => !id)) throw new Error('snapshot record id is required');
  if (new Set(ids).size !== ids.length) throw new Error('snapshot record ids must be unique');
}

function candidateId(candidate) {
  const identity = {
    sourceId: candidate?.sourceId || null,
    signalId: candidate?.signalId || null,
    observedAt: candidate?.observedAt || candidate?.evidence?.observedAt || null,
    evidenceSha256: candidate?.evidence?.sha256 || null,
    observations: (candidate?.observations || []).map(x => ({ field: x.field, value: x.value }))
  };
  return `${identity.signalId || 'unknown'}::${identity.sourceId || 'unknown'}::${sha256(JSON.stringify(identity)).slice(0, 16)}`;
}

function buildReviewPacket(candidates, baseSnapshot, meta = {}) {
  assertSnapshot(baseSnapshot);
  if (!Array.isArray(candidates)) throw new Error('candidates array is required');
  const baseById = new Map(baseSnapshot.records.map(record => [record.id, record]));

  const entries = candidates.map(candidate => {
    const id = candidateId(candidate);
    const baseRecord = baseById.get(candidate?.signalId) || null;
    const reviewRequired = candidate?.state === STATES.NEEDS_REVIEW;
    const observations = candidate?.observations || [];
    const observedFields = new Set(observations.map(x => x.field).filter(Boolean));
    const blockers = [];
    if (reviewRequired && !baseRecord) blockers.push('BASE_RECORD_MISSING');
    if (reviewRequired && !observations.length) blockers.push('NO_OBSERVATIONS');
    for (const field of candidate?.missingRequired || []) blockers.push(`MISSING_REQUIRED:${field}`);
    if (!reviewRequired) blockers.push(`NOT_REVIEWABLE_STATE:${candidate?.state || 'UNKNOWN'}`);

    const fields = observations.map(observation => ({
      field: observation.field,
      previousValue: baseRecord ? baseRecord[observation.field] : undefined,
      proposedValue: observation.value,
      changed: baseRecord ? !sameValue(baseRecord[observation.field], observation.value) : true,
      observationStatus: observation.status || null,
      evidenceSha256: observation.evidenceSha256 || candidate?.evidence?.sha256 || null,
      excerpt: observation.excerpt || null
    }));

    const carriedForwardPreview = baseRecord
      ? Object.keys(baseRecord)
          .filter(field => !RECORD_META_FIELDS.has(field) && !observedFields.has(field))
          .sort()
      : [];

    return {
      candidateId: id,
      state: candidate?.state || null,
      reviewRequired,
      canApprove: reviewRequired && blockers.length === 0,
      sourceId: candidate?.sourceId || null,
      signalId: candidate?.signalId || null,
      provider: candidate?.provider || baseRecord?.provider || null,
      authority: candidate?.authority || null,
      observedAt: candidate?.observedAt || candidate?.evidence?.observedAt || null,
      evidence: candidate?.evidence || null,
      missingRequired: [...(candidate?.missingRequired || [])],
      blockers,
      fields,
      carriedForwardPreview,
      decision: null
    };
  }).sort((a, b) => `${a.signalId}\0${a.sourceId}\0${a.candidateId}`.localeCompare(`${b.signalId}\0${b.sourceId}\0${b.candidateId}`));

  const packetBasis = {
    sourceSnapshotDate: baseSnapshot.date || null,
    candidateIds: entries.map(entry => entry.candidateId)
  };

  return {
    schemaVersion: 'b60-review-packet-v1',
    packetId: `b60rp_${sha256(JSON.stringify(packetBasis)).slice(0, 20)}`,
    generatedAt: meta.generatedAt || new Date().toISOString(),
    sourceSnapshotDate: baseSnapshot.date || null,
    publicationAuthority: 'REVIEW_REQUIRED',
    candidates: entries,
    summary: {
      total: entries.length,
      reviewRequired: entries.filter(x => x.reviewRequired).length,
      approvable: entries.filter(x => x.canApprove).length,
      blocked: entries.filter(x => x.reviewRequired && !x.canApprove).length,
      preRejected: entries.filter(x => !x.reviewRequired).length
    }
  };
}

function renderReviewMarkdown(packet) {
  if (!packet || packet.schemaVersion !== 'b60-review-packet-v1') throw new Error('invalid review packet');
  const lines = [
    '# B60 공식 소스 검토 패킷',
    '',
    `- Packet ID: \`${packet.packetId}\``,
    `- 기준 snapshot: \`${packet.sourceSnapshotDate || 'NONE'}\``,
    `- 검토 필요: **${packet.summary.reviewRequired}**`,
    `- 승인 가능: **${packet.summary.approvable}**`,
    `- 승인 차단: **${packet.summary.blocked}**`,
    '',
    '> 이 문서는 검토용입니다. 이 패킷 자체에는 게시 권한이 없습니다.',
    ''
  ];

  for (const entry of packet.candidates) {
    lines.push(`## ${entry.provider || entry.signalId || 'Unknown'} · ${entry.sourceId || 'unknown-source'}`);
    lines.push('');
    lines.push(`- Candidate ID: \`${entry.candidateId}\``);
    lines.push(`- 상태: \`${entry.state}\``);
    lines.push(`- 승인 가능: **${entry.canApprove ? 'YES' : 'NO'}**`);
    lines.push(`- 관측 시각: \`${entry.observedAt || 'UNKNOWN'}\``);
    if (entry.evidence?.finalUrl || entry.evidence?.requestedUrl) lines.push(`- 공식 근거: ${entry.evidence.finalUrl || entry.evidence.requestedUrl}`);
    if (entry.evidence?.sha256) lines.push(`- Evidence SHA-256: \`${entry.evidence.sha256}\``);
    if (entry.blockers.length) lines.push(`- 차단 사유: ${entry.blockers.map(x => `\`${x}\``).join(', ')}`);
    lines.push('');

    if (entry.fields.length) {
      lines.push('| 필드 | 기존 값 | 관측 값 | 변경 |');
      lines.push('|---|---|---|---|');
      for (const field of entry.fields) {
        const before = field.previousValue === undefined ? '—' : String(field.previousValue).replace(/\|/g, '\\|');
        const after = field.proposedValue === undefined ? '—' : String(field.proposedValue).replace(/\|/g, '\\|');
        lines.push(`| \`${field.field}\` | ${before} | ${after} | ${field.changed ? 'YES' : 'NO'} |`);
      }
      lines.push('');
      for (const field of entry.fields.filter(x => x.excerpt)) {
        lines.push(`- **${field.field} 근거 문맥:** ${field.excerpt}`);
      }
      if (entry.fields.some(x => x.excerpt)) lines.push('');
    }

    if (entry.carriedForwardPreview.length) {
      lines.push(`- 이번 근거에서 관측되지 않아 이전 값을 유지할 필드: ${entry.carriedForwardPreview.map(x => `\`${x}\``).join(', ')}`);
      lines.push('');
    }
    if (entry.reviewRequired) {
      lines.push('- 결정: `[ ] approve` / `[ ] reject`');
      lines.push('');
    }
  }

  lines.push('## 결정 파일 형식');
  lines.push('');
  lines.push('```json');
  lines.push(JSON.stringify({
    packetId: packet.packetId,
    reviewer: 'human-reviewer',
    reviewedAt: '2026-08-24T00:00:00.000Z',
    decisions: packet.candidates.filter(x => x.reviewRequired).map(x => ({ candidateId: x.candidateId, decision: 'approve', reason: null }))
  }, null, 2));
  lines.push('```');
  lines.push('');
  return `${lines.join('\n')}\n`;
}

function applyReviewDecisions(candidates, packet, decisionDoc) {
  if (!packet || packet.schemaVersion !== 'b60-review-packet-v1') throw new Error('invalid review packet');
  if (!decisionDoc || decisionDoc.packetId !== packet.packetId) throw new Error('decision packetId mismatch');
  if (!decisionDoc.reviewer) throw new Error('decision reviewer is required');
  if (!decisionDoc.reviewedAt) throw new Error('decision reviewedAt is required');
  if (!Array.isArray(decisionDoc.decisions)) throw new Error('decisions array is required');

  const requiredIds = packet.candidates.filter(x => x.reviewRequired).map(x => x.candidateId).sort();
  const byId = new Map();
  for (const decision of decisionDoc.decisions) {
    if (!decision?.candidateId) throw new Error('decision candidateId is required');
    if (byId.has(decision.candidateId)) throw new Error(`duplicate decision: ${decision.candidateId}`);
    if (!['approve', 'reject'].includes(decision.decision)) throw new Error(`invalid decision for ${decision.candidateId}`);
    byId.set(decision.candidateId, decision);
  }
  const decisionIds = [...byId.keys()].sort();
  if (!sameValue(requiredIds, decisionIds)) throw new Error('every reviewable candidate requires exactly one explicit decision');

  const packetById = new Map(packet.candidates.map(entry => [entry.candidateId, entry]));
  return candidates.map(candidate => {
    if (candidate?.state !== STATES.NEEDS_REVIEW) return candidate;
    const id = candidateId(candidate);
    const packetEntry = packetById.get(id);
    if (!packetEntry) throw new Error(`candidate missing from packet: ${id}`);
    const decision = byId.get(id);
    if (decision.decision === 'approve' && !packetEntry.canApprove) throw new Error(`candidate approval blocked: ${id}`);
    return reviewCandidate(candidate, {
      decision: decision.decision,
      reviewer: decisionDoc.reviewer,
      reviewedAt: decisionDoc.reviewedAt,
      reason: decision.reason || null
    });
  });
}

function buildSnapshotProposal(baseSnapshot, reviewedCandidates, meta = {}) {
  assertSnapshot(baseSnapshot);
  if (!Array.isArray(reviewedCandidates)) throw new Error('reviewedCandidates array is required');
  if (!meta.snapshotDate) throw new Error('snapshotDate is required');
  if (!meta.capturedAt) throw new Error('capturedAt is required');

  const approved = reviewedCandidates.filter(candidate => candidate?.state === STATES.APPROVED_FOR_SNAPSHOT);
  if (!approved.length) throw new Error('no approved candidates for snapshot proposal');

  const groups = new Map();
  for (const candidate of approved) {
    if (!groups.has(candidate.signalId)) groups.set(candidate.signalId, []);
    groups.get(candidate.signalId).push(candidate);
  }

  const baseIds = new Set(baseSnapshot.records.map(record => record.id));
  for (const signalId of groups.keys()) {
    if (!baseIds.has(signalId)) throw new Error(`base snapshot record missing: ${signalId}`);
  }

  const records = baseSnapshot.records.map(record => {
    const group = groups.get(record.id);
    if (!group) return record;
    return promoteApprovedCandidates(record, group, { snapshotDate: meta.snapshotDate });
  });

  return {
    schemaVersion: 'b60-snapshot-proposal-v1',
    generatedAt: meta.generatedAt || meta.capturedAt,
    sourceSnapshotDate: baseSnapshot.date || null,
    publicationAuthority: 'HUMAN_EXPLICIT_PUBLISH_REQUIRED',
    publishAuthorized: false,
    snapshot: {
      capturedAt: meta.capturedAt,
      date: meta.snapshotDate,
      verification: 'REVIEWED_SOURCE_SNAPSHOT_PROPOSAL',
      records
    }
  };
}

function buildChangeLedger(baseSnapshot, snapshotProposal, meta = {}) {
  assertSnapshot(baseSnapshot);
  const nextSnapshot = snapshotProposal?.snapshot || snapshotProposal;
  assertSnapshot(nextSnapshot);
  const beforeById = new Map(baseSnapshot.records.map(record => [record.id, record]));
  const changes = [];
  const reverifiedUnchanged = [];

  for (const after of nextSnapshot.records) {
    const before = beforeById.get(after.id);
    if (!before) continue;
    for (const [field, verification] of Object.entries(after.fieldVerification || {})) {
      const entry = {
        signalId: after.id,
        provider: after.provider || before.provider || null,
        field,
        before: before[field],
        after: after[field],
        sourceId: verification.sourceId || null,
        observedAt: verification.observedAt || null,
        reviewedAt: verification.reviewedAt || null,
        evidenceSha256: verification.evidenceSha256 || null
      };
      if (sameValue(before[field], after[field])) reverifiedUnchanged.push(entry);
      else changes.push({ ...entry, status: 'VERIFIED_CHANGE' });
    }
  }

  changes.sort((a, b) => `${a.signalId}\0${a.field}`.localeCompare(`${b.signalId}\0${b.field}`));
  reverifiedUnchanged.sort((a, b) => `${a.signalId}\0${a.field}`.localeCompare(`${b.signalId}\0${b.field}`));

  return {
    schemaVersion: 'b60-change-ledger-v1',
    generatedAt: meta.generatedAt || snapshotProposal?.generatedAt || nextSnapshot.capturedAt || null,
    fromSnapshotDate: baseSnapshot.date || null,
    toSnapshotDate: nextSnapshot.date || null,
    publicationAuthority: 'HUMAN_EXPLICIT_PUBLISH_REQUIRED',
    publishAuthorized: false,
    changes,
    reverifiedUnchanged,
    summary: {
      verifiedChanges: changes.length,
      reverifiedUnchanged: reverifiedUnchanged.length
    }
  };
}

function generatePromotionArtifacts(candidates, baseSnapshot, decisionDoc, meta = {}) {
  const packet = buildReviewPacket(candidates, baseSnapshot, { generatedAt: meta.generatedAt });
  const reviewedCandidates = applyReviewDecisions(candidates, packet, decisionDoc);
  const proposal = buildSnapshotProposal(baseSnapshot, reviewedCandidates, meta);
  const changeLedger = buildChangeLedger(baseSnapshot, proposal, { generatedAt: meta.generatedAt });
  return { packet, reviewedCandidates, proposal, changeLedger };
}

module.exports = {
  candidateId,
  buildReviewPacket,
  renderReviewMarkdown,
  applyReviewDecisions,
  buildSnapshotProposal,
  buildChangeLedger,
  generatePromotionArtifacts
};
