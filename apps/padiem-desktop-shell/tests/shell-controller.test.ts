import test from 'node:test';
import assert from 'node:assert/strict';

import { IpcContractError, IPC_CHANNELS } from '../src/contract/ipc.js';
import { ShellController } from '../src/supervisor/shell-controller.js';
import { HeadlessRunnerSupervisor, type RunnerSpawnSpec } from '../src/supervisor/runner-supervisor.js';
import type { RunnerProcessHandle, RunnerProcessPort } from '../src/supervisor/runner-supervisor.js';

class StubHandle implements RunnerProcessHandle {
  readonly pid = 5150;
  #alive = true;
  readonly #listeners = new Set<(r: { code: number | null; signal: string | null }) => void>();
  isAlive(): boolean {
    return this.#alive;
  }
  kill(): void {
    this.exit({ code: 143, signal: null });
  }
  exit(result: { code: number | null; signal: string | null }): void {
    if (!this.#alive) return;
    this.#alive = false;
    for (const l of [...this.#listeners]) l(result);
    this.#listeners.clear();
  }
  waitForExit(timeoutMs: number): Promise<{ code: number | null; signal: string | null }> {
    return new Promise((resolve) => {
      const t = setTimeout(() => resolve({ code: null, signal: null }), timeoutMs);
      this.onExit((r) => {
        clearTimeout(t);
        resolve(r);
      });
    });
  }
  onExit(listener: (r: { code: number | null; signal: string | null }) => void): () => void {
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  }
}

class StubPort implements RunnerProcessPort {
  spawnCount = 0;
  readonly handle = new StubHandle();
  async spawnRunner(_spec: RunnerSpawnSpec): Promise<RunnerProcessHandle> {
    this.spawnCount += 1;
    return this.handle;
  }
}

function makeController(logLines: string[] = []) {
  const port = new StubPort();
  const supervisor = new HeadlessRunnerSupervisor({
    port,
    spec: {
      executablePath: 'node',
      args: [],
      cwd: '.',
      env: {},
      shell: false,
      stdio: 'pipe',
    },
    shutdownGraceMs: 50,
  });
  const controller = new ShellController({
    supervisor,
    boundedLogLines: () => logLines,
    now: () => 1_700_000_000_000,
  });
  return { controller, port, supervisor };
}

test('#3083 controller registers exactly the allowlisted channels, no more', () => {
  const { controller } = makeController();
  const keys = Object.keys(controller.handlers()).sort();
  assert.deepEqual(keys, [...IPC_CHANNELS].sort());
});

test('#3083 controller refuses any non-allowlisted channel at dispatch', async () => {
  const { controller } = makeController();
  for (const hostile of [
    'padiem:shell:exec',
    'padiem:shell:approve',
    'padiem:shell:mint-session',
    '*',
    '__proto__',
    null,
    7,
  ]) {
    await assert.rejects(
      () => controller.dispatch(hostile, {}),
      (error: unknown) => error instanceof IpcContractError,
      `must refuse channel ${String(hostile)}`,
    );
  }
});

test('#3083 status is truthful and never lets the renderer declare ONLINE', async () => {
  const { controller } = makeController();
  const initial = await controller.dispatch('padiem:shell:get-status', undefined);
  assert.deepEqual(initial, {
    deviceState: 'NOT_PAIRED',
    deviceStateRevision: 0,
    runnerState: 'STOPPED',
    runnerPid: null,
    pairingSeamAccepted: false,
    presenceNote: 'no headless runner observation yet',
    authoritativeTruthOwner: '#3080',
    rendererMayDeclareOnline: false,
  });
});

test('#3083 a forged ONLINE payload is ignored — no channel can set device state', async () => {
  const { controller } = makeController();
  for (const forged of [
    { deviceState: 'ONLINE' },
    { state: 'ONLINE' },
    { requestedBy: 'renderer-shell', deviceState: 'ONLINE' },
    'ONLINE',
  ]) {
    const status = (await controller.dispatch('padiem:shell:get-status', forged)) as {
      deviceState: string;
    };
    assert.equal(status.deviceState, 'NOT_PAIRED');
  }
  const health = (await controller.dispatch('padiem:shell:runner-health', {
    deviceState: 'ONLINE',
  })) as { state: string };
  assert.equal(health.state, 'STOPPED');
});

test('#3083 starting a runner on an unpaired shell does NOT claim ONLINE', async () => {
  const { controller, port } = makeController();
  const started = (await controller.dispatch('padiem:shell:runner-start', {
    requestedBy: 'renderer-shell',
  })) as { ok: boolean; state: string; pid: number };
  assert.equal(started.ok, true);
  assert.equal(started.state, 'RUNNING');
  assert.equal(started.pid, 5150);
  assert.equal(port.spawnCount, 1);

  // A live local process is not evidence of a paired, reachable device.
  const status = (await controller.dispatch('padiem:shell:get-status', undefined)) as {
    deviceState: string;
    runnerState: string;
    presenceNote: string;
  };
  assert.equal(status.deviceState, 'NOT_PAIRED');
  assert.equal(status.runnerState, 'RUNNING');
  // The reason is surfaced, not silently swallowed.
  assert.match(status.presenceNote, /still NOT_PAIRED/);
  assert.match(status.presenceNote, /#3080/);
});

test('#3083 after the pairing seam, a healthy runner projects ONLINE and a stop projects OFFLINE', async () => {
  const { controller, port } = makeController();
  await controller.dispatch('padiem:shell:pairing-deeplink-submit', {
    deepLink: 'padiem://pair?code=abc',
  });
  const pairing = (await controller.dispatch('padiem:shell:get-status', undefined)) as {
    deviceState: string;
  };
  assert.equal(pairing.deviceState, 'PAIRING');

  await controller.dispatch('padiem:shell:runner-start', { requestedBy: 'renderer-shell' });
  const online = (await controller.dispatch('padiem:shell:get-status', undefined)) as {
    deviceState: string;
    presenceNote: string;
  };
  assert.equal(online.deviceState, 'ONLINE');
  assert.match(online.presenceNote, /presence confirmed/);

  const stopped = (await controller.dispatch('padiem:shell:runner-stop', {
    requestedBy: 'renderer-shell',
  })) as { ok: boolean; state: string };
  assert.equal(stopped.ok, true);
  assert.equal(stopped.state, 'STOPPED');
  assert.equal(port.handle.isAlive(), false);

  const offline = (await controller.dispatch('padiem:shell:get-status', undefined)) as {
    deviceState: string;
    presenceNote: string;
  };
  assert.equal(offline.deviceState, 'OFFLINE');
  assert.match(offline.presenceNote, /no longer confirmed/);
});

test('#3083 a runner crash projects OFFLINE, never a stale ONLINE', async () => {
  const { controller, port } = makeController();
  await controller.dispatch('padiem:shell:pairing-deeplink-submit', {
    deepLink: 'padiem://pair?code=abc',
  });
  await controller.dispatch('padiem:shell:runner-start', { requestedBy: 'renderer-shell' });
  port.handle.exit({ code: 3, signal: null });
  const health = (await controller.dispatch('padiem:shell:runner-health', undefined)) as {
    state: string;
    lastExitCode: number | null;
  };
  assert.equal(health.state, 'CRASHED');
  assert.equal(health.lastExitCode, 3);
  const status = (await controller.dispatch('padiem:shell:get-status', undefined)) as {
    deviceState: string;
  };
  assert.equal(status.deviceState, 'OFFLINE');
});

test('#3083 runner start/stop requests from a non-shell caller are rejected', async () => {
  const { controller, port } = makeController();
  const bad = await controller.dispatch('padiem:shell:runner-start', { requestedBy: 'attacker' });
  assert.equal((bad as { ok: boolean }).ok, false);
  const missing = await controller.dispatch('padiem:shell:runner-stop', undefined);
  assert.equal((missing as { ok: boolean }).ok, false);
  assert.equal(port.spawnCount, 0, 'no process may be spawned for a rejected request');
});

test('#3083 duplicate start through IPC is refused and spawns only once', async () => {
  const { controller, port } = makeController();
  await controller.dispatch('padiem:shell:runner-start', { requestedBy: 'renderer-shell' });
  const second = (await controller.dispatch('padiem:shell:runner-start', {
    requestedBy: 'renderer-shell',
  })) as { ok: boolean; reason: string };
  assert.equal(second.ok, false);
  assert.match(second.reason, /already RUNNING/);
  assert.equal(port.spawnCount, 1);
});

test('#3083 pairing deep link acceptance never stores a credential or mints a session', async () => {
  const { controller } = makeController();
  const accepted = (await controller.dispatch('padiem:shell:pairing-deeplink-submit', {
    deepLink: 'padiem://pair?code=secret-value',
  })) as Record<string, unknown>;
  assert.equal(accepted.accepted, true);
  assert.equal(accepted.credentialStored, false);
  assert.equal(accepted.sessionMinted, false);
  assert.equal(accepted.pairingAuthorityOwnedBy, '#3080');
  assert.equal(JSON.stringify(accepted).includes('secret-value'), false);
  const status = (await controller.dispatch('padiem:shell:get-status', undefined)) as {
    pairingSeamAccepted: boolean;
  };
  assert.equal(status.pairingSeamAccepted, true);
});

test('#3083 a malformed deep link is rejected and no state is minted', async () => {
  const { controller } = makeController();
  for (const bad of [
    { deepLink: 'https://evil.example/pair?code=1' },
    { deepLink: 'padiem://pairing?code=1' },
    { deepLink: 42 },
    {},
    undefined,
  ]) {
    const result = (await controller.dispatch(
      'padiem:shell:pairing-deeplink-submit',
      bad,
    )) as Record<string, unknown>;
    assert.equal(result.accepted, false);
    assert.equal(result.correlationRef, null);
    assert.equal(result.sessionMinted, false);
  }
  const status = (await controller.dispatch('padiem:shell:get-status', undefined)) as {
    deviceState: string;
  };
  assert.equal(status.deviceState, 'NOT_PAIRED');
});

test('#3083 bounded log goes through redaction and never returns raw runner output', async () => {
  const githubValue = ['ghp', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123'].join('_');
  const { controller } = makeController([
    'padiem-headless-runner ready',
    `token ${githubValue}`,
  ]);
  const log = (await controller.dispatch('padiem:shell:get-bounded-log', { maxLines: 5 })) as {
    lines: string[];
    redactionApplied: boolean;
  };
  assert.equal(log.redactionApplied, true);
  assert.equal(log.lines.length, 2);
  assert.equal(log.lines[1]!.includes(githubValue), false);
  await assert.rejects(
    () => controller.dispatch('padiem:shell:get-bounded-log', { maxLines: -3 }),
    /maxLines must be a positive integer/,
  );
});

test('#3083 controller shutdown stops the runner and leaves nothing running', async () => {
  const { controller, port } = makeController();
  await controller.dispatch('padiem:shell:pairing-deeplink-submit', {
    deepLink: 'padiem://pair?code=abc',
  });
  await controller.dispatch('padiem:shell:runner-start', { requestedBy: 'renderer-shell' });
  await controller.shutdown();
  assert.equal(port.handle.isAlive(), false);
  const status = (await controller.dispatch('padiem:shell:get-status', undefined)) as {
    deviceState: string;
    runnerState: string;
    runnerPid: number | null;
  };
  assert.equal(status.runnerState, 'STOPPED');
  assert.equal(status.runnerPid, null);
  assert.equal(status.deviceState, 'OFFLINE');
});
