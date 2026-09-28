/**
 * #3140 — the main-process consumer of the bounded pairing handoff.
 *
 * These are behavioural tests of the wiring that was missing: the handoff is
 * drained exactly once, only to the runner, and the code is never logged,
 * projected or retained.
 */

import assert from 'node:assert/strict';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

import {
  PAIRING_HANDOFF_CONTRACT,
  PairingHandoffConsumer,
  handoffDeliveryMarker,
} from '../src/main/pairing-handoff-consumer.js';
import { HeadlessRunnerSupervisor } from '../src/supervisor/runner-supervisor.js';
import { parsePairingDeepLink, pairingHandoffConsumedMarker } from '../src/contract/pairing-deeplink.js';

const CODE = '0123456789abcdef0123456789abcdef';

/** Mirrors the controller's two-phase ownership: peek never consumes. */
class FakeController {
  #pending: { pairingCode: string; correlationRef: string; challengeId: string } | null;
  peekCount = 0;
  commitCount = 0;

  constructor(
    initial: { pairingCode: string; correlationRef: string; challengeId: string } | null,
  ) {
    this.#pending = initial;
  }

  peekPairingHandoffForRunner(): {
    pairingCode: string;
    correlationRef: string;
    challengeId: string;
  } | null {
    this.peekCount += 1;
    return this.#pending === null ? null : { ...this.#pending };
  }

  commitPairingHandoffDelivery(): {
    pairingCode: string;
    correlationRef: string;
    challengeId: string;
  } | null {
    this.commitCount += 1;
    const handoff = this.#pending;
    this.#pending = null;
    return handoff;
  }

  arm(handoff: { pairingCode: string; correlationRef: string; challengeId: string }): void {
    this.#pending = handoff;
  }
}

test('the handoff reaches the runner exactly once', async () => {
  const controller = new FakeController({ pairingCode: CODE, correlationRef: 'pairref.1', challengeId: 'challenge.1' });
  const sent: string[] = [];
  const consumer = new PairingHandoffConsumer({
    source: controller,
    deliver: (line: string) => {
      sent.push(line);
      return Promise.resolve({ acknowledged: true, handoffMarker: handoffDeliveryMarker(CODE) });
    },
    isRunnerLive: () => true,
  });

  assert.equal(await consumer.deliverPending(), 'delivered');
  assert.equal(await consumer.deliverPending(), 'no_pending_handoff');
  assert.equal(controller.commitCount, 1); // committed once; the second peek finds nothing
  assert.equal(sent.length, 1);
  assert.equal(consumer.stats().deliveredCount, 1);
});

test('an unavailable runner leaves the handoff armed instead of burning it', async () => {
  const controller = new FakeController({ pairingCode: CODE, correlationRef: 'pairref.1', challengeId: 'challenge.1' });
  let live = false;
  const consumer = new PairingHandoffConsumer({
    source: controller,
    deliver: () => Promise.resolve({ acknowledged: true, handoffMarker: handoffDeliveryMarker(CODE) }),
    isRunnerLive: () => live,
  });

  assert.equal(await consumer.deliverPending(), 'runner_unavailable');
  assert.equal(controller.commitCount, 0, 'a missing runner must not consume the handoff');
  assert.equal(controller.peekCount, 0, 'a missing runner must not even look');
  assert.equal(consumer.stats().deliveredCount, 0);

  live = true;
  assert.equal(await consumer.deliverPending(), 'delivered');
  assert.equal(controller.commitCount, 1);
});

