/**
 * #3093 (reopen) — shipped Electron entrypoint loadability contract.
 *
 * The packaged Windows app must boot on Electron 44. Two measured packaged
 * defects made that impossible on exact main 6fffd5a0:
 *
 *   1. the shipped ESM main entry used top-level named imports from
 *      `electron`, which the packaged runtime rejects at load (SyntaxError);
 *   2. the ESM main's relative imports (`contract/`, `supervisor/`) reached
 *      modules the asar `files` list never packaged
 *      (`ERR_MODULE_NOT_FOUND ... contract/ipc.js`).
 *
 * The shipped shape is now ONE CommonJS bundle built with esbuild
 * (`dist/src/main/main.cjs`): the runtime is reached with
 * `require("electron")` (kept external — the Electron-44-loadable form proven
 * by the #3093 real-Windows evidence harness), and the electron-free shell
 * modules are bundled in, so no relative ESM import can miss at runtime.
 *
 * Source + output assertions only: no Electron binary, no registry, no
 * process. The packaged/installed behaviour is verified by the real-Windows
 * evidence run (independent validation, CLAW3).
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { readFileSync } from 'node:fs';

const here = path.dirname(fileURLToPath(import.meta.url));
const appRoot = path.join(here, '..', '..');

test('package.json ships the CommonJS bundle as the main entry', () => {
  const pkg = JSON.parse(readFileSync(path.join(appRoot, 'package.json'), 'utf8'));
  assert.equal(pkg.main, 'dist/src/main/main.cjs');
});

test('the built main entry is CommonJS that requires electron externally', () => {
  const bundle = readFileSync(path.join(appRoot, 'dist', 'src', 'main', 'main.cjs'), 'utf8');
  // The Electron-44-loadable runtime form.
  assert.match(bundle, /\brequire\("electron"\)/);
  // The bundled output must not carry a top-level ESM import of electron.
  assert.doesNotMatch(bundle, /^\s*import\s+\{[^}]*\}\s+from\s+["']electron["']/m);
  // The import.meta.url shim keeps __dirname semantics correct in CJS.
  assert.match(bundle, /__padiem_import_meta_url/);
  assert.match(bundle, /pathToFileURL\(__filename\)/);
});

test('the build produces the CJS bundle from src/main/main.ts', () => {
  const buildScript = readFileSync(path.join(appRoot, 'scripts', 'build.mjs'), 'utf8');
  assert.match(buildScript, /entryPoints:\s*\[path\.join\(root,\s*'src',\s*'main',\s*'main\.ts'\)\]/);
  assert.match(buildScript, /outfile:\s*path\.join\(root,\s*'dist',\s*'src',\s*'main',\s*'main\.cjs'\)/);
  assert.match(buildScript, /format:\s*'cjs'/);
  assert.match(buildScript, /external:\s*\['electron'\]/);
});

test('the bundle keeps the shipped entry decoupled from the asar module layout', () => {
  // The CJS bundle must not depend on dynamic file:// imports of unpacked
  // modules: everything it needs is bundled, electron stays external.
  const bundle = readFileSync(path.join(appRoot, 'dist', 'src', 'main', 'main.cjs'), 'utf8');
  assert.doesNotMatch(bundle, /await import\(fileUrlFor/);
  assert.doesNotMatch(bundle, /app\.asar\.unpacked/);
  // The builder config does not carry the abandoned unpack workaround.
  const builderConfig = readFileSync(path.join(appRoot, 'electron-builder.yml'), 'utf8');
  assert.doesNotMatch(builderConfig, /asarUnpack/);
});
