/**
 * CLAW2 #3103 — secret-free Desktop support bundle.
 *
 * The user-facing half of the issue: when something is wrong, the user presses
 * "export diagnostics" and hands over *one bounded, readable file* that a support
 * person can act on. They should never have to open developer tools, read raw
 * logs, or screenshot a raw exception.
 *
 *   LOCAL_ONLY=YES
 *   AUTO_UPLOAD=NO
 *   TELEMETRY_UPLOAD=0
 *   SECRET_OUTPUT=0
 *   RAW_TASK_PAYLOAD=0
 *   RAW_STDOUT_STDERR=0
 *
 * ## Format: bounded JSON text, not a new artifact framework
 *
 * The bundle is deterministic, human-readable JSON with a stable key order and a
 * trailing newline. That is chosen over a zip because it needs no dependency,
 * diffs cleanly in a bug report, and cannot accidentally carry a second file
 * that nobody reviewed. A redactor pass runs over the *output*, not the input,
 * so a future field added anywhere upstream is still filtered.
 *
 * ## The secret-free guarantee
 *
 * Two independent mechanisms, because one is not enough:
 *
 * 1. **Projection.** Only the fields named in `BUNDLE_SECTIONS` exist. Anything
 *    not projected cannot be exported — `argv`, `stdout`, `stderr`, document
 *    contents and approval payloads have no path into this file at all.
 * 2. **Redaction.** `redactSupportBundleText()` then scans the serialised text
 *    for high-entropy/credential-shaped values and refuses to emit a bundle
 *    containing one. This catches the case a projection cannot: a secret
 *    accidentally interpolated into a summary or code upstream.
 *
 * Neither is a substitute for the other, which is why the secret-negative tests
 * exercise both.
 */

import {
  DIAGNOSTIC_BOUNDS,
  assertBoundedDiagnosticParts,
  assertSupportSafeRef,
  isCompatibilityReason,
  isDeviceLifecycleState,
  isDiagnosticHealthStatus,
  isRunnerHostModeName,
  isRunnerLifecycleState,
  worstHealthStatus,
  type DiagnosticCategory,
  type DiagnosticHealthStatus,
} from './diagnostic-codes.js';
import {
  coerceDurableStoreHealth,
  type DurableStoreHealth,
} from './durable-store-health-seam.js';
import {
  assertFirstRunHealthReport,
  type FirstRunHealthReport,
} from './first-run-health.js';

/** Bounded, support-safe value. No nested objects, no free-form trees. */
export type SupportBundleScalar = string | number | boolean | null;

export interface SupportBundleSection {
  /** Stable, dotted, machine-matchable section id. */
  readonly id: string;
  /** Grouped category, so support can filter without reading the whole file. */
  readonly category: DiagnosticCategory;
  readonly values: Readonly<Record<string, SupportBundleScalar>>;
}

export interface SupportBundle {
  readonly schema: 'padiem-desktop-support-bundle';
  readonly schemaVersion: 1;
  /** ISO-8601 UTC. Supplied by the caller so export is deterministic in test. */
  readonly generatedAt: string;
  /** Worst status across every projected check, for a one-line triage. */
  readonly overall: DiagnosticHealthStatus;
  readonly sections: readonly SupportBundleSection[];
  /**
   * The first-run health report, projected verbatim.
   *
   * This is the reason the bundle exists for an alpha user, so it is a
   * first-class field rather than being folded into `overall`: the six required
   * first-run checks must each be individually visible to someone reading the
   * exported file, not reducible to a single verdict. It is already validated by
   * `assertFirstRunHealthReport` on the way in, and its strings are authored
   * bounded summaries, so it adds no new secret surface.
   */
  readonly firstRun: FirstRunHealthReport;
  /**
   * Bounded, already `assertSupportSafeRef`-validated correlation markers.
   *
   * These live beside the sections rather than inside one because a ref *list* is
   * not a bounded scalar, and admitting a list into `values` would break the
   * scalar-only invariant that makes a section un-nestable by construction. The
   * main process reduces a consumed #3095 pairing handoff to its `consumed-<hex>`
   * marker precisely so support can join on it; without a projection path that
   * marker was validated and then dropped, which removed the one correlation a
   * support engineer needs to match a user's report to a session. A raw pairing
   * code or session secret is not representable — every entry was checked against
   * the ref shape on the way in.
   */
  readonly supportRefs: readonly string[];
}