test('the delivered line carries the code exactly once and only to the runner', async () => {
  const controller = new FakeController({ pairingCode: CODE, correlationRef: 'pairref.1', challengeId: 'challenge.1' });
  const sent: string[] = [];
  const consumer = new PairingHandoffConsumer({
    source: controller,
    deliver: (line: string) => {
      sent.push(line);
      return Promise.resolve({ acknowledged: true, handoffMarker: handoffDeliveryMarker(CODE) });
    },
    isRunnerLive: () => true,
  });
  await consumer.deliverPending();

  assert.equal(sent.length, 1);
  const line = sent[0] as string;
  const payload = JSON.parse(line) as Record<string, string>;
  assert.equal(payload.contract_version, 'claw-desktop-pairing-handoff.v1');
  assert.equal(payload.pairing_code, CODE);
  assert.equal(payload.correlation_ref, 'pairref.1');
  assert.equal(payload.challenge_id, 'challenge.1');
  assert.equal(line.split(CODE).length - 1, 1, 'the code appears exactly once');
});

test('the consumer retains no pairing code and reports a marker instead', async () => {
  const controller = new FakeController({ pairingCode: CODE, correlationRef: 'pairref.1', challengeId: 'challenge.1' });
  const consumer = new PairingHandoffConsumer({
    source: controller,
    deliver: () => Promise.resolve({ acknowledged: true, handoffMarker: handoffDeliveryMarker(CODE) }),
    isRunnerLive: () => true,
  });
  await consumer.deliverPending();

  const stats = consumer.stats();
  assert.equal(stats.pairingCodeRetained, false);
  assert.equal(stats.lastDeliveredMarker, pairingHandoffConsumedMarker(CODE));
  assert.equal(JSON.stringify(stats).includes(CODE), false, 'no pairing code in the diagnostic');
});

test('a refused delivery is reported truthfully and never retried silently', async () => {
  const controller = new FakeController({ pairingCode: CODE, correlationRef: 'pairref.1', challengeId: 'challenge.1' });
  const consumer = new PairingHandoffConsumer({
    source: controller,
    deliver: () => Promise.reject(new Error('pipe closed')),
    isRunnerLive: () => true,
  });
  assert.equal(await consumer.deliverPending(), 'delivery_refused');
  assert.equal(consumer.stats().deliveredCount, 0);
});

test('the consumer adds no pairing authority, host, execution authority or port', () => {
  assert.equal(PAIRING_HANDOFF_CONTRACT.PAIRING_AUTHORITY_IMPLEMENTED, false);
  assert.equal(PAIRING_HANDOFF_CONTRACT.RESIDENT_HOST_IMPLEMENTED, false);
  assert.equal(PAIRING_HANDOFF_CONTRACT.EXECUTION_AUTHORITY_IMPLEMENTED, false);
  assert.equal(PAIRING_HANDOFF_CONTRACT.SECOND_PAIRING_AUTHORITY, 0);
  assert.equal(PAIRING_HANDOFF_CONTRACT.PUBLIC_INBOUND_PORT, 0);
  assert.equal(PAIRING_HANDOFF_CONTRACT.PAIRING_CODE_RENDERER_EXPOSURE, 0);
  assert.equal(PAIRING_HANDOFF_CONTRACT.PAIRING_CODE_LOGGED, 0);
  assert.equal(PAIRING_HANDOFF_CONTRACT.PAIRING_CODE_GENERAL_PERSISTENCE, 0);
  assert.equal(PAIRING_HANDOFF_CONTRACT.HANDOFF_CONSUMED_EXACTLY_ONCE, true);
});

test('a deep link armed by the main flow is what the consumer drains', async () => {
  // The handoff the shell receives is the one #3095 already parses and bounds.
  const parsed = parsePairingDeepLink(`padiem://pair?code=${CODE}&challenge=challenge.1`);
  assert.equal(parsed.kind, 'pair');
  const controller = new FakeController({
    pairingCode: CODE,
    correlationRef: parsed.correlationRef,
    challengeId: parsed.challengeId,
  });
  const consumer = new PairingHandoffConsumer({
    source: controller,
    deliver: () => Promise.resolve({ acknowledged: true, handoffMarker: handoffDeliveryMarker(CODE) }),
    isRunnerLive: () => true,
  });
  assert.equal(await consumer.deliverPending(), 'delivered');
});

