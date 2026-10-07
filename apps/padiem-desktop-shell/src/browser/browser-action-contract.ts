/**
 * #3647 — bounded browser.control action contract, slice 1.
 *
 * Slice 1 implements exactly the #3607 lease-eligible classes:
 *
 *   scroll / focus / click / type / select
 *
 * Everything else in the #3607 taxonomy is step-up refused here, and the
 * prohibited classes (javascript_evaluate, raw DOM read) are structurally
 * absent. Every action is bound to an element of a fresh #3629 observation:
 * element_ref must resolve against the current projection, and the credential
 * marker plus interaction roles come from the same bounded authority.
 *
 * Because a bounded observation cannot distinguish a submit button from a
 * safe one (arbitrary attributes are banned from the projection), button-role
 * click/focus targets default to step-up refusal; click stays limited to the
 * non-committing interactive roles. Typing is single-line non-credential text
 * delivered by input synthesis — the text is agent-provided material, never
 * page-derived, and control characters (CR/LF would submit forms) are refused.
 *
 * Exact-key validation everywhere: a request whose key set is not the declared
 * one is refused, never silently narrowed.
 */

export const BROWSER_ACTION_HOST_REF = 'desktop-trusted-main-action@1';
export const MAX_ACTION_TEXT_CHARS = 256;
export const MAX_SCROLL_DELTA = 10_000;
export const MAX_SELECT_INDEX = 1023;
export const MAX_SERIALIZED_ACTION_BYTES = 2048;
export const MAX_ACTIONS_PER_LEASE = 64;
export const BROWSER_ACTION_LEASE_MIN_TTL_SECONDS = 60;
export const BROWSER_ACTION_LEASE_MAX_TTL_SECONDS = 900;

/** The #3607 lease-eligible slice-1 set. */
export const LEASE_ELIGIBLE_ACTIONS = Object.freeze([
  'scroll',
  'focus',
  'click',
  'type',
  'select',
] as const);

/** #3607 step-up classes: refused by construction in this slice. */
export const STEP_UP_REQUIRED_ACTIONS = Object.freeze([
  'submit',
  'download',
  'upload',
  'clipboard_read',
  'clipboard_write',
  'open_new_tab',
  'close_tab',
  'cross_origin_navigation',
  'credential_field_interaction',
  'payment_or_purchase',
  'account_or_security_change',
  'permission_prompt',
  'external_protocol_launch',
  'destructive_action',
] as const);

/** Prohibited classes: no code path may ever carry them. */
export const PROHIBITED_ACTIONS = Object.freeze([
  'javascript_evaluate',
  'observe_dom_read',
] as const);

/** Non-committing interactive roles a bounded click/focus may target. */
export const CLICKABLE_ROLE_ALLOWLIST = Object.freeze([
  'link',
  'tab',
  'menuitem',
  'treeitem',
  'checkbox',
  'radio',
  'switch',
  'option',
] as const);

export const TYPEABLE_ROLE_ALLOWLIST = Object.freeze([
  'textbox',
  'textarea',
  'searchbox',
  'combobox',
  'spinbutton',
] as const);

export const SELECT_ROLE_ALLOWLIST = Object.freeze(['listbox', 'combobox'] as const);

export type LeaseEligibleAction = (typeof LEASE_ELIGIBLE_ACTIONS)[number];

export type BrowserActionErrorCode =
  | 'contract_violation'
  | 'unknown_action'
  | 'step_up_required'
  | 'action_prohibited'
  | 'host_unavailable'
  | 'extraction_failed'
  | 'element_not_observed'
  | 'credential_element_forbidden'
  | 'origin_scope_exceeded'
  | 'lease_invalid'
  | 'action_budget_exhausted';

export class BrowserActionContractError extends Error {
  readonly code: BrowserActionErrorCode;

  constructor(code: BrowserActionErrorCode, message: string) {
    super(message);
    this.name = 'BrowserActionContractError';
    this.code = code;
  }
}

const ACTION_ID_PATTERN = /^act_[0-9a-f]{24}$/;
const ELEMENT_REF_PATTERN = /^el-\d{4}$/;

export function assertBoundedElementRef(value: unknown): string {
  if (typeof value !== 'string' || !ELEMENT_REF_PATTERN.test(value)) {
    throw new BrowserActionContractError('contract_violation', 'element_ref must be a bounded el-NNNN reference');
  }
  return value;
}

export function assertActionId(value: unknown): string {
  if (typeof value !== 'string' || !ACTION_ID_PATTERN.test(value)) {
    throw new BrowserActionContractError('contract_violation', 'action_id must be act_ plus 24 lowercase hex characters');
  }
  return value;
}

export interface ScrollParams {
  readonly dx: number;
  readonly dy: number;
}

export interface TypeParams {
  readonly text: string;
}

export interface SelectParams {
  readonly optionIndex: number;
}

