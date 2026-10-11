/**
 * #3629 — trusted accessibility-tree extraction source tests.
 *
 * Hermetic: the Electron `webContents` handle is a structural fake with a
 * scripted CDP debugger. The password node's `value` property is instrumented
 * with a tripwire getter: any read of the typed secret fails the test.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  createElectronBrowserObservationSource,
  boundedOriginFromUrl,
  type ObservationWebContentsLike,
} from '../src/browser/browser-observation-electron-source.js';
import { projectBoundedPageObservation } from '../src/browser/browser-observation-contract.js';
import { BrowserObservationHost } from '../src/browser/browser-observation-host.js';

interface FakeDebuggerResult {
  readonly webContents: ObservationWebContentsLike;
  readonly sentMethods: string[];
  readonly detachCount: () => number;
  readonly isAttached: () => boolean;
  /** Instrumented password AX node; `valueReads()` is 0 unless `value` was read. */
  readonly passwordNode: Record<string, unknown> & { valueReads: () => number };
  readonly tree: unknown;
}

function passwordNode(): Record<string, unknown> & { valueReads: () => number } {
  const node: Record<string, unknown> = {
    nodeId: '42',
    role: { type: 'role', value: 'textbox' },
    name: { type: 'computedString', value: 'password' },
    bounds: { x: 10, y: 20, width: 200, height: 24 },
    checked: 'false',
    properties: [
      { name: 'focusable', value: { type: 'boolean', value: true } },
      { name: 'textInputType', value: { type: 'string', value: 'password' } },
      { name: 'required', value: { type: 'boolean', value: true } },
      { name: 'arbitraryProp', value: { type: 'string', value: 'should-die-here' } },
    ],
    childIds: ['43'],
  };
  let valueReads = 0;
  Object.defineProperty(node, 'value', {
    enumerable: true,
    get: () => {
      valueReads += 1;
      throw new Error('node.value must never be read');
    },
  });
  return Object.assign(node, { valueReads: () => valueReads });
}

function fixtureTree(password: Record<string, unknown>): unknown {
  return {
    nodes: [
      {
        nodeId: '1',
        role: { type: 'role', value: 'genericContainer' },
        name: { type: 'computedString', value: '' },
        bounds: { x: 0, y: 0, width: 800, height: 600 },
        properties: [],
        childIds: ['2', '3', '4', '5', '6'],
      },
      {
        nodeId: '2',
        role: { type: 'role', value: 'button' },
        name: { type: 'computedString', value: '로그인' },
        bounds: { x: 10, y: 10, width: 80, height: 30 },
        properties: [{ name: 'focusable', value: { type: 'boolean', value: true } }],
      },
      password,
      {
        nodeId: '4',
        role: { type: 'role', value: 'textarea' },
        name: { type: 'computedString', value: '메모' },
        bounds: { x: 10, y: 60, width: 300, height: 120 },
        properties: [{ name: 'multiline', value: { type: 'boolean', value: true } }],
      },
      {
        nodeId: '5',
        role: { type: 'role', value: 'ignoredOverlay' },
        name: { type: 'computedString', value: 'noise' },
        ignored: true,
        bounds: { x: 0, y: 0, width: 1, height: 1 },
        properties: [],
      },
      {
        nodeId: '6',
        role: { type: 'role', value: 'link' },
        name: { type: 'computedString', value: '도움말' },
        bounds: { x: 400, y: 560, width: 60, height: 20 },
        properties: [],
      },
    ],
  };
}

function fakeWebContents(
  url: string,
  options: { readonly attachThrows?: boolean; readonly tree?: unknown } = {},
): FakeDebuggerResult {
  const password = passwordNode();
  const tree = options.tree ?? fixtureTree(password);
  const sentMethods: string[] = [];
  let attached = false;
  let detachCount = 0;
  const webContents: ObservationWebContentsLike = {
    getURL: () => url,
    debugger: {
      attach: () => {
        if (options.attachThrows) throw new Error('another debugger is already attached');
        attached = true;
      },
      detach: () => {
        detachCount += 1;
        attached = false;
      },
      sendCommand: async (method: string) => {
        sentMethods.push(method);
        if (!attached) throw new Error('debugger is not attached');
        return tree;
      },
    },
  };
  return {
    webContents,
    sentMethods,
    detachCount: () => detachCount,
    isAttached: () => attached,
    passwordNode: password,
    tree,
  };
}

