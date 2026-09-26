/**
 * CLAW3 #3101 M3/G3 — release artifact identity, publish authority and
 * bad-release withdrawal.
 *
 * Authority boundary (issue #3101):
 *
 *   IMMUTABLE_RELEASE_ARTIFACT_CONTRACT=YES
 *   EXACT_SHA_PROVENANCE_CONTRACT=YES
 *   NO_SILENT_ARTIFACT_OVERWRITE=YES
 *
 * This slice is SOURCE-ONLY. Nothing here publishes, signs, contacts Azure, or
 * mutates a release feed. It defines the contract a real publish step must
 * satisfy, plus the verification a consumer performs before installing.
 *
 * The central rule: a published release identity is immutable. The same release
 * identity may never be re-pointed at different bytes. "Overwrite the file for
 * version 1.2.3" is not a publish operation this contract permits, because it
 * destroys the only property that makes a release verifiable — that an artifact
 * identified by (identity, sha256) was the one that was reviewed.
 *
 * Provenance is exact, not approximate:
 *
 *   - `sourceSha` must be a full 40-hex commit id, never a branch name or an
 *     abbreviated SHA, because evidence belongs to the exact revision;
 *   - `toolchain` must name the exact electron-builder version and the pinned
 *     toolsets, so "same source SHA" plus "same toolchain" is sufficient to
 *     reproduce the bytes;
 *   - a release whose provenance is incomplete is refused, not published with
 *     a warning. An unverifiable release is treated as an unverifiable one.
 */

export const RELEASE_CHANNELS = ['internal', 'beta', 'stable'] as const;
export type ReleaseChannel = (typeof RELEASE_CHANNELS)[number];

const SHA256_RE = /^[0-9a-f]{64}$/;
const GIT_SHA_RE = /^[0-9a-f]{40}$/;
const TOOLCHAIN_RE = /^[A-Za-z0-9@._+\-]{1,64}$/;

/**
 * Toolchain fields must be real strings.
 *
 * `String(undefined)` is the literal text `"undefined"`, which would satisfy a
 * naive pattern check and let a release with NO toolchain provenance pass as if
 * it had one. Requiring the value to already be a string closes that hole, so an
 * absent field is rejected rather than stringified into a plausible token.
 */
function isToolchainToken(value: unknown): value is string {
  return typeof value === 'string' && TOOLCHAIN_RE.test(value.trim());
}
const CHANNEL_RE = /^internal|beta|stable$/;
const RELEASE_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._\-]{0,127}$/;

export type ReleaseRejection =
  | 'REJECT_MALFORMED_RELEASE_ID'
  | 'REJECT_MALFORMED_ARTIFACT_SHA'
  | 'REJECT_MALFORMED_SOURCE_SHA'
  | 'REJECT_MALFORMED_TOOLCHAIN'
  | 'REJECT_MALFORMED_CHANNEL'
  | 'REJECT_MISSING_PROVENANCE'
  | 'REJECT_IDENTITY_ALREADY_PUBLISHED'
  | 'REJECT_ARTIFACT_SHA_MISMATCH'
  | 'REJECT_SOURCE_SHA_MISMATCH'
  | 'REJECT_WITHDRAWN_RELEASE'
  | 'REJECT_MISSING_SIGNING_EVIDENCE';

export const ALLOWED_RELEASE_REJECTIONS: readonly ReleaseRejection[] = Object.freeze([
  'REJECT_MALFORMED_RELEASE_ID',
  'REJECT_MALFORMED_ARTIFACT_SHA',
  'REJECT_MALFORMED_SOURCE_SHA',
  'REJECT_MALFORMED_TOOLCHAIN',
  'REJECT_MALFORMED_CHANNEL',
  'REJECT_MISSING_PROVENANCE',
  'REJECT_IDENTITY_ALREADY_PUBLISHED',
  'REJECT_ARTIFACT_SHA_MISMATCH',
  'REJECT_SOURCE_SHA_MISMATCH',
  'REJECT_WITHDRAWN_RELEASE',
  'REJECT_MISSING_SIGNING_EVIDENCE',
]);