export type BoundedBrowserActionRequest =
  | { readonly action: 'scroll'; readonly sessionRef: string; readonly originRef: string; readonly dx: number; readonly dy: number }
  | { readonly action: 'focus' | 'click'; readonly sessionRef: string; readonly originRef: string; readonly elementRef: string }
  | { readonly action: 'type'; readonly sessionRef: string; readonly originRef: string; readonly elementRef: string; readonly text: string }
  | { readonly action: 'select'; readonly sessionRef: string; readonly originRef: string; readonly elementRef: string; readonly optionIndex: number };

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function refuse(code: BrowserActionErrorCode, message: string): never {
  throw new BrowserActionContractError(code, message);
}

function boundedInt(value: unknown, limit: number, field: string): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || Math.abs(value) > limit) {
    refuse('contract_violation', `${field} must be a bounded integer (|v| <= ${limit})`);
  }
  return value;
}

/**
 * Validate one raw action request into the exact bounded shape. The step-up
 * and prohibited classes are refused with their stable codes; unknown actions
 * are refused rather than guessed.
 */
export function validateBoundedBrowserAction(raw: unknown): BoundedBrowserActionRequest {
  if (!isPlainObject(raw)) refuse('contract_violation', 'action request must be an object');
  const action = raw.action;
  if (typeof action !== 'string') refuse('contract_violation', 'action must be a string');
  if ((PROHIBITED_ACTIONS as readonly string[]).includes(action)) {
    refuse('action_prohibited', `action ${action} is prohibited on this surface`);
  }
  if ((STEP_UP_REQUIRED_ACTIONS as readonly string[]).includes(action)) {
    refuse('step_up_required', `action ${action} requires a separate step-up approval`);
  }
  if (!(LEASE_ELIGIBLE_ACTIONS as readonly string[]).includes(action)) {
    refuse('unknown_action', `unknown browser control action ${action}`);
  }
  const sessionRef = raw.sessionRef;
  if (typeof sessionRef !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$/.test(sessionRef.trim())) {
    refuse('contract_violation', 'sessionRef must be a bounded safe reference');
  }
  const originRef = raw.originRef;
  if (
    typeof originRef !== 'string' ||
    originRef.length > 255 ||
    !/^https:\/\/[a-z0-9.-]+(?::\d{1,5})?$|^http:\/\/[a-z0-9.-]+(?::\d{1,5})?$/.test(originRef.trim().toLowerCase())
  ) {
    refuse('contract_violation', 'originRef must be a bounded bare http(s) origin');
  }
  const unknownKeys = Object.keys(raw).filter(
    (key) => !['action', 'sessionRef', 'originRef', 'elementRef', 'dx', 'dy', 'text', 'optionIndex'].includes(key),
  );
  if (unknownKeys.length > 0) {
    refuse('contract_violation', `action request carries unknown keys: ${unknownKeys.sort().join(',')}`);
  }
  if (action === 'scroll') {
    if ('elementRef' in raw) refuse('contract_violation', 'scroll targets the viewport and must not carry an elementRef');
    if (!('dx' in raw) || !('dy' in raw)) {
      refuse('contract_violation', 'scroll must carry exactly dx and dy');
    }
    return {
      action: 'scroll',
      sessionRef: sessionRef.trim(),
      originRef: originRef.trim().toLowerCase(),
      dx: boundedInt(raw.dx, MAX_SCROLL_DELTA, 'dx'),
      dy: boundedInt(raw.dy, MAX_SCROLL_DELTA, 'dy'),
    };
  }
  const elementRef = assertBoundedElementRef(raw.elementRef);
  if (action === 'focus' || action === 'click') {
    if ('dx' in raw || 'dy' in raw || 'text' in raw || 'optionIndex' in raw) {
      refuse('contract_violation', `${action} carries no params`);
    }
    return { action, sessionRef: sessionRef.trim(), originRef: originRef.trim().toLowerCase(), elementRef };
  }
  if (action === 'type') {
    if ('dx' in raw || 'dy' in raw || 'optionIndex' in raw) {
      refuse('contract_violation', 'type carries only text');
    }
    const text = raw.text;
    if (typeof text !== 'string' || text.length < 1 || text.length > MAX_ACTION_TEXT_CHARS) {
      refuse('contract_violation', `type text must be 1..${MAX_ACTION_TEXT_CHARS} characters`);
    }
    for (const ch of text) {
      const code = ch.codePointAt(0) ?? 0;
      if (code < 32 || code === 127) {
        // CR/LF would submit forms; other control bytes have no place in
        // non-sensitive typing. Input synthesis never needs them.
        refuse('contract_violation', 'type text must not contain control characters');
      }
    }
    return { action, sessionRef: sessionRef.trim(), originRef: originRef.trim().toLowerCase(), elementRef, text };
  }
  if ('dx' in raw || 'dy' in raw || 'text' in raw) {
    refuse('contract_violation', 'select carries only optionIndex');
  }
  return {
    action: 'select',
    sessionRef: sessionRef.trim(),
    originRef: originRef.trim().toLowerCase(),
    elementRef,
    optionIndex: boundedInt(raw.optionIndex, MAX_SELECT_INDEX, 'optionIndex'),
  };
}

