/**
 * #3647 / #3669 — trusted-main bounded action host.
 *
 * Authority boundary of this slice (source of truth: the #3607 CENTRAL final
 * design disposition + the #3629 observation authority + #3609 D1 + the #3669
 * DECISION=B canonical lease ruling):
 *
 *   BROWSER_ACTION_EXECUTION           = lease-eligible slice only
 *     click restricted to CLICK_ALLOWED_ROLE_ALLOWLIST (tab/treeitem);
 *     focus has its own gate (credential=false + focusable + fresh element);
 *   STEP_UP_EXECUTION                  = false
 *   TRUSTED_MAIN_HOST_OWNS_EXTRACTION  = true   (reused #3629 host)
 *   RENDERER_OWNS_PROJECTION_AUTHORITY = false
 *   SECOND_BROWSER_AUTHORITY           = false
 *   GENERIC_IPC_SURFACE                = false
 *   NEW_APPROVAL_STORE                 = false
 *   CANONICAL_LEASE_ADMISSION_WIRED    = false  (the two-phase port and the
 *                                                resident transport module exist;
 *                                                trusted view wiring is the
 *                                                follow-up child)
 *   LOCAL_LEASE_BOOKKEEPING            = 0      (no local mirror; budget/idle
 *                                                correctness lives in the
 *                                                canonical durable store)
 *
 * Two-phase flow per action (#3669 DECISION=B):
 *
 *   1. PHASE A — READ-ONLY RESOLVE. The canonical authority returns the
 *      durable lease (never mutates: no slot increment, no revoke; first
 *      resolve may lazily mint the agent-side row exactly once).
 *   2. Read-only checks against that lease: expiry, session/origin
 *      binding, action coverage.
 *   3. A FRESH #3629 observation; the post-observation origin check; the
 *      element/credential/role/effect checks. A step-up target refuses HERE,
 *      so it never consumes a durable slot.
 *   4. PHASE B — the single atomic durable consume, called immediately
 *      before input-synthesis dispatch and carrying the observed origin.
 *      On refusal INPUT_COMMAND_COUNT=0 and no retry; the store owns every
 *      slot fact (REFUND=NO, DECREMENT=NO, AUTO_RETRY=NO).
 *   5. Dispatch through the injected binding. A dispatch failure refuses:
 *      the already-consumed slot stays consumed — no refund, no retry.
 *
 * Error policy: only closed desktop codes escape this host. The canonical
 * authority's own budget/idle/origin refusals pass through unchanged; every
 * other code — including P01 evidence and issuance failures — collapses into
 * lease_invalid, and authority error text (which may carry approval
 * material) is never forwarded.
 */

import { createHash } from 'node:crypto';

import {
  CLICK_ALLOWED_ROLE_ALLOWLIST,
  TYPEABLE_ROLE_ALLOWLIST,
  SELECT_ROLE_ALLOWLIST,
  assertBoundedActionLease,
  buildBoundedActionReceipt,
  validateBoundedBrowserAction,
  type BoundedActionLease,
  type BoundedActionReceipt,
  type BoundedBrowserActionRequest,
  type LeaseEligibleAction,
} from './browser-action-contract.js';
import { BrowserObservationHost } from './browser-observation-host.js';
import type { BoundedObservationElement, BoundedPageObservation } from './browser-observation-contract.js';

/**
 * #3669 — the canonical lease admission port, two phases.
 *
 * PHASE A (`resolve`) is READ-ONLY: it returns the canonical lease shape —
 * the 14-key desktop lease dict, re-validated by `assertBoundedActionLease`
 * — and mutates no durable state. PHASE B (`consume`) is the single atomic
 * durable slot write for one action, called exactly once immediately before
 * input-synthesis dispatch; it carries the observed origin from the fresh
 * observation and resolves to the new durable consumed-actions count.
 *
 * Unwired, every action refuses. Budget, idle and replay correctness live in
 * the canonical durable store on the agent side — never in this host.
 */
