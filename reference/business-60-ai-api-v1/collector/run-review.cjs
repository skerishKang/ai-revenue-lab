#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { buildReviewPacket, renderReviewMarkdown, generatePromotionArtifacts } = require('./review-promotion.cjs');

function parseArgs(argv) {
  const out = { command: argv[2] || null };
  for (let i = 3; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith('--')) continue;
    const key = arg.slice(2).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
    out[key] = argv[++i];
  }
  return out;
}

function readJson(file) {
  return JSON.parse(fs.readFileSync(path.resolve(file), 'utf8'));
}

function readCandidates(file) {
  const payload = readJson(file);
  const candidates = Array.isArray(payload) ? payload : payload.candidates;
  if (!Array.isArray(candidates)) throw new Error('candidate file must contain an array or { candidates: [] }');
  return candidates;
}

function readSnapshot(file) {
  const abs = path.resolve(file);
  const text = fs.readFileSync(abs, 'utf8');
  if (abs.endsWith('.json')) {
    const parsed = JSON.parse(text);
    if (parsed?.snapshot?.records) return parsed.snapshot;
    if (parsed?.records) return parsed;
    if (Array.isArray(parsed?.snapshots) && parsed.snapshots.length) return parsed.snapshots.at(-1);
    throw new Error('JSON snapshot file does not contain a snapshot record set');
  }

  const sandbox = { window: {} };
  vm.runInNewContext(text, sandbox, { filename: abs, timeout: 1000 });
  const snapshots = sandbox.window.B60_SNAPSHOTS;
  if (!Array.isArray(snapshots) || !snapshots.length) throw new Error('JS snapshot file must assign window.B60_SNAPSHOTS');
  return JSON.parse(JSON.stringify(snapshots.at(-1)));
}

function write(file, data) {
  const abs = path.resolve(file);
  fs.mkdirSync(path.dirname(abs), { recursive: true });
  fs.writeFileSync(abs, typeof data === 'string' ? data : `${JSON.stringify(data, null, 2)}\n`);
}

function help() {
  console.log('B60 human review / snapshot proposal CLI');
  console.log('');
  console.log('Packet:');
  console.log('  node run-review.cjs packet --candidates candidates.json --snapshot ../data/snapshots.js --out review-packet.json --markdown review-packet.md');
  console.log('');
  console.log('Promote:');
  console.log('  node run-review.cjs promote --candidates candidates.json --snapshot ../data/snapshots.js --decisions decisions.json --out-dir ./promotion --date 2026-08-24 --captured-at 2026-08-24T06:00:00.000Z');
  console.log('');
  console.log('Promotion emits proposals only. It never edits snapshots.js or publishes/deploys anything.');
}

(function main() {
  const cli = parseArgs(process.argv);
  if (!cli.command || cli.command === 'help' || cli.command === '--help') {
    help();
    process.exit(0);
  }
  if (!cli.candidates || !cli.snapshot) throw new Error('--candidates and --snapshot are required');
  const candidates = readCandidates(cli.candidates);
  const baseSnapshot = readSnapshot(cli.snapshot);

  if (cli.command === 'packet') {
    if (!cli.out || !cli.markdown) throw new Error('packet requires --out and --markdown');
    const packet = buildReviewPacket(candidates, baseSnapshot, { generatedAt: cli.generatedAt });
    write(cli.out, packet);
    write(cli.markdown, renderReviewMarkdown(packet));
    console.log(`PACKET_ID=${packet.packetId}`);
    console.log(`REVIEW_REQUIRED=${packet.summary.reviewRequired}`);
    console.log(`APPROVABLE=${packet.summary.approvable}`);
    console.log('PUBLICATION_AUTHORITY=REVIEW_REQUIRED');
    return;
  }

  if (cli.command === 'promote') {
    if (!cli.decisions || !cli.outDir || !cli.date || !cli.capturedAt) {
      throw new Error('promote requires --decisions --out-dir --date --captured-at');
    }
    const decisions = readJson(cli.decisions);
    const artifacts = generatePromotionArtifacts(candidates, baseSnapshot, decisions, {
      generatedAt: cli.generatedAt || cli.capturedAt,
      snapshotDate: cli.date,
      capturedAt: cli.capturedAt
    });
    const outDir = path.resolve(cli.outDir);
    write(path.join(outDir, 'review-packet.json'), artifacts.packet);
    write(path.join(outDir, 'review-packet.md'), renderReviewMarkdown(artifacts.packet));
    write(path.join(outDir, 'reviewed-candidates.json'), {
      publicationAuthority: 'HUMAN_EXPLICIT_PUBLISH_REQUIRED',
      candidates: artifacts.reviewedCandidates
    });
    write(path.join(outDir, 'snapshot-proposal.json'), artifacts.proposal);
    write(path.join(outDir, 'change-ledger.json'), artifacts.changeLedger);
    console.log(`VERIFIED_CHANGES=${artifacts.changeLedger.summary.verifiedChanges}`);
    console.log(`REVERIFIED_UNCHANGED=${artifacts.changeLedger.summary.reverifiedUnchanged}`);
    console.log('PUBLISH_AUTHORIZED=false');
    console.log('PUBLICATION_AUTHORITY=HUMAN_EXPLICIT_PUBLISH_REQUIRED');
    return;
  }

  throw new Error(`unknown command: ${cli.command}`);
})();
