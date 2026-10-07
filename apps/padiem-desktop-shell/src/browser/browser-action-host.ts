/**
 * #3647 — trusted-main bounded action host, slice 1.
 *
 * Authority boundary of this slice:
 *
 *   BROWSER_ACTION_EXECUTION          = lease-eligible slice only
 *     (scroll / focus / click / type / select — everything else refuses)
 *   STEP_UP_EXECUTION                 = false  (next slice)
 *   TRUSTED_MAIN_HOST_OWNS_EXTRACTION = true   (reused #3629 host)
 *   RENDERER_OWNS_PROJECTION_AUTHORITY = false
 *   SECOND_BROWSER_AUTHORITY          = false
 *   GENERIC_IPC_SURFACE               = false
 *   NEW_APPROVAL_STORE                = false
 *   CANONICAL_LEASE_ADMISSION_WIRED   = false  (next slice's port)
 *
 * Flow per action: validate the bounded request -> obtain the bounded lease
 * through the fail-closed lease provider port (the canonical P01/durable
 * authority plugs in there next slice; an unwired build refuses everything) ->
 * take a FRESH #3629 observation -> bind element_ref against the current
 * projection -> enforce origin/credential/role/budget boundaries -> dispatch
 * input synthesis through the injected binding -> zero-page-derived receipt.
 *
 * No action is ever dispatched against a stale observation: the element
 * identity, its credential marker and its role all come from the same fresh
 * bounded projection the action is about to act on.
 */

import { createHash } from 'node:crypto';

import {
  BROWSER_ACTION_HOST_REF,
  CLICKABLE_ROLE_ALLOWLIST,
  SELECT_ROLE_ALLOWLIST,
  TYPEABLE_ROLE_ALLOWLIST,
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
  lease(input: { readonly sessionRef: string; readonly action: LeaseEligibleAction }): Promise<unknown>;
}

export type ActionDispatchOp =
  | { readonly kind: 'click'; readonly x: number; readonly y: number }
  | { readonly kind: 'wheel'; readonly x: number; readonly y: number; readonly dx: number; readonly dy: number }
  | { readonly kind: 'insertText'; readonly text: string }
  | { readonly kind: 'key'; readonly key: 'ArrowDown' | 'Enter' };

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
const ACTION_ID_PATTERN_PREFIX = 'act_';

function elementCenter(element: BoundedObservationElement): { x: number; y: number } {
  const x = Math.max(0, Math.min(element.bounds.x + Math.floor(element.bounds.width / 2), MAX_BOUNDS_COORD));
  const y = Math.max(0, Math.min(element.bounds.y + Math.floor(element.bounds.height / 2), MAX_BOUNDS_COORD));
  return { x, y };
}

function assertClickableTarget(element: BoundedObservationElement, action: string): void {
  if (element.role === 'button') {
    // A bounded projection cannot tell a submit button from a safe one:
    // button-role targets default to step-up (#3607).
    throw Object.assign(
      new Error(`${action} on a button-role element requires a separate step-up approval`),
      { code: 'step_up_required' as const },
    );
  }
  if (!(CLICKABLE_ROLE_ALLOWLIST as readonly string[]).includes(element.role)) {
    throw Object.assign(new Error(`${action} target role ${element.role} is not a bounded interactive role`), {
      code: 'contract_violation' as const,
    });
  }
}

