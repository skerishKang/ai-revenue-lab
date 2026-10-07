/**
 * #3647 — trusted-main bounded action host tests.
 *
 * Hermetic: the extraction source, lease provider and dispatch binding are
 * fakes. The host always takes a FRESH observation per action, so element
 * identity, credential markers and roles come from the same bounded authority
 * the action is about to act on. The final block reads real sources so a
 * future edit that widens authority fails here rather than in review.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { IPC_ALLOWLIST } from '../src/contract/ipc.js';
import {
  BrowserObservationHost,
  GENERIC_IPC_SURFACE,
  SECOND_BROWSER_AUTHORITY,
} from '../src/browser/browser-observation-host.js';
import {
  CANONICAL_LEASE_ADMISSION_WIRED,
  NEW_APPROVAL_STORE,
  STEP_UP_EXECUTION_IMPLEMENTED,
  BrowserActionHost,
  type ActionDispatchOp,
  type BrowserActionDispatchPort,
  type BrowserActionLeaseProvider,
} from '../src/browser/browser-action-host.js';
import type { BrowserObservationSourcePort } from '../src/browser/browser-observation-host.js';
import { composeTrustedBrowserActions } from '../src/browser/browser-action-composition.js';
import type {
  ObservationSourceElement,
  ObservationSourceSnapshot,
} from '../src/browser/browser-observation-contract.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const sourceRoot = path.join(here, '..', '..', 'src');

function readSource(...segments: string[]): string {
  return readFileSync(path.join(sourceRoot, ...segments), 'utf8');
}

function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^[ \t]*\/\/.*$/gm, '');
}

const ORIGIN = 'https://example.com';

function sourceElement(overrides: Partial<ObservationSourceElement>): ObservationSourceElement {
  return {
    role: 'link',
    name: 'Docs',
    bounds: { x: 10, y: 10, width: 80, height: 20 },
    stateFlags: ['focusable'],
    interactionFlags: ['clickable'],
    credentialField: false,
    ...overrides,
  } as ObservationSourceElement;
}

/** el-0001 link · el-0002 button · el-0003 textbox · el-0004 credential · el-0005 listbox · el-0006 group */
const DEFAULT_ELEMENTS: ObservationSourceElement[] = [
  sourceElement({ role: 'link', name: 'Docs' }),
  sourceElement({ role: 'button', name: '로그인' }),
  sourceElement({ role: 'textbox', name: '이름', interactionFlags: ['typeable', 'editable'] }),
  sourceElement({ role: 'textbox', name: '', credentialField: true, stateFlags: ['focusable', 'required'] }),
  sourceElement({ role: 'listbox', name: '옵션', bounds: { x: 0, y: 100, width: 200, height: 30 } }),
  sourceElement({ role: 'group', name: '패널', bounds: { x: 0, y: 0, width: 800, height: 600 } }),
];

function validLease(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    leaseId: 'lease/session-1',
    sessionRef: 'run/session-1',
    originRef: ORIGIN,
    allowedActions: ['click', 'type', 'scroll', 'focus', 'select'],
    maxActions: 8,
    issuedAtIso: '2026-10-08T09:00:00.000Z',
    expiresAtIso: '2026-10-08T09:05:00.000Z',
    ...overrides,
  };
}

interface HostHarness {
  readonly host: BrowserActionHost;
  readonly binding: BrowserActionDispatchPort & { ops: ActionDispatchOp[][] };
  readonly snapshotCount: () => number;
}

