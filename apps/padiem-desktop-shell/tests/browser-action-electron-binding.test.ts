/**
 * #3647 — trusted input-synthesis binding tests.
 *
 * Hermetic: the Electron `webContents` handle is a structural fake with a
 * scripted CDP debugger. The whole asserted surface is the Input.* command
 * allowlist — no Runtime, no DOM, no capture, no cookies/storage command is
 * ever sent.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  createElectronBrowserActionBinding,
  type ActionWebContentsLike,
} from '../src/browser/browser-action-electron-binding.js';
import type { ActionDispatchOp } from '../src/browser/browser-action-host.js';

interface FakeDebuggerResult {
  readonly webContents: ActionWebContentsLike;
  readonly commands: Array<{ method: string; params: Record<string, unknown> }>;
  readonly isAttached: () => boolean;
  readonly detachCount: () => number;
}

function fakeWebContents(options: { readonly attachThrows?: boolean } = {}): FakeDebuggerResult {
  const commands: Array<{ method: string; params: Record<string, unknown> }> = [];
  let attached = false;
  let detachCount = 0;
  const webContents: ActionWebContentsLike = {
    debugger: {
      attach: () => {
        if (options.attachThrows) throw new Error('another debugger is already attached');
        attached = true;
      },
      detach: () => {
        detachCount += 1;
        attached = false;
      },
      sendCommand: async (method: string, params?: unknown) => {
        commands.push({ method, params: (params ?? {}) as Record<string, unknown> });
        if (!attached) throw new Error('debugger is not attached');
        return {};
      },
    },
  };
  return { webContents, commands, isAttached: () => attached, detachCount: () => detachCount };
}

test('click dispatches exactly one bounded press/release pair', async () => {
  const fake = fakeWebContents();
  const binding = createElectronBrowserActionBinding(fake.webContents);
  await binding.dispatch([{ kind: 'click', x: 50, y: 20 }]);
  assert.deepEqual(fake.commands, [
    { method: 'Input.dispatchMouseEvent', params: { type: 'mouseMoved', x: 50, y: 20, button: 'none', buttons: 0 } },
    { method: 'Input.dispatchMouseEvent', params: { type: 'mousePressed', x: 50, y: 20, button: 'left', buttons: 1, clickCount: 1 } },
    { method: 'Input.dispatchMouseEvent', params: { type: 'mouseReleased', x: 50, y: 20, button: 'left', buttons: 0, clickCount: 1 } },
  ]);
  assert.equal(fake.isAttached(), false);
  assert.equal(fake.detachCount(), 1);
});

test('wheel, focus, text and key ops map to their allowed command sequences', async () => {
  const fake = fakeWebContents();
  const binding = createElectronBrowserActionBinding(fake.webContents);
  await binding.dispatch([
    { kind: 'wheel', x: 0, y: 0, dx: 0, dy: -240 },
    { kind: 'focus', x: 50, y: 20, releaseX: 50, releaseY: 94 },
    { kind: 'insertText', text: '안녕' },
    { kind: 'key', key: 'Home' },
    { kind: 'key', key: 'ArrowDown' },
    { kind: 'key', key: 'Enter' },
  ]);
  // Focus uses real Chromium pointer state, but release outside target
  // prevents a completed click. Each key op is rawKeyDown + keyUp.
  assert.deepEqual(
    fake.commands.map((entry) => entry.method),
    [
      'Input.dispatchMouseEvent', // wheel
      'Input.dispatchMouseEvent', // move
      'Input.dispatchMouseEvent', // press
      'Input.dispatchMouseEvent', // release outside target
      'Input.insertText',
      'Input.dispatchKeyEvent',
      'Input.dispatchKeyEvent',
      'Input.dispatchKeyEvent',
      'Input.dispatchKeyEvent',
      'Input.dispatchKeyEvent',
      'Input.dispatchKeyEvent',
    ],
  );
  assert.deepEqual(fake.commands[0]?.params, { type: 'mouseWheel', x: 0, y: 0, deltaX: 0, deltaY: -240 });
  assert.deepEqual(fake.commands[1]?.params, { type: 'mouseMoved', x: 50, y: 20, button: 'none', buttons: 0 });
  assert.deepEqual(fake.commands[2]?.params, { type: 'mousePressed', x: 50, y: 20, button: 'left', buttons: 1, clickCount: 1 });
  assert.deepEqual(fake.commands[3]?.params, { type: 'mouseReleased', x: 50, y: 94, button: 'left', buttons: 0, clickCount: 1 });
  assert.deepEqual(fake.commands[4]?.params, { text: '안녕' });
  assert.deepEqual(fake.commands[5]?.params, { type: 'rawKeyDown', key: 'Home', windowsVirtualKeyCode: 36 });
  assert.deepEqual(fake.commands[6]?.params, { type: 'keyUp', key: 'Home', windowsVirtualKeyCode: 36 });
  assert.deepEqual(fake.commands[7]?.params, { type: 'rawKeyDown', key: 'ArrowDown', windowsVirtualKeyCode: 40 });
  assert.deepEqual(fake.commands[8]?.params, { type: 'keyUp', key: 'ArrowDown', windowsVirtualKeyCode: 40 });
  assert.deepEqual(fake.commands[9]?.params, { type: 'rawKeyDown', key: 'Enter', windowsVirtualKeyCode: 13 });
  assert.deepEqual(fake.commands[10]?.params, { type: 'keyUp', key: 'Enter', windowsVirtualKeyCode: 13 });
});

test('a batch is atomic: the debugger is attached and detached exactly once', async () => {
  const fake = fakeWebContents();
  const binding = createElectronBrowserActionBinding(fake.webContents);
  const batch: ActionDispatchOp[] = [
    { kind: 'click', x: 1, y: 2 },
    { kind: 'key', key: 'Enter' },
  ];
  await binding.dispatch(batch);
  await binding.dispatch(batch);
  assert.equal(fake.detachCount(), 2);
});

test('commands outside the allowlist refuse and still detach', async () => {
  const fake = fakeWebContents();
  const binding = createElectronBrowserActionBinding(fake.webContents);
  const rogue = { kind: 'evaluate', expression: '1+1' } as unknown as ActionDispatchOp;
  await assert.rejects(() => binding.dispatch([rogue]));
  assert.equal(fake.isAttached(), false);
  assert.equal(fake.detachCount(), 1);
  assert.deepEqual(
    fake.commands.filter((entry) => !entry.method.startsWith('Input.')).map((entry) => entry.method),
    [],
  );
});

test('attach failures, concurrent batches and closed bindings fail closed', async () => {
  const attachThrows = createElectronBrowserActionBinding(
    fakeWebContents({ attachThrows: true }).webContents,
  );
  await assert.rejects(() => attachThrows.dispatch([{ kind: 'click', x: 1, y: 2 }]));

  const fake = fakeWebContents();
  const binding = createElectronBrowserActionBinding(fake.webContents);
  await assert.rejects(
    () =>
      Promise.all([
        binding.dispatch([{ kind: 'click', x: 1, y: 2 }]),
        binding.dispatch([{ kind: 'click', x: 3, y: 4 }]),
      ]),
    (error: unknown) => error instanceof Error && /already in progress/.test(error.message),
  );
  await binding.close();
  await assert.rejects(() => binding.dispatch([{ kind: 'click', x: 1, y: 2 }]));
});
