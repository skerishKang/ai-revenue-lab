/**
 * Source-level security assertions.
 *
 * These tests read the actual preload / main / renderer sources, so a future
 * edit that reintroduces a generic invoke, a raw shell, a wildcard channel or a
 * node-enabled renderer fails here rather than in a review.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { readFileSync } from 'node:fs';

import { IPC_CHANNELS } from '../src/contract/ipc.js';

const here = path.dirname(fileURLToPath(import.meta.url));
// Tests run from `dist/tests`, so the TypeScript sources live two levels up.
const srcRoot = path.join(here, '..', '..', 'src');

function read(...segments: string[]): string {
  return readFileSync(path.join(srcRoot, ...segments), 'utf8');
}

/**
 * Strips comments so a *prose* mention of e.g. "child_process" in a security
 * note is not mistaken for a real call. Only executable code is asserted on.
 */
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^[ \t]*\/\/.*$/gm, '');
}

const preloadSource = read('preload', 'preload.cts');
const mainSource = read('main', 'main.ts');
const rendererIndexSource = read('renderer', 'index.tsx');
const rendererApiSource = read('renderer', 'api.ts');

const preloadCode = stripComments(preloadSource);
const mainCode = stripComments(mainSource);
const rendererIndexCode = stripComments(rendererIndexSource);
const rendererApiCode = stripComments(rendererApiSource);
const runnerCode = stripComments(read('runner', 'headless-runner.ts'));

test('#3083 preload channel literals are byte-identical to the canonical allowlist', () => {
  for (const channel of IPC_CHANNELS) {
    assert.equal(
      preloadSource.includes(`'${channel}'`),
      true,
      `preload must reference the canonical channel ${channel}`,
    );
  }
  const literalMatches = [...preloadSource.matchAll(/'(padiem:shell:[^']+)'/g)].map((m) => m[1]!);
  assert.deepEqual([...new Set(literalMatches)].sort(), [...IPC_CHANNELS].sort());
});

test('#3083 preload exposes only the narrow bridge and never ipcRenderer itself', () => {
  assert.match(preloadSource, /contextBridge\.exposeInMainWorld\('padiemShell'/);
  assert.equal(/exposeInMainWorld\([^)]*ipcRenderer\s*\)/.test(preloadCode), false);
  assert.equal(/exposeInMainWorld\(\s*['"]ipcRenderer['"]/.test(preloadCode), false);
  // No channel-taking function may be exported.
  assert.equal(/\bon\s*:\s*\(\s*channel/.test(preloadCode), false);
  assert.equal(/\bsend\s*:\s*\(\s*channel/.test(preloadCode), false);
  assert.equal(/\binvoke\s*:\s*\(/.test(preloadCode), false);
  assert.equal(/\brequire\s*\(/.test(preloadCode), false);
  assert.equal(/child_process/.test(preloadCode), false);
  assert.equal(/writeFile|readFile/.test(preloadCode), false);
});

test('#3083 preload fails loudly if contextIsolation is not in effect', () => {
  assert.match(preloadSource, /process\.contextIsolated/);
  assert.match(preloadSource, /requires contextIsolation=true/);
});

test('#3083 main process window keeps contextIsolation on and nodeIntegration off', () => {
  assert.match(mainCode, /contextIsolation:\s*true/);
  assert.match(mainCode, /nodeIntegration:\s*false/);
  assert.match(mainCode, /sandbox:\s*true/);
  assert.match(mainCode, /webSecurity:\s*true/);
  assert.match(mainCode, /setWindowOpenHandler\(\(\)\s*=>\s*\(\{\s*action:\s*'deny'/);
  assert.equal(/nodeIntegration:\s*true/.test(mainCode), false);
  assert.equal(/contextIsolation:\s*false/.test(mainCode), false);
});

test('#3083 main process registers IPC only from the static channel list', () => {
  assert.match(mainCode, /for \(const channel of IPC_CHANNELS\)/);
  // The only permitted registration shape is the loop variable from IPC_CHANNELS.
  const registrations = [...mainCode.matchAll(/ipcMain\.handle\(\s*([^,)]+)/g)].map((m) =>
    m[1]!.trim(),
  );
  assert.deepEqual(registrations, ['channel']);
  assert.equal(/ipcMain\.handle\(\s*`/.test(mainCode), false, 'no dynamic channel names');
});

test('#3083 shell never spawns through a shell and never elevates', () => {
  assert.match(mainCode, /shell:\s*false/);
  assert.equal(/shell:\s*true/.test(mainCode), false);
  assert.equal(/elevation|elevat/i.test(mainCode), false);
  assert.equal(/windowsVerbatimArguments|runas/i.test(mainCode), false);
});

test('#3083 only the production process port may import child_process', () => {
  const productionPort = stripComments(read('supervisor', 'production-runner-process-port.ts'));
  assert.match(productionPort, /from 'node:child_process'/);
  for (const [name, source] of [
    ['preload', preloadCode],
    ['main', mainCode],
    ['renderer/index', rendererIndexCode],
    ['renderer/api', rendererApiCode],
  ] as const) {
    assert.equal(
      /node:child_process|require\(['"]child_process['"]\)/.test(source),
      false,
      `${name} must not reach child_process`,
    );
  }
});

test('#3083 renderer has no node, no fs and no arbitrary channel usage', () => {
  for (const [name, source] of [
    ['renderer/index', rendererIndexCode],
    ['renderer/api', rendererApiCode],
  ] as const) {
    assert.equal(/from 'node:/.test(source), false, `${name} must not import node builtins`);
    assert.equal(/\bipcRenderer\b/.test(source), false, `${name} must not touch ipcRenderer`);
    assert.equal(/child_process/.test(source), false);
    assert.equal(/\bfetch\(/.test(source), false, `${name} must not reach the network`);
    assert.equal(/XMLHttpRequest|WebSocket/.test(source), false);
  }
  assert.match(rendererApiCode, /window\.padiemShell/);
  assert.match(rendererApiSource, /renderer has no authority/);
});

test('#3083 renderer CSP forbids remote script and any network connect', () => {
  const html = read('renderer', 'index.html');
  assert.match(html, /Content-Security-Policy/);
  assert.match(html, /default-src 'none'/);
  assert.match(html, /script-src 'self'/);
  assert.match(html, /connect-src 'none'/);
});

test('#3083 headless runner is a separate process and opens no inbound listener', () => {
  assert.equal(/createServer|\.listen\(/.test(runnerCode), false, 'runner must not listen on a port');
  assert.match(runnerSource(), /RUNNER_EXECUTION_SEMANTICS_IMPLEMENTED=NO/);
  assert.equal(/child_process/.test(runnerCode), false);
});

function runnerSource(): string {
  return read('runner', 'headless-runner.ts');
}
