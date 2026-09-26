/**
 * CLAW2 #3103 — narrow durable-store health seam.
 *
 * ## Why this is a seam and not a reader
 *
 * #3082 (PR #3097) owns the Desktop durable run store, but it is **not merged
 * yet**. #3103 is allowed to run source-only ahead of it, which creates a real
 * risk: if diagnostics read the store directly, #3103 would freeze #3082's
 * internal schema into its own contract and become a second authority over it.
 *
 * So the contract is deliberately the *narrowest* thing that can be useful:
 *
 *   DURABLE_STORE_SCHEMA_DUPLICATION=0
 *   DURABLE_STORE_RECOVERY_AUTHORITY=0
 *   DURABLE_STORE_REPLAY_AUTHORITY=0
 *   DURABLE_STORE_CLASSIFICATION_AUTHORITY=0
 *   DURABLE_STORE_HEALTH=SEAM_READY
 *
 * This port carries one health *category* and nothing else. It cannot read
 * records, cannot classify recovery state, cannot decide replay, and cannot
 * write. It cannot even name a table or a column, so the #3082 schema can move
 * without touching #3103.
 *
 * Until #3082's public contract lands on main, the shell supplies
 * `unimplementedDurableStoreHealth()`, which reports `NOT_IMPLEMENTED`. That is
 * an honest "not wired yet", not a failure and not a fabricated pass.
 */

import {
  assertBoundedDiagnosticParts,
  isDiagnosticHealthStatus,
  type DiagnosticHealthStatus,
} from './diagnostic-codes.js';

/** Bounded health categories. No record counts, no schema details, no paths. */
export const DURABLE_STORE_HEALTH_CATEGORIES = [
  'AVAILABLE',
  'UNAVAILABLE',
  'RECOVERED',
  'REQUIRES_RECONCILIATION',
  'FAIL_CLOSED',
  'NOT_IMPLEMENTED',
] as const;

export type DurableStoreHealthCategory = (typeof DURABLE_STORE_HEALTH_CATEGORIES)[number];

export interface DurableStoreHealth {
  readonly category: DurableStoreHealthCategory;
  readonly status: DiagnosticHealthStatus;
  /** Bounded, authored summary. Never an exception message. */
  readonly summary: string;
  /**
   * How many persisted runs need human reconciliation, or `null` when the store
   * is not wired yet. A count is safe: it carries no record identity.
   */
  readonly reconciliationCount: number | null;
}

export class DurableStoreHealthError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'DurableStoreHealthError';
  }
}

/**
 * The entire integration surface with #3082. One method, one return type.
 */
export interface DurableStoreHealthPort {
  probe(): Promise<DurableStoreHealth>;
}

/** The default until #3082's public contract is on main. */
export function unimplementedDurableStoreHealth(): DurableStoreHealth {
  return Object.freeze({
    category: 'NOT_IMPLEMENTED' as const,
    status: 'WARN' as const,
    summary: 'durable run store diagnostics are not wired in this build yet',
    reconciliationCount: null,
  });
}

export function unimplementedDurableStoreHealthPort(): DurableStoreHealthPort {
  return Object.freeze({ probe: async () => unimplementedDurableStoreHealth() });
}

/**
 * Validates a health value crossing the seam.
 *
 * A store that returns something outside the closed category set has failed
 * closed, and that must surface as `FAIL_CLOSED` — never as a coerced `PASS`.
 */
export function coerceDurableStoreHealth(candidate: unknown): DurableStoreHealth {
  if (typeof candidate !== 'object' || candidate === null) {
    throw new DurableStoreHealthError('durable store health must be an object');
  }
  const raw = candidate as Partial<DurableStoreHealth>;
  const category = raw.category;
  if (
    typeof category !== 'string' ||
    !(DURABLE_STORE_HEALTH_CATEGORIES as readonly string[]).includes(category)
  ) {
    throw new DurableStoreHealthError(
      `durable store returned an unknown health category: ${String(category)}`,
    );
  }
  // A status outside the closed rank set fails closed. Defaulting an absent or
  // unrecognised status to `PASS` would turn a broken store into a green light,
  // which is the exact failure this module exists to prevent.
  if (!isDiagnosticHealthStatus(raw.status)) {
    throw new DurableStoreHealthError(
      `durable store returned an unknown health status: ${String(raw.status)}`,
    );
  }
  return Object.freeze({
    category: category as DurableStoreHealthCategory,
    status: raw.status,
    // The bounded *code* for this section is the closed category token itself;
    // the authored sentence is the bounded summary. Passing the category as the
    // code is what makes both halves validated rather than just the summary.
    summary: assertBoundedDiagnosticParts(
      category,
      raw.summary,
      'durable store health',
    ).summary,
    reconciliationCount:
      typeof raw.reconciliationCount === 'number' &&
      Number.isInteger(raw.reconciliationCount) &&
      raw.reconciliationCount >= 0
        ? raw.reconciliationCount
        : null,
  });
}

export const DURABLE_STORE_SEAM = Object.freeze({
  METHOD_COUNT: 1,
  SCHEMA_DUPLICATION: 0,
  RECOVERY_AUTHORITY: 0,
  REPLAY_AUTHORITY: 0,
  CLASSIFICATION_AUTHORITY: 0,
  WRITE_AUTHORITY: 0,
  HEALTH_READY: true,
  CONCRETE_STORE_IMPLEMENTED_IN_THIS_CHANGE: false,
} as const);
