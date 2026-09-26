/**
 * #3093 — real-Windows evidence harness reproducibility contract.
 *
 * CENTRAL's correction: the harness must generate an Electron 44 loadable
 * main. Electron 44's ESM entry does not provide named exports for
 * `electron`, so a generated `import { app } from 'electron'` throws a
 * SyntaxError at load — the evidence run dies before a single check executes.
 * These assertions pin the shape that actually produces 12/12:
 *
 *   - generated main is `harness-main.cjs` (no `"type": "module"`);
 *   - `require('electron')` is used for the runtime;
 *   - the shell's own ESM modules are reached with dynamic `await import(...)`.
 *
 * Source assertions only: no Electron binary, no registry, no process.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { readFileSync } from 'node:fs';

const here = path.dirname(fileURLToPath(import.meta.url));
// Tests run from `dist/tests`; the harness script lives in the app's `scripts`.
const harnessPath = path.join(here, '..', '..', 'scripts', 'windows-real-evidence.mjs');
const harness = readFileSync(harnessPath, 'utf8');

/**
 * Strips comments so a prose mention of the broken ESM form in the harness's
 * own documentation is not mistaken for generated code. Only executable
 * source is asserted on.
 */
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^[ \t]*\/\/.*$/gm, '');
}

const harnessCode = stripComments(harness);

test('#3093 the generated harness app is CommonJS, not an ESM package', () => {
  assert.match(harness, /main:\s*'harness-main\.cjs'/);
  // `"type": "module"` would make the .cjs main irrelevant only via renaming,
  // but the real defect is the ESM entry: keep the manifest CJS-default.
  assert.equal(/type:\s*'module'/.test(harness), false, 'harness app must not be an ESM package');
  assert.equal(/harness-main\.mjs/.test(harness), false, 'no .mjs main may be generated');
});

test('#3093 the generated main uses require(electron), never a named ESM import', () => {
  assert.match(harnessCode, /"const \{ app \} = require\('electron'\);"/);
  assert.equal(
    /import\s*\{\s*app\s*\}\s*from\s*'electron'/.test(harnessCode),
    false,
    'Electron 44 ESM has no named electron exports; this form fails at load',
  );
});

test('#3093 the shell ESM modules are reached with dynamic import from the CJS main', () => {
  // Every shell module the harness drives must be pulled in via await import(),
  // because the generated main is CommonJS and the shell build output is ESM.
  for (const module of [
    'main/single-instance.js',
    'main/protocol-registration.js',
    'main/runner-host-mode.js',
    'supervisor/production-runner-process-port.js',
    'supervisor/runner-supervisor.js',
  ]) {
    const needle = "await import('file:///${rel('" + module + "')}')";
    assert.equal(
      harnessCode.includes(needle),
      true,
      module + ' must be loaded with dynamic import',
    );
  }
  assert.match(harnessCode, /\(async \(\) => \{/, 'dynamic imports live inside an async main');
});

test('#3093 the launcher still strips an inherited ELECTRON_RUN_AS_NODE', () => {
  // If the parent shell exports it, electron.exe silently degrades to plain
  // Node and the harness cannot load the app at all. The runner child must get
  // the variable back only through the explicit spawn-spec env.
  assert.match(harness, /ELECTRON_RUN_AS_NODE: _stripped/);
  assert.match(harness, /\.\.\.runnerMode\.env/);
});

test('#3093 the harness refuses to fake a Windows run', () => {
  assert.match(harness, /process\.platform !== 'win32'/);
  assert.match(harness, /electron\.exe not found/);
  assert.match(harness, /run npm run build first/);
});