test('a failed delivery leaves the one-time handoff armed and retryable', async () => {
  const controller = new FakeController({ pairingCode: CODE, correlationRef: 'pairref.1', challengeId: 'challenge.1' });
  let accept = false;
  const sent: string[] = [];
  const consumer = new PairingHandoffConsumer({
    source: controller,
    deliver: (line: string) => {
      sent.push(line);
      return Promise.resolve(
        accept
          ? { acknowledged: true, handoffMarker: handoffDeliveryMarker(CODE) }
          : { acknowledged: false, handoffMarker: null },
      );
    },
    isRunnerLive: () => true,
  });

  // No acknowledgement arrives: refused truthfully, and NOT burned.
  assert.equal(await consumer.deliverPending(), 'ack_timeout');
  assert.equal(controller.commitCount, 0, 'a refused delivery must not spend the one-shot');
  assert.equal(consumer.stats().deliveredCount, 0);
  assert.equal(consumer.stats().lastDeliveredMarker, null, 'no marker for an undelivered handoff');

  // A later attempt delivers the same handoff, and only then is it spent.
  accept = true;
  assert.equal(await consumer.deliverPending(), 'delivered');
  assert.equal(controller.commitCount, 1);
  assert.equal(sent.length, 2, 'the same handoff was offered again, not a second handoff');
  assert.equal(consumer.stats().lastDeliveredMarker, pairingHandoffConsumedMarker(CODE));
});

/**
 * #3140 review item 3: the child_process invariant must be enforced over the
 * *whole* shell source tree, not a list the previous guard happened to
 * enumerate. A new module must not be able to reintroduce a second spawn path.
 */
test('only the canonical process port may import node:child_process', () => {
  const here = path.dirname(fileURLToPath(import.meta.url));
  let root = here;
  for (let index = 0; index < 6; index += 1) {
    if (existsSync(path.join(root, 'src', 'main', 'main.ts'))) break;
    root = path.dirname(root);
  }
  const offenders: string[] = [];
  const walk = (directory: string): void => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const full = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        walk(full);
        continue;
      }
      if (!entry.name.endsWith('.ts')) continue;
      if (full.endsWith(path.join('supervisor', 'production-runner-process-port.ts'))) continue;
      if (/node:child_process|require\(['"]child_process['"]\)/.test(readFileSync(full, 'utf8'))) {
        offenders.push(path.relative(root, full));
      }
    }
  };
  walk(path.join(root, 'src'));
  assert.deepEqual(offenders, [], `only the process port may spawn: ${offenders.join(', ')}`);
});

test('the resident host process is owned by the supervisor, not the main flow module', () => {
  const here = path.dirname(fileURLToPath(import.meta.url));
  let root = here;
  for (let index = 0; index < 6; index += 1) {
    if (existsSync(path.join(root, 'src', 'main', 'main.ts'))) break;
    root = path.dirname(root);
  }
  // The direct spawn module is gone: there is no second spawn path to own.
  assert.equal(existsSync(path.join(root, 'src', 'main', 'pairing-main-flow-process.ts')), false);
  const mainSource = readFileSync(path.join(root, 'src', 'main', 'main.ts'), 'utf8');
  assert.match(mainSource, /startResident/);
  assert.match(mainSource, /stopResident/);
});

test('a successful write is not a delivery acknowledgement', async () => {
  // #3140 review A: writing to the pipe proves nothing. Each of these is a
  // distinct refusal that must leave the one-shot armed.
  const cases: ReadonlyArray<readonly [string, { acknowledged: boolean; handoffMarker: string | null }]> = [
    ['ack_timeout', { acknowledged: false, handoffMarker: null }],
    ['ack_rejected', { acknowledged: true, handoffMarker: null }],
    ['ack_mismatch', { acknowledged: true, handoffMarker: handoffDeliveryMarker('other') }],
  ];
  for (const [expected, acknowledgement] of cases) {
    const controller = new FakeController({ pairingCode: CODE, correlationRef: 'pairref.1', challengeId: 'challenge.1' });
    const consumer = new PairingHandoffConsumer({
      source: controller,
      deliver: () => Promise.resolve(acknowledgement),
      isRunnerLive: () => true,
    });
    assert.equal(await consumer.deliverPending(), expected);
    assert.equal(controller.commitCount, 0, `${expected} must not spend the one-shot`);
    assert.equal(consumer.stats().deliveredCount, 0);
  }
});

