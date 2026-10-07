/**
 * #3647 / #3669 — trusted-main bounded action host tests (post-CENTRAL ruling,
 * DECISION=B two-phase canonical lease admission).
 *
 * Hermetic: the extraction source, the two-phase lease authority and the
 * dispatch binding are fakes. The fake authority emulates the canonical
 * durable store: PHASE A resolve is read-only; PHASE B consume is the single
 * owner of the budget/idle/cross-origin slot facts, called immediately before
 * dispatch. The host always takes a FRESH observation per action; click is
 * restricted to roles the projection can prove non-committing; focus has its
 * own gate; a step-up target refuses without ever consuming a slot.
 * The final block reads real sources so authority drift fails here.
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
  LOCAL_LEASE_BOOKKEEPING_IS_AUTHORITY,
  NEW_APPROVAL_STORE,
  STEP_UP_EXECUTION_IMPLEMENTED,
  BrowserActionHost,
  type ActionDispatchOp,
  type BrowserActionDispatchPort,
  type BrowserActionLeaseAuthority,
} from '../src/browser/browser-action-host.js';
import type { BrowserObservationSourcePort } from '../src/browser/browser-observation-host.js';
import { composeTrustedBrowserActions } from '../src/browser/browser-action-composition.js';
import { LEASE_IDLE_SECONDS } from '../src/browser/browser-action-contract.js';
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

/**
 * el-0001 tab · el-0002 button · el-0003 textbox · el-0004 credential
 * el-0005 listbox · el-0006 link · el-0007 treeitem · el-0008 group
 * (textbox has no focusable flag variant below for the focus-gate refusal.)
 */
const DEFAULT_ELEMENTS: ObservationSourceElement[] = [
  sourceElement({ role: 'tab', name: '일반', interactionFlags: ['clickable'] }),
  sourceElement({ role: 'button', name: '로그인' }),
  sourceElement({ role: 'textbox', name: '이름', interactionFlags: ['typeable', 'editable'] }),
  sourceElement({ role: 'textbox', name: '', credentialField: true, stateFlags: ['focusable', 'required'] }),
  sourceElement({ role: 'listbox', name: '옵션', bounds: { x: 0, y: 100, width: 200, height: 30 } }),
  sourceElement({ role: 'link', name: '도움말', bounds: { x: 400, y: 560, width: 60, height: 20 } }),
  sourceElement({ role: 'treeitem', name: '폴더', bounds: { x: 20, y: 200, width: 120, height: 24 } }),
  sourceElement({ role: 'group', name: '패널', bounds: { x: 0, y: 0, width: 800, height: 600 }, stateFlags: [] }),
];

function validLease(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    leaseId: 'lease/session-1',
    requestFingerprint: 'fingerprint/session-1',
    browserSessionRef: 'run/session-1',
    runRef: 'run_3647',
    workspaceRef: 'workspace_3647',
    ownerRef: 'owner_3647',
    allowedActionClasses: ['click', 'type', 'scroll', 'focus', 'select'],
    originScope: ORIGIN,
    maxActions: 25,
    issuedAtIso: '2026-10-08T09:00:00.000Z',
    expiresAtIso: '2026-10-08T09:05:00.000Z',
    approvalRef: 'decision_3647',
    evidenceRef: 'evidence_3647',
    ...overrides,
  };
}

interface AuthorityCounters {
  readonly resolveCalls: number;
  readonly consumeCalls: number;
  readonly consumed: number;
}

interface HostHarness {
  readonly host: BrowserActionHost;
  readonly binding: BrowserActionDispatchPort & { ops: ActionDispatchOp[][] };
  readonly authority: AuthorityCounters;
  readonly snapshotCount: () => number;
}

