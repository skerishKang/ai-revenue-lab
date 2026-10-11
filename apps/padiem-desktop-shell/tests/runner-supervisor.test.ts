import test from 'node:test';
import assert from 'node:assert/strict';

import {
  HeadlessRunnerSupervisor,
  RunnerSupervisorError,
  type RunnerExitResult,
  type RunnerProcessHandle,
  type RunnerProcessPort,
  type RunnerSpawnSpec,
} from '../src/supervisor/runner-supervisor.js';

/** Deterministic in-memory handle so lifecycle tests never touch a real process. */
class FakeHandle implements RunnerProcessHandle {
  readonly pid: number;
  #alive = true;
  readonly #listeners = new Set<(result: RunnerExitResult) => void>();
  readonly killSignals: string[] = [];

  constructor(pid: number) {
    this.pid = pid;
  }

  isAlive(): boolean {
    return this.#alive;
  }

  kill(signal: 'SIGTERM' | 'SIGKILL' = 'SIGTERM'): void {
    this.killSignals.push(signal);
    this.exit({ code: signal === 'SIGKILL' ? 137 : 143, signal });
  }

  exit(result: RunnerExitResult): void {
    if (!this.#alive) return;
    this.#alive = false;
    for (const listener of [...this.#listeners]) listener(result);
    this.#listeners.clear();
  }

  waitForExit(timeoutMs: number): Promise<RunnerExitResult> {
    return new Promise((resolve) => {
      const timer = setTimeout(() => resolve({ code: null, signal: null }), timeoutMs);
      this.onExit((result) => {
        clearTimeout(timer);
        resolve(result);
      });
    });
  }

  onExit(listener: (result: RunnerExitResult) => void): () => void {
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  }
}

class FakePort implements RunnerProcessPort {
  spawnCount = 0;
  readonly handles: FakeHandle[] = [];
  failNext = false;

  async spawnRunner(_spec: RunnerSpawnSpec): Promise<RunnerProcessHandle> {
    this.spawnCount += 1;
    if (this.failNext) {
      this.failNext = false;
      throw new Error('spawn refused by test');
    }
    const handle = new FakeHandle(4000 + this.spawnCount);
    this.handles.push(handle);
    return handle;
  }
}

function makeSpec(): RunnerSpawnSpec {
  return {
    executablePath: 'node',
    args: [],
    cwd: '.',
    env: {},
    shell: false,
    stdio: 'pipe',
  };
}

function makeSupervisor(port: FakePort): HeadlessRunnerSupervisor {
  return new HeadlessRunnerSupervisor({ port, spec: makeSpec(), shutdownGraceMs: 50 });
}

test('#3083 supervisor refuses a shell-enabled spawn spec outright', () => {
  assert.throws(
    () =>
      new HeadlessRunnerSupervisor({
        port: new FakePort(),
        spec: { ...makeSpec(), shell: true } as unknown as RunnerSpawnSpec,
      }),
    (error: unknown) =>
      error instanceof RunnerSupervisorError && error.code === 'SHELL_EXECUTION_FORBIDDEN',
  );
});

test('#3083 supervisor starts the runner once and reports a live pid', async () => {
  const port = new FakePort();
  const supervisor = makeSupervisor(port);
  const started = await supervisor.start(1000);
  assert.equal(started.state, 'RUNNING');
  assert.equal(started.pid, 4001);
  assert.equal(started.startCount, 1);
  assert.equal(started.orphanPrevented, true);
  assert.equal(started.jobObjectImplementedHere, false);
});

test('#3083 supervisor refuses a duplicate start while running', async () => {
  const port = new FakePort();
  const supervisor = makeSupervisor(port);
  await supervisor.start();
  await assert.rejects(
    () => supervisor.start(),
    (error: unknown) =>
      error instanceof RunnerSupervisorError && error.code === 'DUPLICATE_RUNNER_START',
  );
  assert.equal(port.spawnCount, 1);
});

test('#3083 supervisor reports an unexpected exit as a truthful CRASHED state', async () => {
  const port = new FakePort();
  const supervisor = makeSupervisor(port);
  await supervisor.start();
  port.handles[0]!.exit({ code: 7, signal: null });
  const health = await supervisor.health();
  assert.equal(health.state, 'CRASHED');
  assert.equal(health.pid, null);
  assert.equal(health.lastExitCode, 7);
  // Health is not optimistic: a crash stays visible until an explicit action.
  const second = await supervisor.health();
  assert.equal(second.state, 'CRASHED');
  assert.equal(second.lastExitCode, 7);
  // An explicit start is the only way back to a healthy state.
  const restarted = await supervisor.start();
  assert.equal(restarted.state, 'RUNNING');
});

test('#3083 supervisor maps runner health to the shell device projection', async () => {
  const port = new FakePort();
  const supervisor = makeSupervisor(port);
  assert.equal(supervisor.snapshot().state, 'STOPPED');
  await supervisor.start();
  assert.equal((await supervisor.health()).state, 'RUNNING');
  await supervisor.stop();
  assert.equal(supervisor.snapshot().state, 'STOPPED');
});

test('#3083 supervisor stops explicitly and leaves no handle behind', async () => {
  const port = new FakePort();
  const supervisor = makeSupervisor(port);
  await supervisor.start();
  const stopped = await supervisor.stop();
  assert.equal(stopped.state, 'STOPPED');
  assert.equal(stopped.pid, null);
  assert.equal(stopped.stopCount, 1);
  assert.equal(port.handles[0]!.isAlive(), false);
});

test('#3083 supervisor shutdown cleans up the runner exactly once (no orphan)', async () => {
  const port = new FakePort();
  const supervisor = makeSupervisor(port);
  await supervisor.start();
  const first = await supervisor.shutdown();
  const second = await supervisor.shutdown();
  assert.equal(first.state, 'STOPPED');
  assert.equal(second.state, 'STOPPED');
  assert.equal(second.stopCount, 1, 'shutdown must be idempotent');
  assert.equal(port.handles[0]!.isAlive(), false);
});

test('#3083 supervisor reports a failed spawn instead of a phantom RUNNING state', async () => {
  const port = new FakePort();
  port.failNext = true;
  const supervisor = makeSupervisor(port);
  await assert.rejects(
    () => supervisor.start(),
    (error: unknown) => error instanceof RunnerSupervisorError && error.code === 'SPAWN_FAILED',
  );
  assert.equal(supervisor.snapshot().state, 'STOPPED');
  assert.equal(supervisor.snapshot().pid, null);
});

test('#3083 supervisor can be restarted after an explicit stop', async () => {
  const port = new FakePort();
  const supervisor = makeSupervisor(port);
  await supervisor.start();
  await supervisor.stop();
  const restarted = await supervisor.start();
  assert.equal(restarted.state, 'RUNNING');
  assert.equal(port.spawnCount, 2);
});
