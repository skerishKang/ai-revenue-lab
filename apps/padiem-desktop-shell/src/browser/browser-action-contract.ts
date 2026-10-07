/**
 * #3647 — bounded browser.control action contract, slice 1.
 *
 * Source of truth: the #3607 CENTRAL final design disposition
 * (BOUNDED_HYBRID_LEASE_PLUS_STEP_UP), applied to the #3629 observation
 * authority under the #3609 D1=ENABLED_BOUNDED decision.
 *
 * Lease policy (authoritative values, not redefined here):
 *
 *   LEASE_TTL_SECONDS           = 300   (canonical issuance default)
 *   LEASE_TTL_MAX_SECONDS       = 900   (hard max)
 *   LEASE_MAX_ACTIONS           = 25    (canonical issuance default)
 *   LEASE_MAX_ACTIONS_HARD_CAP  = 100
 *   LEASE_IDLE_SECONDS          = 120
 *   LEASE_SITE_SCOPE            = EXACT_ORIGIN_MAX_3_NO_WILDCARD
 *   LEASE_CROSS_ORIGIN_POLICY   = INVALIDATE_AND_REQUIRE_STEP_UP
 *   LEASE_RUN_TRANSFER          = PROHIBITED
 *   LEASE_REVOCATION            = IMMEDIATE_USER_VISIBLE
 *
 * Slice 1 is deliberately stricter on site scope:
 *
 *   SLICE1_ORIGIN_SCOPE = EXACT_ONE_ORIGIN
 *
 * Action taxonomy (#3607 effect-class first, verb second):
 *
 *   LEASE_ALLOWED      bounded non-committing interaction only — and a role is
 *                      lease-allowed ONLY where the #3629 projection can prove
 *                      it (see CLICK_ALLOWED_ROLE_ALLOWLIST; a verb being
 *                      "click" does not make it safe);
 *   STEP_UP_REQUIRED   submit, credential_field_interaction, upload, download
 *                      (download additionally EXECUTION_BLOCKED until the
 *                      artifact/filesystem.write authority exists),
 *                      clipboard_read/write, cross_origin_navigation — every
 *                      action that can create an external/durable effect;
 *   PROHIBITED         javascript_evaluate, payment_or_purchase,
 *                      account_or_security_change, destructive_action,
 *                      permission_prompt;
 *   OUT_OF_SCOPE       external_protocol_launch, OS Computer Use, the generic
 *                      CDP/DevTools surface, file: navigation. (The trusted
 *                      main binding internally uses allowlisted CDP `Input.*`
 *                      commands as input synthesis; no CDP/DevTools surface is
 *                      exposed to renderer or agent.)
 *
 * Every action binds to an element of a FRESH #3629 observation: element_ref,
 * the credential marker and the role all come from the same bounded
 * authority. The projection deliberately carries no href/attributes, so
 * link targets cannot be proven same-origin and step up.
 *
 * Exact-key validation everywhere: a request whose key set is not the declared
 * one is refused, never silently narrowed.
 */

export const BROWSER_ACTION_HOST_REF = 'desktop-trusted-main-action@1';
export const MAX_ACTION_TEXT_CHARS = 256;
export const MAX_SCROLL_DELTA = 10_000;
export const MAX_SELECT_INDEX = 1023;
export const MAX_SERIALIZED_ACTION_BYTES = 2048;

/** #3607 authoritative lease values. */
export const LEASE_TTL_SECONDS = 300;
export const LEASE_TTL_MAX_SECONDS = 900;
export const LEASE_MAX_ACTIONS = 25;
export const LEASE_MAX_ACTIONS_HARD_CAP = 100;
export const LEASE_IDLE_SECONDS = 120;
export const LEASE_SITE_SCOPE_POLICY = 'EXACT_ORIGIN_MAX_3_NO_WILDCARD';
export const LEASE_CROSS_ORIGIN_POLICY = 'INVALIDATE_AND_REQUIRE_STEP_UP';
export const LEASE_RUN_TRANSFER = 'PROHIBITED';
export const LEASE_REVOCATION = 'IMMEDIATE_USER_VISIBLE';
/** Slice-1 tightening, explicitly allowed by CENTRAL review. */
export const SLICE1_ORIGIN_SCOPE = 'EXACT_ONE_ORIGIN';
/** #3607 deliberate deviation: download stays blocked until that authority exists. */
export const DOWNLOAD_EXECUTION_BLOCKED_UNTIL_ARTIFACT_AUTHORITY = true;

