/**
 * #3647 — trusted-main bounded action host, slice 1.
 *
 * Authority boundary of this slice (source of truth: the #3607 CENTRAL final
 * design disposition + the #3629 observation authority + #3609 D1):
 *
 *   BROWSER_ACTION_EXECUTION           = lease-eligible slice only
 *     click restricted to CLICK_ALLOWED_ROLE_ALLOWLIST (tab/treeitem);
 *     focus has its own gate (credential=false + focusable + fresh element);
 *   STEP_UP_EXECUTION                  = false  (next slice)
 *   TRUSTED_MAIN_HOST_OWNS_EXTRACTION  = true   (reused #3629 host)
 *   RENDERER_OWNS_PROJECTION_AUTHORITY = false
 *   SECOND_BROWSER_AUTHORITY           = false
 *   GENERIC_IPC_SURFACE                = false
 *   NEW_APPROVAL_STORE                 = false
 *   CANONICAL_LEASE_ADMISSION_WIRED    = false  (next slice's fail-closed port)
 *
 * Flow per action: validate the bounded request -> obtain the #3607 lease
 * through the fail-closed provider port (the canonical P01 + durable one-shot
 * authority plugs in there next slice; an unwired build refuses everything) ->
 * take a FRESH #3629 observation -> bind element_ref against the current
 * projection -> enforce origin/credential/role/budget/idle boundaries ->
 * dispatch input synthesis through the injected binding -> zero-page-derived
 * receipt.
 *
 * Policy separation (CENTRAL review): focus is NOT click policy. Focus is
 * lease-eligible with its own gate (credential=false, focusable state, fresh
 * element, scope match) and dispatches a press whose release lands OUTSIDE the
 * element so no click activation can occur. Click keeps the strict
 * effect-class gate: a verb being "click" never makes it safe.
 *
 * The local per-lease bookkeeping below is a fast-path mirror ONLY — the
 * canonical durable admission authority (next slice) is the only replay and
 * budget authority. Cross-origin movement invalidates the local lease state
 * immediately (INVALIDATE_AND_REQUIRE_STEP_UP) and the canonical authority is
 * re-consulted on every single execute.
 */

import { createHash } from 'node:crypto';

