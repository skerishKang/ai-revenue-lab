/**
 * #3583 — ZCode provenance & Apache-2.0 redistribution contract tests.
 *
 * Deterministic pins (no network, no fs outside the package):
 *  1. the derived module keeps its upstream provenance header;
 *  2. a local, distributable copy of the Apache-2.0 license exists and is
 *     byte-identical (SHA-256) to the upstream LICENSE at the audited
 *     revision, including the Z.AI copyright notice;
 *  3. THIRD_PARTY_NOTICES.md references that local copy and the upstream
 *     copyright/attribution;
 *  4. the packaging config (electron-builder.yml) includes the notice and
 *     license material so any packaged build ships them.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// Resolved from dist/tests back to the package root, because this file is
// executed from dist/tests while the pinned artifacts live under src/ etc.
const packageRoot = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

const DERIVED_MODULE = path.join(packageRoot, 'src', 'workspace', 'workspace-file-search.ts');
const LICENSE_COPY = path.join(packageRoot, 'LICENSE.zcode');
const NOTICES = path.join(packageRoot, 'THIRD_PARTY_NOTICES.md');
const BUILDER_CONFIG = path.join(packageRoot, 'electron-builder.yml');

/** SHA-256 of the upstream zai-org/ZCode LICENSE at 29628c9acdb81b703bbd4080c207a0e7ce5e276e. */
const UPSTREAM_LICENSE_SHA256 = '606c36baf38b973227273df12a74930e4b4137280eea835c5cd623aa4553c13b';

test('#3583 provenance: derived module header pins the ZCode upstream revision', () => {
  const source = readFileSync(DERIVED_MODULE, 'utf8');
  assert.match(source, /UPSTREAM_REPO=zai-org\/ZCode/);
  assert.match(source, /UPSTREAM_SHA=29628c9acdb81b703bbd4080c207a0e7ce5e276e/);
  assert.match(source, /UPSTREAM_PATH=packages\/shared\/src\/workspaceFileSearch\.ts/);
  assert.match(source, /ADAPTATION_TYPE=DERIVED/);
});

test('#3583 Apache-2.0 §4(a): local license copy exists and matches the upstream bytes', () => {
  const license = readFileSync(LICENSE_COPY, 'utf8');
  // Byte-exact copy of the upstream LICENSE (LF endings preserved).
  const hash = createHash('sha256').update(readFileSync(LICENSE_COPY)).digest('hex');
  assert.equal(hash, UPSTREAM_LICENSE_SHA256);
  // The copy is the real Apache-2.0 text with the upstream APPENDIX notice.
  assert.match(license, /Apache License\s*Version 2\.0, January 2004/);
  assert.match(license, /Copyright 2026 Z\.AI Co\., Ltd/);
});

test('#3583 notices reference the local license copy and the upstream attribution', () => {
  const notices = readFileSync(NOTICES, 'utf8');
  assert.match(notices, /UPSTREAM_REPO=zai-org\/ZCode/);
  assert.match(notices, /UPSTREAM_SHA=29628c9acdb81b703bbd4080c207a0e7ce5e276e/);
  assert.match(notices, /LOCAL_LICENSE_COPY=\.\/LICENSE\.zcode/);
  assert.match(notices, /Copyright 2026 Z\.AI Co\., Ltd/);
  assert.match(notices, /ADAPTATION_TYPE=DERIVED/);
});

test('#3583 packaging includes the notice and license material for distribution', () => {
  const builder = readFileSync(BUILDER_CONFIG, 'utf8');
  // electron-builder `files:` allowlist must carry both files so any packaged
  // build (asar) ships the redistribution material.
  assert.match(builder, /-\s+THIRD_PARTY_NOTICES\.md/);
  assert.match(builder, /-\s+LICENSE\.zcode/);
  // Sanity: both artifacts actually live next to the packaging config.
  assert.ok(
    readFileSync(NOTICES).length > 0,
    'THIRD_PARTY_NOTICES.md must be non-empty',
  );
  assert.ok(
    readFileSync(LICENSE_COPY).length > 0,
    'LICENSE.zcode must be non-empty',
  );
});