/**
 * The closed set of sections a bundle may contain.
 *
 * This list *is* the secret-free guarantee: a section that is not listed cannot
 * be exported. Adding a field therefore requires a deliberate, reviewable edit
 * here, rather than arriving by accident through a new object property.
 */
export const BUNDLE_SECTIONS = Object.freeze({
  APP: 'app',
  RUNTIME_PLATFORM: 'runtime_platform',
  DEVICE_LIFECYCLE: 'device_lifecycle',
  SESSION_ACTIVITY: 'session_activity',
  PAIRING: 'pairing',
  UPDATE: 'update',
  RUNNER_HEALTH: 'runner_health',
  DURABLE_STORE: 'durable_store',
  VERSION_COMPATIBILITY: 'version_compatibility',
} as const);

export type BundleSectionId = (typeof BUNDLE_SECTIONS)[keyof typeof BUNDLE_SECTIONS];

export const BUNDLE_SECTION_IDS: readonly BundleSectionId[] = Object.freeze(
  Object.values(BUNDLE_SECTIONS),
);

const SECTION_CATEGORIES: Readonly<Record<BundleSectionId, DiagnosticCategory>> = Object.freeze({
  [BUNDLE_SECTIONS.APP]: 'app_build',
  [BUNDLE_SECTIONS.RUNTIME_PLATFORM]: 'runtime_platform',
  [BUNDLE_SECTIONS.DEVICE_LIFECYCLE]: 'device_lifecycle',
  [BUNDLE_SECTIONS.SESSION_ACTIVITY]: 'session_activity',
  [BUNDLE_SECTIONS.PAIRING]: 'pairing',
  [BUNDLE_SECTIONS.UPDATE]: 'update',
  [BUNDLE_SECTIONS.RUNNER_HEALTH]: 'runner_health',
  [BUNDLE_SECTIONS.DURABLE_STORE]: 'durable_store',
  [BUNDLE_SECTIONS.VERSION_COMPATIBILITY]: 'version_compatibility',
});

/** The exact keys each section may carry. Anything else is dropped. */
const ALLOWED_SECTION_KEYS: Readonly<Record<BundleSectionId, readonly string[]>> = Object.freeze({
  [BUNDLE_SECTIONS.APP]: [
    'appVersion',
    'buildId',
    'bundleAppVersion',
    'runnerAppVersion',
  ],
  [BUNDLE_SECTIONS.RUNTIME_PLATFORM]: [
    'platform',
    'arch',
    'electronMajor',
    'runtimeVersionClass',
  ],
  [BUNDLE_SECTIONS.DEVICE_LIFECYCLE]: [
    'state',
    'status',
    'code',
    'summary',
    'credentialGeneration',
  ],
  [BUNDLE_SECTIONS.SESSION_ACTIVITY]: [
    'lastSuccessfulSessionAt',
    'lastSuccessfulHeartbeatAt',
  ],
  [BUNDLE_SECTIONS.PAIRING]: ['category', 'status', 'code', 'summary'],
  [BUNDLE_SECTIONS.UPDATE]: ['updateRequired', 'status', 'code', 'summary'],
  [BUNDLE_SECTIONS.RUNNER_HEALTH]: [
    'lifecycleState',
    'hostMode',
    'protocolRegistrationAction',
    'protocolRegistered',
    'status',
    'code',
    'summary',
  ],
  [BUNDLE_SECTIONS.DURABLE_STORE]: [
    'healthCategory',
    'status',
    'code',
    'summary',
    'reconciliationCount',
  ],
  [BUNDLE_SECTIONS.VERSION_COMPATIBILITY]: [
    'compatibilityReason',
    'status',
    'code',
    'summary',
  ],
});

export class SupportBundleError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'SupportBundleError';
  }
}

/**
 * Substrings that must never appear in exported text, in any casing.
 *
 * This is a defence-in-depth check, not the primary mechanism: a field named
 * `stdout` is already un-projected, so a *value* containing the word "stdout"
 * is a strong signal that something upstream passed a raw channel through. It is
 * matched on word boundaries so an honest section id like `runner_health` is not
 * flagged.
 */
const FORBIDDEN_TOKENS: readonly string[] = Object.freeze([
  'argv',
  'stdout',
  'stderr',
  'password',
  'passwd',
  'secret',
  'token',
  'credential_value',
  'device_credential',
  'pairing_code',
  'pairing_token',
  'authorization',
  'bearer',
  'api_key',
  'apikey',
  'private_key',
  'BEGIN RSA',
  'BEGIN PRIVATE',
  'approval_payload',
  'document_body',
  'file_contents',
  'connector_payload',
  'process_env',
  'environ',
]);