export interface BrowserActionLeaseAuthority {
  readonly configured: boolean;
  /** PHASE A — the read-only resolve. Never consumes a slot. */
  resolve(input: {
    readonly browserSessionRef: string;
    readonly action: LeaseEligibleAction;
  }): Promise<unknown>;
  /** PHASE B — the atomic durable consume, immediately before dispatch. */
  consume(input: {
    readonly browserSessionRef: string;
    readonly action: LeaseEligibleAction;
    readonly observedOrigin: string;
  }): Promise<number>;
}

export type ActionDispatchOp =
  | { readonly kind: 'click'; readonly x: number; readonly y: number }
  /** Focus mechanics: press ON the element, release OUTSIDE it — no activation. */
  | { readonly kind: 'focus'; readonly x: number; readonly y: number; readonly releaseX: number; readonly releaseY: number }
  | { readonly kind: 'wheel'; readonly x: number; readonly y: number; readonly dx: number; readonly dy: number }
  | { readonly kind: 'insertText'; readonly text: string }
  | { readonly kind: 'key'; readonly key: 'Home' | 'ArrowDown' | 'Enter' };

/** Input-synthesis binding. Implementations may only use CDP `Input.*`. */
export interface BrowserActionDispatchPort {
  readonly configured: boolean;
  dispatch(ops: readonly ActionDispatchOp[]): Promise<void>;
  /** Teardown of anything this binding attached. Always resolves. */
  close(): Promise<void>;
}

export interface BrowserActionHostDependencies {
  readonly observation: BrowserObservationHost;
  readonly binding: BrowserActionDispatchPort;
  readonly leaseAuthority: BrowserActionLeaseAuthority;
  readonly now?: () => Date;
}

const MAX_BOUNDS_COORD = 10_000_000;
const FOCUS_RELEASE_OFFSET = 64;
const ACTION_ID_PATTERN_PREFIX = 'act_';

/**
 * The closed codes a lease authority failure may surface at the host. The
 * canonical authority's budget, idle and origin-scope facts mean the same
 * thing on the desktop side and pass through; lease_invalid and
 * host_unavailable are the two collapsed outcomes everything else maps to.
 */
const AUTHORITY_ERROR_CODES: ReadonlySet<string> = new Set([
  'action_budget_exhausted',
  'lease_idle_exceeded',
  'origin_scope_exceeded',
  'lease_invalid',
  'host_unavailable',
]);

function elementCenter(element: BoundedObservationElement): { x: number; y: number } {
  const x = Math.max(0, Math.min(element.bounds.x + Math.floor(element.bounds.width / 2), MAX_BOUNDS_COORD));
  const y = Math.max(0, Math.min(element.bounds.y + Math.floor(element.bounds.height / 2), MAX_BOUNDS_COORD));
  return { x, y };
}

function actionError(code: string, message: string): Error {
  return Object.assign(new Error(message), { code });
}

/**
 * CLICK policy: effect class first. Only roles the #3629 projection can prove
 * non-committing are lease-allowed; every other role — including link (href
 * invisible) and button (submit indistinguishable) — steps up.
 */
function assertClickAllowedTarget(element: BoundedObservationElement): void {
  if (!(CLICK_ALLOWED_ROLE_ALLOWLIST as readonly string[]).includes(element.role)) {
    throw actionError(
      'step_up_required',
      `click on role ${element.role} cannot be proven non-committing from the bounded projection`,
    );
  }
}

/** FOCUS policy: separate gate, no role restriction (#3607 lease-eligible). */
function assertFocusAllowedTarget(element: BoundedObservationElement): void {
  if (element.credentialField) {
    throw actionError('credential_element_forbidden', 'focus on credential fields requires step-up approval');
  }
  if (!(element.stateFlags as readonly string[]).includes('focusable')) {
    throw actionError('element_not_focusable', 'focus target is not focusable in the current observation');
  }
}

export class BrowserActionHost {
  readonly #observation: BrowserObservationHost;
  readonly #binding: BrowserActionDispatchPort;
  readonly #leaseAuthority: BrowserActionLeaseAuthority;
  readonly #now: () => Date;
  #sequence = 0;