function harnessFactory(
  options: {
    readonly origin?: string;
    readonly elements?: ObservationSourceElement[];
    readonly lease?: Record<string, unknown>;
    readonly resolveThrows?: Error;
    readonly consumeRefusalCode?: string;
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
  const clock = options.now ?? (() => new Date('2026-10-08T09:00:00.000Z'));
  // The fake authority emulates the canonical durable store: PHASE A is
  // read-only; PHASE B is the single owner of the budget/idle/cross-origin
  // slot facts (check order mirrors the store: cross-origin, idle, budget).
  const state = { resolveCalls: 0, consumeCalls: 0, consumed: 0, lastConsumeAtMs: 0 };
  const leaseAuthority: BrowserActionLeaseAuthority = {
    configured: true,
    resolve: async () => {
      state.resolveCalls += 1;
      if (options.resolveThrows) throw options.resolveThrows;
      return options.lease ?? validLease();
    },
    consume: async (input) => {
      state.consumeCalls += 1;
      if (options.consumeRefusalCode !== undefined) {
        throw Object.assign(new Error('canonical lease refusal'), {
          code: options.consumeRefusalCode,
        });
      }
      const lease = options.lease ?? validLease();
      if (input.observedOrigin !== lease.originScope) {
        // The store revokes with reason=cross_origin and refuses; no increment.
        throw Object.assign(new Error('cross origin'), { code: 'origin_scope_exceeded' });
      }
      const nowMs = clock().getTime();
      if (state.consumed > 0 && nowMs - state.lastConsumeAtMs > LEASE_IDLE_SECONDS * 1000) {
        // The store revokes with reason=idle_expired and refuses; no increment.
        throw Object.assign(new Error('idle expired'), { code: 'lease_idle_exceeded' });
      }
      if (state.consumed + 1 > (lease.maxActions as number)) {
        throw Object.assign(new Error('budget exhausted'), { code: 'action_budget_exhausted' });
      }
      state.consumed += 1;
      state.lastConsumeAtMs = nowMs;
      return state.consumed;
    },
  };
  const host = new BrowserActionHost({
    observation,
    binding,
    leaseAuthority,
    ...(options.now === undefined ? {} : { now: options.now }),
  });
  return {
    host,
    binding,
    authority: {
      get resolveCalls() {
        return state.resolveCalls;
      },
      get consumeCalls() {
        return state.consumeCalls;
      },
      get consumed() {
        return state.consumed;
      },
    },
    snapshotCount: () => snapshots,
  };
}

function errorCode(error: unknown): string {
  assert.ok(error instanceof Error, `expected an Error, got ${String(error)}`);
  return (error as { code?: string }).code ?? '';
}

function clickRequest(elementRef: string): Record<string, unknown> {
  return { action: 'click', browserSessionRef: 'run/session-1', originRef: ORIGIN, elementRef };
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
  assert.equal(composition.leaseAuthorityConfigured, false);
  await assert.rejects(
    () => composition.host.execute(clickRequest('el-0001')),
    (error: unknown) => errorCode(error) === 'host_unavailable',
  );
});

test('a refusing canonical lease authority collapses into lease_invalid without leaking', async () => {
  const harness = harnessFactory({
    elements: DEFAULT_ELEMENTS,
    resolveThrows: new Error('internal approval material: p01-decision-xyz'),
  });
  await assert.rejects(
    () => harness.host.execute(clickRequest('el-0001')),
    (error: unknown) => {
      assert.equal(errorCode(error), 'lease_invalid');
      assert.ok(!((error as Error).message.includes('p01-decision-xyz')));
      return true;
    },
  );

  // A coded authority failure carrying P01 material collapses the same way.
  const coded = harnessFactory({
    elements: DEFAULT_ELEMENTS,
    consumeRefusalCode: 'p01_approval_invalid',
  });
  await assert.rejects(
    () => coded.host.execute(clickRequest('el-0001')),
    (error: unknown) => {
      assert.equal(errorCode(error), 'lease_invalid');
      assert.ok(!((error as Error).message.includes('p01')));
      return true;
    },
  );
  assert.equal(coded.binding.ops.length, 0);
});