/**
 * High-entropy credential shapes.
 *
 * Catches the failure projection cannot: a secret interpolated into an
 * otherwise-authored summary. The patterns are deliberately narrow — a bare
 * long hex/octal run and a `scheme:opaque` URI with a non-trivial body — so that
 * legitimate bounded values (a git SHA, a 32-char pairing ref, a build id) do
 * not trip the guard and make the redaction useless through false positives.
 */
const CREDENTIAL_SHAPES: readonly RegExp[] = Object.freeze([
  // PEM body lines. Presence of a long base64 run is the signal.
  /[A-Za-z0-9+/]{120,}={0,2}/,
  // JWT: three base64url segments separated by dots.
  /\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}/,
  // Credential-bearing URI scheme with a real body.
  /\b(?:token|secret|password|passwd|apikey|api_key|auth)=[A-Za-z0-9._~+/=-]{8,}/i,
  // Windows credential-manager style `secret://name:body` pairref-shaped value.
  /\bsecret:\/\/[^\s"']{6,}/i,
  // A long run of a single character class reads as an opaque blob.
  /\b[0-9a-f]{48,}\b/i,
]);

/**
 * Scans a serialised bundle and throws if it looks like it carries a secret.
 *
 * Runs on the *output* text, so it also protects against a caller passing an
 * object that smuggled something in through a value rather than a key.
 */
