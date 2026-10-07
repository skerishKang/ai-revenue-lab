/**
 * #3611 — trustworthy `browser.open` host tests.
 *
 * Hermetic: the ephemeral view is a fake port, so no Electron process, no
 * network, no real profile and no real account is involved. The last two blocks
 * read real sources (the IPC allowlist and the Electron binding) so a future
 * edit that widens authority fails here rather than in review.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import {
  BROWSER_OPEN_HOST_REF,
  BROWSER_OPEN_RECEIPT_FIELDS,
  BrowserOpenContractError,
  assertApprovedBrowserOpenRequest,
  type ApprovedBrowserOpenRequest,
  type BrowserOpenReceipt,
} from '../src/browser/browser-open-contracts.js';
import {
  BROWSER_CONTROL_IMPLEMENTED,
  BROWSER_OPEN_IMPLEMENTED,
  BROWSER_OPEN_PAGE_DERIVED_OUTPUT_SUPPORTED,
  BROWSER_OPEN_REDEMPTION_REQUIRED,
  BROWSER_OPEN_USES_EXISTING_P01,
  DESKTOP_DURABLE_REDEMPTION_AUTHORITY,
  IN_PROCESS_CONSUMED_SET_IS_AUTHORITY,
  SECOND_BROWSER_AUTHORITY,
  BrowserOpenHost,
  BrowserOpenRefusalError,
  PERSISTENT_BROWSER_PROFILE_SUPPORTED,
  unconfiguredBrowserOpenRedemption,
  type BrowserOpenRedemptionPort,
  type BrowserOpenViewPort,
  type BrowserOpenViewSession,
  type TrustedBrowserOpenGrant,
} from '../src/browser/browser-open-host.js';
import { evaluatePublicUrl, isPermittedPublicUrl } from '../src/browser/public-url-policy.js';
import { IPC_ALLOWLIST, DENIED_IPC_CHANNELS, isAllowedIpcChannel } from '../src/contract/ipc.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const sourceRoot = path.join(here, '..', '..', 'src');
const appRoot = path.join(here, '..', '..');

function readSource(...segments: string[]): string {
  return readFileSync(path.join(sourceRoot, ...segments), 'utf8');
}

function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^[ \t]*\/\/.*$/gm, '');
}

const APPROVED_URL = 'https://example.com/report?id=7';
const NOW = new Date('2026-10-07T12:00:00.000Z');

/**
 * Forbidden-name fixtures are assembled from fragments on purpose (same idiom as
 * `tests/support-bundle.test.ts`): the #3611 credential-boundary guard scans this
 * file as well, so an unassembled literal would trip the guard it exists to test.
 * The assertions below are unchanged — the runtime strings are identical.
 */
const FORBIDDEN_BINDING_LITERALS = [
  ['execute', 'JavaScript'].join(''),
  ['capture', 'Page'].join(''),
  ['print', 'ToPDF'].join(''),
  ['claim', 'Tab'].join(''),
  ['persist', ':'].join(''),
];

function approvedRequest(overrides: Partial<ApprovedBrowserOpenRequest> = {}) {
  return assertApprovedBrowserOpenRequest({
    openId: 'open_1',
    runRef: 'run_3611',
    workspaceRef: 'workspace_3611',
    ownerRef: 'owner_3611',
    ticketRef: 'ticket_3611',
    requestedUrl: 'https://example.com/report?id=7#section',
    normalizedUrl: APPROVED_URL,
    requestFingerprint: 'fingerprint_3611',
    p01ApprovalRef: 'decision_3611',
    evidenceRef: 'evidence_3611',
    admissionRef: 'admission_3611',
    revisionRef: 'revision_3611',
    hostLeaseRef: 'host_lease_3611',
    issuedAtIso: NOW.toISOString(),
    expiresAtIso: new Date(NOW.getTime() + 300_000).toISOString(),
    ...overrides,
  });
}

function grant(overrides: Partial<TrustedBrowserOpenGrant> = {}): TrustedBrowserOpenGrant {
  return {
    grantId: 'grant_3611',
    openId: 'open_1',
    runRef: 'run_3611',
    workspaceRef: 'workspace_3611',
    normalizedUrl: APPROVED_URL,
    requestFingerprint: 'fingerprint_3611',
    p01ApprovalRef: 'decision_3611',
    hostLeaseRef: 'host_lease_3611',
    redemptionRef: 'redemption_3611',
    issuedAtIso: NOW.toISOString(),
    expiresAtIso: new Date(NOW.getTime() + 300_000).toISOString(),
    ...overrides,
  };
}