test('expired leases and scope mismatches refuse read-only, without consuming', async () => {
  const expired = harnessFactory({
    elements: DEFAULT_ELEMENTS,
    lease: validLease({ expiresAtIso: '2026-10-08T08:00:00.000Z' }),
  });
  await assert.rejects(
    () => expired.host.execute(clickRequest('el-0001')),
    (error: unknown) => errorCode(error) === 'lease_invalid',
  );
  assert.equal(expired.authority.consumeCalls, 0);

  const otherOrigin = harnessFactory({
    elements: DEFAULT_ELEMENTS,
    lease: validLease({ originScope: 'https://other.example' }),
  });
  await assert.rejects(
    () => otherOrigin.host.execute(clickRequest('el-0001')),
    (error: unknown) => errorCode(error) === 'origin_scope_exceeded',
  );
  assert.equal(otherOrigin.binding.ops.length, 0);

  const viewMoved = harnessFactory({ elements: DEFAULT_ELEMENTS, origin: 'https://moved.example' });
  await assert.rejects(
    () => viewMoved.host.execute(clickRequest('el-0001')),
    (error: unknown) => errorCode(error) === 'origin_scope_exceeded',
  );
  assert.equal(viewMoved.binding.ops.length, 0);
  assert.equal(viewMoved.authority.consumeCalls, 0);

  const uncovered = harnessFactory({
    elements: DEFAULT_ELEMENTS,
    lease: validLease({ allowedActionClasses: ['click'] }),
  });
  await assert.rejects(
    () =>
      uncovered.host.execute({
        action: 'type',
        browserSessionRef: 'run/session-1',
        originRef: ORIGIN,
        elementRef: 'el-0003',
        text: 'hi',
      }),
    (error: unknown) => errorCode(error) === 'lease_invalid',
  );
  assert.equal(uncovered.authority.consumeCalls, 0);
});

test('actions bind only to elements of the fresh observation', async () => {
  const harness = harnessFactory({ elements: DEFAULT_ELEMENTS });
  await assert.rejects(
    () => harness.host.execute(clickRequest('el-0099')),
    (error: unknown) => errorCode(error) === 'element_not_observed',
  );
  assert.equal(harness.snapshotCount(), 1);
  assert.equal(harness.binding.ops.length, 0);
  assert.equal(harness.authority.consumeCalls, 0);
});

test('credential elements refuse every direct action on the masked marker alone', async () => {
  const harness = harnessFactory({ elements: DEFAULT_ELEMENTS });
  await assert.rejects(
    () =>
      harness.host.execute({
        action: 'type',
        browserSessionRef: 'run/session-1',
        originRef: ORIGIN,
        elementRef: 'el-0004',
        text: 'hunter2',
      }),
    (error: unknown) => errorCode(error) === 'credential_element_forbidden',
  );
  await assert.rejects(
    () => harness.host.execute(clickRequest('el-0004')),
    (error: unknown) => errorCode(error) === 'credential_element_forbidden',
  );
  await assert.rejects(
    () =>
      harness.host.execute({
        action: 'focus',
        browserSessionRef: 'run/session-1',
        originRef: ORIGIN,
        elementRef: 'el-0004',
      }),
    (error: unknown) => errorCode(error) === 'credential_element_forbidden',
  );
  assert.equal(harness.binding.ops.length, 0);
  assert.equal(harness.authority.consumeCalls, 0);
});

test('click policy: effect class first — step-up targets refuse without consuming', async () => {
  const harness = harnessFactory({ elements: DEFAULT_ELEMENTS });
  // Provable non-committing roles dispatch — each through a PHASE B consume.
  const receipt = await harness.host.execute(clickRequest('el-0001'));
  assert.equal(receipt.outcome, 'dispatched');
  assert.deepEqual(harness.binding.ops[0], [{ kind: 'click', x: 50, y: 20 }]);
  await harness.host.execute(clickRequest('el-0007'));
  assert.deepEqual(harness.binding.ops[1], [{ kind: 'click', x: 80, y: 212 }]);
  assert.equal(harness.authority.consumeCalls, 2);

  // Everything the projection cannot prove steps up — the target check
  // refuses BEFORE PHASE B, so no slot is consumed and nothing dispatches.
  for (const [elementRef, role] of [
    ['el-0002', 'button'],
    ['el-0006', 'link'],
    ['el-0008', 'group'],
  ] as const) {
    await assert.rejects(
      () => harness.host.execute(clickRequest(elementRef)),
      (error: unknown) => {
        assert.equal(errorCode(error), 'step_up_required');
        assert.ok((error as Error).message.includes(role));
        return true;
      },
      `click on ${role} must step up`,
    );
  }
  assert.equal(harness.authority.consumeCalls, 2);
  assert.equal(harness.binding.ops.length, 2);
});