/** Toolchain provenance. Reproducibility needs all three fields exact. */
export interface ReleaseToolchain {
  /** Exact electron-builder version, e.g. "26.16.1". */
  readonly electronBuilder: string;
  /** Pinned winCodeSign toolset key, per the #3096 M1 pin. */
  readonly winCodeSignToolset: string;
  /** Pinned nsis toolset key, per the #3096 M1 pin. */
  readonly nsisToolset: string;
}

/** Immutable identity + provenance of one published release. */
export interface ReleaseArtifact {
  /** Stable identity. Never reused for different bytes. */
  readonly releaseId: string;
  readonly channel: ReleaseChannel;
  readonly appVersion: string;
  /** SHA-256 of the exact installer bytes. */
  readonly artifactSha256: string;
  /** Full 40-hex source commit that produced these bytes. */
  readonly sourceSha: string;
  readonly toolchain: ReleaseToolchain;
  /** Populated only when a real signature exists. Absent in this source-only slice. */
  readonly signatureEvidence?: ReleaseSignatureEvidence | null;
  readonly withdrawn?: boolean;
}

/**
 * Signing evidence as it would be recorded by a real Azure Artifact Signing
 * step. This slice never produces one, so any release that CLAIMS to be signed
 * without complete evidence must be rejected — see `verifyReleaseForInstall`.
 */
export interface ReleaseSignatureEvidence {
  /** Subject thumbprint of the signing certificate, hex, uppercase. */
  readonly certificateThumbprint: string;
  /** Identity that performed the signing (workload identity subject). */
  readonly signingIdentity: string;
  /** Signature blob digest, hex. */
  readonly signatureSha256: string;
}

export interface PublishRequest {
  readonly release: ReleaseArtifact;
  /**
   * Releases already published to this feed, keyed by releaseId. A publish is
   * additive only.
   */
  readonly existing: Readonly<Record<string, ReleaseArtifact>>;
}

export type PublishOutcome =
  | { readonly accepted: true; readonly releaseId: string }
  | { readonly accepted: false; readonly rejection: ReleaseRejection; readonly detail: string };

function fail(rejection: ReleaseRejection, detail: string): PublishOutcome {
  return { accepted: false, rejection, detail };
}

function validateShape(release: unknown): PublishOutcome | null {
  if (release === null || typeof release !== 'object') {
    return fail('REJECT_MISSING_PROVENANCE', 'release must be an object');
  }
  const candidate = release as Partial<ReleaseArtifact>;
  if (typeof candidate.releaseId !== 'string' || !RELEASE_ID_RE.test(candidate.releaseId)) {
    return fail('REJECT_MALFORMED_RELEASE_ID', 'releaseId is missing or malformed');
  }
  if (typeof candidate.channel !== 'string' || !CHANNEL_RE.test(candidate.channel)) {
    return fail('REJECT_MALFORMED_CHANNEL', 'channel is missing or unknown');
  }
  if (
    typeof candidate.artifactSha256 !== 'string' ||
    !SHA256_RE.test(candidate.artifactSha256.trim().toLowerCase())
  ) {
    return fail('REJECT_MALFORMED_ARTIFACT_SHA', 'artifactSha256 must be a 64-hex digest');
  }
  // Full SHA only: an abbreviated SHA or a branch name cannot identify the
  // exact revision the evidence belongs to.
  if (typeof candidate.sourceSha !== 'string' || !GIT_SHA_RE.test(candidate.sourceSha)) {
    return fail('REJECT_MALFORMED_SOURCE_SHA', 'sourceSha must be a full 40-hex commit id');
  }
  const toolchain = candidate.toolchain;
  if (
    toolchain === null ||
    typeof toolchain !== 'object' ||
    !isToolchainToken(toolchain.electronBuilder) ||
    !isToolchainToken(toolchain.winCodeSignToolset) ||
    !isToolchainToken(toolchain.nsisToolset)
  ) {
    return fail('REJECT_MALFORMED_TOOLCHAIN', 'toolchain provenance is missing or malformed');
  }
  if (typeof candidate.appVersion !== 'string' || candidate.appVersion.trim() === '') {
    return fail('REJECT_MISSING_PROVENANCE', 'appVersion is required');
  }
  return null;
}