/**
 * Fake canonical redemption authority.
 *
 * The ledger is supplied by the caller on purpose: handing two different hosts
 * the SAME ledger while each keeps its own private consumed set is exactly a
 * restart, and it is how the tests below prove the host's memory is not the
 * authority.
 */
class FakeRedemption implements BrowserOpenRedemptionPort {
  configured = true;
  denied = false;
  readonly redeemed: string[] = [];
  readonly #ledger: Set<string> | undefined;

  constructor(ledger?: Set<string>) {
    this.#ledger = ledger;
  }

  async redeem(input: { redemptionRef: string }): Promise<void> {
    if (this.denied) {
      throw new BrowserOpenRefusalError(
        'grant_rejected',
        'canonical redemption refused this browser open',
      );
    }
    if (this.#ledger !== undefined) {
      if (this.#ledger.has(input.redemptionRef)) {
        throw new BrowserOpenRefusalError(
          'grant_rejected',
          'canonical redemption has already been consumed',
        );
      }
      this.#ledger.add(input.redemptionRef);
    }
    this.redeemed.push(input.redemptionRef);
  }
}

type ViewBehavior = 'loaded' | 'blocked' | 'load_failed' | 'hang' | 'throw';

class FakeView implements BrowserOpenViewPort {
  configured = true;
  behavior: ViewBehavior = 'loaded';
  finalUrlOverride: string | null = null;
  calls: Array<{ hostLeaseRef: string; approvedUrl: string }> = [];
  gate: ((candidate: unknown) => boolean) | null = null;
  closeCount = 0;
  /** Leases torn down, whether through a session or the lease-scoped teardown. */
  closedLeases: string[] = [];

  async close(hostLeaseRef: string): Promise<void> {
    this.closeCount += 1;
    this.closedLeases.push(hostLeaseRef);
  }

  async open(input: {
    hostLeaseRef: string;
    approvedUrl: string;
    expiresAtIso: string;
    onNavigationAttempt: (candidate: unknown) => boolean;
  }): Promise<BrowserOpenViewSession> {
    this.calls.push({ hostLeaseRef: input.hostLeaseRef, approvedUrl: input.approvedUrl });
    this.gate = input.onNavigationAttempt;
    if (this.behavior === 'hang') {
      return await new Promise<BrowserOpenViewSession>(() => undefined);
    }
    if (this.behavior === 'throw') {
      throw new Error('view failure');
    }
    const close = async (): Promise<void> => {
      this.closeCount += 1;
      this.closedLeases.push(input.hostLeaseRef);
    };
    const finalUrl =
      this.finalUrlOverride ?? (this.behavior === 'loaded' ? input.approvedUrl : null);
    return {
      navigationBlocked: this.behavior === 'blocked',
      loadFailed: this.behavior === 'load_failed',
      finalUrl,
      redirectCount: 0,
      dialogsSuppressed: 0,
      close,
    };
  }
}

function hostWith(
  view: FakeView,
  timeoutMs = 1_000,
  redemption: BrowserOpenRedemptionPort = new FakeRedemption(),
): BrowserOpenHost {
  return new BrowserOpenHost({ view, redemption, now: () => NOW, timeoutMs });
}

function assertReceiptShape(receipt: BrowserOpenReceipt): void {
  assert.deepEqual(Object.keys(receipt).sort(), [...BROWSER_OPEN_RECEIPT_FIELDS].sort());
  assert.equal(receipt.pageContentIncluded, false);
  assert.equal(receipt.cookieIncluded, false);
  assert.equal(receipt.credentialIncluded, false);
  assert.equal(receipt.domApiExposed, false);
  assert.equal(receipt.networkScope, 'approved_url_fetch_only');
  assert.equal(receipt.hostRef, BROWSER_OPEN_HOST_REF);
}