import {
  CLICK_ALLOWED_ROLE_ALLOWLIST,
  LEASE_IDLE_SECONDS,
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

/** Canonical lease admission port. Unwired => every action refuses. */
export interface BrowserActionLeaseProvider {
  readonly configured: boolean;
  lease(input: {
    readonly browserSessionRef: string;
    readonly runRef?: string;
    readonly action: LeaseEligibleAction;
  }): Promise<unknown>;
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
  readonly leaseProvider: BrowserActionLeaseProvider;
  readonly now?: () => Date;
}

const MAX_BOUNDS_COORD = 10_000_000;
const FOCUS_RELEASE_OFFSET = 64;
const ACTION_ID_PATTERN_PREFIX = 'act_';

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
  readonly #leaseProvider: BrowserActionLeaseProvider;
  readonly #now: () => Date;
  #sequence = 0;
  // Fast-path mirror ONLY: per-lease dispatch count and last-activity stamp
  // used to surface idle/budget refusals early. It is NOT the replay or budget
  // authority — the canonical durable admission (next slice) is, and this map
  // is invalidated on scope loss and re-derived from the provider's lease on
  // every execute.
  readonly #leaseFastPath = new Map<string, { consumed: number; lastDispatchAtMs: number }>();

  constructor(dependencies: BrowserActionHostDependencies) {
    if (
      !dependencies ||
      !(dependencies.observation instanceof BrowserObservationHost) ||
      typeof dependencies.binding?.dispatch !== 'function' ||
      typeof dependencies.leaseProvider?.lease !== 'function'
    ) {
      throw new Error('browser action host requires observation host, dispatch binding and lease provider');
    }
    this.#observation = dependencies.observation;
    this.#binding = dependencies.binding;
    this.#leaseProvider = dependencies.leaseProvider;
    this.#now = dependencies.now ?? (() => new Date());
  }

  get configured(): boolean {
    return this.#binding.configured === true && this.#leaseProvider.configured === true;
  }

  get dispatchedCount(): number {
    return this.#sequence;
  }

  async execute(raw: unknown): Promise<BoundedActionReceipt> {
    const request: BoundedBrowserActionRequest = validateBoundedBrowserAction(raw);
    if (!this.configured) {
      throw actionError('host_unavailable', 'no trusted browser action binding and lease authority is configured');
    }

    // The canonical authority is consulted on EVERY execute; nothing here
    // mints, refreshes, stores or replays a lease.
    let lease: BoundedActionLease;
    try {
      lease = assertBoundedActionLease(
        await this.#leaseProvider.lease({ browserSessionRef: request.browserSessionRef, action: request.action }),
      );
    } catch (error) {
      if (error instanceof Error && 'code' in error) throw error;
      // Never surface provider error text: it may carry approval material.
      throw actionError('lease_invalid', 'the canonical action lease authority refused this request');
    }
    if (Date.parse(lease.expiresAtIso) <= this.#now().getTime()) {
      this.#leaseFastPath.delete(lease.leaseId);
      throw actionError('lease_invalid', 'the action lease has expired');
    }
    if (
      request.originRef !== lease.originScope ||
      request.browserSessionRef !== lease.browserSessionRef
    ) {
      // INVALIDATE_AND_REQUIRE_STEP_UP: scope loss drops the local mirror at once.
      this.#leaseFastPath.delete(lease.leaseId);
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
      // The view moved off the leased origin: invalidate, require step-up.
      this.#leaseFastPath.delete(lease.leaseId);
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

    const fastPath = this.#leaseFastPath.get(lease.leaseId) ?? { consumed: 0, lastDispatchAtMs: 0 };
    if (fastPath.consumed + 1 > lease.maxActions) {
      throw actionError('action_budget_exhausted', 'the action lease budget is exhausted');
    }
    const nowMs = this.#now().getTime();
    if (
      fastPath.consumed > 0 &&
      nowMs - fastPath.lastDispatchAtMs > LEASE_IDLE_SECONDS * 1000
    ) {
      // Idle expiry (local mirror of LEASE_IDLE_SECONDS=120): invalidate.
      this.#leaseFastPath.delete(lease.leaseId);
      throw actionError('lease_idle_exceeded', 'the action lease went idle beyond the bounded idle window');
    }
    try {
      await this.#binding.dispatch(ops);
    } catch (error) {
      if (error instanceof Error && 'code' in error) throw error;
      throw actionError('contract_violation', 'trusted action dispatch failed');
    }
    this.#leaseFastPath.set(lease.leaseId, { consumed: fastPath.consumed + 1, lastDispatchAtMs: nowMs });
    this.#sequence += 1;
    const digest = createHash('sha256')
      .update(`${request.browserSessionRef}\u0000${request.action}\u0000${this.#sequence}`)
      .digest('hex')
      .slice(0, 24);
    return buildBoundedActionReceipt({
      actionId: `${ACTION_ID_PATTERN_PREFIX}${digest}`,
      action: request.action,
      elementRef: request.action === 'scroll' ? null : (element?.elementRef ?? null),
      originRef: lease.originScope,
    });
  }

  /** Fast-path mirror reset; the canonical authority stays authoritative. */
  resetFastPath(): void {
    this.#leaseFastPath.clear();
  }
}

export const BROWSER_ACTION_EXECUTION_IMPLEMENTED = true;
export const STEP_UP_EXECUTION_IMPLEMENTED = false;
export const CANONICAL_LEASE_ADMISSION_WIRED = false;
export const NEW_APPROVAL_STORE = false;
export const SECOND_BROWSER_AUTHORITY = false;
export const GENERIC_IPC_SURFACE = false;
/** The local per-lease bookkeeping never claims replay/budget authority. */
export const LOCAL_LEASE_BOOKKEEPING_IS_AUTHORITY = false;