/** The #3607 lease-eligible verbs of slice 1. */
export const LEASE_ELIGIBLE_ACTIONS = Object.freeze([
  'scroll',
  'focus',
  'click',
  'type',
  'select',
] as const);

/** #3607 step-up classes: any action that can create an external/durable effect. */
export const STEP_UP_REQUIRED_ACTIONS = Object.freeze([
  'submit',
  'credential_field_interaction',
  'upload',
  'download',
  'clipboard_read',
  'clipboard_write',
  'cross_origin_navigation',
] as const);

/** #3607 prohibited classes: no code path may ever carry them. */
export const PROHIBITED_ACTIONS = Object.freeze([
  'javascript_evaluate',
  'payment_or_purchase',
  'account_or_security_change',
  'destructive_action',
  'permission_prompt',
] as const);

/** #3607 out-of-scope surfaces (never classified, never implemented here). */
export const OUT_OF_SCOPE_ACTIONS = Object.freeze(['external_protocol_launch'] as const);
export const OUT_OF_SCOPE_SURFACES = Object.freeze([
  'os_computer_use',
  'generic_cdp_devtools_surface',
  'file_navigation',
] as const);

/**
 * Roles where the #3629 projection can actually prove non-committing
 * interaction. Everything else — link (href invisible), button (submit
 * indistinguishable), menuitem/checkbox/radio/switch/option (durable or
 * external effect not disprovable) — steps up. Effect class first, verb
 * second; no new observation attribute was invented for this.
 */
export const CLICK_ALLOWED_ROLE_ALLOWLIST = Object.freeze(['tab', 'treeitem'] as const);

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
  | 'out_of_scope'
  | 'host_unavailable'
  | 'extraction_failed'
  | 'element_not_observed'
  | 'element_not_focusable'
  | 'credential_element_forbidden'
  | 'origin_scope_exceeded'
  | 'lease_invalid'
  | 'lease_idle_exceeded'
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
const SAFE_REF_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$/;
const ORIGIN_PATTERN = /^https:\/\/[a-z0-9.-]+(?::\d{1,5})?$|^http:\/\/[a-z0-9.-]+(?::\d{1,5})?$/;

export function assertBoundedElementRef(value: unknown): string {
  if (typeof value !== 'string' || !ELEMENT_REF_PATTERN.test(value)) {
    throw new BrowserActionContractError('contract_violation', 'element_ref must be a bounded el-NNNN reference');
  }
  return value;
}