test('focus policy is separate: focusable non-credential elements focus without role limits', async () => {
  const harness = harnessFactory({ elements: DEFAULT_ELEMENTS });
  // A textbox (never click-allowed) focuses fine through the focus gate.
  const receipt = await harness.host.execute({
    action: 'focus',
    browserSessionRef: 'run/session-1',
    originRef: ORIGIN,
    elementRef: 'el-0003',
  });
  assert.equal(receipt.action, 'focus');
  // Press ON the element, release BELOW it — no click activation.
  assert.deepEqual(harness.binding.ops[0], [
    { kind: 'focus', x: 50, y: 20, releaseX: 50, releaseY: 94 },
  ]);
  assert.equal(harness.authority.consumeCalls, 1);
  // A non-focusable element refuses through the focus gate — without consuming.
  await assert.rejects(
    () =>
      harness.host.execute({
        action: 'focus',
        browserSessionRef: 'run/session-1',
        originRef: ORIGIN,
        elementRef: 'el-0008',
      }),
    (error: unknown) => errorCode(error) === 'element_not_focusable',
  );
  assert.equal(harness.binding.ops.length, 1);
  assert.equal(harness.authority.consumeCalls, 1);
});

test('type dispatches a bounded click-then-insertText pair at the observed center', async () => {
  const harness = harnessFactory({ elements: DEFAULT_ELEMENTS });
  const receipt = await harness.host.execute({
    action: 'type',
    browserSessionRef: 'run/session-1',
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
        browserSessionRef: 'run/session-1',
        originRef: ORIGIN,
        elementRef: 'el-0001',
        text: 'hi',
      }),
    (error: unknown) => errorCode(error) === 'contract_violation',
  );
});

test('select uses the deterministic absolute index path', async () => {
  const harness = harnessFactory({ elements: DEFAULT_ELEMENTS });
  await harness.host.execute({
    action: 'select',
    browserSessionRef: 'run/session-1',
    originRef: ORIGIN,
    elementRef: 'el-0005',
    optionIndex: 2,
  });
  // optionIndex=2 must be exactly: click, Home, 2×ArrowDown, Enter —
  // independent of whatever was already selected.
  assert.deepEqual(harness.binding.ops[0], [
    { kind: 'click', x: 100, y: 115 },
    { kind: 'key', key: 'Home' },
    { kind: 'key', key: 'ArrowDown' },
    { kind: 'key', key: 'ArrowDown' },
    { kind: 'key', key: 'Enter' },
  ]);

  // optionIndex=0 is Home+Enter with zero ArrowDowns.
  await harness.host.execute({
    action: 'select',
    browserSessionRef: 'run/session-1',
    originRef: ORIGIN,
    elementRef: 'el-0005',
    optionIndex: 0,
  });
  assert.deepEqual(harness.binding.ops[1], [
    { kind: 'click', x: 100, y: 115 },
    { kind: 'key', key: 'Home' },
    { kind: 'key', key: 'Enter' },
  ]);

  // The same index always produces the same absolute key path (already-selected
  // middle options change nothing).
  const before = JSON.stringify(harness.binding.ops[0]);
  await harness.host.execute({
    action: 'select',
    browserSessionRef: 'run/session-1',
    originRef: ORIGIN,
    elementRef: 'el-0005',
    optionIndex: 2,
  });
  assert.equal(JSON.stringify(harness.binding.ops[2]), before);

  // Max bounded index stays bounded.
  await harness.host.execute({
    action: 'select',
    browserSessionRef: 'run/session-1',
    originRef: ORIGIN,
    elementRef: 'el-0005',
    optionIndex: 1023,
  });
  assert.equal(harness.binding.ops[3]?.length, 1 + 1 + 1023 + 1);
  assert.equal(harness.authority.consumeCalls, 4);

  const scrollReceipt = await harness.host.execute({
    action: 'scroll',
    browserSessionRef: 'run/session-1',
    originRef: ORIGIN,
    dx: 0,
    dy: -240,
  });
  assert.equal(scrollReceipt.elementRef, null);
  assert.deepEqual(harness.binding.ops[4], [{ kind: 'wheel', x: 0, y: 0, dx: 0, dy: -240 }]);
  assert.equal(harness.authority.consumeCalls, 5);
});