test('#3611 a permitted open loads through the injected view and returns a bounded receipt', async () => {
  const view = new FakeView();
  const receipt = await hostWith(view).open(approvedRequest(), grant());
  assertReceiptShape(receipt);
  assert.equal(receipt.loadOutcome, 'loaded');
  assert.equal(receipt.finalUrlNormalized, APPROVED_URL);
  assert.equal(receipt.requestedUrlNormalized, APPROVED_URL);
  assert.equal(receipt.p01ApprovalRef, 'decision_3611');
  assert.equal(receipt.admissionRef, 'admission_3611');
  assert.deepEqual(view.calls, [{ hostLeaseRef: 'host_lease_3611', approvedUrl: APPROVED_URL }]);
  // A loaded view stays visible for the user; the port owns the lease-bounded teardown.
  assert.equal(view.closeCount, 0);
});

test('#3611 the host navigates only the canonical approved URL', async () => {
  const view = new FakeView();
  await hostWith(view).open(approvedRequest(), grant());
  assert.equal(view.calls[0]!.approvedUrl, APPROVED_URL);
  assert.notEqual(view.calls[0]!.approvedUrl, 'https://example.com/report?id=7#section');
});

test('#3611 page-derived and unexpected request fields are refused', async () => {
  for (const [field, value] of [
    ['title', '보고서'],
    ['html', '<h1>x</h1>'],
    ['screenshot', 'base64'],
    ['cookies', 'a=b'],
    ['formValues', {}],
    ['selector', '#submit'],
  ] as const) {
    assert.throws(
      () => assertApprovedBrowserOpenRequest({ ...approvedRequest(), [field]: value }),
      BrowserOpenContractError,
      `${field} must be refused`,
    );
  }
});

test('#3611 a lifetime beyond the reviewed grant maximum is refused', () => {
  assert.throws(
    () =>
      assertApprovedBrowserOpenRequest({
        ...approvedRequest(),
        expiresAtIso: new Date(NOW.getTime() + 901_000).toISOString(),
      }),
    BrowserOpenContractError,
  );
});

test('#3611 the grant must bind the exact approved open', async () => {
  const view = new FakeView();
  const host = hostWith(view);
  for (const mutated of [
    grant({ normalizedUrl: 'https://example.org/other' }),
    grant({ requestFingerprint: 'other_fingerprint' }),
    grant({ runRef: 'run_other' }),
    grant({ openId: 'open_other' }),
    grant({ hostLeaseRef: 'host_lease_other' }),
  ]) {
    await assert.rejects(
      () => host.open(approvedRequest(), mutated),
      (error: unknown) =>
        error instanceof BrowserOpenRefusalError && error.code === 'grant_rejected',
    );
  }
  assert.equal(view.calls.length, 0, 'the view must never be opened for an unbound grant');
});

test('#3611 a grant that outlives the approved request is refused', async () => {
  const view = new FakeView();
  await assert.rejects(
    () =>
      hostWith(view).open(
        approvedRequest({ expiresAtIso: new Date(NOW.getTime() + 120_000).toISOString() }),
        grant({ expiresAtIso: new Date(NOW.getTime() + 300_000).toISOString() }),
      ),
    (error: unknown) => error instanceof BrowserOpenRefusalError && error.code === 'grant_rejected',
  );
  assert.equal(view.calls.length, 0);
});

test('#3611 the grant is one-shot and replay is denied', async () => {
  const view = new FakeView();
  const host = hostWith(view);
  await host.open(approvedRequest(), grant());
  await assert.rejects(
    () => host.open(approvedRequest(), grant()),
    (error: unknown) => error instanceof BrowserOpenRefusalError && error.code === 'grant_rejected',
  );
  assert.equal(view.calls.length, 1);
  assert.equal(host.consumedCount, 1);
});

test('#3611 an expired grant never reaches the view', async () => {
  const view = new FakeView();
  const host = new BrowserOpenHost({
    view,
    redemption: new FakeRedemption(),
    now: () => new Date(NOW.getTime() + 600_000),
  });
  await assert.rejects(
    () => host.open(approvedRequest(), grant()),
    (error: unknown) => error instanceof BrowserOpenRefusalError && error.code === 'grant_rejected',
  );
  assert.equal(view.calls.length, 0);
});