export function redactSupportBundleText(text: string): string {
  if (typeof text !== 'string') {
    throw new SupportBundleError('support bundle text must be a string');
  }
  const lower = text.toLowerCase();
  for (const token of FORBIDDEN_TOKENS) {
    // Word-boundary match so `runner_health` does not match a substring rule.
    const pattern = new RegExp(`\\b${token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'i');
    if (pattern.test(lower)) {
      throw new SupportBundleError(
        `refusing to export a support bundle containing a forbidden token (${token})`,
      );
    }
  }
  for (const shape of CREDENTIAL_SHAPES) {
    if (shape.test(text)) {
      throw new SupportBundleError(
        'refusing to export a support bundle containing a credential-shaped value',
      );
    }
  }
  return text;
}

/**
 * Facts the main process supplies for one export.
 *
 * Everything is a bounded scalar or a small struct of them. There is
 * intentionally no `unknown`-typed catch-all and no raw log/argv/document field,
 * so a caller cannot pass one even by accident.
 */
export interface SupportBundleInput {
  readonly generatedAt: string;
  readonly appVersion: string;
  readonly buildId: string;
  /** Main-process probe: the OS/arch and a runtime version *class*, not a dump. */
  readonly platform: string;
  readonly arch: string;
  readonly electronMajor: number;
  /** #3083 device lifecycle projection. */
  readonly deviceState: unknown;
  readonly deviceStatus: DiagnosticHealthStatus;
  readonly deviceCode: string;
  readonly deviceSummary: string;
  /** Bounded integer generation counter, never the credential itself. */
  readonly credentialGeneration: number;
  /** ISO-8601 UTC or `null`. A timestamp, never a session token. */
  readonly lastSuccessfulSessionAt: string | null;
  readonly lastSuccessfulHeartbeatAt: string | null;
  /** #3095 pairing category. */
  readonly pairingCategory: string;
  readonly pairingStatus: DiagnosticHealthStatus;
  readonly pairingCode: string;
  readonly pairingSummary: string;
  /** #3101 update requirement. */
  readonly updateRequired: boolean;
  readonly updateStatus: DiagnosticHealthStatus;
  readonly updateCode: string;
  readonly updateSummary: string;
  /** #3093 runner health. */
  readonly runnerLifecycleState: unknown;
  readonly runnerHostMode: unknown;
  readonly protocolRegistrationAction: string;
  readonly protocolRegistered: boolean;
  readonly runnerStatus: DiagnosticHealthStatus;
  readonly runnerCode: string;
  readonly runnerSummary: string;
  /** #3082 seam. Projected as a category only. */
  readonly durableStoreHealth: unknown;
  /** embedded-runtime `REASON_*`. */
  readonly compatibilityReason: unknown;
  readonly compatibilityStatus: DiagnosticHealthStatus;
  readonly compatibilityCode: string;
  readonly compatibilitySummary: string;
  /** Optional support-safe refs so support can join on a correlation id. */
  readonly supportRefs?: readonly string[];
  /** The first-run report, projected verbatim into the bundle. */
  readonly firstRun: FirstRunHealthReport;
}

function boundedScalar(
  value: unknown,
  fieldName: string,
  maxLength: number,
): string | number | boolean | null {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) {
      throw new SupportBundleError(`${fieldName} must be a finite number`);
    }
    return value;
  }
  if (typeof value === 'boolean') {
    return value;
  }
  if (typeof value !== 'string') {
    // An object or array here would mean an unbounded tree is being offered as
    // a "value". Refuse rather than serialise it.
    throw new SupportBundleError(`${fieldName} must be a bounded scalar, not ${typeof value}`);
  }
  const text = value.trim();
  if (text.length === 0 || text.length > maxLength) {
    throw new SupportBundleError(`${fieldName} must be a non-empty bounded string`);
  }
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f]/.test(text)) {
    throw new SupportBundleError(`${fieldName} must not contain control characters`);
  }
  return text;
}

function projectSection(
  id: BundleSectionId,
  values: Readonly<Record<string, unknown>>,
): SupportBundleSection {
  const allowed = ALLOWED_SECTION_KEYS[id];
  const projected: Record<string, SupportBundleScalar> = {};
  // Iterate the allowlist, not the input, so an unexpected extra key is dropped
  // rather than accidentally exported.
  for (const key of allowed) {
    if (!(key in values)) {
      continue;
    }
    projected[key] = boundedScalar(values[key], `${id}.${key}`, DIAGNOSTIC_BOUNDS.MAX_SUMMARY_LENGTH);
  }
  return Object.freeze({
    id,
    category: SECTION_CATEGORIES[id],
    values: Object.freeze(projected),
  });
}

function requireStatus(candidate: unknown, fieldName: string): DiagnosticHealthStatus {
  if (!isDiagnosticHealthStatus(candidate)) {
    throw new SupportBundleError(`${fieldName} is not a known health status`);
  }
  return candidate;
}

const ISO_8601_UTC = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/;

function requireIsoTimestamp(candidate: unknown, fieldName: string): string {
  if (typeof candidate !== 'string' || !ISO_8601_UTC.test(candidate)) {
    throw new SupportBundleError(`${fieldName} must be an ISO-8601 UTC timestamp or null`);
  }
  return candidate;
}

/**
 * Validates a support-safe ref, reporting failures as this module's own error.
 *
 * `assertSupportSafeRef` is the canonical validator and throws
 * `DiagnosticContractError`. That is correct at its own layer, but it would leak
 * a second error type out of the bundle boundary, so a caller of
 * `buildSupportBundle`/`serializeSupportBundle` would have to catch both to
 * handle "bad input" — the two functions already report bad statuses and
 * timestamps as `SupportBundleError`, and a ref should not be the exception.
 * The canonical message is preserved.
 */
function requireSafeRef(candidate: unknown, fieldName: string): string {
  try {
    return assertSupportSafeRef(candidate, fieldName);
  } catch (error) {
    throw new SupportBundleError(
      error instanceof Error ? error.message : `${fieldName} is not a safe reference`,
    );
  }
}

/**
 * Builds the secret-free support bundle from bounded facts.
 *
 * Validation happens here, before serialisation, so a caller learns *which*
 * field was wrong rather than receiving a silently-dropped value. The redaction
 * pass then runs in `serializeSupportBundle`, so both mechanisms always apply
 * to real output.
 */
export function buildSupportBundle(input: SupportBundleInput): SupportBundle {
  if (typeof input !== 'object' || input === null) {
    throw new SupportBundleError('support bundle input must be an object');
  }
  const firstRun = assertFirstRunHealthReport(input.firstRun);
  const durableStore: DurableStoreHealth = coerceDurableStoreHealth(input.durableStoreHealth);
  const generatedAt = requireIsoTimestamp(input.generatedAt, 'generatedAt');

  const refs = input.supportRefs ?? [];
  if (refs.length > DIAGNOSTIC_BOUNDS.MAX_SUPPORT_REFS) {
    throw new SupportBundleError('supportRefs exceeds the maximum ref count');
  }
  const safeRefs = Object.freeze(refs.map((ref, index) => requireSafeRef(ref, `supportRefs[${index}]`)));

  const sections: SupportBundleSection[] = [
    projectSection(BUNDLE_SECTIONS.APP, {
      appVersion: input.appVersion,
      buildId: input.buildId,
    }),
    projectSection(BUNDLE_SECTIONS.RUNTIME_PLATFORM, {
      platform: input.platform,
      arch: input.arch,
      electronMajor: input.electronMajor,
      runtimeVersionClass: 'supported',
    }),
    projectSection(BUNDLE_SECTIONS.DEVICE_LIFECYCLE, {
      state: isDeviceLifecycleState(input.deviceState) ? input.deviceState : 'UNKNOWN',
      status: requireStatus(input.deviceStatus, 'deviceStatus'),
      code: requireSafeRef(input.deviceCode, 'deviceCode'),
      summary: input.deviceSummary,
      credentialGeneration: input.credentialGeneration,
    }),
    projectSection(BUNDLE_SECTIONS.SESSION_ACTIVITY, {
      lastSuccessfulSessionAt: requireIsoTimestamp(
        input.lastSuccessfulSessionAt,
        'lastSuccessfulSessionAt',
      ),
      lastSuccessfulHeartbeatAt: requireIsoTimestamp(
        input.lastSuccessfulHeartbeatAt,
        'lastSuccessfulHeartbeatAt',
      ),
    }),
    projectSection(BUNDLE_SECTIONS.PAIRING, {
      category: requireSafeRef(input.pairingCategory, 'pairingCategory'),
      status: requireStatus(input.pairingStatus, 'pairingStatus'),
      code: requireSafeRef(input.pairingCode, 'pairingCode'),
      summary: input.pairingSummary,
    }),
    projectSection(BUNDLE_SECTIONS.UPDATE, {
      updateRequired: input.updateRequired,
      status: requireStatus(input.updateStatus, 'updateStatus'),
      code: requireSafeRef(input.updateCode, 'updateCode'),
      summary: input.updateSummary,
    }),
    projectSection(BUNDLE_SECTIONS.RUNNER_HEALTH, {
      lifecycleState: isRunnerLifecycleState(input.runnerLifecycleState)
        ? input.runnerLifecycleState
        : 'UNKNOWN',
      hostMode: isRunnerHostModeName(input.runnerHostMode) ? input.runnerHostMode : 'UNKNOWN',
      protocolRegistrationAction: requireSafeRef(
        input.protocolRegistrationAction,
        'protocolRegistrationAction',
      ),
      protocolRegistered: input.protocolRegistered,
      status: requireStatus(input.runnerStatus, 'runnerStatus'),
      code: requireSafeRef(input.runnerCode, 'runnerCode'),
      summary: input.runnerSummary,
    }),
    projectSection(BUNDLE_SECTIONS.DURABLE_STORE, {
      healthCategory: durableStore.category,
      status: requireStatus(durableStore.status, 'durableStore.status'),
      code: 'durable-store.health',
      summary: durableStore.summary,
      reconciliationCount: durableStore.reconciliationCount,
    }),
    projectSection(BUNDLE_SECTIONS.VERSION_COMPATIBILITY, {
      compatibilityReason: isCompatibilityReason(input.compatibilityReason)
        ? input.compatibilityReason
        : 'UNKNOWN',
      status: requireStatus(input.compatibilityStatus, 'compatibilityStatus'),
      code: requireSafeRef(input.compatibilityCode, 'compatibilityCode'),
      summary: input.compatibilitySummary,
    }),
  ];

  const statuses: DiagnosticHealthStatus[] = [
    firstRun.overall,
    ...firstRun.checks.map((check) => check.status),
    requireStatus(input.deviceStatus, 'deviceStatus'),
    requireStatus(input.pairingStatus, 'pairingStatus'),
    requireStatus(input.updateStatus, 'updateStatus'),
    requireStatus(input.runnerStatus, 'runnerStatus'),
    requireStatus(durableStore.status, 'durableStore.status'),
    requireStatus(input.compatibilityStatus, 'compatibilityStatus'),
  ];

  return Object.freeze({
    schema: 'padiem-desktop-support-bundle',
    schemaVersion: 1,
    generatedAt,
    overall: worstHealthStatus(statuses),
    sections: Object.freeze(sections),
    firstRun,
    supportRefs: safeRefs,
  });
}

/**
 * Serialises a bundle to the deterministic text a user actually exports.
 *
 * Determinism is a testable property, not a nicety: two exports of the same
 * facts must be byte-identical so a bug report diffs cleanly. The key order is
 * therefore fixed by construction — section order is `BUNDLE_SECTION_IDS` and
 * value order is the allowlist order — never JavaScript property order, which
 * depends on insertion.
 *
 * The redaction pass runs *here*, on the serialised output, which is what makes
 * it a genuine second mechanism: it inspects the bytes that would actually reach
 * the user's disk, not the object we hope describes them.
 */
export function serializeSupportBundle(bundle: SupportBundle): string {
  if (typeof bundle !== 'object' || bundle === null) {
    throw new SupportBundleError('support bundle must be an object');
  }
  const byId = new Map(bundle.sections.map((section) => [section.id, section]));
  // Re-validated here, not trusted from the builder: `serializeSupportBundle`
  // accepts any object shaped like a bundle, so this is the last point at which
  // a ref can be refused before it reaches the user's disk.
  const refs = Array.isArray(bundle.supportRefs) ? bundle.supportRefs : [];
  if (refs.length > DIAGNOSTIC_BOUNDS.MAX_SUPPORT_REFS) {
    throw new SupportBundleError('support bundle supportRefs exceeds the maximum ref count');
  }
  const safeRefs = refs.map((ref, index) => requireSafeRef(ref, `supportRefs[${index}]`));
  // Re-asserted, not trusted: `serializeSupportBundle` accepts any object shaped
  // like a bundle, so a hand-built or tampered report must be refused here too.
  const firstRun = assertFirstRunHealthReport(bundle.firstRun);
  const payload: Record<string, unknown> = {
    schema: bundle.schema,
    schemaVersion: bundle.schemaVersion,
    generatedAt: bundle.generatedAt,
    overall: bundle.overall,
    firstRun,
    sections: BUNDLE_SECTION_IDS.map((id) => {
      const section = byId.get(id);
      if (!section) {
        throw new SupportBundleError(`support bundle is missing the required section: ${id}`);
      }
      const allowed = ALLOWED_SECTION_KEYS[id];
      const values: Record<string, SupportBundleScalar> = {};
      for (const key of allowed) {
        const value = section.values[key];
        if (value !== undefined) {
          values[key] = value;
        }
      }
      return { id: section.id, category: section.category, values };
    }),
    supportRefs: safeRefs,
  };
  const text = `${JSON.stringify(payload, null, 2)}\n`;
  const bytes = Buffer.byteLength(text, 'utf8');
  if (bytes > DIAGNOSTIC_BOUNDS.MAX_BUNDLE_BYTES) {
    throw new SupportBundleError(
      `support bundle is ${bytes} bytes, above the ${DIAGNOSTIC_BOUNDS.MAX_BUNDLE_BYTES} byte bound`,
    );
  }
  return redactSupportBundleText(text);
}

/**
 * Build *and* serialise in one call.
 *
 * This is the function the main process calls, and the function the tests
 * exercise, so there is no path that produces bundle text without passing the
 * redaction pass. Keeping them separate would create exactly the kind of
 * "some caller forgot" hole the issue is trying to close.
 */
export function exportSupportBundleText(input: SupportBundleInput): string {
  return serializeSupportBundle(buildSupportBundle(input));
}

/**
 * A support-safe filename for the export. Derived only from bounded, already
 * validated values, so it cannot carry a user name, a path or a secret.
 */
export function supportBundleFileName(bundle: SupportBundle): string {
  const stamp = bundle.generatedAt.replace(/[-:]/g, '').replace(/\.\d+Z$/, 'Z');
  return `padiem-support-bundle-${stamp}.json`;
}

export const SUPPORT_BUNDLE_CONTRACT = Object.freeze({
  FORMAT: 'json-text',
  SCHEMA: 'padiem-desktop-support-bundle',
  SCHEMA_VERSION: 1,
  LOCAL_ONLY: true,
  AUTO_UPLOAD: false,
  TELEMETRY_UPLOAD: 0,
  SECRET_OUTPUT: 0,
  RAW_TASK_PAYLOAD: 0,
  RAW_STDOUT_STDERR: 0,
  RAW_ARGV: 0,
  DOCUMENT_BODY: 0,
  /** One reviewable allowlist is the guarantee; a new field needs a deliberate edit. */
  PROJECTED_KEY_ALLOWLIST: true,
  /** Redaction runs on serialised output, so it also catches smuggled values. */
  REDACTS_SERIALISED_OUTPUT: true,
  DETERMINISTIC_KEY_ORDER: true,
  UNKNOWN_STATUS_FAILS_CLOSED: true,
  NETWORK_CALLS_MADE: 0,
  NEW_ARTIFACT_FRAMEWORK: false,
} as const);

