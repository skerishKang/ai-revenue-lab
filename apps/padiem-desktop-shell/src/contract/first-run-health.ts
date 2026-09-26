/**
 * CLAW2 #3103 — Desktop first-run health.
 *
 * The first thing an assisted-alpha user needs is a short, honest answer to
 * "is this install actually able to work, and if not, what do I do?". This module
 * produces exactly that, from facts the shell already owns, as bounded codes.
 *
 *   FIRST_RUN_HEALTH=PASS
 *   UNBOUNDED_EXCEPTION_DUMP=NO
 *   HEALTH_CODES=BOUNDED
 *   CREATES_NO_NEW_AUTHORITY=YES
 *
 * Each check is a *pure projection* of a canonical fact. This module never
 * probes the filesystem, never opens a socket, never reads the registry and never
 * reads an environment variable: the main process performs those probes and
 * hands in bounded results. That keeps this file testable, side-effect free and
 * honest about the difference between "I checked" and "I was told".
 */

import {
  DIAGNOSTIC_BOUNDS,
  FirstRunCheckError,
  assertBoundedDiagnosticParts,
  isCompatibilityReason,
  isDiagnosticHealthStatus,
  isRunnerHostModeName,
  worstHealthStatus,
  type DiagnosticHealthStatus,
} from './diagnostic-codes.js';

/**
 * The closed set of first-run checks. This list is the issue's required scope and
 * nothing more: each entry is a thing a user can act on.
 */
export const FIRST_RUN_CHECKS = [
  'DESKTOP_RUNNER_EXECUTABLE_MODE',
  'PROTOCOL_REGISTRATION',
  'APP_DATA_WRITABLE',
  'CREDENTIAL_STORE_AVAILABLE',
  'BROKER_ROUTE_CONFIG_READY',
  'VERSION_COMPATIBILITY',
] as const;

export type FirstRunCheck = (typeof FIRST_RUN_CHECKS)[number];

export interface FirstRunCheckResult {
  readonly check: FirstRunCheck;
  readonly status: DiagnosticHealthStatus;
  /** Bounded, authored, canonical-vocabulary code. */
  readonly code: string;
  /** Bounded safe sentence. Never an exception. */
  readonly summary: string;
  /** Short user-facing next step, or `null` when nothing is needed. */
  readonly remediation: string | null;
}

export interface FirstRunHealthReport {
  readonly checks: readonly FirstRunCheckResult[];
  readonly overall: DiagnosticHealthStatus;
  readonly generatedAtMs: number;
}

function boundedRemediation(candidate: unknown): string | null {
  if (candidate === null || candidate === undefined) {
    return null;
  }
  if (
    typeof candidate !== 'string' ||
    candidate.length === 0 ||
    candidate.length > DIAGNOSTIC_BOUNDS.MAX_REMEDIATION_LENGTH
  ) {
    throw new FirstRunCheckError('remediation must be null or a bounded short sentence');
  }
  return candidate;
}

export function firstRunResult(
  check: FirstRunCheck,
  status: DiagnosticHealthStatus,
  code: string,
  summary: string,
  remediation: string | null,
): FirstRunCheckResult {
  const bounded = assertBoundedDiagnosticParts(code, summary, `first_run.${check}`);
  return Object.freeze({
    check,
    status,
    code: bounded.code,
    summary: bounded.summary,
    remediation: boundedRemediation(remediation),
  });
}

/** Fact inputs for one first-run evaluation. All are already-probed facts. */
export interface FirstRunProbeInput {
  /** #3093 `resolveRunnerHostMode(...).mode`. */
  readonly runnerHostMode: unknown;
  /** #3093 `windowsProtocolRegistrationPlan(...).action`. */
  readonly protocolRegistrationAction: unknown;
  readonly protocolRegistered: boolean;
  /** Main-process probe: is the app-data directory writable? */
  readonly appDataWritable: boolean;
  /** Main-process probe: is an OS credential store reachable? */
  readonly credentialStoreAvailable: boolean;
  /** Main-process probe: is broker route config present and parseable? */
  readonly brokerRouteConfigReady: boolean;
  /** #3101/OS-level: is an update required before this build can be used? */
  readonly updateRequired: boolean;
  /** `compatibility.py` `REASON_*` code for the runtime/host contract check. */
  readonly compatibilityReason: unknown;
  /** Optional support-safe refs (e.g. a pairref) to correlate support. */
  readonly supportRefs?: readonly string[];
  /** Caller-supplied clock, so the report is deterministic under test. */
  readonly generatedAtMs: number;
}

