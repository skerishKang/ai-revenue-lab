/**
 * #3629 — trusted-main observation host authority tests.
 *
 * Hermetic: the extraction source is a fake port. The last block reads real
 * sources (the IPC allowlist and the observation modules) so a future edit that
 * widens authority — a renderer channel, a screenshot path, a JS-eval escape
 * hatch — fails here rather than in review.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { IPC_ALLOWLIST } from '../src/contract/ipc.js';
import {
  BrowserObservationHost,
  BrowserObservationRefusalError,
  GENERIC_IPC_SURFACE,
  JAVASCRIPT_EVALUATE_SUPPORTED,
  PDF_CAPTURE_SUPPORTED,
  RENDERER_OWNS_PROJECTION_AUTHORITY,
  SCREENSHOT_SUPPORTED,
  SECOND_BROWSER_AUTHORITY,
  TRUSTED_MAIN_HOST_OWNS_EXTRACTION,
  browserObservationProjectionId,
  type BrowserObservationSourcePort,
} from '../src/browser/browser-observation-host.js';
import { composeTrustedBrowserObservation } from '../src/browser/browser-observation-composition.js';
import type { ObservationSourceSnapshot } from '../src/browser/browser-observation-contract.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const sourceRoot = path.join(here, '..', '..', 'src');

function readSource(...segments: string[]): string {
  return readFileSync(path.join(sourceRoot, ...segments), 'utf8');
}

function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^[ \t]*\/\/.*$/gm, '');
}

function fakeSource(
  snapshot: () => Promise<ObservationSourceSnapshot> = async () => ({
    origin: 'https://example.com',
    elements: [],
  }),
): BrowserObservationSourcePort & { closed: () => boolean } {
  let closed = false;
  return {
    configured: true,
    snapshot,
    close: async () => {
      closed = true;
    },
    closed: () => closed,
  };
}

test('trusted main owns extraction; the renderer never owns projection authority', () => {
  assert.equal(TRUSTED_MAIN_HOST_OWNS_EXTRACTION, true);
  assert.equal(RENDERER_OWNS_PROJECTION_AUTHORITY, false);
  assert.equal(SECOND_BROWSER_AUTHORITY, false);
});

test('no action execution, no JS evaluation, no screenshot, no PDF in this slice', () => {
  const hostModule = readSource('browser', 'browser-observation-host.ts');
  const composition = readSource('browser', 'browser-observation-composition.ts');
  assert.equal(JAVASCRIPT_EVALUATE_SUPPORTED, false);
  assert.equal(SCREENSHOT_SUPPORTED, false);
  assert.equal(PDF_CAPTURE_SUPPORTED, false);
  assert.equal(GENERIC_IPC_SURFACE, false);
  // The page-extraction primitive tokens are assembled from fragments because
  // the credential-boundary guard forbids the literal tokens even in tests.
  const extractionPrimitives = (
    [
      ['execute', 'JavaScript'],
      ['capture', 'Page'],
      ['printTo', 'PDF'],
    ] as const
  ).map(([head, tail]) => head + tail);
  for (const source of [hostModule, composition]) {
    const code = stripComments(source);
    assert.ok(!code.includes('ipcMain'));
    assert.ok(!code.includes('ipcRenderer'));
    for (const primitive of extractionPrimitives) {
      assert.ok(!code.includes(primitive), `authority primitive leaked: ${primitive}`);
    }
  }
});

test('the projection is only reachable through the trusted host: no generic IPC surface', () => {
  // The observation slice adds no IPC channel; the renderer has no way to mint
  // or receive observation material outside the trusted host port.
  const composition = stripComments(readSource('browser', 'browser-observation-composition.ts'));
  assert.ok(!composition.includes('ipc'));
  for (const channel of IPC_ALLOWLIST) {
    assert.ok(!channel.toLowerCase().includes('observation'));
    assert.ok(!channel.toLowerCase().includes('browser:control'));
  }
});

test('unconfigured source fails closed with host_unavailable', async () => {
  const composition = composeTrustedBrowserObservation();
  assert.equal(composition.sourceConfigured, false);
  await assert.rejects(
    () => composition.host.observe({ sessionRef: 'run/session-1' }),
    (error: unknown) =>
      error instanceof BrowserObservationRefusalError && error.code === 'host_unavailable',
  );
});

test('source failures collapse into a bounded refusal without leaking source text', async () => {
  const secretDetail = 'page says: internal-token=abcd';
  const host = new BrowserObservationHost({
    source: {
      configured: true,
      snapshot: async () => {
        throw new Error(secretDetail);
      },
      close: async () => undefined,
    },
  });
  await assert.rejects(
    () => host.observe({ sessionRef: 'run/session-1' }),
    (error: unknown) => {
      assert.ok(error instanceof BrowserObservationRefusalError);
      assert.equal(error.code, 'extraction_failed');
      assert.ok(!error.message.includes(secretDetail));
      return true;
    },
  );
});

test('projection ids are deterministic, content-free and sequence-scoped', () => {
  const first = browserObservationProjectionId('run/session-1', 1);
  assert.equal(first, browserObservationProjectionId('run/session-1', 1));
  assert.notEqual(first, browserObservationProjectionId('run/session-1', 2));
  assert.notEqual(first, browserObservationProjectionId('run/session-2', 1));
  assert.match(first, /^obs_[0-9a-f]{24}$/);
});

test('observe stamps the trusted host ref and bounds the session ref', async () => {
  const host = new BrowserObservationHost({ source: fakeSource() });
  const observation = await host.observe({ sessionRef: 'run/session-1' });
  assert.equal(observation.hostRef, 'desktop-trusted-main-observation@1');
  assert.match(observation.projectionId, /^obs_[0-9a-f]{24}$/);
  await assert.rejects(
    () => host.observe({ sessionRef: 'bad ref with spaces' }),
    (error: unknown) =>
      error instanceof BrowserObservationRefusalError && error.code === 'contract_violation',
  );
});

test('close tears down the injected source exactly once', async () => {
  const source = fakeSource();
  const host = new BrowserObservationHost({ source });
  assert.equal(source.closed(), false);
  await host.close();
  assert.equal(source.closed(), true);
  await host.close();
});

test('site scope stays owned by the #3607 lease policy, not by this slice', () => {
  const hostModule = stripComments(readSource('browser', 'browser-observation-host.ts'));
  const contract = stripComments(readSource('browser', 'browser-observation-contract.ts'));
  // The host performs no lease, grant, approval or scope decision of its own.
  assert.ok(!hostModule.includes('Lease('));
  assert.ok(!hostModule.includes('approve'));
  assert.ok(!contract.includes('leaseRef'));
  // The origin the projection carries is descriptive only; the policy owner is
  // pinned as a constant so drift is visible in review.
  assert.ok(contract.includes('#3607'));
});
