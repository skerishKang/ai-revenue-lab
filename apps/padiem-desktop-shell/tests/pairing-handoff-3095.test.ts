import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { ShellController } from '../src/supervisor/shell-controller.js';
import { HeadlessRunnerSupervisor, type RunnerSpawnSpec } from '../src/supervisor/runner-supervisor.js';
import type { RunnerProcessHandle, RunnerProcessPort } from '../src/supervisor/runner-supervisor.js';

const HERE = dirname(fileURLToPath(import.meta.url));
// `npm test` runs the compiled output from `dist/tests`, so the repository
// source lives two levels up from that. Resolve it by walking up until the
// `src` tree is found, which works for both the source and compiled layouts.
function repoRootFrom(start: string): string {
  let dir = start;
  for (let i = 0; i < 6; i += 1) {
    if (existsSync(join(dir, 'src', 'supervisor', 'shell-controller.ts'))) return dir;
    dir = dirname(dir);
  }
  throw new Error('desktop shell source root not found');
}
const REPO = repoRootFrom(HERE);
const SRC = join(REPO, 'src');

/** A code with the exact #3080 shape: 32 lowercase hex characters. */
const CODE = '0123456789abcdef0123456789abcdef';

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
  return { controller, logLines, port, supervisor };
}

test('#3095 controller hands one bounded pairing code to the trusted runner', async () => {
  const { controller } = makeController();
  const response = await controller.pairingDeepLinkSubmit({
    deepLink: `padiem://pair?code=${CODE}&source=shell`,
  });
  assert.equal(response.accepted, true);
  assert.equal(response.pairingCodeTransferred, true);

  const handoff = controller.takePairingHandoffForRunner();
  assert.ok(handoff);
  assert.equal(handoff.pairingCode, CODE);
  assert.match(handoff.correlationRef, /^pairref-[0-9a-f]{16}$/);
});

test('#3095 the renderer response never carries the pairing code', async () => {
  const { controller } = makeController();
  const response = await controller.pairingDeepLinkSubmit({
    deepLink: `padiem://pair?code=${CODE}`,
  });
  const serialised = JSON.stringify(response);
  assert.equal(serialised.includes(CODE), false);
  assert.equal('pairingCode' in response, false);
  assert.equal(response.pairingCodePersisted, false);
  assert.equal(response.pairingCodeRendererDiagnostic, false);
  // Only the boolean fact crosses the IPC surface.
  assert.equal(response.pairingCodeTransferred, true);
});

test('#3095 the handoff is consumed exactly once', async () => {
  const { controller } = makeController();
  await controller.pairingDeepLinkSubmit({ deepLink: `padiem://pair?code=${CODE}` });
  const first = controller.takePairingHandoffForRunner();
  assert.ok(first);
  // A second take cannot replay an already-consumed code.
  assert.equal(controller.takePairingHandoffForRunner(), null);
});

test('#3095 no pairing code is ever written to the bounded log', async () => {
  const logLines: string[] = ['padiem://pair?code=boot'];
  const { controller } = makeController(logLines);
  await controller.pairingDeepLinkSubmit({ deepLink: `padiem://pair?code=${CODE}` });
  controller.takePairingHandoffForRunner();
  assert.equal(logLines.join('\n').includes(CODE), false);
  const projected = JSON.stringify(controller.getBoundedLog({ maxLines: 50 }));
  assert.equal(projected.includes(CODE), false);
});

test('#3095 an out-of-shape code is never transferred', async () => {
  const { controller } = makeController();
  for (const bad of ['abc123', CODE.toUpperCase(), `${CODE.slice(0, 31)}g`]) {
    const response = await controller.pairingDeepLinkSubmit({
      deepLink: `padiem://pair?code=${bad}`,
    });
    assert.equal(response.accepted, true, 'the seam still accepts the deep link');
    assert.equal(response.pairingCodeTransferred, false, `no transfer for ${bad}`);
    assert.equal(controller.takePairingHandoffForRunner(), null);
  }
});

test('#3095 controller still owns no pairing authority', async () => {
  const source = readFileSync(join(SRC, 'supervisor', 'shell-controller.ts'), 'utf8');
  const pairingSource = readFileSync(join(SRC, 'contract', 'pairing-deeplink.ts'), 'utf8');
  // The shell must not mint a session or persist a credential.
  assert.equal(/credentialStored:\s*true/.test(source), false);
  assert.equal(/sessionMinted:\s*true/.test(source), false);
  assert.equal(/CREDENTIAL_PERSISTENCE:\s*true/.test(pairingSource), false);
  // SECOND_DEEPLINK_PARSER=0: only the controller interprets a deep link.
  const mainSource = readFileSync(join(SRC, 'main', 'main.ts'), 'utf8');
  const singleInstanceSource = readFileSync(join(SRC, 'main', 'single-instance.ts'), 'utf8');
  assert.equal(/parsePairingDeepLink\s*\(/.test(mainSource), false);
  assert.equal(/parsePairingDeepLink\s*\(/.test(singleInstanceSource), false);
  assert.equal(/takePairingCodeTransfer\s*\(/.test(mainSource), false);
});