export function assertBoundedSafeRef(value: unknown, field: string): string {
  if (typeof value !== 'string' || !SAFE_REF_PATTERN.test(value.trim())) {
    throw new BrowserActionContractError('contract_violation', `${field} must be a bounded safe reference`);
  }
  return value.trim();
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

export interface SelectParams {
  readonly optionIndex: number;
}

export type BoundedBrowserActionRequest =
  | { readonly action: 'scroll'; readonly browserSessionRef: string; readonly originRef: string; readonly dx: number; readonly dy: number }
  | { readonly action: 'focus' | 'click'; readonly browserSessionRef: string; readonly originRef: string; readonly elementRef: string }
  | { readonly action: 'type'; readonly browserSessionRef: string; readonly originRef: string; readonly elementRef: string; readonly text: string }
  | { readonly action: 'select'; readonly browserSessionRef: string; readonly originRef: string; readonly elementRef: string; readonly optionIndex: number };

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

function boundedOrigin(value: unknown, field: string): string {
  if (
    typeof value !== 'string' ||
    value.length > 255 ||
    !ORIGIN_PATTERN.test(value.trim().toLowerCase())
  ) {
    refuse('contract_violation', `${field} must be a bounded bare http(s) origin`);
  }
  return value.trim().toLowerCase();
}

/**
 * Validate one raw action request into the exact bounded shape. The step-up,
 * prohibited and out-of-scope classes are refused with their stable codes;
 * unknown actions are refused rather than guessed.
 */
export function validateBoundedBrowserAction(raw: unknown): BoundedBrowserActionRequest {
  if (!isPlainObject(raw)) refuse('contract_violation', 'action request must be an object');
  const action = raw.action;
  if (typeof action !== 'string') refuse('contract_violation', 'action must be a string');
  if ((PROHIBITED_ACTIONS as readonly string[]).includes(action)) {
    refuse('action_prohibited', `action ${action} is prohibited on this surface`);
  }
  if ((OUT_OF_SCOPE_ACTIONS as readonly string[]).includes(action)) {
    refuse('out_of_scope', `action ${action} is out of scope for browser.control`);
  }
  if ((STEP_UP_REQUIRED_ACTIONS as readonly string[]).includes(action)) {
    refuse('step_up_required', `action ${action} requires a separate step-up approval`);
  }
  if (!(LEASE_ELIGIBLE_ACTIONS as readonly string[]).includes(action)) {
    refuse('unknown_action', `unknown browser control action ${action}`);
  }
  const browserSessionRef = assertBoundedSafeRef(raw.browserSessionRef, 'browserSessionRef');
  const originRef = boundedOrigin(raw.originRef, 'originRef');
  const unknownKeys = Object.keys(raw).filter(
    (key) =>
      !['action', 'browserSessionRef', 'originRef', 'elementRef', 'dx', 'dy', 'text', 'optionIndex'].includes(key),
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
      browserSessionRef,
      originRef,
      dx: boundedInt(raw.dx, MAX_SCROLL_DELTA, 'dx'),
      dy: boundedInt(raw.dy, MAX_SCROLL_DELTA, 'dy'),
    };
  }
  const elementRef = assertBoundedElementRef(raw.elementRef);
  if (action === 'focus' || action === 'click') {
    if ('dx' in raw || 'dy' in raw || 'text' in raw || 'optionIndex' in raw) {
      refuse('contract_violation', `${action} carries no params`);
    }
    return { action, browserSessionRef, originRef, elementRef };
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
    return { action, browserSessionRef, originRef, elementRef, text };
  }
  if ('dx' in raw || 'dy' in raw || 'text' in raw) {
    refuse('contract_violation', 'select carries only optionIndex');
  }
  return {
    action: 'select',
    browserSessionRef,
    originRef,
    elementRef,
    optionIndex: boundedInt(raw.optionIndex, MAX_SELECT_INDEX, 'optionIndex'),
  };
}

/**
 * The #3607 bounded lease shape as the trusted host sees it, with the full
 * correlation set: request fingerprint, browser session, owner/workspace/run,
 * exact action classes, exact origin scope, bounded action count, expiry and
 * the P01 approval/evidence references. The canonical durable admission that
 * mints it is NOT wired in this slice — the provider port is fail-closed and
 * the next slice connects it; nothing here mints, refreshes or stores leases.
 */
export interface BoundedActionLease {
  readonly leaseId: string;
  readonly requestFingerprint: string;
  readonly browserSessionRef: string;
  readonly runRef: string;
  readonly workspaceRef: string;
  readonly ownerRef: string;
  readonly allowedActionClasses: readonly LeaseEligibleAction[];
  readonly originScope: string;
  readonly maxActions: number;
  readonly issuedAtIso: string;
  readonly expiresAtIso: string;
  readonly approvalRef: string;
  readonly evidenceRef: string;
}

const BOUNDED_ACTION_LEASE_KEYS = Object.freeze([
  'allowedActionClasses',
  'approvalRef',
  'evidenceRef',
  'expiresAtIso',
  'issuedAtIso',
  'leaseId',
  'maxActions',
  'originScope',
  'ownerRef',
  'requestFingerprint',
  'browserSessionRef',
  'runRef',
  'workspaceRef',
] as const);