test('the canonical store owns the action budget: N succeeds, N+1 refuses without dispatch', async () => {
  let clock = new Date('2026-10-08T09:00:00.000Z');
  const harness = harnessFactory({
    elements: DEFAULT_ELEMENTS,
    lease: validLease({ allowedActionClasses: ['click'], maxActions: 2 }),
    now: () => clock,
  });
  await harness.host.execute(clickRequest('el-0001'));
  await harness.host.execute(clickRequest('el-0007'));
  assert.equal(harness.authority.consumed, 2);
  // The N+1th action: the durable consume refuses; INPUT_COMMAND_COUNT=0.
  await assert.rejects(
    () => harness.host.execute(clickRequest('el-0001')),
    (error: unknown) => errorCode(error) === 'action_budget_exhausted',
  );
  assert.equal(harness.binding.ops.length, 2);
  assert.equal(harness.authority.consumed, 2);
  // No retry after the refusal: the refusal stands.
  await assert.rejects(
    () => harness.host.execute(clickRequest('el-0001')),
    (error: unknown) => errorCode(error) === 'action_budget_exhausted',
  );
  assert.equal(harness.binding.ops.length, 2);
});

test('the canonical store owns the idle window: a >120s gap refuses, inside it still admits', async () => {
  let clock = new Date('2026-10-08T09:00:00.000Z');
  const harness = harnessFactory({
    elements: DEFAULT_ELEMENTS,
    lease: validLease({ allowedActionClasses: ['click'], maxActions: 5 }),
    now: () => clock,
  });
  await harness.host.execute(clickRequest('el-0001'));
  clock = new Date(clock.getTime() + 121 * 1000);
  await assert.rejects(
    () => harness.host.execute(clickRequest('el-0001')),
    (error: unknown) => errorCode(error) === 'lease_idle_exceeded',
  );
  assert.equal(harness.binding.ops.length, 1);

  const within = harnessFactory({
    elements: DEFAULT_ELEMENTS,
    lease: validLease({ allowedActionClasses: ['click'], maxActions: 5 }),
    now: () => clock,
  });
  // The new authority has no last-consume fact, so the idle gate does not apply.
  await within.host.execute(clickRequest('el-0001'));
  assert.equal(within.binding.ops.length, 1);
});

test('a PHASE B cross-origin consume refusal passes through and dispatches nothing', async () => {
  const harness = harnessFactory({
    elements: DEFAULT_ELEMENTS,
    consumeRefusalCode: 'origin_scope_exceeded',
  });
  await assert.rejects(
    () => harness.host.execute(clickRequest('el-0001')),
    (error: unknown) => errorCode(error) === 'origin_scope_exceeded',
  );
  assert.equal(harness.binding.ops.length, 0);
  assert.equal(harness.authority.consumed, 0);
});