/**
 * `DESKTOP_RUNNER_EXECUTABLE_MODE`.
 *
 * `plain-node` is legal for a checkout and wrong for a packaged build, so it
 * downgrades to `ACTION_REQUIRED` rather than failing: a developer running from
 * source is not a broken install.
 */
export function projectRunnerExecutableMode(mode: unknown): FirstRunCheckResult {
  if (!isRunnerHostModeName(mode)) {
    throw new FirstRunCheckError(
      `DESKTOP_RUNNER_EXECUTABLE_MODE requires a canonical runner host mode; got ${String(mode)}`,
    );
  }
  switch (mode) {
    case 'explicit-executable':
      return firstRunResult(
        'DESKTOP_RUNNER_EXECUTABLE_MODE',
        'PASS',
        'runner-host-mode.explicit-executable',
        'runner uses the operator-provided runner executable',
        null,
      );
    case 'electron-run-as-node':
      return firstRunResult(
        'DESKTOP_RUNNER_EXECUTABLE_MODE',
        'PASS',
        'runner-host-mode.electron-run-as-node',
        'runner reuses the shell binary in Electron run-as-node host mode',
        null,
      );
    default:
      return firstRunResult(
        'DESKTOP_RUNNER_EXECUTABLE_MODE',
        'ACTION_REQUIRED',
        'runner-host-mode.plain-node',
        'runner is on a plain Node host, which is not a packaged Desktop install',
        'install the packaged Desktop build so the runner has a real host mode',
      );
  }
}

/**
 * `PROTOCOL_REGISTRATION`.
 *
 * Non-Windows is a supported, intentional outcome, not a failure, so the
 * `skip-not-windows` plan is a `PASS` with an explicit code. A Windows launch
 * that did not register is `ACTION_REQUIRED`, because that breaks the pairing
 * handoff a user actually needs.
 */
export function projectProtocolRegistration(
  action: unknown,
  registered: boolean,
): FirstRunCheckResult {
  if (typeof action !== 'string' || action.length === 0 || action.length > 64) {
    throw new FirstRunCheckError('PROTOCOL_REGISTRATION requires a registration action');
  }
  if (action === 'skip-not-windows') {
    return firstRunResult(
      'PROTOCOL_REGISTRATION',
      'PASS',
      'protocol-registration.skip-not-windows',
      'protocol registration is a Windows-only handoff contract and is skipped here',
      null,
    );
  }
  if (action === 'skip-dev-without-app-path') {
    return firstRunResult(
      'PROTOCOL_REGISTRATION',
      'FAIL_CLOSED',
      'protocol-registration.skip-dev-without-app-path',
      'a development launch named no app directory, so registration was refused',
      'start the shell with its app directory argument',
    );
  }
  if (action === 'register-dev-host' || action === 'register-direct') {
    if (registered) {
      return firstRunResult(
        'PROTOCOL_REGISTRATION',
        'PASS',
        `protocol-registration.${action}`,
        'the shell is reachable through its registered protocol handler',
        null,
      );
    }
    return firstRunResult(
      'PROTOCOL_REGISTRATION',
      'ACTION_REQUIRED',
      'protocol-registration.rejected-by-os',
      'the operating system did not accept the protocol registration',
      'reinstall the Desktop app so the protocol handler can be registered',
    );
  }
  throw new FirstRunCheckError(`unknown protocol registration action: ${action}`);
}