test('#3611 a non-public approved URL is refused before any view exists', async () => {
  for (const url of [
    'http://localhost:3000/dashboard',
    'https://169.254.169.254/latest/meta-data',
    'https://10.0.0.5/',
    'https://93.184.216.34/',
  ]) {
    const view = new FakeView();
    await assert.rejects(
      () => hostWith(view).open(approvedRequest({ normalizedUrl: url }), grant({ normalizedUrl: url })),
      (error: unknown) => error instanceof BrowserOpenRefusalError && error.code === 'policy_denied',
    );
    assert.equal(view.calls.length, 0, `${url} must not create a view`);
  }
});

test('#3611 an unconfigured host fails closed', async () => {
  const view = new FakeView();
  view.configured = false;
  await assert.rejects(
    () => hostWith(view).open(approvedRequest(), grant()),
    (error: unknown) => error instanceof BrowserOpenRefusalError && error.code === 'host_unavailable',
  );
  assert.equal(view.calls.length, 0);
});

test('#3611 the per-navigation gate refuses off-origin, non-public and unparsable targets', async () => {
  const view = new FakeView();
  await hostWith(view).open(approvedRequest(), grant());
  assert.ok(view.gate);
  assert.equal(view.gate(APPROVED_URL), true);
  assert.equal(view.gate('https://example.com/other'), true, 'same origin stays inside the gate');
  for (const candidate of [
    'https://example.org/',
    'https://sub.example.com/',
    'http://example.com/',
    'https://example.com:8443/',
    'http://localhost:3000/',
    'https://127.0.0.1/',
    'https://169.254.169.254/',
    'file:///C:/Users/limone/secrets.txt',
    'padiem://pair',
    'javascript:alert(1)',
    'about:blank',
    'not-a-url',
  ]) {
    assert.equal(view.gate(candidate), false, `${candidate} must be blocked`);
  }
});

test('#3611 a blocked navigation produces navigation_blocked and closes the view', async () => {
  const view = new FakeView();
  view.behavior = 'blocked';
  const receipt = await hostWith(view).open(approvedRequest(), grant());
  assertReceiptShape(receipt);
  assert.equal(receipt.loadOutcome, 'navigation_blocked');
  assert.equal(receipt.finalUrlNormalized, null);
  assert.equal(view.closeCount, 1);
});

test('#3611 a session that lands off-origin is reported as blocked, never as loaded', async () => {
  const view = new FakeView();
  view.finalUrlOverride = 'https://evil.example.com/landing';
  const receipt = await hostWith(view).open(approvedRequest(), grant());
  assert.equal(receipt.loadOutcome, 'navigation_blocked');
  assert.equal(receipt.finalUrlNormalized, null);
  assert.equal(view.closeCount, 1);
});

test('#3611 a load failure is reported truthfully', async () => {
  const view = new FakeView();
  view.behavior = 'load_failed';
  const receipt = await hostWith(view).open(approvedRequest(), grant());
  assert.equal(receipt.loadOutcome, 'load_failed');
  assert.equal(receipt.finalUrlNormalized, null);
  assert.equal(view.closeCount, 1);
});

test('#3611 a hanging view times out and is torn down by lease', async () => {
  const view = new FakeView();
  view.behavior = 'hang';
  const receipt = await hostWith(view, 20).open(approvedRequest(), grant());
  assert.equal(receipt.loadOutcome, 'timeout');
  assert.equal(receipt.finalUrlNormalized, null);
  // The port never returned a session, so teardown must not depend on one.
  assert.deepEqual(view.closedLeases, ['host_lease_3611']);
});

test('#3611 an unexpected view failure is torn down before it propagates', async () => {
  const view = new FakeView();
  view.behavior = 'throw';
  await assert.rejects(() => hostWith(view).open(approvedRequest(), grant()), /view failure/);
  assert.deepEqual(view.closedLeases, ['host_lease_3611']);
});

test('#3611 teardown is scoped to the failing lease only', async () => {
  const view = new FakeView();
  view.behavior = 'hang';
  await hostWith(view, 20).open(approvedRequest(), grant());
  assert.equal(view.closedLeases.includes('host_lease_other'), false);
});

test('#3611 redirect accounting stays bounded', async () => {
  const view = new FakeView();
  view.finalUrlOverride = APPROVED_URL;
  const receipt = await hostWith(view).open(approvedRequest(), grant());
  assert.ok(receipt.redirectCount >= 0 && receipt.redirectCount <= 5);
});

