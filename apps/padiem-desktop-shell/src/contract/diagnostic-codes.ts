/**
 * CLAW2 #3103 — bounded, secret-free Desktop diagnostic vocabulary.
 *
 * A 3–5 person assisted-alpha user who hits a problem must be able to see what
 * is wrong and export it *without* opening developer tools or reading raw logs.
 * That only works if a diagnostic is a small closed set of codes rather than a
 * pasted exception, so this module fixes the vocabulary in one place.
 *
 *   UNBOUNDED_EXCEPTION_DUMP=NO
 *   FREE_FORM_ERROR_STRING_AS_CODE=NO
 *   DIAGNOSTIC_CODES=BOUNDED
 *
 * ## Reuse, not invention
 *
 * The repository already owns several status/code vocabularies. #3103 must not
 * create a competing one, so this module *reuses* them and adds only what is
 * genuinely missing (a status rank and a summary bound):
 *
 *   - `src/main/runner-host-mode.ts`  → `RunnerHostModeName`
 *   - `src/main/protocol-registration.ts` → `ProtocolRegistrationPlan.action`
 *   - `src/contract/device-lifecycle.ts` → `DeviceLifecycleState` (incl. its
 *     existing `ACTION_REQUIRED`)
 *   - `packages/padiem-embedded-runtime` `compatibility.py` `REASON_*` codes
 *
 * The one genuinely new vocabulary is the four-level health rank, because
 * nothing on main models "healthy / degraded / user must act / refuse to
 * proceed" as a single comparable scale.
 */

import {
  DEVICE_LIFECYCLE_STATES,
  type DeviceLifecycleState,
} from './device-lifecycle.js';
import { RUNNER_HOST_MODE_CONTRACT, type RunnerHostModeName } from '../main/runner-host-mode.js';
import type { RunnerLifecycleState } from './ipc.js';

/**
 * Bounded health ranks. `FAIL_CLOSED` is the worst because it means the shell
 * refused to proceed rather than merely warning.
 */
export const DIAGNOSTIC_HEALTH_STATUSES = ['PASS', 'WARN', 'ACTION_REQUIRED', 'FAIL_CLOSED'] as const;

export type DiagnosticHealthStatus = (typeof DIAGNOSTIC_HEALTH_STATUSES)[number];

/** Higher is worse. Used to reduce a set of checks to one overall verdict. */
const HEALTH_RANK: Readonly<Record<DiagnosticHealthStatus, number>> = Object.freeze({
  PASS: 0,
  WARN: 1,
  ACTION_REQUIRED: 2,
  FAIL_CLOSED: 3,
});

export function isDiagnosticHealthStatus(candidate: unknown): candidate is DiagnosticHealthStatus {
  return (
    typeof candidate === 'string' &&
    (DIAGNOSTIC_HEALTH_STATUSES as readonly string[]).includes(candidate)
  );
}

/** Worst-of reduction. An empty set is a `PASS` (nothing observed went wrong). */
export function worstHealthStatus(
  statuses: readonly DiagnosticHealthStatus[],
): DiagnosticHealthStatus {
  let worst: DiagnosticHealthStatus = 'PASS';
  for (const status of statuses) {
    if (!isDiagnosticHealthStatus(status)) {
      // Fail closed rather than ranking an unknown rank.
      return 'FAIL_CLOSED';
    }
    if (HEALTH_RANK[status] > HEALTH_RANK[worst]) {
      worst = status;
    }
  }
  return worst;
}

/**
 * Bounds for every user-visible string a diagnostic may carry.
 *
 * The summary bound is what makes "bounded code + safe summary" real: a summary
 * is a short authored sentence, never an interpolated exception, stack trace or
 * environment dump.
 */
export const DIAGNOSTIC_BOUNDS = Object.freeze({
  MAX_CODE_LENGTH: 64,
  MAX_SUMMARY_LENGTH: 160,
  MAX_CHECKS: 32,
  MAX_SUPPORT_REFS: 16,
  MAX_SUPPORT_REF_LENGTH: 96,
  MAX_BUNDLE_BYTES: 64 * 1024,
  MAX_REMEDIATION_LENGTH: 160,
} as const);

/** Control characters and newlines are never allowed inside a projected string. */
const UNSAFE_CODE_CHARS = /[^A-Za-z0-9_.:-]/;
const CONTROL_CHARS = /[\u0000-\u001f\u007f]/;

export class DiagnosticContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'DiagnosticContractError';
  }
}

/**
 * Raised when a first-run *input* is not something the shell is allowed to
 * project. Kept distinct from `DiagnosticContractError` so a caller can tell
 * "the output was malformed" from "the input was not a canonical fact".
 */
export class FirstRunCheckError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'FirstRunCheckError';
  }
}

/**
 * Validates one code and summary. A diagnostic that cannot be bounded is
 * rejected instead of being truncated into something that reads as a different
 * code — silent truncation of a *code* would be a correctness bug, not a
 * formatting one.
 */
