/**
 * #3669 — Desktop canonical browser-control lease transport tests.
 *
 * Hermetic: the supervised pipe is a boundary double, so no resident process, no
 * Electron, no network and no real profile is involved. These tests are about
 * the *wire* contract — the two bounded request kinds, the closed response
 * schemas over the shared slot — and above all about the fact that the
 * Desktop can never resolve or consume a lease the agent-side canonical
 * authority refuses.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import {
  BROWSER_CONTROL_LEASE_CARRIES_CREDENTIAL,
  BROWSER_CONTROL_LEASE_CARRIES_PAGE_CONTENT,
  BROWSER_CONTROL_LEASE_CARRIES_P01_PAYLOAD,
  BROWSER_CONTROL_LEASE_CONSUME_KIND,
  BROWSER_CONTROL_LEASE_EVENT,
  BROWSER_CONTROL_LEASE_NEW_LISTENER,
  BROWSER_CONTROL_LEASE_REQUEST_CONTRACT_VERSION,
  BROWSER_CONTROL_LEASE_REQUEST_KINDS_ADDED,
  BROWSER_CONTROL_LEASE_REQUEST_MINTS_LEASE,
  BROWSER_CONTROL_LEASE_REFUND_SUPPORTED,
  BROWSER_CONTROL_LEASE_RESPONSE_CONTRACT_VERSION,
  BROWSER_CONTROL_LEASE_RESOLVE_KIND,
  BROWSER_CONTROL_LEASE_SECOND_READER,
  BROWSER_CONTROL_LEASE_USES_EXISTING_PIPE,
  browserControlLeaseConsumeRequestLine,
  browserControlLeaseResolveRequestLine,
  createResidentBrowserControlLeaseAuthority,
  isBrowserControlLeaseAnswerLine,
  parseBrowserControlLeaseLine,
  type BrowserControlLeaseContext,
  type ResidentBrowserControlLeaseBoundary,
  ResidentLeaseRefusalError,
} from '../src/conversation/resident-browser-control-lease.js';
import { assertBoundedActionLease, type LeaseEligibleAction } from '../src/browser/browser-action-contract.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const sourceRoot = path.join(here, '..', '..', 'src');

const CONTEXT: BrowserControlLeaseContext = Object.freeze({
  requestFingerprint: 'a'.repeat(64),
  browserSessionRef: 'run/session-1',
  deviceRef: 'device_3669',
  runRef: 'run_3669',
  workspaceRef: 'workspace_3669',
  ownerRef: 'owner_3669',
  originScope: 'https://example.com',
  allowedActionClasses: ['click', 'focus', 'scroll', 'type'],
  ttlSeconds: 300,
  maxActions: 25,
});

function leaseDict(): Record<string, unknown> {
  return {
    leaseId: 'lease/3669',
    requestFingerprint: CONTEXT.requestFingerprint,
    browserSessionRef: CONTEXT.browserSessionRef,
    runRef: CONTEXT.runRef,
    workspaceRef: CONTEXT.workspaceRef,
    ownerRef: CONTEXT.ownerRef,
    allowedActionClasses: [...CONTEXT.allowedActionClasses],
    originScope: CONTEXT.originScope,
    maxActions: CONTEXT.maxActions,
    issuedAtIso: '2026-10-08T09:00:00.000Z',
    expiresAtIso: '2026-10-08T09:05:00.000Z',
    approvalRef: 'decision_3669',
    evidenceRef: 'evidence_3669',
  };
}

function answerLine(kind: string, overrides: Record<string, unknown> = {}): string {
  const base: Record<string, unknown> = {
    event: BROWSER_CONTROL_LEASE_EVENT,
    contract_version: BROWSER_CONTROL_LEASE_RESPONSE_CONTRACT_VERSION,
    request: kind,
    ok: true,
    request_fingerprint: CONTEXT.requestFingerprint,
    reason: null,
    ...(kind === BROWSER_CONTROL_LEASE_RESOLVE_KIND
      ? { lease: leaseDict() }
      : { consumed_actions: 3 }),
  };
  return JSON.stringify({ ...base, ...overrides });
}

class FakeBoundary implements ResidentBrowserControlLeaseBoundary {
  sent: string[] = [];
  answers: string[] = [];
  running = true;
  sendOk = true;

  sendResidentLine(line: string): boolean {
    this.sent.push(line);
    return this.sendOk;
  }

  takeResidentBrowserControlLeaseLine(): string | null {
    const line = this.answers.shift() ?? null;
    return line;
  }

  residentRunning(): boolean {
    return this.running;
  }
}

function authorityWith(boundary: FakeBoundary) {
  return createResidentBrowserControlLeaseAuthority({
    context: CONTEXT,
    boundary,
    timeoutMs: 1_000,
    pollIntervalMs: 0,
    sleep: async () => undefined,
  });
}

test('#3669 the resolve request carries exactly the bounded context fields', () => {
  const line = browserControlLeaseResolveRequestLine(CONTEXT);
  const parsed = JSON.parse(line) as Record<string, unknown>;
  assert.deepEqual(
    Object.keys(parsed).sort(),
    [
      'allowedActionClasses',
      'browserSessionRef',
      'contract_version',
      'deviceRef',
      'maxActions',
      'originScope',
      'ownerRef',
      'request',
      'requestFingerprint',
      'runRef',
      'ttlSeconds',
      'workspaceRef',
    ].sort(),
  );
  assert.equal(parsed['request'], BROWSER_CONTROL_LEASE_RESOLVE_KIND);
  assert.equal(parsed['contract_version'], BROWSER_CONTROL_LEASE_REQUEST_CONTRACT_VERSION);
  for (const forbidden of ['url', 'p01', 'pause', 'decision', 'credential', 'cookies', 'pageContent']) {
    assert.equal(Object.hasOwn(parsed, forbidden), false, `request must not carry ${forbidden}`);
  }
});

test('#3669 the consume request carries exactly the bounded consume facts', () => {
  const line = browserControlLeaseConsumeRequestLine(CONTEXT, {
    action: 'click',
    observedOrigin: CONTEXT.originScope,
  });
  const parsed = JSON.parse(line) as Record<string, unknown>;
  assert.deepEqual(
    Object.keys(parsed).sort(),
    [
      'action',
      'browserSessionRef',
      'contract_version',
      'observedOrigin',
      'ownerRef',
      'request',
      'requestFingerprint',
      'runRef',
      'workspaceRef',
    ].sort(),
  );
  assert.equal(parsed['request'], BROWSER_CONTROL_LEASE_CONSUME_KIND);
  // The observed origin is normalised exactly like the request origin.
  assert.equal(parsed['observedOrigin'], 'https://example.com');
  for (const forbidden of ['deviceRef', 'originScope', 'allowedActionClasses', 'ttlSeconds', 'maxActions']) {
    assert.equal(Object.hasOwn(parsed, forbidden), false, `consume must not carry ${forbidden}`);
  }
});

test('#3669 an unbounded context or observed origin is refused before sending', () => {
  for (const badContext of [
    { ...CONTEXT, requestFingerprint: 'x'.repeat(60) },
    { ...CONTEXT, requestFingerprint: 'A'.repeat(64) },
    { ...CONTEXT, deviceRef: '' },
    { ...CONTEXT, originScope: 'not-an-origin' },
    { ...CONTEXT, allowedActionClasses: [] },
    { ...CONTEXT, allowedActionClasses: ['click', 'submit'] },
    { ...CONTEXT, ttlSeconds: 0 },
    { ...CONTEXT, ttlSeconds: 901 },
    { ...CONTEXT, maxActions: 101 },
  ]) {
    assert.throws(
      () => browserControlLeaseResolveRequestLine(badContext),
      ResidentLeaseRefusalError,
      `resolve context must be refused: ${JSON.stringify(Object.keys(badContext))}`,
    );
  }
  assert.throws(
    () => browserControlLeaseConsumeRequestLine(CONTEXT, { action: 'click', observedOrigin: ' ' }),
    ResidentLeaseRefusalError,
  );
  assert.throws(
    () =>
      browserControlLeaseConsumeRequestLine(CONTEXT, {
        action: 'submit' as unknown as LeaseEligibleAction,
        observedOrigin: CONTEXT.originScope,
      }),
    ResidentLeaseRefusalError,
  );
});

test('#3669 a successful PHASE A answer resolves to the bounded lease shape', async () => {
  const boundary = new FakeBoundary();
  boundary.answers.push(answerLine(BROWSER_CONTROL_LEASE_RESOLVE_KIND));
  const lease = await authorityWith(boundary).resolve({
    browserSessionRef: CONTEXT.browserSessionRef,
    action: 'click',
  });
  assertBoundedActionLease(lease);
  assert.equal(boundary.sent.length, 1);
  assert.deepEqual(JSON.parse(boundary.sent[0] as string)['request'], BROWSER_CONTROL_LEASE_RESOLVE_KIND);
});

test('#3669 a successful PHASE B answer resolves to the new durable count', async () => {
  const boundary = new FakeBoundary();
  boundary.answers.push(answerLine(BROWSER_CONTROL_LEASE_CONSUME_KIND, { consumed_actions: 7 }));
  const consumed = await authorityWith(boundary).consume({
    browserSessionRef: CONTEXT.browserSessionRef,
    action: 'click',
    observedOrigin: CONTEXT.originScope,
  });
  assert.equal(consumed, 7);
  assert.deepEqual(JSON.parse(boundary.sent[0] as string)['action'], 'click');
});

test('#3669 the store refusals pass through as desktop codes', async () => {
  for (const reason of ['action_budget_exhausted', 'lease_idle_exceeded', 'origin_scope_exceeded']) {
    const boundary = new FakeBoundary();
    boundary.answers.push(answerLine(BROWSER_CONTROL_LEASE_CONSUME_KIND, { ok: false, reason, consumed_actions: null }));
    await assert.rejects(
      () =>
        authorityWith(boundary).consume({
          browserSessionRef: CONTEXT.browserSessionRef,
          action: 'click',
          observedOrigin: CONTEXT.originScope,
        }),
      (error: unknown) =>
        error instanceof ResidentLeaseRefusalError && error.code === reason,
    );
  }
});

test('#3669 P01 and evidence failures collapse into lease_invalid without leaking', async () => {
  for (const reason of ['p01_approval_invalid', 'evidence_unavailable', 'lease_unknown', 'weird_reason']) {
    const boundary = new FakeBoundary();
    boundary.answers.push(answerLine(BROWSER_CONTROL_LEASE_RESOLVE_KIND, { ok: false, reason, lease: null }));
    await assert.rejects(
      () =>
        authorityWith(boundary).resolve({ browserSessionRef: CONTEXT.browserSessionRef, action: 'click' }),
      (error: unknown) => {
        assert.ok(error instanceof ResidentLeaseRefusalError);
        assert.equal((error as ResidentLeaseRefusalError).code, 'lease_invalid');
        assert.ok(!((error as Error).message.includes('p01-decision')));
        return true;
      },
    );
  }
});

test('#3669 an unconfigured agent-side authority maps to host_unavailable', async () => {
  const boundary = new FakeBoundary();
  boundary.answers.push(answerLine(BROWSER_CONTROL_LEASE_RESOLVE_KIND, { ok: false, reason: 'lease_unavailable', lease: null }));
  await assert.rejects(
    () => authorityWith(boundary).resolve({ browserSessionRef: CONTEXT.browserSessionRef, action: 'click' }),
    (error: unknown) =>
      error instanceof ResidentLeaseRefusalError && (error as ResidentLeaseRefusalError).code === 'host_unavailable',
  );
});

test('#3669 an answer for a different fingerprint is never accepted', async () => {
  const boundary = new FakeBoundary();
  boundary.answers.push(answerLine(BROWSER_CONTROL_LEASE_CONSUME_KIND, { request_fingerprint: 'b'.repeat(64) }));
  await assert.rejects(
    () =>
      authorityWith(boundary).consume({
        browserSessionRef: CONTEXT.browserSessionRef,
        action: 'click',
        observedOrigin: CONTEXT.originScope,
      }),
    (error: unknown) =>
      error instanceof ResidentLeaseRefusalError && (error as Error).message.includes('different request'),
  );
});

test('#3669 the host may not address a session the trusted context does not bind', async () => {
  const boundary = new FakeBoundary();
  await assert.rejects(
    () =>
      authorityWith(boundary).resolve({
        browserSessionRef: 'run/other-session',
        action: 'click',
      }),
    ResidentLeaseRefusalError,
  );
  assert.equal(boundary.sent.length, 0);
});

test('#3669 the shared slot routes each kind: a stale other-kind line is skipped', async () => {
  const boundary = new FakeBoundary();
  // A stale consume answer (from an earlier PHASE B) sits in the shared slot,
  // then the real resolve answer arrives. The consume line must be skipped,
  // never misrouted into the resolve parse.
  boundary.answers.push(answerLine(BROWSER_CONTROL_LEASE_CONSUME_KIND));
  boundary.answers.push(answerLine(BROWSER_CONTROL_LEASE_RESOLVE_KIND));
  const lease = await authorityWith(boundary).resolve({
    browserSessionRef: CONTEXT.browserSessionRef,
    action: 'click',
  });
  assertBoundedActionLease(lease);
  assert.equal(boundary.sent.length, 1);
});

test('#3669 a not-running or unwritable resident fails closed', async () => {
  const stopped = new FakeBoundary();
  stopped.running = false;
  await assert.rejects(
    () => authorityWith(stopped).resolve({ browserSessionRef: CONTEXT.browserSessionRef, action: 'click' }),
    (error: unknown) =>
      error instanceof ResidentLeaseRefusalError && (error as ResidentLeaseRefusalError).code === 'host_unavailable',
  );
  const unwritable = new FakeBoundary();
  unwritable.sendOk = false;
  await assert.rejects(
    () =>
      authorityWith(unwritable).consume({
        browserSessionRef: CONTEXT.browserSessionRef,
        action: 'click',
        observedOrigin: CONTEXT.originScope,
      }),
    (error: unknown) =>
      error instanceof ResidentLeaseRefusalError && (error as ResidentLeaseRefusalError).code === 'host_unavailable',
  );
});

test('#3669 the response schemas are exact-closed per kind', () => {
  assert.notEqual(parseBrowserControlLeaseLine(answerLine(BROWSER_CONTROL_LEASE_RESOLVE_KIND), BROWSER_CONTROL_LEASE_RESOLVE_KIND), null);
  assert.notEqual(parseBrowserControlLeaseLine(answerLine(BROWSER_CONTROL_LEASE_CONSUME_KIND), BROWSER_CONTROL_LEASE_CONSUME_KIND), null);
  // A payload key of the OTHER kind is not this contract.
  assert.equal(
    parseBrowserControlLeaseLine(answerLine(BROWSER_CONTROL_LEASE_RESOLVE_KIND, { consumed_actions: 1 }), BROWSER_CONTROL_LEASE_RESOLVE_KIND),
    null,
  );
  assert.equal(
    parseBrowserControlLeaseLine(answerLine(BROWSER_CONTROL_LEASE_CONSUME_KIND, { lease: leaseDict() }), BROWSER_CONTROL_LEASE_CONSUME_KIND),
    null,
  );
  // An extra key is not this contract, even when the extra would be discarded.
  assert.equal(
    parseBrowserControlLeaseLine(answerLine(BROWSER_CONTROL_LEASE_RESOLVE_KIND, { note: 'extra' }), BROWSER_CONTROL_LEASE_RESOLVE_KIND),
    null,
  );
  // A different event or version is not this contract either.
  assert.equal(
    parseBrowserControlLeaseLine(answerLine(BROWSER_CONTROL_LEASE_RESOLVE_KIND, { event: 'something_else' }), BROWSER_CONTROL_LEASE_RESOLVE_KIND),
    null,
  );
  assert.equal(
    parseBrowserControlLeaseLine(answerLine(BROWSER_CONTROL_LEASE_RESOLVE_KIND, { contract_version: 'v0' }), BROWSER_CONTROL_LEASE_RESOLVE_KIND),
    null,
  );
  // A malformed payload type is not this contract.
  assert.equal(
    parseBrowserControlLeaseLine(answerLine(BROWSER_CONTROL_LEASE_RESOLVE_KIND, { lease: ['not', 'an', 'object'] }), BROWSER_CONTROL_LEASE_RESOLVE_KIND),
    null,
  );
  assert.equal(
    parseBrowserControlLeaseLine(answerLine(BROWSER_CONTROL_LEASE_CONSUME_KIND, { consumed_actions: 2.5 }), BROWSER_CONTROL_LEASE_CONSUME_KIND),
    null,
  );
  // Recognition only answers to its own kind on the shared slot.
  assert.equal(isBrowserControlLeaseAnswerLine(answerLine(BROWSER_CONTROL_LEASE_CONSUME_KIND), BROWSER_CONTROL_LEASE_RESOLVE_KIND), false);
  assert.equal(isBrowserControlLeaseAnswerLine(answerLine(BROWSER_CONTROL_LEASE_RESOLVE_KIND), BROWSER_CONTROL_LEASE_RESOLVE_KIND), true);
});

test('#3669 the transport reuses the existing supervised pipe and adds no reader', () => {
  assert.equal(BROWSER_CONTROL_LEASE_USES_EXISTING_PIPE, true);
  assert.equal(BROWSER_CONTROL_LEASE_NEW_LISTENER, false);
  assert.equal(BROWSER_CONTROL_LEASE_SECOND_READER, false);
  assert.equal(BROWSER_CONTROL_LEASE_REQUEST_KINDS_ADDED, 2);
  assert.equal(BROWSER_CONTROL_LEASE_CARRIES_P01_PAYLOAD, false);
  assert.equal(BROWSER_CONTROL_LEASE_CARRIES_CREDENTIAL, false);
  assert.equal(BROWSER_CONTROL_LEASE_CARRIES_PAGE_CONTENT, false);
  assert.equal(BROWSER_CONTROL_LEASE_REQUEST_MINTS_LEASE, false);
  assert.equal(BROWSER_CONTROL_LEASE_REFUND_SUPPORTED, false);
});

test('#3669 the transport never opens a socket or a listener', () => {
  for (const file of [
    path.join('conversation', 'resident-browser-control-lease.ts'),
    path.join('browser', 'browser-action-host.ts'),
    path.join('browser', 'browser-action-composition.ts'),
  ]) {
    const source = readFileSync(path.join(sourceRoot, file), 'utf8');
    for (const forbidden of [
      "from 'node:net'",
      "from 'node:http'",
      'createServer(',
      '.listen(',
      "from 'electron'",
    ]) {
      assert.equal(source.includes(forbidden), false, `${file} must not contain ${forbidden}`);
    }
  }
});
