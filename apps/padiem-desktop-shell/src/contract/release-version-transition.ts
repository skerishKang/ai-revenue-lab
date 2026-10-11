/**
 * CLAW3 #3101 M2/G2 — installed-version authority, update and rollback semantics.
 *
 * Authority boundary (issue #3101, parent #3099, foundation #3096):
 *
 *   INSTALLED_VERSION_AUTHORITY_COUNT=1
 *   OWNED_HERE=installed_desktop_app_version_and_transition_decision
 *
 * What this module decides: whether a candidate release may be installed over
 * the currently installed app version, and whether a downgrade/rollback is
 * permitted. That is the whole authority.
 *
 * What this module is NOT, and must never grow into:
 *
 *   - it does not own, read, migrate or rewrite #3082 durable local run state;
 *   - it does not own broker command state (#3080/#3093);
 *   - it does not own conversation or task state;
 *   - it does not schedule, retry, resume or replay any execution.
 *
 * The four axes are deliberately kept separate. An app version is a byte
 * identity of the installed program. A durable run record is a fact about work
 * that already happened. Updating the program can never make a terminal local
 * command become a replay candidate, and rolling the program back can never
 * make local execution history untrue.
 *
 * #3082 is still OPEN and not merged, so this module does NOT import, mirror or
 * anticipate its store schema. It depends on no #3082 type at all. The
 * separation is achieved by *not modelling* durable state here: a version
 * transition is evaluated purely from version numbers and declared
 * compatibility, and its output describes what may happen to app bytes only.
 * When #3082 lands, durable-state compatibility is enforced at its own seam via
 * a declared schema range, never by reaching into its tables.
 *
 * Fail-closed rules that are load-bearing, not advisory:
 *
 *   UNKNOWN_INSTALLED_VERSION=REJECTED
 *   UNKNOWN_TARGET_VERSION=REJECTED
 *   UNKNOWN_SCHEMA_RANGE=REJECTED
 *   UNKNOWN_RUNTIME_RANGE=REJECTED
 *   UNSUPPORTED_UPGRADE=REJECTED
 *   UNSUPPORTED_DOWNGRADE=REJECTED
 *   TERMINAL_RUN_REPLAY=NEVER
 */

export const SEMVER_RE = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;

/** A parsed semantic version. Comparison is numeric per component. */
export interface InstalledVersion {
  readonly major: number;
  readonly minor: number;
  readonly patch: number;
}

export function parseVersion(value: unknown): InstalledVersion | null {
  if (typeof value !== 'string') return null;
  const match = SEMVER_RE.exec(value.trim());
  if (!match) return null;
  return {
    major: Number(match[1]),
    minor: Number(match[2]),
    patch: Number(match[3]),
  };
}

export function compareVersions(a: InstalledVersion, b: InstalledVersion): number {
  if (a.major !== b.major) return a.major < b.major ? -1 : 1;
  if (a.minor !== b.minor) return a.minor < b.minor ? -1 : 1;
  if (a.patch !== b.patch) return a.patch < b.patch ? -1 : 1;
  return 0;
}

/** Result of one installed-version authority decision. */
export type VersionTransitionDecision =
  | 'INSTALL'
  | 'REJECT_UNSUPPORTED_UPGRADE'
  | 'REJECT_UNSUPPORTED_DOWNGRADE'
  | 'REJECT_UNKNOWN_INSTALLED_VERSION'
  | 'REJECT_UNKNOWN_TARGET_VERSION'
  | 'REJECT_INCOMPATIBLE_SCHEMA'
  | 'REJECT_INCOMPATIBLE_RUNTIME'
  | 'REJECT_SAME_VERSION_REPUBLISH'
  | 'REJECT_IDENTITY_MISMATCH';

export const ALLOWED_VERSION_DECISIONS: readonly VersionTransitionDecision[] = Object.freeze([
  'INSTALL',
  'REJECT_UNSUPPORTED_UPGRADE',
  'REJECT_UNSUPPORTED_DOWNGRADE',
  'REJECT_UNKNOWN_INSTALLED_VERSION',
  'REJECT_UNKNOWN_TARGET_VERSION',
  'REJECT_INCOMPATIBLE_SCHEMA',
  'REJECT_INCOMPATIBLE_RUNTIME',
  'REJECT_SAME_VERSION_REPUBLISH',
  'REJECT_IDENTITY_MISMATCH',
]);

/** Every decision other than INSTALL is a refusal that installs no bytes. */
export function isInstallAllowed(decision: VersionTransitionDecision): boolean {
  return decision === 'INSTALL';
}

/**
 * Declared compatibility for one target release.
 *
 * `minSchemaVersion` / `maxSchemaVersion` describe the durable-run schema range
 * the release supports, expressed as app versions. They are a *declared range*,
 * not a read of any store: #3101 never opens a durable store to discover it.
 */