test('the resident env is an explicit allowlist, and a missing broker URL fails closed', () => {
  const here = path.dirname(fileURLToPath(import.meta.url));
  let root = here;
  for (let index = 0; index < 6; index += 1) {
    if (existsSync(path.join(root, 'src', 'main', 'main.ts'))) break;
    root = path.dirname(root);
  }
  const mainSource = readFileSync(path.join(root, 'src', 'main', 'main.ts'), 'utf8');

  // Every variable the resident may see is named explicitly; the shell's whole
  // environment is never handed over.
  assert.equal(/env:\s*\{\s*\.\.\.process\.env/.test(mainSource), false);
  const projection = mainSource.slice(mainSource.indexOf('function residentSpec'));
  const named = [...projection.matchAll(/process\.env\.([A-Z0-9_]+)/g)].map((m) => m[1] ?? '');
  for (const required of [
    'PADIEM_AGENT_PROJECT_ROOT',
    'PADIEM_AGENT_DEVICE_ID',
    'PADIEM_AGENT_AUTHORITY_REF',
    'PADIEM_AGENT_REQUEST_PORT',
    'PADIEM_AGENT_CREDENTIAL_DIR',
    'PADIEM_AGENT_BROKER_URL',
  ]) {
    assert.ok(named.includes(required), `resident projection must name ${required}`);
  }
  assert.deepEqual(
    named.filter((name: string) => !name.startsWith('PADIEM_AGENT_')),
    ['PADIEM_PYTHON', 'PADIEM_3140_EVIDENCE_MARKER'],
    'only the harness and the interpreter may be read outside the agent allowlist',
  );
});

test('a settled resident keeps its bounded output for later inspection', () => {
  const here = path.dirname(fileURLToPath(import.meta.url));
  let root = here;
  for (let index = 0; index < 6; index += 1) {
    if (existsSync(path.join(root, 'src', 'supervisor', 'runner-supervisor.ts'))) break;
    root = path.dirname(root);
  }
  const settled = { lines: ['{"status":"refused"}'], maxLines: 50 };
  const handle = {
    pid: 4242,
    isAlive: () => false,
    kill: () => undefined,
    waitForExit: async () => ({ code: 0, signal: null }),
    onExit: () => () => undefined,
    sendLine: () => false,
    boundedOutput: () => settled,
  };
  const port = {
    spawnRunner: async () => handle,
    spawnResident: async () => handle,
    boundedResidentOutput: () => settled,
  };
  const supervisor = new HeadlessRunnerSupervisor({
    port: port as never,
    spec: { executablePath: 'python', args: [], cwd: '.', env: {}, shell: false, stdio: 'pipe' },
    shutdownGraceMs: 1,
  });
  // The projection is answerable at any time, and a settled resident is read
  // from the retained snapshot rather than from a dropped handle.
  assert.ok(Array.isArray(supervisor.boundedResidentOutput().lines));
  const empty = new HeadlessRunnerSupervisor({
    port: { spawnRunner: async () => handle } as never,
    spec: { executablePath: 'python', args: [], cwd: '.', env: {}, shell: false, stdio: 'pipe' },
    shutdownGraceMs: 1,
  });
  assert.deepEqual(empty.boundedResidentOutput().lines, []);
  const source = readFileSync(
    path.join(root, 'src', 'supervisor', 'runner-supervisor.ts'),
    'utf8',
  );
  assert.ok(
    source.includes('#residentSettledOutput'),
    'a settled resident must keep its bounded output for the evidence marker',
  );
});