/** The #3607 bounded lease shape for slice 1, as the trusted host sees it. */
export interface BoundedActionLease {
  readonly leaseId: string;
  readonly sessionRef: string;
  readonly originRef: string;
  readonly allowedActions: readonly LeaseEligibleAction[];
  readonly maxActions: number;
  readonly issuedAtIso: string;
  readonly expiresAtIso: string;
}

const SAFE_REF = /^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$/;

export function assertBoundedActionLease(value: unknown): BoundedActionLease {
  if (!isPlainObject(value)) refuse('lease_invalid', 'action lease must be an object');
  const keys = Object.keys(value).sort();
  if (keys.join(',') !== 'allowedActions,expiresAtIso,issuedAtIso,leaseId,maxActions,originRef,sessionRef') {
    refuse('lease_invalid', 'action lease carries an unexpected key set');
  }
  const leaseId = value.leaseId;
  if (typeof leaseId !== 'string' || !SAFE_REF.test(leaseId.trim())) {
    refuse('lease_invalid', 'leaseId must be a bounded safe reference');
  }
  const sessionRef = value.sessionRef;
  if (typeof sessionRef !== 'string' || !SAFE_REF.test(sessionRef.trim())) {
    refuse('lease_invalid', 'sessionRef must be a bounded safe reference');
  }
  const originRef = value.originRef;
  if (
    typeof originRef !== 'string' ||
    originRef.length > 255 ||
    !/^https:\/\/[a-z0-9.-]+(?::\d{1,5})?$|^http:\/\/[a-z0-9.-]+(?::\d{1,5})?$/.test(originRef.trim().toLowerCase())
  ) {
    refuse('lease_invalid', 'lease originRef must be a bounded bare http(s) origin');
  }
  const allowed = value.allowedActions;
  if (!Array.isArray(allowed) || allowed.length < 1) {
    refuse('lease_invalid', 'lease must allow at least one bounded action');
  }
  for (const entry of allowed) {
    if (!(LEASE_ELIGIBLE_ACTIONS as readonly string[]).includes(entry as string)) {
      refuse('lease_invalid', 'lease allowedActions must be lease-eligible only');
    }
  }
  const maxActions = value.maxActions;
  if (typeof maxActions !== 'number' || !Number.isInteger(maxActions) || maxActions < 1 || maxActions > MAX_ACTIONS_PER_LEASE) {
    refuse('lease_invalid', `lease maxActions must be 1..${MAX_ACTIONS_PER_LEASE}`);
  }
  const issuedAtIso = value.issuedAtIso;
  const expiresAtIso = value.expiresAtIso;
  if (typeof issuedAtIso !== 'string' || typeof expiresAtIso !== 'string' || !Number.isFinite(Date.parse(issuedAtIso)) || !Number.isFinite(Date.parse(expiresAtIso))) {
    refuse('lease_invalid', 'lease lifetime must be ISO instants');
  }
  const lifetime = (Date.parse(expiresAtIso) - Date.parse(issuedAtIso)) / 1000;
  if (
    lifetime < BROWSER_ACTION_LEASE_MIN_TTL_SECONDS ||
    lifetime > BROWSER_ACTION_LEASE_MAX_TTL_SECONDS
  ) {
    refuse(
      'lease_invalid',
      `lease lifetime must be ${BROWSER_ACTION_LEASE_MIN_TTL_SECONDS}..${BROWSER_ACTION_LEASE_MAX_TTL_SECONDS} seconds`,
    );
  }
  return {
    leaseId: leaseId.trim(),
    sessionRef: sessionRef.trim(),
    originRef: originRef.trim().toLowerCase(),
    allowedActions: [...new Set(allowed as LeaseEligibleAction[])].sort(),
    maxActions,
    issuedAtIso,
    expiresAtIso,
  };
}

export interface BoundedActionReceipt {
  readonly actionId: string;
  readonly action: LeaseEligibleAction;
  readonly elementRef: string | null;
  readonly originRef: string;
  readonly outcome: 'dispatched';
  readonly pageContentIncluded: false;
  readonly cookieIncluded: false;
  readonly credentialValueIncluded: false;
  readonly domApiExposed: false;
}

export const BOUNDED_ACTION_RECEIPT_FIELDS = Object.freeze([
  'actionId',
  'action',
  'elementRef',
  'originRef',
  'outcome',
  'pageContentIncluded',
  'cookieIncluded',
  'credentialValueIncluded',
  'domApiExposed',
] as const);

export function buildBoundedActionReceipt(input: {
  readonly actionId: string;
  readonly action: LeaseEligibleAction;
  readonly elementRef: string | null;
  readonly originRef: string;
}): BoundedActionReceipt {
  assertActionId(input.actionId);
  return Object.freeze({
    actionId: input.actionId,
    action: input.action,
    elementRef: input.elementRef,
    originRef: input.originRef,
    outcome: 'dispatched',
    pageContentIncluded: false,
    cookieIncluded: false,
    credentialValueIncluded: false,
    domApiExposed: false,
  });
}