export interface ReleaseCompatibility {
  /** Lowest app version whose durable schema this release can still read. */
  readonly minSchemaVersion: string;
  /** Highest app version whose durable schema this release can still read. */
  readonly maxSchemaVersion: string;
  /** Lowest Electron/Node runtime this release supports. */
  readonly minRuntimeMajor: number;
  /** Whether this release may be installed as a downgrade/rollback target. */
  readonly rollbackEligible: boolean;
}

export interface VersionTransitionRequest {
  /** Currently installed app version, or null/undefined when unknown. */
  readonly installedVersion: string | null | undefined;
  /** Candidate release app version. */
  readonly targetVersion: string | null | undefined;
  /**
   * Identity of the candidate artifact, used to refuse a silent overwrite of
   * an already-installed version by a different artifact.
   */
  readonly targetArtifactSha256?: string | null;
  /** Identity of the currently installed artifact, when known. */
  readonly installedArtifactSha256?: string | null;
  readonly compatibility: ReleaseCompatibility | null | undefined;
  /** Explicit rollback intent. Without it, a lower target is an unsupported downgrade. */
  readonly intent?: 'upgrade' | 'rollback';
}

export interface VersionTransitionVerdict {
  readonly decision: VersionTransitionDecision;
  readonly installedVersion: InstalledVersion | null;
  readonly targetVersion: InstalledVersion | null;
  /** True only when app bytes may change. Durable state is never a factor here. */
  readonly mayInstallAppBytes: boolean;
  /**
   * Always false. This module has no authority to schedule, resume or replay
   * work; a version change can never make a terminal run replayable.
   */
  readonly mayReplayLocalRun: false;
  readonly mayRewriteDurableRunState: false;
  readonly reason: string;
}

function reject(
  decision: VersionTransitionDecision,
  installed: InstalledVersion | null,
  target: InstalledVersion | null,
  reason: string,
): VersionTransitionVerdict {
  return Object.freeze({
    decision,
    installedVersion: installed,
    targetVersion: target,
    mayInstallAppBytes: false,
    mayReplayLocalRun: false,
    mayRewriteDurableRunState: false,
    reason,
  });
}

/**
 * The single installed-version authority.
 *
 * Exactly one function decides an app-version transition. There is deliberately
 * no second helper that can answer the same question, so the authority count
 * stays 1 by construction.
 */
