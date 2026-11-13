// #6828: the deployed BookAI public tree answers with PADIEM grades only.
// This lock scans every file under public/ (the whole Pages deploy directory)
// for model-identity shapes instead of a name list, so the test itself never
// writes a model or provider name into the repository.
//
// What it catches:
//   1. "provider/upstream" shaped model ids whose upstream carries both letters
//      and a digit inside a hyphen/dot separated token (the shape every
//      registered id uses). File paths, URLs and bare division expressions do
//      not match.
//   2. Well-known model family words (industry vocabulary, not owner data).
//
// What it cannot catch (recorded so the next sweep does not re-litigate):
//   - public/_worker.js is exempt for now: Chat's /api/apps/ai requires
//     agent.model_policy.model in the caller allowlist (apps_ai.py validates
//     the key set and the allowlist), so the caller must name a model until a
//     server-side selection path exists (#6828 follow-up). The exemption is
//     by path only and must be removed together with that Chat change.
//   - Bare upstream names without a provider prefix (no "/" shape).
//   - Provider hosts and provider ids that never appear in an id shape; hosts
//     are covered by the chat-side user-path contract, not here.
//   - Names inside non-deployed build tooling; public/ is the deploy set.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const publicRoot = path.join(appRoot, 'public');

// Deployed files only: everything Cloudflare Pages publishes from public/.
const DEPLOYED_SUFFIXES = new Set([
  '.html', '.js', '.mjs', '.css', '.json', '.svg', '.txt', '.webmanifest',
  '.png', '.jpg', '.jpeg', '.webp', '.ico', '.woff', '.woff2', '.xml',
]);

// "provider/upstream": lowercase on both sides, the upstream is a hyphen or
// dot separated token that mixes letters with a digit. Word boundaries and the
// look-behind keep relative asset paths ("./styles/..."), absolute paths and
// URLs out; the extension guard keeps "shard-05.json" style names out.
const MODEL_ID_SHAPE = new RegExp(
  [
    '(?<![\\w./@-])',
    '[a-z][a-z0-9]{1,20}',
    '/',
    '(?=[a-z0-9]*[a-z])', // letters, not a bare number
    '(?=[a-z0-9.-]*\\d)', // and at least one digit
    '[a-z0-9]+(?:[.-][a-z0-9]+)+', // separator-separated token
    '(?![\\w/-])',
  ].join(''),
  'g',
);

// Industry-wide model family words only. Deliberately generic: no owner
// registry value is named here, and the list must stay free of them.
const MODEL_FAMILY_WORDS = /\b(gemini|gemma|gpt-?\d|claude|llama|qwen\d?|deepseek|mistral|kimi)\b/gi;

// Files the identity lock may not judge yet, with the reason recorded above.
const PENDING_SERVER_SELECTION = new Set(['_worker.js']);

function* deployedFiles(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      yield* deployedFiles(full);
    } else if (DEPLOYED_SUFFIXES.has(path.extname(entry.name).toLowerCase())) {
      yield full;
    }
  }
}

// Deployable-file extensions: a match that ends in one is an asset path
// ("packs/xxx-v1.json"), not a model id.
const ASSET_EXTENSION = /\.(?:json|css|js|mjs|png|svg|webp|jpe?g|ico|txt|html|woff2?|map|webmanifest|xml)$/i;

function identityFindings(text) {
  const ids = new Set();
  for (const match of text.matchAll(MODEL_ID_SHAPE)) {
    if (!ASSET_EXTENSION.test(match[0])) ids.add(match[0].toLowerCase());
  }
  const families = new Set();
  for (const match of text.matchAll(MODEL_FAMILY_WORDS)) families.add(match[0].toLowerCase());
  return { ids: [...ids], families: [...families] };
}

test('deployed public files carry no model-identity shapes', () => {
  assert.ok(fs.existsSync(publicRoot), 'public/ must exist');
  const offenders = [];
  let scanned = 0;
  for (const file of deployedFiles(publicRoot)) {
    const relative = path.relative(publicRoot, file).split(path.sep).join('/');
    if (PENDING_SERVER_SELECTION.has(relative)) continue;
    scanned += 1;
    const text = fs.readFileSync(file, 'utf8');
    const { ids, families } = identityFindings(text);
    if (ids.length || families.length) offenders.push({ file: relative, ids, families });
  }
  assert.ok(scanned > 100, `expected the real deploy set, scanned ${scanned}`);
  assert.deepEqual(
    offenders,
    [],
    `model-identity shapes found in deployed files: ${offenders.map((o) => o.file).join(', ')}`,
  );
});

test('the pending exemption list stays minimal and reason-bound', () => {
  // The exemption exists only while the caller must name a model. If the file
  // goes away or the Chat path lands, this test forces the list to shrink.
  for (const relative of PENDING_SERVER_SELECTION) {
    assert.ok(
      fs.existsSync(path.join(publicRoot, relative)),
      `exempted file no longer deployed, drop it from the exemption list: ${relative}`,
    );
  }
});
