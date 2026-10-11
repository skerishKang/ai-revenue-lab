/**
 * #3775 — trusted command ingress contract. This suite never uses a live
 * Broker/P01/model/Electron and MUST NOT be mistaken for product activation.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import {
  createTrustedBrowserControlCommandIngress,
  validateCanonicalApprovedBrowserControlCommand,
  CANONICAL_BROWSER_CONTROL_COMMAND_SOURCE_WIRED,
  type CanonicalApprovedBrowserControlCommand,
  type CanonicalBrowserControlCommandPort,
} from '../src/browser/browser-control-canonical-command-ingress.js';
import type { BrowserControlLeaseContext } from '../src/conversation/resident-browser-control-lease.js';
import type { BoundTrustedBrowserControl } from '../src/browser/browser-action-trusted-main.js';
import type { BoundedActionReceipt, BoundedBrowserActionRequest } from '../src/browser/browser-action-contract.js';

const ctx: BrowserControlLeaseContext = Object.freeze({
  requestFingerprint: 'a'.repeat(64),
  browserSessionRef: 'run/session-1',
  deviceRef: 'device_3669',
  runRef: 'run_3669', workspaceRef: 'workspace_3669', ownerRef: 'owner_3669',
  originScope: 'https://example.com',
  allowedActionClasses: ['scroll'],
  ttlSeconds: 300,
  maxActions: 4,
});
const action: BoundedBrowserActionRequest = Object.freeze({
  action: 'scroll', browserSessionRef: ctx.browserSessionRef,
  originRef: ctx.originScope, dx: 0, dy: 20,
});
const approved: CanonicalApprovedBrowserControlCommand = Object.freeze({
  commandRef: 'command_3775',
  hostLeaseRef: 'host_lease_3669',
  capability: 'browser.control',
  context: ctx, action,
});

function fake(override: unknown = approved) {
  const counts = { takes: 0, binds: 0, executes: 0, closes: 0 };
  const receipt = Object.freeze({ marker: 'trusted-result' }) as unknown as BoundedActionReceipt;
  const bound: BoundTrustedBrowserControl = {
    configured: true,
    execute: async () => { counts.executes += 1; return receipt; },
    close: async () => { counts.closes += 1; },
  };
  const owner = {
    bindApprovedView: (hostRef: string, c: BrowserControlLeaseContext): BoundTrustedBrowserControl => {
      counts.binds += 1;
      assert.equal(hostRef, 'host_lease_3669');
      assert.equal(c, ctx);
      return bound;
    },
  };
  const port: CanonicalBrowserControlCommandPort = {
    configured: true,
    takeApprovedCommand: async () => { counts.takes += 1; return override; },
  };
  return { counts, receipt, owner, port };
}

test('unconfigured real product entry refuses without requesting a lease or Input.*', async () => {
  const f = fake();
  const ingress = createTrustedBrowserControlCommandIngress({ browserControl: f.owner });
  assert.equal(CANONICAL_BROWSER_CONTROL_COMMAND_SOURCE_WIRED, false);
  assert.equal(ingress.configured, false);
  await assert.rejects(() => ingress.executeApprovedCommand('command_3775'));
  assert.deepEqual(f.counts, {takes: 0, binds: 0, executes: 0, closes: 0});
});

test('trusted canonical take alone supplies action + lease; one execution and one closure', async () => {
  const f = fake();
  const ingress = createTrustedBrowserControlCommandIngress({
    browserControl: f.owner, approvedCommands: f.port,
  });
  assert.equal(ingress.configured, true);
  assert.equal(await ingress.executeApprovedCommand('command_3775'), f.receipt);
  assert.deepEqual(f.counts, {takes: 1, binds: 1, executes: 1, closes: 1});
  await assert.rejects(() => ingress.executeApprovedCommand('command_3775'));
  assert.deepEqual(f.counts, {takes: 1, binds: 1, executes: 1, closes: 1});
});

test('hostile or wrong canonical command envelope never binds a view', async () => {
  const bad = [
    {...approved, capability: 'browser.open'},
    {...approved, commandRef: 'other_command'},
    {...approved, hostLeaseRef: ''},
    {...approved, password: 'untrusted extra field'},
    {...approved, context: {...ctx, browserSessionRef: 'other_session'}},
    {...approved, context: {...ctx, originScope: 'https://other.example.com'}},
    {...approved, context: {...ctx, allowedActionClasses: ['focus']}},
    {...approved, context: {...ctx, rawP01Approval: 'must-not-transport'}},
    {...approved, action: {...action, action: 'submit'}},
    {...approved, action: {...action, originRef: 'https://other.example.com'}},
    {...approved, action: {...action, browserSessionRef: 'other_session'}},
  ];
  for (const value of bad) {
    const f = fake(value);
    const ingress = createTrustedBrowserControlCommandIngress({
      browserControl: f.owner, approvedCommands: f.port,
    });
    await assert.rejects(() => ingress.executeApprovedCommand('command_3775'),
      (e: unknown) => (e as {code:string}).code === 'host_unavailable');
    assert.deepEqual(f.counts, {takes: 1, binds: 0, executes: 0, closes: 0});
  }
});

test('malformed commandRef and raw broker rejection never touch browser control', async () => {
  const f = fake();
  const ingress = createTrustedBrowserControlCommandIngress({
    browserControl: f.owner, approvedCommands: f.port,
  });
  await assert.rejects(() => ingress.executeApprovedCommand('dangerous command; drop'),
    (e: unknown) => (e as {code:string}).code === 'host_unavailable');
  assert.equal(f.counts.takes, 0);
  const errPort: CanonicalBrowserControlCommandPort = {
    configured: true, takeApprovedCommand: async () => {
      throw new Error('raw P01 approval message: secret-must-not-escape');
    },
  };
  const rejection = createTrustedBrowserControlCommandIngress({
    browserControl: f.owner, approvedCommands: errPort,
  });
  await assert.rejects(() => rejection.executeApprovedCommand('command_3775'), (e: unknown) => {
    assert.equal((e as {code:string}).code, 'host_unavailable');
    assert.ok(!(e as Error).message.includes('secret-must-not-escape'));
    return true;
  });
  assert.equal(f.counts.binds, 0);
});

test('failed dispatch still closes one-shot handle with no auto retry', async () => {
  const counts = {takes: 0, executes: 0, closes: 0};
  const ingress = createTrustedBrowserControlCommandIngress({
    approvedCommands: {
      configured: true, takeApprovedCommand: async () => {counts.takes++; return approved;},
    },
    browserControl: {
      bindApprovedView: () => ({
        configured: true,
        execute: async () => {counts.executes++; throw new Error('Input dispatch refused');},
        close: async () => {counts.closes++;},
      }),
    },
  });
  await assert.rejects(() => ingress.executeApprovedCommand('command_3775'));
  await assert.rejects(() => ingress.executeApprovedCommand('command_3775'));
  assert.deepEqual(counts, {takes: 1, executes: 1, closes: 1});
});

test('main composition leaves canonical command ingress unconfigured; no IPC expansion', () => {
  const sourceRoot = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'src');
  const main = readFileSync(path.join(sourceRoot, 'main', 'main.ts'), 'utf8');
  const source = readFileSync(path.join(sourceRoot, 'browser', 'browser-control-canonical-command-ingress.ts'), 'utf8');
  const resident = readFileSync(
    path.join(sourceRoot, '..', '..', 'korean-ai-code-agent', 'src', 'kagent', 'local_agent_resident_process.py'),
    'utf8',
  );
  assert.match(main, /createTrustedBrowserControlCommandIngress\(\{\s*browserControl,\s*\}\)/);
  assert.doesNotMatch(main, /approvedCommands:\s*\{/);
  assert.doesNotMatch(source, /ipcMain|ipcRenderer|contextBridge|from ['"]electron['"]/);
  assert.match(resident, /ACCEPTANCE_COMMAND_ID\s*=\s*["']command\.3140\.p01\.1["']/);
});
