/**
 * #3629 — trusted-main bounded page-observation host.
 *
 * Authority boundary of this slice:
 *
 *   TRUSTED_MAIN_HOST_OWNS_EXTRACTION  = true
 *   RENDERER_OWNS_PROJECTION_AUTHORITY = false
 *   BROWSER_ACTION_EXECUTION           = false  (click/type/select/scroll: next child)
 *   JAVASCRIPT_EVALUATE                = false
 *   SCREENSHOT / PDF / COOKIE / STORAGE EXPORT = false
 *   GENERIC_IPC_SURFACE                = false  (no renderer channel exists here)
 *   SECOND_BROWSER_AUTHORITY           = false
 *
 * The host is the only projection authority: it drives the injected extraction
 * source, projects through the bounded contract, and refuses everything else.
 * There is deliberately no IPC export in this slice — the future lease/action
 * child owns the transport decision under the #3607 lease/origin policy, which
 * stays the sole authority for site scope, leases and step-up approval.
 *
 * Flow: validate the bounded session ref -> snapshot via the trusted extraction
 * source -> project through the bounded contract -> bounded observation. The
 * source is the ONLY raw-material path, and its failures are collapsed into
 * bounded refusal codes so no page-derived error text can escape.
 */

import { createHash } from 'node:crypto';

import {
  BROWSER_OBSERVATION_HOST_REF,
  BrowserObservationContractError,
  projectBoundedPageObservation,
  type BoundedPageObservation,
  type ObservationSourceSnapshot,
} from './browser-observation-contract.js';

export type { BrowserObservationErrorCode } from './browser-observation-contract.js';

export class BrowserObservationRefusalError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = 'BrowserObservationRefusalError';
    this.code = code;
  }
}

/**
 * The raw-material path. Only the trusted main host may hold one; it is
 * injected by composition (in the product, an Electron-bound source) and is
 * never reachable from a renderer. Snapshot output is *pre-projection* input:
 * it must still survive the bounded contract before anything is observable.
 */
export interface BrowserObservationSourcePort {
  /** False when no trusted extraction source is wired: the host fails closed. */
  readonly configured: boolean;
  snapshot(): Promise<ObservationSourceSnapshot>;
  /** Lease-scoped teardown of anything this source attached for extraction. */
  close(): Promise<void>;
}

const SAFE_REF = /^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$/;

export function assertBoundedSessionRef(value: unknown): string {
  if (typeof value !== 'string' || !SAFE_REF.test(value.trim())) {
    throw new BrowserObservationRefusalError(
      'contract_violation',
      'session ref must be a bounded safe reference',
    );
  }
  return value.trim();
}

/** Deterministic, content-free projection id: obs_ + 24 hex of session+sequence. */
export function browserObservationProjectionId(sessionRef: string, sequence: number): string {
  if (!Number.isInteger(sequence) || sequence < 1) {
    throw new BrowserObservationRefusalError(
      'contract_violation',
      'projection sequence must be a positive integer',
    );
  }
  const digest = createHash('sha256')
    .update(`${sessionRef}\u0000${sequence}`)
    .digest('hex')
    .slice(0, 24);
  return `obs_${digest}`;
}

export interface BrowserObservationHostDependencies {
  readonly source: BrowserObservationSourcePort;
}

export class BrowserObservationHost {
  readonly #source: BrowserObservationSourcePort;
  #sequence = 0;

  constructor(dependencies: BrowserObservationHostDependencies) {
    if (
      !dependencies ||
      typeof dependencies.source !== 'object' ||
      dependencies.source === null ||
      typeof dependencies.source.snapshot !== 'function'
    ) {
      throw new BrowserObservationContractError(
        'contract_violation',
        'browser observation host requires an injected extraction source port',
      );
    }
    this.#source = dependencies.source;
  }

  get configured(): boolean {
    return this.#source.configured === true;
  }

  get observedCount(): number {
    return this.#sequence;
  }

  /**
   * One bounded observation of the trusted view. `sessionRef` is the trusted
   * browser-session reference the future #3607 lease will bind to; this slice
   * uses it only to derive the deterministic projection id.
   */
  async observe(input: { readonly sessionRef: string }): Promise<BoundedPageObservation> {
    const sessionRef = assertBoundedSessionRef(input?.sessionRef);
    if (!this.configured) {
      throw new BrowserObservationRefusalError(
        'host_unavailable',
        'no trusted browser observation source is configured',
      );
    }
    this.#sequence += 1;
    const projectionId = browserObservationProjectionId(sessionRef, this.#sequence);
    let snapshot: ObservationSourceSnapshot;
    try {
      snapshot = await this.#source.snapshot();
    } catch {
      // Never surface source error text: it may carry page-derived material.
      throw new BrowserObservationRefusalError(
        'extraction_failed',
        'trusted observation extraction failed',
      );
    }
    // Contract violations carry bounded codes only; nothing else escapes.
    return projectBoundedPageObservation({ projectionId, source: snapshot });
  }

  async close(): Promise<void> {
    await this.#source.close().catch(() => undefined);
  }
}

export const BROWSER_OBSERVATION_IMPLEMENTED = true;
export const BROWSER_OBSERVATION_HOST = BROWSER_OBSERVATION_HOST_REF;
export const BROWSER_ACTION_EXECUTION_IMPLEMENTED = false;
export const RENDERER_OWNS_PROJECTION_AUTHORITY = false;
export const TRUSTED_MAIN_HOST_OWNS_EXTRACTION = true;
export const SECOND_BROWSER_AUTHORITY = false;
export const GENERIC_IPC_SURFACE = false;
export const JAVASCRIPT_EVALUATE_SUPPORTED = false;
export const SCREENSHOT_SUPPORTED = false;
export const PDF_CAPTURE_SUPPORTED = false;
export const COOKIE_STORAGE_EXPORT_SUPPORTED = false;
export const CREDENTIAL_VALUE_EXPORT_SUPPORTED = false;
