/**
 * #3093 — explicit runner host mode tests.
 *
 * The defect this prevents: #3083's spawn spec used
 * `process.env.PADIEM_RUNNER_EXECUTABLE ?? process.execPath` and assumed
 * execPath was Node. Under a packaged Electron build execPath is the Electron
 * GUI binary, so `electron.exe headless-runner.js` with no node-mode env would
 * start a second full Electron app instead of a runner. These tests pin the
 * explicit three-way decision.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  ELECTRON_RUN_AS_NODE_ENV,
  RUNNER_HOST_MODE_CONTRACT,
  resolveRunnerHostMode,
} from '../src/main/runner-host-mode.js';

test('#3093 under Electron the runner reuses the Electron binary in ELECTRON_RUN_AS_NODE=1 mode', () => {
  const mode = resolveRunnerHostMode({
    execPath: 'C:\\Program Files\\Padiem\\Padiem Desktop Shell.exe',
    electronVersion: '44.4.5',
    runnerExecutableOverride: undefined,
    platform: 'win32',
  });
  assert.equal(mode.mode, 'electron-run-as-node');
  assert.equal(mode.executablePath, 'C:\\Program Files\\Padiem\\Padiem Desktop Shell.exe');
  assert.deepEqual(mode.env, { [ELECTRON_RUN_AS_NODE_ENV]: '1' });
  assert.equal(mode.testOrDevOnly, false);
});

test('#3093 an operator-pinned runner executable wins over Electron node mode', () => {
  const mode = resolveRunnerHostMode({
    execPath: 'C:\\Program Files\\Padiem\\Padiem Desktop Shell.exe',
    electronVersion: '44.4.5',
    runnerExecutableOverride: 'C:\\padiem\\bin\\padiem-runner.exe',
    platform: 'win32',
  });
  assert.equal(mode.mode, 'explicit-executable');
  assert.equal(mode.executablePath, 'C:\\padiem\\bin\\padiem-runner.exe');
  // A dedicated runner binary is already a node host; no ELECTRON_RUN_AS_NODE.
  assert.deepEqual(mode.env, {});
});

test('#3093 a relative PADIEM_RUNNER_EXECUTABLE is refused — no PATH resolution', () => {
  assert.throws(
    () =>
      resolveRunnerHostMode({
        execPath: 'C:\\e\\electron.exe',
        electronVersion: '44.4.5',
        runnerExecutableOverride: 'padiem-runner',
        platform: 'win32',
      }),
    /absolute path/,
  );
  assert.throws(
    () =>
      resolveRunnerHostMode({
        execPath: '/usr/bin/electron',
        electronVersion: '44.4.5',
        runnerExecutableOverride: '../runner/padiem-runner',
        platform: 'linux',
      }),
    /absolute path/,
  );
});

test('#3093 plain Node host is marked testOrDevOnly so production cannot assume it', () => {
  const mode = resolveRunnerHostMode({
    execPath: 'C:\\Program Files\\nodejs\\node.exe',
    electronVersion: undefined,
    runnerExecutableOverride: undefined,
    platform: 'win32',
  });
  assert.equal(mode.mode, 'plain-node');
  assert.equal(mode.testOrDevOnly, true);
  assert.deepEqual(mode.env, {});
});

test('#3093 UNC and POSIX-style absolute overrides are accepted on win32', () => {
  for (const candidate of ['\\\\fileserver\\share\\padiem-runner.exe', '/c/padiem/runner.exe']) {
    const mode = resolveRunnerHostMode({
      execPath: 'C:\\e\\electron.exe',
      electronVersion: '44.4.5',
      runnerExecutableOverride: candidate,
      platform: 'win32',
    });
    assert.equal(mode.mode, 'explicit-executable', candidate);
    assert.equal(mode.executablePath, candidate);
  }
});

test('#3093 an empty or whitespace override is treated as absent', () => {
  const mode = resolveRunnerHostMode({
    execPath: 'C:\\e\\electron.exe',
    electronVersion: '44.4.5',
    runnerExecutableOverride: '   ',
    platform: 'win32',
  });
  assert.equal(mode.mode, 'electron-run-as-node');
});

test('#3093 the contract names exactly the three modes and both env keys', () => {
  assert.deepEqual([...RUNNER_HOST_MODE_CONTRACT.MODES], [
    'explicit-executable',
    'electron-run-as-node',
    'plain-node',
  ]);
  assert.equal(RUNNER_HOST_MODE_CONTRACT.OVERRIDE_ENV, 'PADIEM_RUNNER_EXECUTABLE');
  assert.equal(RUNNER_HOST_MODE_CONTRACT.NODE_MODE_ENV, 'ELECTRON_RUN_AS_NODE');
  assert.equal(RUNNER_HOST_MODE_CONTRACT.OVERRIDE_MUST_BE_ABSOLUTE, true);
  assert.equal(RUNNER_HOST_MODE_CONTRACT.IMPLICIT_EXEC_PATH_ASSUMPTION, false);
});