  constructor(dependencies: BrowserActionHostDependencies) {
    if (
      !dependencies ||
      !(dependencies.observation instanceof BrowserObservationHost) ||
      typeof dependencies.binding?.dispatch !== 'function' ||
      typeof dependencies.leaseAuthority?.resolve !== 'function' ||
      typeof dependencies.leaseAuthority?.consume !== 'function'
    ) {
      throw new Error('browser action host requires observation host, dispatch binding and lease authority');
    }
    this.#observation = dependencies.observation;
    this.#binding = dependencies.binding;
    this.#leaseAuthority = dependencies.leaseAuthority;
    this.#now = dependencies.now ?? (() => new Date());
  }

  get configured(): boolean {
    return this.#binding.configured === true && this.#leaseAuthority.configured === true;
  }

  get dispatchedCount(): number {
    return this.#sequence;
  }

  async execute(raw: unknown): Promise<BoundedActionReceipt> {
    const request: BoundedBrowserActionRequest = validateBoundedBrowserAction(raw);
    if (!this.configured) {
      throw actionError('host_unavailable', 'no trusted browser action binding and lease authority is configured');
    }

    // PHASE A — the READ-ONLY resolve: confirm the durable lease, never burn a
    // slot. The canonical authority is consulted on every execute; nothing in
    // this host mints, refreshes, stores or replays a lease.
    let lease: BoundedActionLease;
    try {
      const resolved: unknown = await this.#leaseAuthority.resolve({
        browserSessionRef: request.browserSessionRef,
        action: request.action,
      });
      lease = assertBoundedActionLease(resolved);
    } catch (error) {
      throw this.#authorityRefusal(error);
    }
    if (Date.parse(lease.expiresAtIso) <= this.#now().getTime()) {
      throw actionError('lease_invalid', 'the action lease has expired');
    }
    if (request.originRef !== lease.originScope || request.browserSessionRef !== lease.browserSessionRef) {
      // Read-only scope check: the lease does not bind this origin/session.
      // No slot is consumed and nothing durable is mutated.
      throw actionError('origin_scope_exceeded', 'the lease does not bind this origin/session');
    }
    if (!(lease.allowedActionClasses as readonly string[]).includes(request.action)) {
      throw actionError('lease_invalid', 'the lease does not cover this action class');
    }

    let observation: BoundedPageObservation;
    try {
      observation = await this.#observation.observe({ sessionRef: request.browserSessionRef });
    } catch (error) {
      const code = error instanceof Error && 'code' in error ? (error.code as string) : 'extraction_failed';
      throw actionError(code, 'bounded observation for the action target failed');
    }
    if (observation.originRef !== lease.originScope) {
      // The view moved off the leased origin. This refusal is read-only:
      // INPUT_COMMAND_COUNT=0 and no slot is consumed. The canonical store's
      // cross-origin revoke is the backstop for any consume that did carry a
      // mismatched observed origin; the host never relies on it for checks.
      throw actionError('origin_scope_exceeded', 'the view left the leased origin');
    }

    let element: BoundedObservationElement | undefined;
    if (request.action !== 'scroll') {
      element = observation.elements.find((entry) => entry.elementRef === request.elementRef);
      if (element === undefined) {
        throw actionError('element_not_observed', 'element_ref is not part of the current bounded observation');
      }
      if (element.credentialField) {
        throw actionError('credential_element_forbidden', 'actions against credential fields require step-up approval');
      }
    }

    const ops: ActionDispatchOp[] = [];
    if (request.action === 'scroll') {
      ops.push({ kind: 'wheel', x: 0, y: 0, dx: request.dx, dy: request.dy });
    } else if (element) {
      const center = elementCenter(element);
      if (request.action === 'focus') {
        // Separate focus gate (credential checked above; focusable state here).
        assertFocusAllowedTarget(element);
        // Mechanics without activation: release lands below the element so no
        // click is completed on it or on the element under the release point.
        const releaseY = Math.min(element.bounds.y + element.bounds.height + FOCUS_RELEASE_OFFSET, MAX_BOUNDS_COORD);
        ops.push({ kind: 'focus', x: center.x, y: center.y, releaseX: center.x, releaseY });
      } else if (request.action === 'click') {
        assertClickAllowedTarget(element);
        ops.push({ kind: 'click', x: center.x, y: center.y });
      } else if (request.action === 'type') {
        if (!(TYPEABLE_ROLE_ALLOWLIST as readonly string[]).includes(element.role)) {
          throw actionError('contract_violation', `type target role ${element.role} is not typeable`);
        }
        ops.push({ kind: 'click', x: center.x, y: center.y });
        ops.push({ kind: 'insertText', text: request.text });
      } else if (request.action === 'select') {
        if (!(SELECT_ROLE_ALLOWLIST as readonly string[]).includes(element.role)) {
          throw actionError('contract_violation', `select target role ${element.role} is not a bounded selection role`);
        }
        // Deterministic ABSOLUTE index: Home resets to the first option, then
        // exactly optionIndex ArrowDowns, then Enter — independent of whatever
        // was already selected.
        ops.push({ kind: 'click', x: center.x, y: center.y });
        ops.push({ kind: 'key', key: 'Home' });
        for (let index = 0; index < request.optionIndex; index += 1) {
          ops.push({ kind: 'key', key: 'ArrowDown' });
        }
        ops.push({ kind: 'key', key: 'Enter' });
      }
    }

    // PHASE B — the single atomic durable consume, immediately before dispatch.
    // The observed origin comes from the fresh observation. A refusal means
    // INPUT_COMMAND_COUNT=0 with no retry; the store owns every slot fact
    // (REFUND=NO, DECREMENT=NO, AUTO_RETRY=NO).
    try {
      await this.#leaseAuthority.consume({
        browserSessionRef: request.browserSessionRef,
        action: request.action,
        observedOrigin: observation.originRef,
      });
    } catch (error) {
      throw this.#authorityRefusal(error);
    }

    try {
      await this.#binding.dispatch(ops);
    } catch (error) {
      // Dispatch failed AFTER the durable consume: the slot stays consumed —
      // no refund, no decrement, no auto-retry.
      if (error instanceof Error && 'code' in error) throw error;
      throw actionError('contract_violation', 'trusted action dispatch failed');
    }
    this.#sequence += 1;
    const digest = createHash('sha256')
      .update(`${request.browserSessionRef}\u0000${request.action}\u0000${this.#sequence}`)
      .digest('hex')
      .slice(0, 24);
    return buildBoundedActionReceipt({
      actionId: `${ACTION_ID_PATTERN_PREFIX}${digest}`,
      action: request.action,
      elementRef: request.action === 'scroll' ? null : (element?.elementRef ?? null),
      originRef: observation.originRef,
    });
  }

  /**
   * Collapses one lease-authority failure into the closed desktop code set.
   * Only a code already in the vocabulary may escape; authority error text may
   * carry P01 approval material and is never forwarded.
   */
  #authorityRefusal(error: unknown): Error {
    if (error instanceof Error) {
      const code = (error as { code?: unknown }).code;
      if (typeof code === 'string' && AUTHORITY_ERROR_CODES.has(code)) {
        return error;
      }
    }
    return actionError('lease_invalid', 'the canonical action lease authority refused this request');
  }
}

export const BROWSER_ACTION_EXECUTION_IMPLEMENTED = true;
export const STEP_UP_EXECUTION_IMPLEMENTED = false;
/** The two-phase port and resident transport exist; trusted view wiring is the follow-up child. */
export const CANONICAL_LEASE_ADMISSION_WIRED = false;
export const NEW_APPROVAL_STORE = false;
export const SECOND_BROWSER_AUTHORITY = false;
export const GENERIC_IPC_SURFACE = false;
/** No local lease bookkeeping exists at all: budget/idle correctness lives in the canonical durable store. */
export const LOCAL_LEASE_BOOKKEEPING_IS_AUTHORITY = false;