function harnessFactory(
  options: {
    readonly origin?: string;
    readonly elements?: ObservationSourceElement[];
    readonly lease?: Record<string, unknown>;
    readonly leaseThrows?: Error;
    readonly now?: () => Date;
  } = {},
): HostHarness {
  let current: ObservationSourceElement[] = options.elements ?? [];
  let snapshots = 0;
  const source: BrowserObservationSourcePort = {
    configured: true,
    snapshot: async (): Promise<ObservationSourceSnapshot> => {
      snapshots += 1;
      return { origin: options.origin ?? ORIGIN, elements: current };
    },
    close: async () => undefined,
  };
  const observation = new BrowserObservationHost({ source });
  const ops: ActionDispatchOp[][] = [];
  const binding: BrowserActionDispatchPort & { ops: ActionDispatchOp[][] } = {
    configured: true,
    dispatch: async (batch) => {
      ops.push([...batch]);
    },
    close: async () => undefined,
    ops,
  };
  const leaseProvider: BrowserActionLeaseProvider = {
    configured: true,
    lease: async () => {
      if (options.leaseThrows) throw options.leaseThrows;
      return options.lease ?? validLease();
    },
  };
  const host = new BrowserActionHost({
    observation,
    binding,
    leaseProvider,
    ...(options.now === undefined ? {} : { now: options.now }),
  });
  return { host, binding, snapshotCount: () => snapshots };
}

function errorCode(error: unknown): string {
  assert.ok(error instanceof Error, `expected an Error, got ${String(error)}`);
  return (error as { code?: string }).code ?? '';
}

test('unwired composition fails closed: no action is ever dispatched', async () => {
  const source: BrowserObservationSourcePort = {
    configured: true,
    snapshot: async () => ({ origin: ORIGIN, elements: [] }),
    close: async () => undefined,
  };
  const composition = composeTrustedBrowserActions({
    observation: new BrowserObservationHost({ source }),
  });
  assert.equal(composition.bindingConfigured, false);
  assert.equal(composition.leaseProviderConfigured, false);
  await assert.rejects(
    () =>
      composition.host.execute({
        action: 'click',
        sessionRef: 'run/session-1',
        originRef: ORIGIN,
        elementRef: 'el-0001',
      }),
    (error: unknown) => errorCode(error) === 'host_unavailable',
  );
});

test('a refusing canonical lease authority collapses into lease_invalid without leaking', async () => {
  const harness = harnessFactory({
    elements: DEFAULT_ELEMENTS,
    leaseThrows: new Error('internal approval material: p01-decision-xyz'),
  });
  await assert.rejects(
    () =>
      harness.host.execute({
        action: 'click',
        sessionRef: 'run/session-1',
        originRef: ORIGIN,
        elementRef: 'el-0001',
      }),
    (error: unknown) => {
      assert.equal(errorCode(error), 'lease_invalid');
      assert.ok(!((error as Error).message.includes('p01-decision-xyz')));
      return true;
    },
  );
});

test('expired leases and scope mismatches refuse before any dispatch', async () => {
  const expired = harnessFactory({
    elements: DEFAULT_ELEMENTS,
    lease: validLease({ expiresAtIso: '2026-10-08T08:00:00.000Z' }),
  });
  await assert.rejects(
    () =>
      expired.host.execute({
        action: 'click',
        sessionRef: 'run/session-1',
        originRef: ORIGIN,
        elementRef: 'el-0001',
      }),
    (error: unknown) => errorCode(error) === 'lease_invalid',
  );

  const otherOrigin = harnessFactory({
    elements: DEFAULT_ELEMENTS,
    lease: validLease({ originRef: 'https://other.example' }),
  });
  await assert.rejects(
    () =>
      otherOrigin.host.execute({
        action: 'click',
        sessionRef: 'run/session-1',
        originRef: ORIGIN,
        elementRef: 'el-0001',
      }),
    (error: unknown) => errorCode(error) === 'origin_scope_exceeded',
  );

  const viewMoved = harnessFactory({ elements: DEFAULT_ELEMENTS, origin: 'https://moved.example' });
  await assert.rejects(
    () =>
      viewMoved.host.execute({
        action: 'click',
        sessionRef: 'run/session-1',
        originRef: ORIGIN,
        elementRef: 'el-0001',
      }),
    (error: unknown) => errorCode(error) === 'origin_scope_exceeded',
  );
  assert.equal(viewMoved.binding.ops.length, 0);

  const uncovered = harnessFactory({
    elements: DEFAULT_ELEMENTS,
    lease: validLease({ allowedActions: ['click'] }),
  });
  await assert.rejects(
    () =>
      uncovered.host.execute({
        action: 'type',
        sessionRef: 'run/session-1',
        originRef: ORIGIN,
        elementRef: 'el-0003',
        text: 'hi',
      }),
    (error: unknown) => errorCode(error) === 'lease_invalid',
  );
});