test('a dispatch failure after the durable consume keeps the slot consumed, no retry', async () => {
  const source: BrowserObservationSourcePort = {
    configured: true,
    snapshot: async () => ({ origin: ORIGIN, elements: DEFAULT_ELEMENTS }),
    close: async () => undefined,
  };
  const ops: ActionDispatchOp[][] = [];
  let dispatchFails = true;
  const binding: BrowserActionDispatchPort = {
    configured: true,
    dispatch: async (batch) => {
      if (dispatchFails) {
        dispatchFails = false;
        throw new Error('the input channel dropped the batch');
      }
      ops.push([...batch]);
    },
    close: async () => undefined,
  };
  const state = { consumed: 0 };
  const authority: BrowserActionLeaseAuthority = {
    configured: true,
    resolve: async () => validLease(),
    consume: async () => {
      state.consumed += 1;
      return state.consumed;
    },
  };
  const host = new BrowserActionHost({
    observation: new BrowserObservationHost({ source }),
    binding,
    leaseAuthority: authority,
    now: () => new Date('2026-10-08T09:00:00.000Z'),
  });
  // First action: the PHASE B consume succeeds (the slot is written), then the
  // dispatch fails. REFUND=NO, DECREMENT=NO — the slot stays consumed.
  await assert.rejects(
    () => host.execute(clickRequest('el-0001')),
    (error: unknown) => errorCode(error) === 'contract_violation',
  );
  assert.equal(state.consumed, 1);
  // No auto-retry of the failed batch: the next action is a new admission.
  const receipt = await host.execute(clickRequest('el-0001'));
  assert.equal(receipt.outcome, 'dispatched');
  assert.equal(ops.length, 1);
  assert.equal(state.consumed, 2);
});

test('action ids are deterministic, content-free and sequence-scoped', async () => {
  const first = harnessFactory({
    elements: DEFAULT_ELEMENTS,
    now: () => new Date('2026-10-08T09:00:00.000Z'),
  });
  const receipt = await first.host.execute(clickRequest('el-0001'));
  const second = harnessFactory({
    elements: DEFAULT_ELEMENTS,
    now: () => new Date('2026-10-08T09:00:00.000Z'),
  });
  const replayed = await second.host.execute(clickRequest('el-0001'));
  assert.match(receipt.actionId, /^act_[0-9a-f]{24}$/);
  assert.equal(receipt.actionId, replayed.actionId);
});

test('no renderer channel, no second authority, no script evaluation exists', () => {
  const hostModule = stripComments(readSource('browser', 'browser-action-host.ts'));
  const composition = stripComments(readSource('browser', 'browser-action-composition.ts'));
  const binding = stripComments(readSource('browser', 'browser-action-electron-binding.ts'));
  const contract = stripComments(readSource('browser', 'browser-action-contract.ts'));
  assert.equal(STEP_UP_EXECUTION_IMPLEMENTED, false);
  assert.equal(CANONICAL_LEASE_ADMISSION_WIRED, false);
  assert.equal(NEW_APPROVAL_STORE, false);
  assert.equal(SECOND_BROWSER_AUTHORITY, false);
  assert.equal(GENERIC_IPC_SURFACE, false);
  // No local lease bookkeeping survives: the canonical store owns budget/idle.
  assert.equal(LOCAL_LEASE_BOOKKEEPING_IS_AUTHORITY, false);
  assert.ok(!hostModule.includes('leaseFastPath'), 'the local fast-path mirror is gone');
  // The two phases are explicit in the host.
  assert.ok(hostModule.includes('leaseAuthority.resolve'));
  assert.ok(hostModule.includes('leaseAuthority.consume'));
  for (const code of [hostModule, composition]) {
    assert.ok(!code.includes('ipcMain'));
    assert.ok(!code.includes('ipcRenderer'));
    assert.ok(!code.includes('execute' + 'JavaScript'));
  }
  // The lease carries the full correlation set (code-level, not comments).
  for (const correlation of [
    'requestFingerprint',
    'runRef',
    'workspaceRef',
    'ownerRef',
    'approvalRef',
    'evidenceRef',
  ]) {
    assert.ok(contract.includes(correlation), `lease correlation ${correlation} missing`);
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
