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
} from '../src/main/pairing-handoff-consumer.js';
import { parsePairingDeepLink, pairingHandoffConsumedMarker } from '../src/contract/pairing-deeplink.js';

const CODE = '0123456789abcdef0123456789abcdef';

/** Mirrors the controller's two-phase ownership: peek never consumes. */
class FakeController {
  #pending: { pairingCode: string; correlationRef: string } | null;
  peekCount = 0;
  commitCount = 0;

  constructor(initial: { pairingCode: string; correlationRef: string } | null) {
    this.#pending = initial;
  }

  peekPairingHandoffForRunner(): { pairingCode: string; correlationRef: string } | null {
    this.peekCount += 1;
    return this.#pending === null ? null : { ...this.#pending };
  }

  commitPairingHandoffDelivery(): { pairingCode: string; correlationRef: string } | null {
    this.commitCount += 1;
    const handoff = this.#pending;
    this.#pending = null;
    return handoff;
  }

  arm(handoff: { pairingCode: string; correlationRef: string }): void {
    this.#pending = handoff;
  }
}

test('the handoff reaches the runner exactly once', () => {
  const controller = new FakeController({ pairingCode: CODE, correlationRef: 'pairref.1' });
  const sent: string[] = [];
  const consumer = new PairingHandoffConsumer({
    source: controller,
    deliver: (line: string) => {
      sent.push(line);
      return true;
    },
    isRunnerLive: () => true,
  });

  assert.equal(consumer.deliverPending(), 'delivered');
  assert.equal(consumer.deliverPending(), 'no_pending_handoff');
  assert.equal(controller.commitCount, 1); // committed once; the second peek finds nothing
  assert.equal(sent.length, 1);
  assert.equal(consumer.stats().deliveredCount, 1);
});

test('an unavailable runner leaves the handoff armed instead of burning it', () => {
  const controller = new FakeController({ pairingCode: CODE, correlationRef: 'pairref.1' });
  let live = false;
  const consumer = new PairingHandoffConsumer({
    source: controller,
    deliver: () => true,
    isRunnerLive: () => live,
  });

  assert.equal(consumer.deliverPending(), 'runner_unavailable');
  assert.equal(controller.commitCount, 0, 'a missing runner must not consume the handoff');
  assert.equal(controller.peekCount, 0, 'a missing runner must not even look');
  assert.equal(consumer.stats().deliveredCount, 0);

  live = true;
  assert.equal(consumer.deliverPending(), 'delivered');
  assert.equal(controller.commitCount, 1);
});

test('the delivered line carries the code exactly once and only to the runner', () => {
  const controller = new FakeController({ pairingCode: CODE, correlationRef: 'pairref.1' });
  const sent: string[] = [];
  const consumer = new PairingHandoffConsumer({
    source: controller,
    deliver: (line: string) => {
      sent.push(line);
      return true;
    },
    isRunnerLive: () => true,
  });
  consumer.deliverPending();

  assert.equal(sent.length, 1);
  const line = sent[0] as string;
  const payload = JSON.parse(line) as Record<string, string>;
  assert.equal(payload.contract_version, 'claw-desktop-pairing-handoff.v1');
  assert.equal(payload.pairing_code, CODE);
  assert.equal(payload.correlation_ref, 'pairref.1');
  assert.equal(line.split(CODE).length - 1, 1, 'the code appears exactly once');
});

test('the consumer retains no pairing code and reports a marker instead', () => {
  const controller = new FakeController({ pairingCode: CODE, correlationRef: 'pairref.1' });
  const consumer = new PairingHandoffConsumer({
    source: controller,
    deliver: () => true,
    isRunnerLive: () => true,
  });
  consumer.deliverPending();

  const stats = consumer.stats();
  assert.equal(stats.pairingCodeRetained, false);
  assert.equal(stats.lastDeliveredMarker, pairingHandoffConsumedMarker(CODE));
  assert.equal(JSON.stringify(stats).includes(CODE), false, 'no pairing code in the diagnostic');
});

test('a refused delivery is reported truthfully and never retried silently', () => {
  const controller = new FakeController({ pairingCode: CODE, correlationRef: 'pairref.1' });
  const consumer = new PairingHandoffConsumer({
    source: controller,
    deliver: () => false,
    isRunnerLive: () => true,
  });
  assert.equal(consumer.deliverPending(), 'delivery_refused');
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

test('a deep link armed by the main flow is what the consumer drains', () => {
  // The handoff the shell receives is the one #3095 already parses and bounds.
  const parsed = parsePairingDeepLink(`padiem://pair?code=${CODE}&ref=pairref.1`);
  assert.equal(parsed.kind, 'pair');
  const controller = new FakeController({ pairingCode: CODE, correlationRef: parsed.correlationRef });
  const consumer = new PairingHandoffConsumer({
    source: controller,
    deliver: () => true,
    isRunnerLive: () => true,
  });
  assert.equal(consumer.deliverPending(), 'delivered');
});

test('a failed delivery leaves the one-time handoff armed and retryable', () => {
  const controller = new FakeController({ pairingCode: CODE, correlationRef: 'pairref.1' });
  let accept = false;
  const sent: string[] = [];
  const consumer = new PairingHandoffConsumer({
    source: controller,
    deliver: (line: string) => {
      sent.push(line);
      return accept;
    },
    isRunnerLive: () => true,
  });

  // The write is refused: refused truthfully, and NOT burned.
  assert.equal(consumer.deliverPending(), 'delivery_refused');
  assert.equal(controller.commitCount, 0, 'a refused delivery must not spend the one-shot');
  assert.equal(consumer.stats().deliveredCount, 0);
  assert.equal(consumer.stats().lastDeliveredMarker, null, 'no marker for an undelivered handoff');

  // A later attempt delivers the same handoff, and only then is it spent.
  accept = true;
  assert.equal(consumer.deliverPending(), 'delivered');
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