export class BrowserActionHost {
  readonly #observation: BrowserObservationHost;
  readonly #binding: BrowserActionDispatchPort;
  readonly #leaseProvider: BrowserActionLeaseProvider;
  readonly #now: () => Date;
  #sequence = 0;
  /** Fast path only. Never the replay/budget authority (mirrors #3611). */
  readonly #consumedByLease = new Map<string, number>();

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
      throw Object.assign(new Error('no trusted browser action binding and lease authority is configured'), {
        code: 'host_unavailable' as const,
      });
    }

    let lease: BoundedActionLease;
    try {
      lease = assertBoundedActionLease(
        await this.#leaseProvider.lease({ sessionRef: request.sessionRef, action: request.action }),
      );
    } catch (error) {
      if (error instanceof Error && 'code' in error) throw error;
      // Never surface provider error text: it may carry approval material.
      throw Object.assign(new Error('the canonical action lease authority refused this request'), {
        code: 'lease_invalid' as const,
      });
    }
    if (Date.parse(lease.expiresAtIso) <= this.#now().getTime()) {
      throw Object.assign(new Error('the action lease has expired'), { code: 'lease_invalid' as const });
    }
    if (request.originRef !== lease.originRef || request.sessionRef !== lease.sessionRef) {
      throw Object.assign(new Error('the lease does not bind this origin/session'), {
        code: 'origin_scope_exceeded' as const,
      });
    }
    if (!(lease.allowedActions as readonly string[]).includes(request.action)) {
      throw Object.assign(new Error('the lease does not cover this action class'), {
        code: 'lease_invalid' as const,
      });
    }

    let observation: BoundedPageObservation;
    try {
      observation = await this.#observation.observe({ sessionRef: request.sessionRef });
    } catch (error) {
      const code = error instanceof Error && 'code' in error ? (error.code as string) : 'extraction_failed';
      throw Object.assign(new Error('bounded observation for the action target failed'), { code });
    }
    if (observation.originRef !== lease.originRef) {
      throw Object.assign(new Error('the view left the leased origin'), {
        code: 'origin_scope_exceeded' as const,
      });
    }

    let element: BoundedObservationElement | undefined;
    if (request.action !== 'scroll') {
      element = observation.elements.find((entry) => entry.elementRef === request.elementRef);
      if (element === undefined) {
        throw Object.assign(new Error('element_ref is not part of the current bounded observation'), {
          code: 'element_not_observed' as const,
        });
      }
      if (element.credentialField) {
        throw Object.assign(new Error('actions against credential fields require step-up approval'), {
          code: 'credential_element_forbidden' as const,
        });
      }
    }

    const ops: ActionDispatchOp[] = [];
    if (request.action === 'scroll') {
      ops.push({ kind: 'wheel', x: 0, y: 0, dx: request.dx, dy: request.dy });
    } else if (element) {
      assertClickableTargetForAction(element, request.action);
      const center = elementCenter(element);
      if (request.action === 'click' || request.action === 'focus') {
        ops.push({ kind: 'click', x: center.x, y: center.y });
      } else if (request.action === 'type') {
        if (!(TYPEABLE_ROLE_ALLOWLIST as readonly string[]).includes(element.role)) {
          throw Object.assign(new Error(`type target role ${element.role} is not typeable`), {
            code: 'contract_violation' as const,
          });
        }
        ops.push({ kind: 'click', x: center.x, y: center.y });
        ops.push({ kind: 'insertText', text: request.text });
      } else if (request.action === 'select') {
        if (!(SELECT_ROLE_ALLOWLIST as readonly string[]).includes(element.role)) {
          throw Object.assign(new Error(`select target role ${element.role} is not a bounded selection role`), {
            code: 'contract_violation' as const,
          });
        }
        ops.push({ kind: 'click', x: center.x, y: center.y });
        for (let index = 0; index <= request.optionIndex; index += 1) {
          ops.push({ kind: 'key', key: 'ArrowDown' });
        }
        ops.push({ kind: 'key', key: 'Enter' });
      }
    }

    const consumed = this.#consumedByLease.get(lease.leaseId) ?? 0;
    if (consumed + 1 > lease.maxActions) {
      throw Object.assign(new Error('the action lease budget is exhausted'), {
        code: 'action_budget_exhausted' as const,
      });
    }
    try {
      await this.#binding.dispatch(ops);
    } catch (error) {
      if (error instanceof Error && 'code' in error) throw error;
      throw Object.assign(new Error('trusted action dispatch failed'), {
        code: 'contract_violation' as const,
      });
    }
    this.#consumedByLease.set(lease.leaseId, consumed + 1);
    this.#sequence += 1;
    const digest = createHash('sha256')
      .update(`${request.sessionRef}\u0000${request.action}\u0000${this.#sequence}`)
      .digest('hex')
      .slice(0, 24);
    return buildBoundedActionReceipt({
      actionId: `${ACTION_ID_PATTERN_PREFIX}${digest}`,
      action: request.action,
      elementRef: request.action === 'scroll' ? null : (element?.elementRef ?? null),
      originRef: lease.originRef,
    });
  }

  /** Lease-scoped fast-path reset; the canonical authority stays authoritative. */
  resetFastPath(): void {
    this.#consumedByLease.clear();
  }
}

function assertClickableTargetForAction(
  element: BoundedObservationElement,
  action: 'click' | 'focus' | 'type' | 'select',
): void {
  if (action === 'type' || action === 'select') return;
  assertClickableTarget(element, action);
}

export const BROWSER_ACTION_HOST_REF_BINDING = BROWSER_ACTION_HOST_REF;
export const BROWSER_ACTION_EXECUTION_IMPLEMENTED = true;
export const STEP_UP_EXECUTION_IMPLEMENTED = false;
export const CANONICAL_LEASE_ADMISSION_WIRED = false;
export const NEW_APPROVAL_STORE = false;
export const SECOND_BROWSER_AUTHORITY = false;
export const GENERIC_IPC_SURFACE = false;