export function assertBoundedDiagnosticParts(
  code: unknown,
  summary: unknown,
  fieldPrefix = 'diagnostic',
): { code: string; summary: string } {
  if (typeof code !== 'string' || code.length === 0 || code.length > DIAGNOSTIC_BOUNDS.MAX_CODE_LENGTH) {
    throw new DiagnosticContractError(`${fieldPrefix}.code must be a non-empty bounded token`);
  }
  if (UNSAFE_CODE_CHARS.test(code)) {
    throw new DiagnosticContractError(`${fieldPrefix}.code must be an uppercase-safe token`);
  }
  if (typeof summary !== 'string' || summary.length === 0) {
    throw new DiagnosticContractError(`${fieldPrefix}.summary must be a non-empty safe sentence`);
  }
  if (summary.length > DIAGNOSTIC_BOUNDS.MAX_SUMMARY_LENGTH) {
    throw new DiagnosticContractError(
      `${fieldPrefix}.summary exceeds ${DIAGNOSTIC_BOUNDS.MAX_SUMMARY_LENGTH} characters`,
    );
  }
  if (CONTROL_CHARS.test(summary)) {
    throw new DiagnosticContractError(`${fieldPrefix}.summary must not contain control characters`);
  }
  return { code, summary };
}


/**
 * The closed set of diagnostic *categories*, each of which already has a
 * canonical owner on main. #3103 projects these owners; it never owns them.
 */
export const DIAGNOSTIC_CATEGORIES = [
  'app_build',
  'runtime_platform',
  'device_lifecycle',
  'session_activity',
  'pairing',
  'update',
  'runner_health',
  'durable_store',
  'version_compatibility',
] as const;

export type DiagnosticCategory = (typeof DIAGNOSTIC_CATEGORIES)[number];

/** Re-exported canonical vocabularies, so callers project rather than redefine. */
export const REUSED_CANONICAL_VOCABULARIES = Object.freeze({
  RUNNER_HOST_MODES: RUNNER_HOST_MODE_CONTRACT.MODES,
  RUNNER_LIFECYCLE_STATES: ['STOPPED', 'STARTING', 'RUNNING', 'STOPPING', 'CRASHED'] as const,
  DEVICE_LIFECYCLE_STATES,
  /** `compatibility.py` REASON_* — the canonical compatibility verdict codes. */
  COMPATIBILITY_REASONS: [
    'COMPATIBLE',
    'UNSUPPORTED_CONTRACT_MAJOR',
    'MALFORMED_CONTRACT_VERSION',
    'MISSING_CONTRACT_VERSION',
  ] as const,
} as const);

export function isRunnerHostModeName(candidate: unknown): candidate is RunnerHostModeName {
  return (
    typeof candidate === 'string' &&
    (REUSED_CANONICAL_VOCABULARIES.RUNNER_HOST_MODES as readonly string[]).includes(candidate)
  );
}

export function isRunnerLifecycleState(candidate: unknown): candidate is RunnerLifecycleState {
  return (
    typeof candidate === 'string' &&
    (REUSED_CANONICAL_VOCABULARIES.RUNNER_LIFECYCLE_STATES as readonly string[]).includes(candidate)
  );
}

export function isDeviceLifecycleState(candidate: unknown): candidate is DeviceLifecycleState {
  return (
    typeof candidate === 'string' && (DEVICE_LIFECYCLE_STATES as readonly string[]).includes(candidate)
  );
}

export function isCompatibilityReason(candidate: unknown): candidate is string {
  return (
    typeof candidate === 'string' &&
    (REUSED_CANONICAL_VOCABULARIES.COMPATIBILITY_REASONS as readonly string[]).includes(candidate)
  );
}

/**
 * A single support-safe correlation reference.
 *
 * Diagnostics must be *joinable* by support without carrying the underlying
 * value, so refs are opaque, bounded, and drawn from a character set that
 * cannot hold a credential. Anything else is rejected rather than sanitised:
 * sanitising a token-shaped value into a "safe" ref would leak its shape.
 */
export const SUPPORT_REF_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$/;

export function assertSupportSafeRef(candidate: unknown, fieldName: string): string {
  if (typeof candidate !== 'string' || !SUPPORT_REF_PATTERN.test(candidate)) {
    throw new DiagnosticContractError(
      `${fieldName} must be a bounded opaque support-safe ref`,
    );
  }
  return candidate;
}

export const DIAGNOSTICS_CONTRACT = Object.freeze({
  STATUSES: DIAGNOSTIC_HEALTH_STATUSES,
  CATEGORIES: DIAGNOSTIC_CATEGORIES,
  BOUNDS: DIAGNOSTIC_BOUNDS,
  UNBOUNDED_EXCEPTION_DUMP: false,
  FREE_FORM_ERROR_STRING_AS_CODE: false,
  INVENTS_RUNNER_MODE_VOCABULARY: false,
  INVENTS_DEVICE_LIFECYCLE_VOCABULARY: false,
  INVENTS_COMPATIBILITY_VOCABULARY: false,
  AUTHORITY_OWNERS: Object.freeze({
    runner_host_mode: '#3093',
    protocol_registration: '#3093',
    device_lifecycle: '#3083',
    version_compatibility: 'padiem-embedded-runtime',
    durable_store: '#3082',
    pairing: '#3095/#3080',
    update: '#3101',
  }),
} as const);