export function assertBoundedActionLease(value: unknown): BoundedActionLease {
  try {
    return assertBoundedActionLeaseInner(value);
  } catch (error) {
    // Every lease-shape refusal is a lease refusal: normalize the bounded
    // field-helper codes so callers see one stable code.
    if (error instanceof BrowserActionContractError && error.code === 'contract_violation') {
      throw new BrowserActionContractError('lease_invalid', error.message);
    }
    throw error;
  }
}

function assertBoundedActionLeaseInner(value: unknown): BoundedActionLease {
  if (!isPlainObject(value)) refuse('lease_invalid', 'action lease must be an object');
  const keys = Object.keys(value).sort();
  const expected = [...BOUNDED_ACTION_LEASE_KEYS].sort();
  if (keys.join(',') !== expected.join(',')) {
    refuse('lease_invalid', 'action lease carries an unexpected key set');
  }
  const leaseId = assertBoundedSafeRef(value.leaseId, 'leaseId');
  const requestFingerprint = assertBoundedSafeRef(value.requestFingerprint, 'requestFingerprint');
  const browserSessionRef = assertBoundedSafeRef(value.browserSessionRef, 'browserSessionRef');
  const runRef = assertBoundedSafeRef(value.runRef, 'runRef');
  const workspaceRef = assertBoundedSafeRef(value.workspaceRef, 'workspaceRef');
  const ownerRef = assertBoundedSafeRef(value.ownerRef, 'ownerRef');
  const approvalRef = assertBoundedSafeRef(value.approvalRef, 'approvalRef');
  const evidenceRef = assertBoundedSafeRef(value.evidenceRef, 'evidenceRef');
  // Slice 1: exactly one exact origin. The general #3607 policy allows up to
  // three exact origins without wildcards; this slice never exercises that.
  const originScope = boundedOrigin(value.originScope, 'originScope');
  const allowed = value.allowedActionClasses;
  if (!Array.isArray(allowed) || allowed.length < 1) {
    refuse('lease_invalid', 'lease must allow at least one bounded action class');
  }
  for (const entry of allowed) {
    if (!(LEASE_ELIGIBLE_ACTIONS as readonly string[]).includes(entry as string)) {
      refuse('lease_invalid', 'lease allowedActionClasses must be lease-eligible only');
    }
  }
  const maxActions = value.maxActions;
  if (
    typeof maxActions !== 'number' ||
    !Number.isInteger(maxActions) ||
    maxActions < 1 ||
    maxActions > LEASE_MAX_ACTIONS_HARD_CAP
  ) {
    refuse('lease_invalid', `lease maxActions must be 1..${LEASE_MAX_ACTIONS_HARD_CAP}`);
  }
  const issuedAtIso = value.issuedAtIso;
  const expiresAtIso = value.expiresAtIso;
  if (
    typeof issuedAtIso !== 'string' ||
    typeof expiresAtIso !== 'string' ||
    !Number.isFinite(Date.parse(issuedAtIso)) ||
    !Number.isFinite(Date.parse(expiresAtIso))
  ) {
    refuse('lease_invalid', 'lease lifetime must be ISO instants');
  }
  const lifetime = (Date.parse(expiresAtIso) - Date.parse(issuedAtIso)) / 1000;
  if (lifetime <= 0 || lifetime > LEASE_TTL_MAX_SECONDS) {
    refuse('lease_invalid', `lease lifetime must be positive and at most ${LEASE_TTL_MAX_SECONDS} seconds`);
  }
  return {
    leaseId,
    requestFingerprint,
    browserSessionRef,
    runRef,
    workspaceRef,
    ownerRef,
    allowedActionClasses: [...new Set(allowed as LeaseEligibleAction[])].sort(),
    originScope,
    maxActions,
    issuedAtIso,
    expiresAtIso,
    approvalRef,
    evidenceRef,
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