/** `APP_DATA_WRITABLE`. A read-only profile is a real, common install fault. */
export function projectAppDataWritable(writable: boolean): FirstRunCheckResult {
  if (typeof writable !== 'boolean') {
    throw new FirstRunCheckError('APP_DATA_WRITABLE requires a boolean probe result');
  }
  if (writable) {
    return firstRunResult(
      'APP_DATA_WRITABLE',
      'PASS',
      'app-data.writable',
      'the app data directory accepts writes',
      null,
    );
  }
  return firstRunResult(
    'APP_DATA_WRITABLE',
    'FAIL_CLOSED',
    'app-data.not-writable',
    'the app data directory cannot be written, so the Desktop cannot run',
    'fix the permissions on the Padiem app data folder and restart',
  );
}

/**
 * `CREDENTIAL_STORE_AVAILABLE`.
 *
 * Without a credential store the shell can start but can never hold a device
 * credential, so the user would fail later at pairing with a worse message. It is
 * therefore surfaced at first run as `ACTION_REQUIRED`, not hidden.
 */
export function projectCredentialStoreAvailable(available: boolean): FirstRunCheckResult {
  if (typeof available !== 'boolean') {
    throw new FirstRunCheckError('CREDENTIAL_STORE_AVAILABLE requires a boolean probe result');
  }
  if (available) {
    return firstRunResult(
      'CREDENTIAL_STORE_AVAILABLE',
      'PASS',
      'credential-store.available',
      'the operating system credential store is reachable',
      null,
    );
  }
  return firstRunResult(
    'CREDENTIAL_STORE_AVAILABLE',
    'ACTION_REQUIRED',
    'credential-store.unavailable',
    'no operating system credential store was reachable for device credentials',
    'unlock the system credential store, or reinstall the Desktop app',
  );
}

/** `BROKER_ROUTE_CONFIG_READY`. A missing route is a configuration, not a crash. */
export function projectBrokerRouteConfigReady(ready: boolean): FirstRunCheckResult {
  if (typeof ready !== 'boolean') {
    throw new FirstRunCheckError('BROKER_ROUTE_CONFIG_READY requires a boolean probe result');
  }
  if (ready) {
    return firstRunResult(
      'BROKER_ROUTE_CONFIG_READY',
      'PASS',
      'broker-route.ready',
      'the broker route configuration is present and parseable',
      null,
    );
  }
  return firstRunResult(
    'BROKER_ROUTE_CONFIG_READY',
    'ACTION_REQUIRED',
    'broker-route.not-configured',
    'no usable broker route configuration was found for this install',
    'sign the Desktop app in again so its broker route can be configured',
  );
}

/**
 * `VERSION_COMPATIBILITY`, combining the embedded-runtime contract check with the
 * #3101 update requirement.
 *
 * Both are *categories the shell already owns*, so this only orders them. An
 * incompatible host contract is the worse of the two because it means the
 * runner and control plane disagree structurally, not just in version.
 */
export function projectVersionCompatibility(
  compatibilityReason: unknown,
  updateRequired: boolean,
): FirstRunCheckResult {
  if (!isCompatibilityReason(compatibilityReason)) {
    throw new FirstRunCheckError(
      `VERSION_COMPATIBILITY requires a canonical compatibility reason; got ${String(compatibilityReason)}`,
    );
  }
  if (typeof updateRequired !== 'boolean') {
    throw new FirstRunCheckError('VERSION_COMPATIBILITY requires a boolean updateRequired');
  }
  if (compatibilityReason !== 'COMPATIBLE') {
    return firstRunResult(
      'VERSION_COMPATIBILITY',
      'FAIL_CLOSED',
      `version-compatibility.${compatibilityReason.toLowerCase()}`,
      'this Desktop build and its runner declare incompatible contract versions',
      'update the Desktop app and the runner to matching versions',
    );
  }
  if (updateRequired) {
    return firstRunResult(
      'VERSION_COMPATIBILITY',
      'ACTION_REQUIRED',
      'version-compatibility.update-required',
      'a newer Desktop build is available and should be installed',
      'install the available Desktop update and restart',
    );
  }
  return firstRunResult(
    'VERSION_COMPATIBILITY',
    'PASS',
    'version-compatibility.compatible',
    'the Desktop build, runner and control plane declare compatible contracts',
    null,
  );
}