test('actions bind only to elements of the fresh observation', async () => {
  const harness = harnessFactory({ elements: DEFAULT_ELEMENTS });
  await assert.rejects(
    () =>
      harness.host.execute({
        action: 'click',
        sessionRef: 'run/session-1',
        originRef: ORIGIN,
        elementRef: 'el-0099',
      }),
    (error: unknown) => errorCode(error) === 'element_not_observed',
  );
  assert.equal(harness.snapshotCount(), 1);
  assert.equal(harness.binding.ops.length, 0);
});

test('credential elements refuse every direct action on the masked marker alone', async () => {
  const harness = harnessFactory({ elements: DEFAULT_ELEMENTS });
  await assert.rejects(
    () =>
      harness.host.execute({
        action: 'type',
        sessionRef: 'run/session-1',
        originRef: ORIGIN,
        elementRef: 'el-0004',
        text: 'hunter2',
      }),
    (error: unknown) => errorCode(error) === 'credential_element_forbidden',
  );
  await assert.rejects(
    () =>
      harness.host.execute({
        action: 'click',
        sessionRef: 'run/session-1',
        originRef: ORIGIN,
        elementRef: 'el-0004',
      }),
    (error: unknown) => errorCode(error) === 'credential_element_forbidden',
  );
  assert.equal(harness.binding.ops.length, 0);
});

test('button-role click and focus default to step-up; other roles stay bounded', async () => {
  const harness = harnessFactory({ elements: DEFAULT_ELEMENTS });
  await assert.rejects(
    () =>
      harness.host.execute({
        action: 'click',
        sessionRef: 'run/session-1',
        originRef: ORIGIN,
        elementRef: 'el-0002',
      }),
    (error: unknown) => errorCode(error) === 'step_up_required',
  );
  await assert.rejects(
    () =>
      harness.host.execute({
        action: 'focus',
        sessionRef: 'run/session-1',
        originRef: ORIGIN,
        elementRef: 'el-0002',
      }),
    (error: unknown) => errorCode(error) === 'step_up_required',
  );
  await assert.rejects(
    () =>
      harness.host.execute({
        action: 'click',
        sessionRef: 'run/session-1',
        originRef: ORIGIN,
        elementRef: 'el-0006',
      }),
    (error: unknown) => errorCode(error) === 'contract_violation',
  );
  assert.equal(harness.binding.ops.length, 0);

  const receipt = await harness.host.execute({
    action: 'click',
    sessionRef: 'run/session-1',
    originRef: ORIGIN,
    elementRef: 'el-0001',
  });
  assert.equal(receipt.outcome, 'dispatched');
  assert.equal(receipt.elementRef, 'el-0001');
  assert.equal(receipt.pageContentIncluded, false);
  assert.deepEqual(harness.binding.ops[0], [{ kind: 'click', x: 50, y: 20 }]);
});

test('type dispatches a bounded click-then-insertText pair at the observed center', async () => {
  const harness = harnessFactory({ elements: DEFAULT_ELEMENTS });
  const receipt = await harness.host.execute({
    action: 'type',
    sessionRef: 'run/session-1',
    originRef: ORIGIN,
    elementRef: 'el-0003',
    text: '안녕하세요',
  });
  assert.equal(receipt.action, 'type');
  assert.deepEqual(harness.binding.ops[0], [
    { kind: 'click', x: 50, y: 20 },
    { kind: 'insertText', text: '안녕하세요' },
  ]);
  await assert.rejects(
    () =>
      harness.host.execute({
        action: 'type',
        sessionRef: 'run/session-1',
        originRef: ORIGIN,
        elementRef: 'el-0001',
        text: 'hi',
      }),
    (error: unknown) => errorCode(error) === 'contract_violation',
  );
});

