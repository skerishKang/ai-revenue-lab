/**
 * #3669 / #3583 — genuine trusted-main port composition with a fake
 * ephemeral WebContents and the existing resident PHASE A/B wire contract.
 * No Electron runtime, live page, network, P01 mint, provider or renderer.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import {
  createTrustedMainBrowserActionOwner,
  type TrustedControlView,
} from '../src/browser/browser-action-trusted-main.js';
import {
  BROWSER_CONTROL_LEASE_EVENT,
  BROWSER_CONTROL_LEASE_RESOLVE_KIND,
  BROWSER_CONTROL_LEASE_CONSUME_KIND,
  BROWSER_CONTROL_LEASE_RESPONSE_CONTRACT_VERSION,
  type BrowserControlLeaseContext,
} from '../src/conversation/resident-browser-control-lease.js';
import type { BoundedBrowserActionRequest } from '../src/browser/browser-action-contract.js';

const context: BrowserControlLeaseContext = Object.freeze({
  requestFingerprint: 'a'.repeat(64),
  browserSessionRef: 'run/session-1',
  deviceRef: 'device_3669',
  runRef: 'run_3669',
  workspaceRef: 'workspace_3669',
  ownerRef: 'owner_3669',
  originScope: 'https://example.com',
  allowedActionClasses: ['scroll'],
  ttlSeconds: 300,
  maxActions: 4,
});
const scroll = {
  action: 'scroll', browserSessionRef: context.browserSessionRef,
  originRef: context.originScope, dx: 0, dy: 20,
} as BoundedBrowserActionRequest;

function fixture() {
  const sent: Record<string, unknown>[] = [];
  const commands: string[] = [];
  const answers: string[] = [];
  let url = 'https://example.com/document';
  let current: TrustedControlView | null = null;
  let accept = true;
  const webContents = {
    getURL: () => url,
    debugger: {
      attach: () => undefined,
      detach: () => undefined,
      sendCommand: async (method: string): Promise<unknown> => {
        commands.push(method);
        if (method === 'Accessibility.getFullAXTree') return { nodes: [] };
        return undefined;
      },
    },
  };
  current = {
    webContents, runRef: context.runRef,
    workspaceRef: context.workspaceRef, ownerRef: context.ownerRef,
  };
  const owner = createTrustedMainBrowserActionOwner({
    findActiveControlView: (ref) => ref === 'lease_3669' ? current : null,
    residentBoundary: {
      residentRunning: () => true,
      sendResidentLine: (line) => {
        const req = JSON.parse(line) as Record<string, unknown>;
        sent.push(req);
        const resolve = req.request === BROWSER_CONTROL_LEASE_RESOLVE_KIND;
        answers.push(JSON.stringify({
          event: BROWSER_CONTROL_LEASE_EVENT,
          contract_version: BROWSER_CONTROL_LEASE_RESPONSE_CONTRACT_VERSION,
          request: req.request,
          ok: accept,
          request_fingerprint: context.requestFingerprint,
          reason: accept ? null : 'p01_approval_invalid',
          ...(resolve ? {lease: accept ? {
            leaseId: 'lease/3669',
            requestFingerprint: context.requestFingerprint,
            browserSessionRef: context.browserSessionRef,
            runRef: context.runRef, workspaceRef: context.workspaceRef,
            ownerRef: context.ownerRef,
            allowedActionClasses: [...context.allowedActionClasses],
            originScope: context.originScope,
            maxActions: context.maxActions,
            issuedAtIso: new Date(Date.now() - 1000).toISOString(),
            expiresAtIso: new Date(Date.now() + 120_000).toISOString(),
            approvalRef: 'decision_3669',
            evidenceRef: 'evidence_3669',
          } : null} : {consumed_actions: 1}),
        }));
        return true;
      },
      takeResidentBrowserControlLeaseLine: () => answers.shift() ?? null,
    },
  });
  return {
    owner, commands, sent,
    setView: (view: TrustedControlView | null) => { current = view; },
    view: () => current!,
    setUrl: (value: string) => { url = value; },
    refuse: () => { accept = false; },
  };
}

test('trusted-main bridge binds a real view and sends both phases before Input.*', async () => {
  const f = fixture();
  const control = f.owner.bindApprovedView('lease_3669', context);
  const receipt = await control.execute(scroll);
  assert.equal(receipt.action, 'scroll');
  assert.deepEqual(f.sent.map(v => v.request), [
    BROWSER_CONTROL_LEASE_RESOLVE_KIND, BROWSER_CONTROL_LEASE_CONSUME_KIND,
  ]);
  assert.deepEqual(f.commands, [
    'Accessibility.getFullAXTree', 'Input.dispatchMouseEvent',
  ]);
  await control.close();
  await assert.rejects(() => control.execute(scroll), (e: unknown) => {
    assert.equal((e as {code:string}).code, 'host_unavailable');
    return true;
  });
});

test('no view, cross-owner binding or wrong origin cannot reach resident or Input.*', () => {
  const f = fixture();
  for (const [ref, ctx] of [
    ['missing', context],
    ['lease_3669', {...context, ownerRef: 'wrong_owner'}],
    ['lease_3669', {...context, workspaceRef: 'wrong_workspace'}],
    ['lease_3669', {...context, runRef: 'wrong_run'}],
  ] as const) {
    assert.throws(() => f.owner.bindApprovedView(ref, ctx),
      (e: unknown) => (e as {code:string}).code === 'host_unavailable');
  }
  f.setUrl('https://moved.example/');
  assert.throws(() => f.owner.bindApprovedView('lease_3669', context),
    (e: unknown) => (e as {code:string}).code === 'host_unavailable');
  assert.equal(f.sent.length, 0);
  assert.equal(f.commands.length, 0);
});

test('canonical P01 refusal and view removal dispatch no Input.*', async () => {
  const f = fixture();
  f.refuse();
  const control = f.owner.bindApprovedView('lease_3669', context);
  await assert.rejects(() => control.execute(scroll));
  assert.deepEqual(f.sent.map(v=>v.request), [BROWSER_CONTROL_LEASE_RESOLVE_KIND]);
  assert.equal(f.commands.filter(x => x.startsWith('Input.')).length, 0);
  f.setView(null);
  await assert.rejects(() => control.execute(scroll), (e: unknown) =>
    (e as {code:string}).code === 'host_unavailable');
  assert.equal(f.sent.length, 1);
  await control.close();
});

test('source-only product wiring has no renderer IPC or local authority', () => {
  const src = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'src');
  const bridge = readFileSync(path.join(src, 'browser', 'browser-action-trusted-main.ts'), 'utf8');
  const main = readFileSync(path.join(src, 'main', 'main.ts'), 'utf8');
  const opener = readFileSync(path.join(src, 'browser', 'browser-open-electron-view.ts'), 'utf8');
  assert.doesNotMatch(bridge, /from ['"]electron['"]|ipcMain|ipcRenderer|contextBridge/);
  assert.match(main, /createTrustedMainBrowserActionOwner\(/);
  assert.match(main, /takeResidentBrowserControlLeaseLine\(\)/);
  assert.match(main, /findActiveControlView: browserOpenViewOwner.findActiveControlView/);
  assert.match(opener, /active.ready = finalUrl !== null/);
  assert.match(opener, /isNavigationPermitted\(currentUrl, active.approvedUrl\)/);
  assert.match(opener, /isNavigationPermitted\(finalUrl, input.approvedUrl\)/);
  assert.doesNotMatch(opener, /clearTimeout\(expiryTimer\)/);
  assert.doesNotMatch(main, /ipcMain\.handle\(['"]browser/);
});
