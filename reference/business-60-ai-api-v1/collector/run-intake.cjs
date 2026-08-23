#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const manifest = require('./source-manifest.cjs');
const { collectSource } = require('./intake-core.cjs');

function args(argv) {
  const out = { source: null, output: null };
  for (let i = 2; i < argv.length; i += 1) {
    if (argv[i] === '--source') out.source = argv[++i];
    else if (argv[i] === '--out') out.output = argv[++i];
    else if (argv[i] === '--help') out.help = true;
  }
  return out;
}

(async () => {
  const cli = args(process.argv);
  if (cli.help) {
    console.log('Usage: node run-intake.cjs [--source source-id] [--out candidates.json]');
    console.log('Fetches official pages and emits NEEDS_REVIEW candidates. It never publishes or verifies them.');
    process.exit(0);
  }

  const sources = cli.source ? manifest.filter(x => x.id === cli.source) : manifest;
  if (!sources.length) throw new Error(`unknown source: ${cli.source}`);
  const candidates = [];
  for (const source of sources) {
    try {
      candidates.push(await collectSource(source));
    } catch (error) {
      candidates.push({ state: 'REJECTED', sourceId: source.id, signalId: source.signalId, reason: `FETCH_ERROR: ${error.message}` });
    }
  }
  const payload = JSON.stringify({ generatedAt: new Date().toISOString(), publicationAuthority: 'REVIEW_REQUIRED', candidates }, null, 2);
  if (cli.output) {
    fs.mkdirSync(path.dirname(path.resolve(cli.output)), { recursive: true });
    fs.writeFileSync(cli.output, payload + '\n');
  } else {
    process.stdout.write(payload + '\n');
  }
})();
