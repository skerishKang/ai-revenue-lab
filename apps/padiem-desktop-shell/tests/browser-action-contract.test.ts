/**
 * #3647 — bounded action contract tests, slice 1.
 *
 * Hermetic. The taxonomy boundary (lease-eligible vs step-up vs prohibited)
 * and every parameter bound are exercised at the exact-key level so a future
 * edit that widens the action surface fails here rather than in review.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  BROWSER_ACTION_LEASE_MAX_TTL_SECONDS,
  BROWSER_ACTION_LEASE_MIN_TTL_SECONDS,
  LEASE_ELIGIBLE_ACTIONS,
  MAX_ACTIONS_PER_LEASE,
  MAX_ACTION_TEXT_CHARS,
  MAX_SCROLL_DELTA,
  MAX_SELECT_INDEX,
  PROHIBITED_ACTIONS,
  STEP_UP_REQUIRED_ACTIONS,
  BrowserActionContractError,
  assertBoundedActionLease,
  buildBoundedActionReceipt,
  validateBoundedBrowserAction,
} from '../src/browser/browser-action-contract.js';

const BASE = {
  sessionRef: 'run/session-1',
  originRef: 'https://example.com',
};

function rawRequest(overrides: Record<string, unknown>): Record<string, unknown> {
  return { ...BASE, ...overrides };
}

test('slice 1 implements exactly the lease-eligible set', () => {
  assert.deepEqual(LEASE_ELIGIBLE_ACTIONS, ['scroll', 'focus', 'click', 'type', 'select']);
});

test('click and focus validate into the exact bounded shape', () => {
  for (const action of ['click', 'focus'] as const) {
    const request = validateBoundedBrowserAction(rawRequest({ action, elementRef: 'el-0002' }));
    assert.deepEqual(request, {
      action,
      sessionRef: 'run/session-1',
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
  const request = validateBoundedBrowserAction(rawRequest({ action: 'scroll', dx: 0, dy: -MAX_SCROLL_DELTA }));
  assert.deepEqual(request, {
    action: 'scroll',
    sessionRef: 'run/session-1',
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
  const request = validateBoundedBrowserAction(rawRequest({ action: 'type', elementRef: 'el-0003', text: '안녕하세요' }));
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

test('every step-up class refuses with its stable code', () => {
  for (const action of STEP_UP_REQUIRED_ACTIONS) {
    assert.throws(
      () => validateBoundedBrowserAction(rawRequest({ action })),
      (error: unknown) =>
        error instanceof BrowserActionContractError && error.code === 'step_up_required',
      `step-up action ${action} must refuse`,
    );
  }
});

test('prohibited actions refuse with action_prohibited and are never lease-eligible', () => {
  assert.deepEqual(PROHIBITED_ACTIONS, ['javascript_evaluate', 'observe_dom_read']);
  for (const action of PROHIBITED_ACTIONS) {
    assert.throws(
      () => validateBoundedBrowserAction(rawRequest({ action })),
      (error: unknown) =>
        error instanceof BrowserActionContractError && error.code === 'action_prohibited',
      `prohibited action ${action} must refuse`,
    );
    assert.ok(!(LEASE_ELIGIBLE_ACTIONS as readonly string[]).includes(action));
  }
});

test('unknown actions refuse rather than guess', () => {
  assert.throws(
    () => validateBoundedBrowserAction(rawRequest({ action: 'format_the_disk' })),
    (error: unknown) =>
      error instanceof BrowserActionContractError && error.code === 'unknown_action',
  );
});

test('action leases validate the #3607 shape exactly', () => {
  const lease = assertBoundedActionLease({
    leaseId: 'lease/session-1',
    sessionRef: 'run/session-1',
    originRef: 'https://example.com',
    allowedActions: ['type', 'click'],
    maxActions: 8,
    issuedAtIso: '2026-10-08T09:00:00.000Z',
    expiresAtIso: '2026-10-08T09:05:00.000Z',
  });
  assert.deepEqual(lease.allowedActions, ['click', 'type']);
  const mutations: Array<Record<string, unknown>> = [
    { allowedActions: [] },
    { allowedActions: ['submit'] },
    { maxActions: MAX_ACTIONS_PER_LEASE + 1 },
    { maxActions: 0 },
    { expiresAtIso: '2026-10-08T09:00:30.000Z' },
    { expiresAtIso: '2026-10-08T10:00:00.000Z' },
    { originRef: 'https://example.com/path?token=secret' },
    { unexpected: true },
  ];
  for (const mutation of mutations) {
    assert.throws(
      () =>
        assertBoundedActionLease({
          leaseId: 'lease/session-1',
          sessionRef: 'run/session-1',
          originRef: 'https://example.com',
          allowedActions: ['click'],
          maxActions: 1,
          issuedAtIso: '2026-10-08T09:00:00.000Z',
          expiresAtIso: '2026-10-08T09:05:00.000Z',
          ...mutation,
        }),
      (error: unknown) =>
        error instanceof BrowserActionContractError && error.code === 'lease_invalid',
      `lease mutation ${JSON.stringify(mutation)} must refuse`,
    );
  }
  assert.ok(
    BROWSER_ACTION_LEASE_MIN_TTL_SECONDS === 60 && BROWSER_ACTION_LEASE_MAX_TTL_SECONDS === 900,
  );
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
    () => buildBoundedActionReceipt({
      actionId: 'renderer-minted',
      action: 'click',
      elementRef: null,
      originRef: 'https://example.com',
    }),
    (error: unknown) =>
      error instanceof BrowserActionContractError && error.code === 'contract_violation',
  );
});
