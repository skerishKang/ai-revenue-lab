/**
 * #3611 — trusted-main `browser.open` composition tests.
 *
 * Hermetic. The composition module must not import Electron (so it stays
 * unit-testable), and both of its ports must fail closed when unwired.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import {
  BROWSER_CONTROL_IMPLEMENTED,
  BROWSER_OPEN_ELECTRON_IMPORTED_HERE,
  DESKTOP_DURABLE_REDEMPTION_AUTHORITY,
  SECOND_BROWSER_AUTHORITY,
  TRUSTED_MAIN_BROWSER_OPEN_COMPOSED,
  UNCONFIGURED_PORT_FAILS_CLOSED,
  composeTrustedBrowserOpen,
  unconfiguredBrowserOpenViewPort,
} from '../src/browser/browser-open-composition.js';
import {
  BrowserOpenRefusalError,
  type BrowserOpenRedemptionPort,
  type BrowserOpenViewPort,
} from '../src/browser/browser-open-host.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const appRoot = path.join(here, '..', '..');
const sourceRoot = path.join(appRoot, 'src');

function readSource(...segments: string[]): string {
  return readFileSync(path.join(sourceRoot, ...segments), 'utf8');
}

test('#3611 the composition root does not import Electron', () => {
  const source = readSource('browser', 'browser-open-composition.ts');
  for (const forbidden of ["from 'electron'", 'BrowserWindow', 'BrowserView', 'WebContentsView']) {
    assert.equal(source.includes(forbidden), false, `composition must not contain ${forbidden}`);
  }
  assert.equal(BROWSER_OPEN_ELECTRON_IMPORTED_HERE, false);
});

test('#3611 an unwired composition fails closed on both ports', async () => {
  const composed = composeTrustedBrowserOpen();
  assert.equal(composed.viewConfigured, false);
  assert.equal(composed.redemptionConfigured, false);
  assert.equal(composed.host.redemptionConfigured, false);
  assert.equal(UNCONFIGURED_PORT_FAILS_CLOSED, true);

  // A view port that claims to be configured but is never wired must still be
  // refused by the missing redemption authority.
  const view: BrowserOpenViewPort = {
    configured: true,
    close: async () => undefined,
    open: async () => {
      throw new Error('must not be reached');
    },
  };
  // The clock is injected exactly like the fully-wired test below: the grant
  // carries absolute review timestamps, so a real clock past 12:05Z must not
  // reorder this refusal from redemption_unavailable into grant_rejected.
  const halfWired = composeTrustedBrowserOpen({
    view,
    now: () => new Date('2026-10-07T12:00:00.000Z'),
  });
  await assert.rejects(
    () =>
      halfWired.host.open(
        {
          openId: 'open_1',
          runRef: 'run_3611',
          workspaceRef: 'workspace_3611',
          ownerRef: 'owner_3611',
          ticketRef: 'ticket_3611',
          requestedUrl: 'https://example.com/report',
          normalizedUrl: 'https://example.com/report',
          requestFingerprint: 'fingerprint_3611',
          p01ApprovalRef: 'decision_3611',
          evidenceRef: 'evidence_3611',
          admissionRef: 'admission_3611',
          revisionRef: 'revision_3611',
          hostLeaseRef: 'host_lease_3611',
          issuedAtIso: '2026-10-07T12:00:00.000Z',
          expiresAtIso: '2026-10-07T12:05:00.000Z',
        },
        {
          grantId: 'grant_3611',
          openId: 'open_1',
          runRef: 'run_3611',
          workspaceRef: 'workspace_3611',
          normalizedUrl: 'https://example.com/report',
          requestFingerprint: 'fingerprint_3611',
          p01ApprovalRef: 'decision_3611',
          hostLeaseRef: 'host_lease_3611',
          redemptionRef: 'redemption_3611',
          issuedAtIso: '2026-10-07T12:00:00.000Z',
          expiresAtIso: '2026-10-07T12:05:00.000Z',
        },
      ),
    (error: unknown) =>
      error instanceof BrowserOpenRefusalError && error.code === 'redemption_unavailable',
  );
});

test('#3611 the unconfigured view port refuses instead of pretending to open', async () => {
  const view = unconfiguredBrowserOpenViewPort();
  assert.equal(view.configured, false);
  await view.close('host_lease_3611');
  await assert.rejects(() =>
    view.open({
      hostLeaseRef: 'host_lease_3611',
      approvedUrl: 'https://example.com/report',
      expiresAtIso: '2026-10-07T12:05:00.000Z',
      onNavigationAttempt: () => false,
    }),
  );
});

test('#3611 a fully wired composition assembles one host without opening anything', () => {
  let viewOpens = 0;
  const view: BrowserOpenViewPort = {
    configured: true,
    close: async () => undefined,
    open: async () => {
      viewOpens += 1;
      throw new Error('not reached');
    },
  };
  const redemption: BrowserOpenRedemptionPort = {
    configured: true,
    redeem: async () => undefined,
  };
  const composed = composeTrustedBrowserOpen({
    view,
    redemption,
    now: () => new Date('2026-10-07T12:00:00.000Z'),
  });
  assert.equal(composed.viewConfigured, true);
  assert.equal(composed.redemptionConfigured, true);
  assert.equal(viewOpens, 0, 'composing a host must not open a browser');
});

test('#3611 the composition states the boundary truthfully', () => {
  assert.equal(TRUSTED_MAIN_BROWSER_OPEN_COMPOSED, true);
  assert.equal(BROWSER_CONTROL_IMPLEMENTED, false);
  assert.equal(SECOND_BROWSER_AUTHORITY, false);
  assert.equal(DESKTOP_DURABLE_REDEMPTION_AUTHORITY, false);
});