export function evaluateVersionTransition(
  request: VersionTransitionRequest,
): VersionTransitionVerdict {
  if (request === null || typeof request !== 'object') {
    return reject('REJECT_UNKNOWN_INSTALLED_VERSION', null, null, 'request must be an object');
  }

  const installed = parseVersion(request.installedVersion);
  const target = parseVersion(request.targetVersion);

  if (installed === null) {
    // Fail closed: an unknown installed version means the compatibility window
    // cannot be established, so no install may be authorised.
    return reject(
      'REJECT_UNKNOWN_INSTALLED_VERSION',
      null,
      target,
      'installed version is unknown; compatibility cannot be established',
    );
  }
  if (target === null) {
    return reject('REJECT_UNKNOWN_TARGET_VERSION', installed, null, 'target version is unknown');
  }

  const compatibility = request.compatibility;
  if (
    compatibility === null ||
    compatibility === undefined ||
    typeof compatibility !== 'object'
  ) {
    return reject(
      'REJECT_INCOMPATIBLE_SCHEMA',
      installed,
      target,
      'release compatibility is not declared; schema range unknown',
    );
  }

  const minSchema = parseVersion(compatibility.minSchemaVersion);
  const maxSchema = parseVersion(compatibility.maxSchemaVersion);
  if (minSchema === null || maxSchema === null) {
    return reject(
      'REJECT_INCOMPATIBLE_SCHEMA',
      installed,
      target,
      'declared schema range is unreadable; refusing rather than assuming',
    );
  }
  if (compareVersions(minSchema, maxSchema) > 0) {
    return reject(
      'REJECT_INCOMPATIBLE_SCHEMA',
      installed,
      target,
      'declared schema range is inverted; refusing rather than assuming',
    );
  }
  if (
    !Number.isInteger(compatibility.minRuntimeMajor) ||
    compatibility.minRuntimeMajor < 1
  ) {
    return reject(
      'REJECT_INCOMPATIBLE_RUNTIME',
      installed,
      target,
      'declared runtime floor is unreadable; refusing rather than assuming',
    );
  }

  // Schema compatibility: the INSTALLED app version's schema must sit inside the
  // range the target release declares it can read. This is a range comparison
  // over versions only. No durable store is opened.
  if (compareVersions(installed, minSchema) < 0 || compareVersions(installed, maxSchema) > 0) {
    return reject(
      'REJECT_INCOMPATIBLE_SCHEMA',
      installed,
      target,
      'installed app version is outside the target release declared schema range',
    );
  }

  const order = compareVersions(target, installed);
  const intent = request.intent === 'rollback' ? 'rollback' : 'upgrade';

  if (order === 0) {
    // Same version. Installing the identical bytes is a no-op, but a DIFFERENT
    // artifact claiming the same version is a silent-overwrite attempt and must
    // be refused. This is the M3 immutability rule enforced at the M2 seam.
    const installedSha = normaliseSha(request.installedArtifactSha256);
    const targetSha = normaliseSha(request.targetArtifactSha256);
    if (installedSha !== null && targetSha !== null && installedSha !== targetSha) {
      return reject(
        'REJECT_IDENTITY_MISMATCH',
        installed,
        target,
        'a different artifact already claims this installed version; silent overwrite refused',
      );
    }
    return reject(
      'REJECT_SAME_VERSION_REPUBLISH',
      installed,
      target,
      'target version equals the installed version; no version transition to authorise',
    );
  }

  if (order < 0) {
    if (intent !== 'rollback') {
      return reject(
        'REJECT_UNSUPPORTED_DOWNGRADE',
        installed,
        target,
        'a lower target version requires an explicit rollback intent',
      );
    }
    if (compatibility.rollbackEligible !== true) {
      return reject(
        'REJECT_UNSUPPORTED_DOWNGRADE',
        installed,
        target,
        'target release is not rollback eligible',
      );
    }
    // A rollback changes app bytes only. It is explicitly forbidden from
    // touching durable run truth; the verdict carries that as a typed false.
    return Object.freeze({
      decision: 'INSTALL' as const,
      installedVersion: installed,
      targetVersion: target,
      mayInstallAppBytes: true,
      mayReplayLocalRun: false as const,
      mayRewriteDurableRunState: false as const,
      reason: 'rollback installs older app bytes only; durable run truth is untouched',
    });
  }

  return Object.freeze({
    decision: 'INSTALL' as const,
    installedVersion: installed,
    targetVersion: target,
    mayInstallAppBytes: true,
    mayReplayLocalRun: false as const,
    mayRewriteDurableRunState: false as const,
    reason: 'upgrade is within the declared schema range and runtime floor',
  });
}

const SHA256_RE = /^[0-9a-f]{64}$/;

export function normaliseSha(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim().toLowerCase();
  return SHA256_RE.test(trimmed) ? trimmed : null;
}

/**
 * Durable-run truth is never an input to, nor an output of, the version
 * authority. This projection exists so the separation is machine-checkable
 * rather than a claim in a comment.
 */
export interface DurableRunSeparation {
  readonly versionAuthorityOwnsDurableState: false;
  readonly versionTransitionReadsDurableStore: false;
  readonly terminalRunBecomesReplayCandidate: false;
  readonly brokerCommandStateOwnedHere: false;
  readonly conversationOrTaskStateOwnedHere: false;
}

export const DURABLE_RUN_SEPARATION: DurableRunSeparation = Object.freeze({
  versionAuthorityOwnsDurableState: false,
  versionTransitionReadsDurableStore: false,
  terminalRunBecomesReplayCandidate: false,
  brokerCommandStateOwnedHere: false,
  conversationOrTaskStateOwnedHere: false,
});

export const INSTALLED_VERSION_AUTHORITY = Object.freeze({
  /** Exactly one authority function decides an app-version transition. */
  AUTHORITY_COUNT: 1,
  DECISION_FUNCTION: 'evaluateVersionTransition',
  /** The only decision that may change app bytes. */
  INSTALL_DECISION: 'INSTALL',
  ALLOWED_DECISIONS: ALLOWED_VERSION_DECISIONS,
  UNKNOWN_INSTALLED_VERSION_FAIL_CLOSED: true,
  UNKNOWN_TARGET_VERSION_FAIL_CLOSED: true,
  SCHEMA_COMPATIBILITY_FAIL_CLOSED: true,
  RUNTIME_COMPATIBILITY_FAIL_CLOSED: true,
  UNSUPPORTED_UPGRADE_FAIL_CLOSED: true,
  UNSUPPORTED_DOWNGRADE_FAIL_CLOSED: true,
  UPDATE_REPLAYS_TERMINAL_RUN: false,
  ROLLBACK_REPLAYS_LOCAL_RUN: false,
  /** Durable run state is never an input to a version decision. */
  DURABLE_STATE_READ_BY_VERSION_AUTHORITY: false,
  /** #3082 internals are not imported; no schema coupling exists here. */
  IMPORTS_3082_STORE_INTERNALS: false,
  DURABLE_RUN_SEPARATION,
} as const);