/**
 * Publish admission. Additive only.
 *
 * The immutability rule lives here: if a releaseId already exists, the publish
 * is refused outright — whether the bytes are identical or not. Re-publishing
 * identical bytes under the same identity is still a no-op that this contract
 * declines to treat as a publish, because the feed must be append-only for the
 * withdrawal bookkeeping in `withdrawRelease` to remain sound.
 */
export function admitPublish(request: PublishRequest): PublishOutcome {
  if (request === null || typeof request !== 'object') {
    return fail('REJECT_MISSING_PROVENANCE', 'request must be an object');
  }
  const shapeProblem = validateShape(request.release);
  if (shapeProblem !== null) return shapeProblem;

  const release = request.release as ReleaseArtifact;
  const existing = request.existing ?? {};
  const previous = Object.prototype.hasOwnProperty.call(existing, release.releaseId)
    ? existing[release.releaseId]
    : undefined;

  if (previous !== undefined) {
    if (previous.withdrawn === true) {
      return fail(
        'REJECT_IDENTITY_ALREADY_PUBLISHED',
        'release identity is withdrawn; publish a new identity instead of reviving this one',
      );
    }
    const sameBytes =
      previous.artifactSha256.trim().toLowerCase() ===
      release.artifactSha256.trim().toLowerCase() &&
      previous.sourceSha === release.sourceSha;
    if (sameBytes) {
      return fail(
        'REJECT_IDENTITY_ALREADY_PUBLISHED',
        'release identity is already published with identical bytes; publish is additive only',
      );
    }
    return fail(
      'REJECT_IDENTITY_ALREADY_PUBLISHED',
      'a different artifact already claims this release identity; silent overwrite refused',
    );
  }

  return { accepted: true, releaseId: release.releaseId };
}

export interface InstallVerificationRequest {
  /** The release the feed offered. */
  readonly offered: ReleaseArtifact;
  /** SHA-256 of the bytes actually downloaded. */
  readonly observedArtifactSha256: string;
  /** Source SHA the consumer independently knows it expects. */
  readonly expectedSourceSha: string;
  /**
   * Whether the consumer requires a signed installer. A release that CLAIMS a
   * signature must always carry complete evidence; a release that claims none is
   * rejected outright when `requireSigned` is set.
   */
  readonly requireSigned: boolean;
}

/**
 * Consumer-side verification before any byte is installed.
 *
 * Every check is fail-closed and ordered cheapest-first. A withdrawn release is
 * refused even when the bytes and provenance match, so a bad release cannot be
 * re-installed from a cached feed entry.
 */
export function verifyReleaseForInstall(
  request: InstallVerificationRequest,
): PublishOutcome {
  if (request === null || typeof request !== 'object') {
    return fail('REJECT_MISSING_PROVENANCE', 'request must be an object');
  }
  const shapeProblem = validateShape(request.offered);
  if (shapeProblem !== null) return shapeProblem;
  const offered = request.offered as ReleaseArtifact;

  if (offered.withdrawn === true) {
    return fail(
      'REJECT_WITHDRAWN_RELEASE',
      'release is withdrawn; it must not be installed even with matching bytes',
    );
  }

  const observed = String(request.observedArtifactSha256 ?? '')
    .trim()
    .toLowerCase();
  if (!SHA256_RE.test(observed)) {
    return fail('REJECT_MALFORMED_ARTIFACT_SHA', 'observed artifact digest is malformed');
  }
  if (observed !== offered.artifactSha256.trim().toLowerCase()) {
    return fail(
      'REJECT_ARTIFACT_SHA_MISMATCH',
      'downloaded bytes do not match the published artifact digest',
    );
  }

  const expectedSource = String(request.expectedSourceSha ?? '').trim().toLowerCase();
  if (!GIT_SHA_RE.test(expectedSource)) {
    return fail('REJECT_MALFORMED_SOURCE_SHA', 'expected source SHA is malformed');
  }
  if (expectedSource !== offered.sourceSha) {
    return fail(
      'REJECT_SOURCE_SHA_MISMATCH',
      'release was not built from the source revision the consumer expects',
    );
  }

  // Signing evidence is all-or-nothing. A partial claim is treated as no
  // evidence, and a required signature that is absent is a rejection rather
  // than a warning.
  const evidence = offered.signatureEvidence;
  const hasCompleteEvidence =
    evidence !== null &&
    evidence !== undefined &&
    typeof evidence === 'object' &&
    typeof evidence.certificateThumbprint === 'string' &&
    evidence.certificateThumbprint.trim() !== '' &&
    typeof evidence.signingIdentity === 'string' &&
    evidence.signingIdentity.trim() !== '' &&
    typeof evidence.signatureSha256 === 'string' &&
    SHA256_RE.test(evidence.signatureSha256.trim().toLowerCase());

  if (request.requireSigned === true) {
    if (!hasCompleteEvidence) {
      return fail(
        'REJECT_MISSING_SIGNING_EVIDENCE',
        'a signed installer is required but no complete signing evidence is present',
      );
    }
  } else if (evidence !== null && evidence !== undefined && !hasCompleteEvidence) {
    // Incomplete evidence is never treated as "probably fine".
    return fail(
      'REJECT_MISSING_SIGNING_EVIDENCE',
      'release claims signing evidence but it is incomplete',
    );
  }

  return { accepted: true, releaseId: offered.releaseId };
}

