#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const manifest = require('./source-manifest.cjs');

const ALLOWED_STATES = new Set(['NEEDS_REVIEW', 'REJECTED']);

function parseArgs(argv) {
  const out = { input: null, summary: null, sha: null };
  for (let i = 2; i < argv.length; i += 1) {
    if (argv[i] === '--input') out.input = argv[++i];
    else if (argv[i] === '--summary') out.summary = argv[++i];
    else if (argv[i] === '--sha') out.sha = argv[++i];
    else if (argv[i] === '--help') out.help = true;
    else throw new Error(`unknown argument: ${argv[i]}`);
  }
  return out;
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function hasOwn(value, key) {
  return Object.prototype.hasOwnProperty.call(value, key);
}

function validatePayload(payload) {
  assert(payload && typeof payload === 'object' && !Array.isArray(payload), 'payload must be an object');
  assert(payload.publicationAuthority === 'REVIEW_REQUIRED', 'publicationAuthority must be REVIEW_REQUIRED');
  assert(typeof payload.generatedAt === 'string' && payload.generatedAt.length > 0, 'generatedAt is required');
  assert(Array.isArray(payload.candidates), 'candidates must be an array');

  const expectedIds = manifest.map(source => source.id);
  const expectedSet = new Set(expectedIds);
  assert(expectedSet.size === expectedIds.length, 'source manifest contains duplicate ids');
  assert(payload.candidates.length === expectedIds.length,
    `candidate count ${payload.candidates.length} does not match manifest count ${expectedIds.length}`);

  const seen = new Set();
  const rows = [];
  let reviewable = 0;
  let rejected = 0;

  for (const candidate of payload.candidates) {
    assert(candidate && typeof candidate === 'object' && !Array.isArray(candidate), 'candidate must be an object');
    assert(typeof candidate.sourceId === 'string' && expectedSet.has(candidate.sourceId),
      `unexpected sourceId: ${candidate.sourceId}`);
    assert(!seen.has(candidate.sourceId), `duplicate candidate sourceId: ${candidate.sourceId}`);
    seen.add(candidate.sourceId);

    assert(ALLOWED_STATES.has(candidate.state),
      `scheduled intake emitted forbidden state ${candidate.state} for ${candidate.sourceId}`);
    assert(candidate.review == null,
      `scheduled intake must not contain a human review for ${candidate.sourceId}`);
    assert(!hasOwn(candidate, 'body'),
      `scheduled intake artifact must not contain raw page body for ${candidate.sourceId}`);

    if (candidate.state === 'NEEDS_REVIEW') {
      reviewable += 1;
      assert(candidate.evidence && typeof candidate.evidence === 'object',
        `reviewable candidate missing evidence: ${candidate.sourceId}`);
      assert(typeof candidate.evidence.sha256 === 'string' && /^[a-f0-9]{64}$/.test(candidate.evidence.sha256),
        `reviewable candidate missing evidence SHA-256: ${candidate.sourceId}`);
      assert(Array.isArray(candidate.observations),
        `reviewable candidate observations must be an array: ${candidate.sourceId}`);
      assert(Array.isArray(candidate.missingRequired),
        `reviewable candidate missingRequired must be an array: ${candidate.sourceId}`);
    } else {
      rejected += 1;
      assert(typeof candidate.reason === 'string' && candidate.reason.length > 0,
        `rejected candidate must explain its reason: ${candidate.sourceId}`);
    }

    rows.push({
      sourceId: candidate.sourceId,
      signalId: candidate.signalId || '',
      state: candidate.state,
      observations: Array.isArray(candidate.observations) ? candidate.observations.length : 0,
      missingRequired: Array.isArray(candidate.missingRequired) ? candidate.missingRequired.length : 0,
      reason: candidate.reason || ''
    });
  }

  for (const sourceId of expectedIds) {
    assert(seen.has(sourceId), `manifest source missing from scheduled intake output: ${sourceId}`);
  }

  return {
    generatedAt: payload.generatedAt,
    publicationAuthority: payload.publicationAuthority,
    manifestSources: expectedIds.length,
    reviewable,
    rejected,
    rows
  };
}

function cell(value) {
  return String(value ?? '').replace(/\|/g, '\\|').replace(/\r?\n/g, ' ');
}

function renderSummary(audit, sha = null) {
  const lines = [
    '# B60 official-source intake',
    '',
    `- Generated: \`${cell(audit.generatedAt)}\``,
    `- Repository SHA: \`${cell(sha || 'unknown')}\``,
    `- Manifest sources: **${audit.manifestSources}**`,
    `- NEEDS_REVIEW: **${audit.reviewable}**`,
    `- REJECTED: **${audit.rejected}**`,
    `- Publication authority: \`${audit.publicationAuthority}\``,
    '',
    '| Source | Signal | State | Observations | Missing required | Reason |',
    '|---|---|---|---:|---:|---|'
  ];

  for (const row of audit.rows) {
    lines.push(`| ${cell(row.sourceId)} | ${cell(row.signalId)} | ${cell(row.state)} | ${row.observations} | ${row.missingRequired} | ${cell(row.reason)} |`);
  }

  lines.push(
    '',
    '> REVIEW ARTIFACT ONLY — no candidate was approved, no snapshot was written, no publication occurred, and no deployment occurred.',
    '',
    '`AUTO_APPROVAL=0` · `AUTO_SNAPSHOT_WRITE=0` · `AUTO_PUBLICATION=0` · `AUTO_DEPLOY=0`',
    ''
  );
  return lines.join('\n');
}

function main() {
  const cli = parseArgs(process.argv);
  if (cli.help) {
    console.log('Usage: node audit-intake-output.cjs --input candidates.json --summary summary.md [--sha commit-sha]');
    console.log('Validates scheduled intake as review-only and writes a human-readable summary.');
    return;
  }
  assert(cli.input, '--input is required');
  assert(cli.summary, '--summary is required');

  const payload = JSON.parse(fs.readFileSync(path.resolve(cli.input), 'utf8'));
  const audit = validatePayload(payload);
  const summary = renderSummary(audit, cli.sha);
  const summaryPath = path.resolve(cli.summary);
  fs.mkdirSync(path.dirname(summaryPath), { recursive: true });
  fs.writeFileSync(summaryPath, summary + '\n');
  process.stdout.write(JSON.stringify({
    manifestSources: audit.manifestSources,
    needsReview: audit.reviewable,
    rejected: audit.rejected,
    publicationAuthority: audit.publicationAuthority,
    autoApproval: 0,
    autoSnapshotWrite: 0,
    autoPublication: 0,
    autoDeploy: 0
  }) + '\n');
}

if (require.main === module) main();

module.exports = { validatePayload, renderSummary };