test('#3611 the public URL policy vectors keep the host mirror aligned with the canonical policy', () => {
  const vectorPath = path.join(appRoot, 'tests', 'vectors', 'public-url-policy-vectors.json');
  const payload = JSON.parse(readFileSync(vectorPath, 'utf8')) as {
    vectors: Array<{
      input: string;
      python: 'allow' | 'reject';
      python_normalized?: string;
      ts: 'allow' | 'reject';
      why: string;
    }>;
  };
  assert.ok(payload.vectors.length >= 20);
  for (const vector of payload.vectors) {
    const evaluation = evaluatePublicUrl(vector.input);
    assert.equal(
      evaluation.allowed ? 'allow' : 'reject',
      vector.ts,
      `host mirror decision changed for ${vector.input} (${vector.why})`,
    );
    if (evaluation.allowed) {
      assert.equal(
        vector.python,
        'allow',
        `host mirror must never allow what the canonical policy rejects: ${vector.input}`,
      );
      assert.ok(typeof vector.python_normalized === 'string' && vector.python_normalized.length > 0);
    }
  }
});

test('#3611 the module declarations state the open-only boundary', () => {
  assert.equal(BROWSER_OPEN_IMPLEMENTED, true);
  assert.equal(BROWSER_CONTROL_IMPLEMENTED, false);
  assert.equal(BROWSER_OPEN_USES_EXISTING_P01, true);
  assert.equal(SECOND_BROWSER_AUTHORITY, false);
  assert.equal(PERSISTENT_BROWSER_PROFILE_SUPPORTED, false);
  assert.equal(BROWSER_OPEN_PAGE_DERIVED_OUTPUT_SUPPORTED, false);
});

test('#3611 no browser IPC channel exists and browser control names stay denied', () => {
  assert.equal(isAllowedIpcChannel('padiem:shell:browser-open'), false);
  assert.equal(IPC_ALLOWLIST.has('padiem:shell:browser-open'), false);
  for (const name of [
    'padiem:shell:browser-control',
    'padiem:shell:browser-evaluate',
    'padiem:shell:browser-cookie-read',
    'padiem:shell:browser-profile-import',
    'padiem:shell:browser-download',
    'padiem:shell:approve',
  ]) {
    assert.equal(isAllowedIpcChannel(name), false, `${name} must stay denied`);
    assert.ok((DENIED_IPC_CHANNELS as readonly string[]).includes(name), `${name} must be listed`);
  }
});

