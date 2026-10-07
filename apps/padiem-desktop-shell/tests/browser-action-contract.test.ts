/**
 * #3647 — bounded action contract tests, slice 1 (post-CENTRAL-review).
 *
 * Hermetic. The taxonomy boundary is aligned to the #3607 CENTRAL final
 * design disposition (effect class first, verb second), the lease carries the
 * full correlation set with the authoritative policy values, and every
 * parameter bound is exercised at the exact-key level.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  DOWNLOAD_EXECUTION_BLOCKED_UNTIL_ARTIFACT_AUTHORITY,
  LEASE_CROSS_ORIGIN_POLICY,
  LEASE_ELIGIBLE_ACTIONS,
  LEASE_IDLE_SECONDS,
  LEASE_MAX_ACTIONS,
  LEASE_MAX_ACTIONS_HARD_CAP,
  LEASE_REVOCATION,
  LEASE_RUN_TRANSFER,
  LEASE_SITE_SCOPE_POLICY,
  LEASE_TTL_MAX_SECONDS,
  LEASE_TTL_SECONDS,
  MAX_ACTION_TEXT_CHARS,
  MAX_SCROLL_DELTA,
  MAX_SELECT_INDEX,
  OUT_OF_SCOPE_ACTIONS,
  OUT_OF_SCOPE_SURFACES,
  PROHIBITED_ACTIONS,
  SLICE1_ORIGIN_SCOPE,
  STEP_UP_REQUIRED_ACTIONS,
  BrowserActionContractError,
  assertBoundedActionLease,
  buildBoundedActionReceipt,
  validateBoundedBrowserAction,
} from '../src/browser/browser-action-contract.js';

const BASE = {
  browserSessionRef: 'run/session-1',
  originRef: 'https://example.com',
};

function rawRequest(overrides: Record<string, unknown>): Record<string, unknown> {
  return { ...BASE, ...overrides };
}

function validLease(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    leaseId: 'lease/session-1',
    requestFingerprint: 'fingerprint/session-1',
    browserSessionRef: 'run/session-1',
    runRef: 'run_3647',
    workspaceRef: 'workspace_3647',
    ownerRef: 'owner_3647',
    allowedActionClasses: ['click', 'type', 'scroll', 'focus', 'select'],
    originScope: 'https://example.com',
    maxActions: LEASE_MAX_ACTIONS,
    issuedAtIso: '2026-10-08T09:00:00.000Z',
    expiresAtIso: '2026-10-08T09:05:00.000Z',
    approvalRef: 'decision_3647',
    evidenceRef: 'evidence_3647',
    ...overrides,
  };
}

test('authoritative #3607 lease values are declared exactly', () => {
  assert.equal(LEASE_TTL_SECONDS, 300);
  assert.equal(LEASE_TTL_MAX_SECONDS, 900);
  assert.equal(LEASE_MAX_ACTIONS, 25);
  assert.equal(LEASE_MAX_ACTIONS_HARD_CAP, 100);
  assert.equal(LEASE_IDLE_SECONDS, 120);
  assert.equal(LEASE_SITE_SCOPE_POLICY, 'EXACT_ORIGIN_MAX_3_NO_WILDCARD');
  assert.equal(SLICE1_ORIGIN_SCOPE, 'EXACT_ONE_ORIGIN');
  assert.equal(LEASE_CROSS_ORIGIN_POLICY, 'INVALIDATE_AND_REQUIRE_STEP_UP');
  assert.equal(LEASE_RUN_TRANSFER, 'PROHIBITED');
  assert.equal(LEASE_REVOCATION, 'IMMEDIATE_USER_VISIBLE');
  assert.equal(DOWNLOAD_EXECUTION_BLOCKED_UNTIL_ARTIFACT_AUTHORITY, true);
});

test('slice 1 implements exactly the lease-eligible verbs', () => {
  assert.deepEqual(LEASE_ELIGIBLE_ACTIONS, ['scroll', 'focus', 'click', 'type', 'select']);
});

test('step-up classes match the #3607 effect classes', () => {
  assert.deepEqual(STEP_UP_REQUIRED_ACTIONS, [
    'submit',
    'credential_field_interaction',
    'upload',
    'download',
    'clipboard_read',
    'clipboard_write',
    'cross_origin_navigation',
  ]);
  for (const action of STEP_UP_REQUIRED_ACTIONS) {
    assert.throws(
      () => validateBoundedBrowserAction(rawRequest({ action })),
      (error: unknown) =>
        error instanceof BrowserActionContractError && error.code === 'step_up_required',
      `step-up action ${action} must refuse`,
    );
  }
});

test('prohibited classes are never step-up able', () => {
  assert.deepEqual(PROHIBITED_ACTIONS, [
    'javascript_evaluate',
    'payment_or_purchase',
    'account_or_security_change',
    'destructive_action',
    'permission_prompt',
  ]);
  for (const action of PROHIBITED_ACTIONS) {
    assert.throws(
      () => validateBoundedBrowserAction(rawRequest({ action })),
      (error: unknown) =>
        error instanceof BrowserActionContractError && error.code === 'action_prohibited',
      `prohibited action ${action} must refuse`,
    );
    assert.ok(!(LEASE_ELIGIBLE_ACTIONS as readonly string[]).includes(action));
    assert.ok(!(STEP_UP_REQUIRED_ACTIONS as readonly string[]).includes(action));
  }
});

test('out-of-scope surfaces refuse with out_of_scope', () => {
  assert.deepEqual(OUT_OF_SCOPE_ACTIONS, ['external_protocol_launch']);
  assert.deepEqual(OUT_OF_SCOPE_SURFACES, [
    'os_computer_use',
    'generic_cdp_devtools_surface',
    'file_navigation',
  ]);
  assert.throws(
    () => validateBoundedBrowserAction(rawRequest({ action: 'external_protocol_launch' })),
    (error: unknown) =>
      error instanceof BrowserActionContractError && error.code === 'out_of_scope',
  );
});

test('unknown actions refuse rather than guess', () => {
  assert.throws(
    () => validateBoundedBrowserAction(rawRequest({ action: 'format_the_disk' })),
    (error: unknown) =>
      error instanceof BrowserActionContractError && error.code === 'unknown_action',
  );
});

test('click and focus validate into the exact bounded shape', () => {
  for (const action of ['click', 'focus'] as const) {
    const request = validateBoundedBrowserAction(rawRequest({ action, elementRef: 'el-0002' }));
    assert.deepEqual(request, {
      action,
      browserSessionRef: 'run/session-1',
      originRef: 'https://example.com',
      elementRef: 'el-0002',
    });
    assert.throws(
      () => validateBoundedBrowserAction(rawRequest({ action, elementRef: 'el-0002', force: true })),
      (error: unknown) =>
        error instanceof BrowserActionContractError && error.code === 'contract_violation',
    );
  }
});

test('scroll takes bounded deltas and refuses an element target', () => {
  const request = validateBoundedBrowserAction(
    rawRequest({ action: 'scroll', dx: 0, dy: -MAX_SCROLL_DELTA }),
  );
  assert.deepEqual(request, {
    action: 'scroll',
    browserSessionRef: 'run/session-1',
    originRef: 'https://example.com',
    dx: 0,
    dy: -MAX_SCROLL_DELTA,
  });
  assert.throws(
    () => validateBoundedBrowserAction(rawRequest({ action: 'scroll', dx: MAX_SCROLL_DELTA + 1, dy: 0 })),
    (error: unknown) => error instanceof BrowserActionContractError,
  );
  assert.throws(
    () => validateBoundedBrowserAction(rawRequest({ action: 'scroll', elementRef: 'el-0001', dx: 0, dy: 1 })),
    (error: unknown) =>
      error instanceof BrowserActionContractError && error.code === 'contract_violation',
  );
  assert.throws(
    () => validateBoundedBrowserAction(rawRequest({ action: 'scroll', dx: 1 })),
    (error: unknown) => error instanceof BrowserActionContractError,
  );
});

test('type text is single-line, control-character-free and bounded', () => {
  const request = validateBoundedBrowserAction(
    rawRequest({ action: 'type', elementRef: 'el-0003', text: '안녕하세요' }),
  );
  assert.ok(request.action === 'type' && request.text === '안녕하세요');
  for (const text of ['line1\nline2', 'line1\rline2', 'tab\there', 'null\u0000byte', '']) {
    assert.throws(
      () => validateBoundedBrowserAction(rawRequest({ action: 'type', elementRef: 'el-0003', text })),
      (error: unknown) =>
        error instanceof BrowserActionContractError && error.code === 'contract_violation',
      `type text ${JSON.stringify(text)} must refuse`,
    );
  }
  assert.throws(
    () =>
      validateBoundedBrowserAction(
        rawRequest({ action: 'type', elementRef: 'el-0003', text: 'x'.repeat(MAX_ACTION_TEXT_CHARS + 1) }),
      ),
    (error: unknown) => error instanceof BrowserActionContractError,
  );
});

test('select takes a bounded option index and nothing else', () => {
  const request = validateBoundedBrowserAction(
    rawRequest({ action: 'select', elementRef: 'el-0005', optionIndex: MAX_SELECT_INDEX }),
  );
  assert.ok(request.action === 'select' && request.optionIndex === MAX_SELECT_INDEX);
  assert.throws(
    () =>
      validateBoundedBrowserAction(
        rawRequest({ action: 'select', elementRef: 'el-0005', optionIndex: MAX_SELECT_INDEX + 1 }),
      ),
    (error: unknown) => error instanceof BrowserActionContractError,
  );
  assert.throws(
    () =>
      validateBoundedBrowserAction(
        rawRequest({ action: 'select', elementRef: 'el-0005', optionIndex: 1, text: 'x' }),
      ),
    (error: unknown) => error instanceof BrowserActionContractError,
  );
});

test('action leases carry the full #3607 correlation set', () => {
  const lease = assertBoundedActionLease(validLease());
  assert.equal(lease.requestFingerprint, 'fingerprint/session-1');
  assert.equal(lease.browserSessionRef, 'run/session-1');
  assert.equal(lease.runRef, 'run_3647');
  assert.equal(lease.workspaceRef, 'workspace_3647');
  assert.equal(lease.ownerRef, 'owner_3647');
  assert.equal(lease.approvalRef, 'decision_3647');
  assert.equal(lease.evidenceRef, 'evidence_3647');
  assert.equal(lease.originScope, 'https://example.com');
  assert.deepEqual(lease.allowedActionClasses, ['click', 'focus', 'scroll', 'select', 'type']);
});

test('lease mutations refuse with lease_invalid', () => {
  const mutations: Array<Record<string, unknown>> = [
    { allowedActionClasses: [] },
    { allowedActionClasses: ['submit'] },
    { maxActions: LEASE_MAX_ACTIONS_HARD_CAP + 1 },
    { maxActions: 0 },
    { expiresAtIso: 'not-an-instant' },
    { expiresAtIso: '2026-10-08T10:00:00.000Z' },
    { originScope: 'https://example.com/path?token=secret' },
    { requestFingerprint: '' },
    { approvalRef: '' },
    { unexpected: true },
  ];
  for (const mutation of mutations) {
    assert.throws(
      () => assertBoundedActionLease(validLease(mutation)),
      (error: unknown) =>
        error instanceof BrowserActionContractError && error.code === 'lease_invalid',
      `lease mutation ${JSON.stringify(mutation)} must refuse`,
    );
  }
});

test('action receipts pin zero page-derived bytes', () => {
  const receipt = buildBoundedActionReceipt({
    actionId: 'act_' + 'a'.repeat(24),
    action: 'click',
    elementRef: 'el-0002',
    originRef: 'https://example.com',
  });
  assert.equal(receipt.outcome, 'dispatched');
  assert.equal(receipt.pageContentIncluded, false);
  assert.equal(receipt.cookieIncluded, false);
  assert.equal(receipt.credentialValueIncluded, false);
  assert.equal(receipt.domApiExposed, false);
  assert.throws(
    () =>
      buildBoundedActionReceipt({
        actionId: 'renderer-minted',
        action: 'click',
        elementRef: null,
        originRef: 'https://example.com',
      }),
    (error: unknown) =>
      error instanceof BrowserActionContractError && error.code === 'contract_violation',
  );
});