test('extraction sends only Accessibility.getFullAXTree and always detaches', async () => {
  const fake = fakeWebContents('https://example.com/login?next=/secret');
  const source = createElectronBrowserObservationSource(fake.webContents);
  const snapshot = await source.snapshot();
  assert.deepEqual(fake.sentMethods, ['Accessibility.getFullAXTree']);
  assert.equal(fake.isAttached(), false);
  assert.equal(fake.detachCount(), 1);
  assert.equal(snapshot.origin, 'https://example.com');
  await source.close();
  await source.close();
});

test('the typed value of a password field is never read, and the field is masked', async () => {
  const fake = fakeWebContents('https://example.com/login');
  const source = createElectronBrowserObservationSource(fake.webContents);
  const snapshot = await source.snapshot();
  const passwordSource = snapshot.elements.find((element) => element.credentialField === true);
  assert.ok(passwordSource);
  assert.equal(passwordSource.name, '');
  assert.equal(fake.passwordNode.valueReads(), 0);

  // End to end: the projected credential control carries the masked marker only.
  const host = new BrowserObservationHost({ source });
  const observation = await host.observe({ sessionRef: 'run/session-1' });
  const projected = observation.elements.find((element) => element.credentialField);
  assert.ok(projected);
  assert.equal(projected.name, '[credential]');
  assert.equal(observation.credentialValueIncluded, false);
  await host.close();
});

test('raw DOM handles, unknown roles and arbitrary properties die at the mapping boundary', async () => {
  const fake = fakeWebContents('https://example.com/login');
  const source = createElectronBrowserObservationSource(fake.webContents);
  const snapshot = await source.snapshot();
  for (const element of snapshot.elements) {
    assert.deepEqual(Object.keys(element).sort(), [
      'bounds',
      'credentialField',
      'interactionFlags',
      'name',
      'role',
      'stateFlags',
    ]);
  }
  const observation = projectBoundedPageObservation({
    projectionId: 'obs_bbbbbbbbbbbbbbbbbbbbbbbb',
    source: snapshot,
  });
  for (const element of observation.elements) {
    assert.ok(!('nodeId' in element));
    assert.ok(!('childIds' in element));
    assert.ok(!('backendDOMNodeId' in element));
  }
  // The ignored node is dropped in mapping; the generic container role is
  // unclassifiable at the contract layer and counted as omitted.
  assert.equal(observation.elementCount, 4);
  assert.equal(observation.omittedElements, 1);
});

test('textarea maps to a bounded metadata element without its contents', async () => {
  const fake = fakeWebContents('https://example.com/editor');
  const source = createElectronBrowserObservationSource(fake.webContents);
  const snapshot = await source.snapshot();
  const textarea = snapshot.elements.find((element) => element.role === 'textarea');
  assert.ok(textarea);
  assert.equal(textarea.name, '메모');
  assert.deepEqual(textarea.stateFlags, ['multiline']);
  assert.deepEqual(textarea.interactionFlags, ['editable', 'typeable']);
});

test('attach failures and non-bounded origins fail closed', async () => {
  const failing = createElectronBrowserObservationSource(
    fakeWebContents('https://example.com', { attachThrows: true }).webContents,
  );
  await assert.rejects(() => failing.snapshot());

  const localFile = createElectronBrowserObservationSource(
    fakeWebContents('file:///C:/Users/secret.txt').webContents,
  );
  await assert.rejects(() => localFile.snapshot());

  const closedSource = createElectronBrowserObservationSource(
    fakeWebContents('https://example.com').webContents,
  );
  await closedSource.close();
  await assert.rejects(() => closedSource.snapshot());
});

test('origin reduction keeps scheme/host/port only and never path, query or credentials', () => {
  assert.equal(boundedOriginFromUrl('https://example.com/a/b?token=xyz'), 'https://example.com');
  assert.equal(boundedOriginFromUrl('http://example.com:8080/x'), 'http://example.com:8080');
  assert.equal(boundedOriginFromUrl('https://user:pass@example.com/'), null);
  assert.equal(boundedOriginFromUrl('file:///etc/passwd'), null);
  assert.equal(boundedOriginFromUrl('not a url'), null);
});