test('#3611 the electron binding keeps the ephemeral, gated, content-free invariants', () => {
  const binding = stripComments(readSource('browser', 'browser-open-electron-view.ts'));
  assert.match(binding, /sandbox: true/);
  assert.match(binding, /contextIsolation: true/);
  assert.match(binding, /nodeIntegration: false/);
  assert.match(binding, /webSecurity: true/);
  assert.match(binding, /partition: ephemeralPartitionName\(\)/);
  assert.match(binding, /`browser-open-\$\{randomUUID\(\)\}`/);
  assert.match(binding, /setWindowOpenHandler\(\(\) => \(\{ action: 'deny' \}\)\)/);
  assert.match(binding, /setPermissionRequestHandler\(\(_contents, _permission, callback\) => \{\s*callback\(false\)/);
  assert.match(binding, /setPermissionCheckHandler\(\(\) => false\)/);
  assert.match(binding, /'will-download', \(event\) => event\.preventDefault\(\)\)/);
  assert.match(binding, /'page-title-updated', \(event\) => event\.preventDefault\(\)\)/);
  assert.match(binding, /'will-navigate', \(event, url\) => \{[\s\S]*?onNavigationAttempt\(url\)/);
  assert.match(binding, /'will-redirect', \(event, url\) => \{[\s\S]*?onNavigationAttempt\(url\)/);
  assert.match(binding, /redirects > BROWSER_OPEN_MAX_REDIRECTS/);
  assert.match(binding, /window\.destroy\(\)/);
  assert.match(binding, /setTimeout\([\s\S]*?expiresAtMs - Date\.now\(\)/);

  assert.equal(FORBIDDEN_BINDING_LITERALS.length, 5);
  for (const forbidden of [
    ...FORBIDDEN_BINDING_LITERALS,
    'preload',
    'webviewTag: true',
    'nodeIntegration: true',
    'cookies',
    'localStorage',
    'sessionStorage',
  ]) {
    assert.equal(
      binding.includes(forbidden),
      false,
      `the browser-open binding must not contain ${forbidden}`,
    );
  }
});

test('#3611 the host and contracts never touch Electron browser or session APIs', () => {
  for (const file of ['browser-open-host.ts', 'browser-open-contracts.ts', 'public-url-policy.ts']) {
    const source = stripComments(readSource('browser', file));
    for (const forbidden of [
      'from \'electron\'',
      'BrowserWindow',
      'WebContentsView',
      'BrowserView',
      'setPermissionRequestHandler',
      'will-download',
      'partition',
    ]) {
      assert.equal(source.includes(forbidden), false, `${file} must not reference ${forbidden}`);
    }
  }
});

test('#3611 the durable redemption gate runs before any view exists', async () => {
  const view = new FakeView();
  const order: string[] = [];
  const inner = new FakeRedemption();
  const observed: BrowserOpenRedemptionPort = {
    configured: true,
    redeem: async (input) => {
      order.push(`redeem:${input.redemptionRef}`);
      await inner.redeem(input);
    },
  };
  // Record the view call in the same order log. The point is the *order*, so the
  // open still succeeds and the receipt is still produced.
  const originalOpen = view.open.bind(view);
  view.open = async (input: Parameters<BrowserOpenViewPort['open']>[0]) => {
    order.push('view');
    return await originalOpen(input);
  };

  const receipt = await hostWith(view, 1_000, observed).open(approvedRequest(), grant());
  assert.deepEqual(order, ['redeem:redemption_3611', 'view']);
  assert.equal(receipt.loadOutcome, 'loaded');
});

test('#3611 an unconfigured redemption authority fails closed with no view', async () => {
  const view = new FakeView();
  const host = new BrowserOpenHost({
    view,
    redemption: unconfiguredBrowserOpenRedemption(),
    now: () => NOW,
  });
  assert.equal(host.redemptionConfigured, false);
  await assert.rejects(
    () => host.open(approvedRequest(), grant()),
    (error: unknown) =>
      error instanceof BrowserOpenRefusalError && error.code === 'redemption_unavailable',
  );
  assert.equal(view.calls.length, 0);
});

test('#3611 a refused canonical redemption never creates a view', async () => {
  const view = new FakeView();
  const redemption = new FakeRedemption();
  redemption.denied = true;
  await assert.rejects(
    () => hostWith(view, 1_000, redemption).open(approvedRequest(), grant()),
    (error: unknown) => error instanceof BrowserOpenRefusalError && error.code === 'grant_rejected',
  );
  assert.equal(view.calls.length, 0);
});

test('#3611 a restarted host reuses the canonical ledger and denies a replayed grant', async () => {
  // One canonical ledger, two independent hosts. The second host has an EMPTY
  // in-process consumed set, which is exactly what a restart leaves behind.
  const ledger = new Set<string>();
  const firstView = new FakeView();
  await hostWith(firstView, 1_000, new FakeRedemption(ledger)).open(
    approvedRequest(),
    grant(),
  );
  assert.equal(firstView.calls.length, 1);

  const secondView = new FakeView();
  const restarted = hostWith(secondView, 1_000, new FakeRedemption(ledger));
  assert.equal(restarted.consumedCount, 0, 'a restarted host remembers nothing');
  await assert.rejects(
    () => restarted.open(approvedRequest(), grant()),
    (error: unknown) =>
      error instanceof BrowserOpenRefusalError &&
      error.message.includes('already been consumed'),
  );
  assert.equal(secondView.calls.length, 0, 'a replayed grant must not create a view');
});

test('#3611 the desktop is not a durable redemption authority and the host is not the replay gate', () => {
  assert.equal(BROWSER_OPEN_REDEMPTION_REQUIRED, true);
  assert.equal(DESKTOP_DURABLE_REDEMPTION_AUTHORITY, false);
  assert.equal(IN_PROCESS_CONSUMED_SET_IS_AUTHORITY, false);
  assert.equal(SECOND_BROWSER_AUTHORITY, false);
});