export type WithdrawalReason =
  | 'signature_invalid'
  | 'provenance_unverifiable'
  | 'defect_confirmed'
  | 'superseded_by_emergency_release';

export interface WithdrawalRecord {
  readonly releaseId: string;
  readonly reason: WithdrawalReason;
  /** Withdrawn artifacts keep their identity; the feed entry is marked, not deleted. */
  readonly artifactSha256: string;
  readonly replacementReleaseId: string | null;
}

/**
 * Bad-release withdrawal.
 *
 * Withdrawal is a state transition on an existing feed entry, never a delete.
 * The bytes and identity are retained so the audit trail survives, and the
 * entry can never be re-published (see `admitPublish`).
 */
export function withdrawRelease(
  feed: Readonly<Record<string, ReleaseArtifact>>,
  withdrawal: WithdrawalRecord,
): PublishOutcome {
  if (withdrawal === null || typeof withdrawal !== 'object') {
    return fail('REJECT_MISSING_PROVENANCE', 'withdrawal must be an object');
  }
  if (typeof withdrawal.releaseId !== 'string' || !RELEASE_ID_RE.test(withdrawal.releaseId)) {
    return fail('REJECT_MALFORMED_RELEASE_ID', 'withdrawal releaseId is malformed');
  }
  const existing = feed?.[withdrawal.releaseId];
  if (existing === undefined) {
    return fail(
      'REJECT_MALFORMED_RELEASE_ID',
      'cannot withdraw a release identity that was never published',
    );
  }
  if (existing.withdrawn === true) {
    return fail(
      'REJECT_WITHDRAWN_RELEASE',
      'release is already withdrawn; withdrawal is idempotent-by-refusal',
    );
  }
  return { accepted: true, releaseId: withdrawal.releaseId };
}

export const RELEASE_PUBLISH_CONTRACT = Object.freeze({
  /** Publish is additive only; an identity is written once. */
  PUBLISH_IS_APPEND_ONLY: true,
  SILENT_ARTIFACT_OVERWRITE: false,
  ARTIFACT_IDENTITY_IMMUTABLE: true,
  /** Full 40-hex source SHA is mandatory; abbreviations and branch names refused. */
  REQUIRES_EXACT_SOURCE_SHA: true,
  REQUIRES_TOOLCHAIN_PROVENANCE: true,
  WITHDRAWAL_PRESERVES_IDENTITY: true,
  WITHDRAWN_RELEASE_INSTALLABLE: false,
  SIGNING_EVIDENCE_ALL_OR_NOTHING: true,
  SIGNED_INSTALLER_PRODUCED: false,
  AZURE_ARTIFACT_SIGNING_LIVE: false,
  PRODUCTION_PUBLISH: false,
  ALLOWED_REJECTIONS: ALLOWED_RELEASE_REJECTIONS,
  CHANNELS: RELEASE_CHANNELS,
} as const);