/**
 * Builds the whole first-run report.
 *
 * Ordering is the issue's declared check order, and every check is always
 * present: a check the shell could not evaluate is reported as `FAIL_CLOSED`
 * with an explicit code, never omitted, because an omitted check would read to
 * the user as a check that passed.
 */
export function buildFirstRunHealthReport(input: FirstRunProbeInput): FirstRunHealthReport {
  const checks: FirstRunCheckResult[] = [
    projectRunnerExecutableMode(input.runnerHostMode),
    projectProtocolRegistration(input.protocolRegistrationAction, input.protocolRegistered),
    projectAppDataWritable(input.appDataWritable),
    projectCredentialStoreAvailable(input.credentialStoreAvailable),
    projectBrokerRouteConfigReady(input.brokerRouteConfigReady),
    projectVersionCompatibility(input.compatibilityReason, input.updateRequired),
  ];
  if (checks.length > FIRST_RUN_CHECKS.length) {
    throw new FirstRunCheckError('first-run report contains more checks than the closed set');
  }
  return Object.freeze({
    checks: Object.freeze(checks),
    overall: worstHealthStatus(checks.map((check) => check.status)),
    generatedAtMs: input.generatedAtMs,
  });
}

/**
 * Validates a first-run report crossing a module boundary.
 *
 * The support bundle consumes reports from the main process, so a malformed or
 * hand-rolled object must fail closed at the seam rather than be trusted into a
 * user-facing export. An unknown check name is the important case: a check that
 * is not in the closed set means some other module invented a vocabulary.
 */
export function assertFirstRunHealthReport(candidate: unknown): FirstRunHealthReport {
  if (typeof candidate !== 'object' || candidate === null || Array.isArray(candidate)) {
    throw new FirstRunCheckError('first-run report must be an object');
  }
  const raw = candidate as Partial<FirstRunHealthReport>;
  if (!Array.isArray(raw.checks)) {
    throw new FirstRunCheckError('first-run report must carry a checks array');
  }
  if (raw.checks.length === 0) {
    throw new FirstRunCheckError('first-run report must not be empty');
  }
  if (raw.checks.length > DIAGNOSTIC_BOUNDS.MAX_CHECKS) {
    throw new FirstRunCheckError('first-run report exceeds the maximum check count');
  }
  if (!isDiagnosticHealthStatus(raw.overall)) {
    throw new FirstRunCheckError('first-run report overall status is not a known health status');
  }
  if (typeof raw.generatedAtMs !== 'number' || !Number.isFinite(raw.generatedAtMs)) {
    throw new FirstRunCheckError('first-run report must carry a finite generatedAtMs');
  }
  for (const check of raw.checks) {
    if (typeof check !== 'object' || check === null) {
      throw new FirstRunCheckError('each first-run check must be an object');
    }
    const entry = check as Partial<FirstRunCheckResult>;
    if (typeof entry.check !== 'string' || !(FIRST_RUN_CHECKS as readonly string[]).includes(entry.check)) {
      throw new FirstRunCheckError('a first-run check name is outside the closed set');
    }
    if (!isDiagnosticHealthStatus(entry.status)) {
      throw new FirstRunCheckError('a first-run check status is not a known health status');
    }
    assertBoundedDiagnosticParts(entry.code, entry.summary, `first_run.${entry.check}`);
  }
  return raw as FirstRunHealthReport;
}

export const FIRST_RUN_HEALTH_CONTRACT = Object.freeze({
  CHECKS: FIRST_RUN_CHECKS,
  PROBES_THE_ENVIRONMENT: false,
  READS_ENVIRONMENT_VARIABLES: false,
  RETURNS_UNBOUNDED_EXCEPTIONS: false,
  DUPLICATES_DEVICE_LIFECYCLE_AUTHORITY: false,
  DUPLICATES_RUNNER_HOST_MODE_AUTHORITY: false,
  DUPLICATES_COMPATIBILITY_AUTHORITY: false,
  OVERALL_IS_WORST_OF: true,
  MISSING_CHECKS_ARE_OMITTED: false,
} as const);