test('select dispatches the bounded keyboard path and scroll needs no element', async () => {
  const harness = harnessFactory({ elements: DEFAULT_ELEMENTS });
  await harness.host.execute({
    action: 'select',
    sessionRef: 'run/session-1',
    originRef: ORIGIN,
    elementRef: 'el-0005',
    optionIndex: 2,
  });
  assert.deepEqual(harness.binding.ops[0], [
    { kind: 'click', x: 100, y: 115 },
    { kind: 'key', key: 'ArrowDown' },
    { kind: 'key', key: 'ArrowDown' },
    { kind: 'key', key: 'ArrowDown' },
    { kind: 'key', key: 'Enter' },
  ]);
  const scrollReceipt = await harness.host.execute({
    action: 'scroll',
    sessionRef: 'run/session-1',
    originRef: ORIGIN,
    dx: 0,
    dy: -240,
  });
  assert.equal(scrollReceipt.elementRef, null);
  assert.deepEqual(harness.binding.ops[1], [{ kind: 'wheel', x: 0, y: 0, dx: 0, dy: -240 }]);
});

test('the lease action budget is enforced on the fast path', async () => {
  const harness = harnessFactory({
    elements: DEFAULT_ELEMENTS,
    lease: validLease({ allowedActions: ['click'], maxActions: 1 }),
  });
  await harness.host.execute({
    action: 'click',
    sessionRef: 'run/session-1',
    originRef: ORIGIN,
    elementRef: 'el-0001',
  });
  await assert.rejects(
    () =>
      harness.host.execute({
        action: 'click',
        sessionRef: 'run/session-1',
        originRef: ORIGIN,
        elementRef: 'el-0001',
      }),
    (error: unknown) => errorCode(error) === 'action_budget_exhausted',
  );
});

test('action ids are deterministic, content-free and sequence-scoped', async () => {
  const first = harnessFactory({
    elements: DEFAULT_ELEMENTS,
    now: () => new Date('2026-10-08T09:00:00.000Z'),
  });
  const receipt = await first.host.execute({
    action: 'click',
    sessionRef: 'run/session-1',
    originRef: ORIGIN,
    elementRef: 'el-0001',
  });
  const second = harnessFactory({
    elements: DEFAULT_ELEMENTS,
    now: () => new Date('2026-10-08T09:00:00.000Z'),
  });
  const replayed = await second.host.execute({
    action: 'click',
    sessionRef: 'run/session-1',
    originRef: ORIGIN,
    elementRef: 'el-0001',
  });
  assert.match(receipt.actionId, /^act_[0-9a-f]{24}$/);
  assert.equal(receipt.actionId, replayed.actionId);
});

test('no renderer channel, no second authority, no script evaluation exists', () => {
  const hostModule = stripComments(readSource('browser', 'browser-action-host.ts'));
  const composition = stripComments(readSource('browser', 'browser-action-composition.ts'));
  const binding = stripComments(readSource('browser', 'browser-action-electron-binding.ts'));
  assert.equal(STEP_UP_EXECUTION_IMPLEMENTED, false);
  assert.equal(CANONICAL_LEASE_ADMISSION_WIRED, false);
  assert.equal(NEW_APPROVAL_STORE, false);
  assert.equal(SECOND_BROWSER_AUTHORITY, false);
  assert.equal(GENERIC_IPC_SURFACE, false);
  for (const code of [hostModule, composition]) {
    assert.ok(!code.includes('ipcMain'));
    assert.ok(!code.includes('ipcRenderer'));
    assert.ok(!code.includes('execute' + 'JavaScript'));
  }
  // The binding's whole CDP surface is the declared Input.* allowlist.
  assert.ok(binding.includes("'Input.dispatchMouseEvent'"));
  assert.ok(binding.includes("'Input.insertText'"));
  assert.ok(binding.includes("'Input.dispatchKeyEvent'"));
  assert.ok(!binding.includes('Runtime.'));
  assert.ok(!binding.includes("'DOM."));
  for (const channel of IPC_ALLOWLIST) {
    assert.ok(!channel.toLowerCase().includes('browser:action'));
    assert.ok(!channel.toLowerCase().includes('observation'));
  }
});
