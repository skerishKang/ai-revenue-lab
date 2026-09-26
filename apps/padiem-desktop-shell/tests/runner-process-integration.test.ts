/**
 * Real-process supervision test.
 *
 * This spawns an actual separate OS process (`node dist/src/runner/headless-runner.js`)
 * so the "separate headless process" and "no orphan after shutdown" claims are
 * demonstrated against the operating system, not a fake.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { existsSync } from 'node:fs';

import { HeadlessRunnerSupervisor } from '../src/supervisor/runner-supervisor.js';
import { NodeRunnerProcessPort } from '../src/supervisor/production-runner-process-port.js';
import { projectBoundedLog } from '../src/contract/safe-log-projection.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const runnerEntry = path.join(here, '..', 'src', 'runner', 'headless-runner.js');

function isAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

async function waitUntil(predicate: () => boolean, timeoutMs = 5000): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) return true;
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  return predicate();
}

test('#3083 the compiled headless runner entry exists as a separate process module', () => {
  assert.equal(existsSync(runnerEntry), true, `runner entry missing at ${runnerEntry}`);
});

test('#3083 real runner: start once, health, explicit stop, no orphan process', async () => {
  const port = new NodeRunnerProcessPort();
  const supervisor = new HeadlessRunnerSupervisor({
    port,
    spec: {
      executablePath: process.execPath,
      args: [runnerEntry],
      cwd: path.join(here, '..'),
      env: {},
      shell: false,
      stdio: 'pipe',
    },
    shutdownGraceMs: 4000,
  });

  const started = await supervisor.start();
  assert.equal(started.state, 'RUNNING');
  const pid = started.pid;
  assert.ok(pid && pid > 0, 'runner must report a real pid');
  assert.equal(isAlive(pid), true);

  // The runner is a genuinely separate OS process, not an in-process stub.
  assert.notEqual(pid, process.pid);

  const health = await supervisor.health();
  assert.equal(health.state, 'RUNNING');
  assert.equal(health.pid !== null && health.state === 'RUNNING', true);

  // Duplicate start is refused at the supervisor, before any second spawn.
  await assert.rejects(() => supervisor.start(), /DUPLICATE_RUNNER_START|already/);

  // The runner's own stdout is only visible through the redacted projection.
  const projected = projectBoundedLog(port.boundedActiveOutput().lines, 20);
  assert.equal(projected.redactionApplied, true);
  await waitUntil(() => projected.lines.length >= 0);

  const stopped = await supervisor.stop();
  assert.equal(stopped.state, 'STOPPED');
  assert.equal(stopped.pid, null);
  assert.equal(await waitUntil(() => !isAlive(pid)), true, 'runner process must not survive stop');
});

test('#3083 real runner: app shutdown leaves no orphan', async () => {
  const port = new NodeRunnerProcessPort();
  const supervisor = new HeadlessRunnerSupervisor({
    port,
    spec: {
      executablePath: process.execPath,
      args: [runnerEntry],
      cwd: path.join(here, '..'),
      env: {},
      shell: false,
      stdio: 'pipe',
    },
    shutdownGraceMs: 4000,
  });
  const started = await supervisor.start();
  const pid = started.pid!;
  const final = await supervisor.shutdown();
  assert.equal(final.state, 'STOPPED');
  assert.equal(await waitUntil(() => !isAlive(pid)), true, 'shutdown must not orphan the runner');
});

test('#3083 real runner: an unexpected runner crash is reported as CRASHED, not RUNNING', async () => {
  const port = new NodeRunnerProcessPort();
  const supervisor = new HeadlessRunnerSupervisor({
    port,
    spec: {
      // A process that exits immediately stands in for a crashing runner.
      executablePath: process.execPath,
      args: ['-e', 'process.exit(9)'],
      cwd: path.join(here, '..'),
      env: {},
      shell: false,
      stdio: 'pipe',
    },
    shutdownGraceMs: 2000,
  });
  const started = await supervisor.start();
  const pid = started.pid!;
  const deadline = Date.now() + 5000;
  let health = await supervisor.health();
  while (health.state === 'RUNNING' && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 25));
    health = await supervisor.health();
  }
  assert.equal(health.state, 'CRASHED');
  assert.equal(health.pid, null);
  assert.equal(health.lastExitCode, 9);
  assert.equal(await waitUntil(() => !isAlive(pid)), true);
});
