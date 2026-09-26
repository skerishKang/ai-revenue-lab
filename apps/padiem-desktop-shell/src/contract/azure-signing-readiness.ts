/**
 * CLAW3 #3101 M4 — Azure Artifact Signing adapter READINESS contract.
 *
 * This slice is READINESS-ONLY, by explicit instruction:
 *
 *   AZURE_LIVE_SIGNING=NO
 *   PRODUCTION_PUBLISH=NO
 *   SECRET_CREATION=NO
 *   OIDC_CLOUD_MUTATION=NO
 *   PRIVATE_PFX=NO
 *   LONG_LIVED_SIGNING_SECRET=NO
 *
 * CENTRAL's signing decision is fixed and this module does not change it:
 *
 *   PRODUCTION_SIGNING_AUTHORITY=AZURE_ARTIFACT_SIGNING
 *   PRIVATE_PFX_IN_GITHUB=NO
 *   GITHUB_OIDC_FIRST=YES
 *   ELECTRON_BUILDER_AZURE_BETA_ADAPTER=NOT_CANONICAL_YET
 *
 * What this module provides: the adapter contract, the required inputs, the
 * workload-identity boundary, the expected signature-verification shape, and the
 * fail-closed failure modes — all as source and tests. It performs no signing,
 * creates no tenant or service principal, and holds no key material.
 *
 * The two properties that matter most:
 *
 *  1. There is no key fallback. The adapter accepts a workload-identity token
 *     flow only. A "just use a certificate file" path does not exist in the
 *     type surface, so a long-lived secret cannot be introduced by accident.
 *  2. Every identity or revocation failure is a hard failure. A signature that
 *     cannot be verified, or was made by an unexpected identity, is never
 *     treated as "probably fine" — the release is rejected, which is what makes
 *     `SIGNED_INSTALLER` claimable at all in a later slice.
 */

import type { ReleaseSignatureEvidence } from './release-publish-contract.js';

/** Channels are the readiness surface; the canonical selection stays CENTRAL's. */
export type SigningReadinessStatus =
  | 'READY_FOR_PROVISIONED_IDENTITY'
  | 'BLOCKED_NO_WORKLOAD_IDENTITY'
  | 'BLOCKED_IDENTITY_MISMATCH'
  | 'BLOCKED_CERTIFICATE_UNAVAILABLE'
  | 'BLOCKED_REVOKED'
  | 'BLOCKED_SIGNATURE_INVALID'
  | 'BLOCKED_NOT_CONFIGURED';

/**
 * Inputs a real adapter requires. Note what is absent: there is no
 * `pfxPath`, `pfxPassword`, `certificateFile` or generic `secret` field. A
 * long-lived signing credential cannot be threaded through this contract
 * without changing its shape, which is the point.
 */
export interface SigningJobRequest {
  /** Path to the artifact to sign, as produced by the #3096 packaging pin. */
  readonly artifactPath: string;
  readonly expectedArtifactSha256: string;
  /** Full 40-hex source SHA. Signing a release of unknown provenance is refused. */
  readonly sourceSha: string;
  readonly channel: string;
  /** OIDC token minted by the CI provider for the workload identity. */
  readonly federatedToken: string;
  /** Azure tenant the workload identity belongs to. */
  readonly tenantId: string;
  /** Signing profile / account name in Azure Artifact Signing. */
  readonly signingProfile: string;
  /** Certificate identity that MUST have signed the artifact. */
  readonly expectedCertificateIdentity: string;
}

export interface SigningJobResult {
  readonly status: SigningReadinessStatus;
  /** Present only on success. Never a key, token or secret. */
  readonly evidence?: ReleaseSignatureEvidence | null;
  readonly detail: string;
}

export type SigningFailureMode =
  | 'missing_federated_token'
  | 'missing_tenant'
  | 'missing_signing_profile'
  | 'missing_expected_identity'
  | 'unknown_source_provenance'
  | 'artifact_digest_mismatch'
  | 'identity_mismatch'
  | 'certificate_revoked'
  | 'certificate_unavailable'
  | 'signature_verification_failed'
  | 'not_configured';

export const ALL_SIGNING_FAILURE_MODES: readonly SigningFailureMode[] = Object.freeze([
  'missing_federated_token',
  'missing_tenant',
  'missing_signing_profile',
  'missing_expected_identity',
  'unknown_source_provenance',
  'artifact_digest_mismatch',
  'identity_mismatch',
  'certificate_revoked',
  'certificate_unavailable',
  'signature_verification_failed',
  'not_configured',
]);

const GIT_SHA_RE = /^[0-9a-f]{40}$/;
const SHA256_RE = /^[0-9a-f]{64}$/;

/**
 * The unconfigured adapter. This is what ships in this slice: it refuses every
 * request with `not_configured` and performs no I/O, no network call and no
 * signing.
 *
 * It exists so the readiness contract is executable today without pretending a
 * real Azure adapter has been selected or proven. CENTRAL recorded
 * `ELECTRON_BUILDER_AZURE_BETA_ADAPTER=NOT_CANONICAL_YET`, so binding a
 * concrete implementation here would be exactly the premature canonicalisation
 * the decision forbids.
 */
export class UnconfiguredAzureArtifactSigningAdapter {
  readonly adapterName = 'azure-artifact-signing';
  readonly liveSigningConfigured = false;

  isConfigured(): boolean {
    return false;
  }

  sign(_request: SigningJobRequest): SigningJobResult {
    // Every request is refused. Returning a refusal rather than throwing keeps
    // the failure shape uniform with the real adapter's contract.
    void _request;
    return {
      status: 'BLOCKED_NOT_CONFIGURED',
      evidence: null,
      detail: 'no Azure Artifact Signing adapter is configured; live signing is not attempted',
    };
  }
}

export interface SigningAdapter {
  readonly adapterName: string;
  readonly liveSigningConfigured: boolean;
  isConfigured(): boolean;
  sign(request: SigningJobRequest): SigningJobResult;
}

/**
 * Readiness evaluation, independent of any adapter.
 *
 * This is the part that is genuinely testable without Azure: given a request
 * and an observed outcome, does the contract accept it? It is what proves the
 * fail-closed behaviour of identity mismatch, revocation and bad signatures, and
 * it is what a real adapter will be measured against in a later slice.
 */
export interface SigningObservation {
  readonly request: SigningJobRequest;
  /** Observed certificate identity, when a signature was produced. */
  readonly observedSigningIdentity?: string | null;
  readonly observedThumbprint?: string | null;
  readonly observedSignatureSha256?: string | null;
  readonly certificateRevoked?: boolean;
  readonly signatureVerified?: boolean;
}

export function evaluateSigningReadiness(observation: SigningObservation): SigningJobResult {
  if (observation === null || typeof observation !== 'object') {
    return { status: 'BLOCKED_NOT_CONFIGURED', evidence: null, detail: 'observation is required' };
  }
  const request = observation.request;
  if (request === null || typeof request !== 'object') {
    return {
      status: 'BLOCKED_NOT_CONFIGURED',
      evidence: null,
      detail: 'signing request is required',
    };
  }

  // Input completeness first: an incomplete request can never be signed, and
  // saying so is more useful than a downstream identity error.
  if (typeof request.federatedToken !== 'string' || request.federatedToken.trim() === '') {
    return blocked('missing_federated_token', 'BLOCKED_NO_WORKLOAD_IDENTITY');
  }
  if (typeof request.tenantId !== 'string' || request.tenantId.trim() === '') {
    return blocked('missing_tenant', 'BLOCKED_NO_WORKLOAD_IDENTITY');
  }
  if (typeof request.signingProfile !== 'string' || request.signingProfile.trim() === '') {
    return blocked('missing_signing_profile', 'BLOCKED_NOT_CONFIGURED');
  }
  if (
    typeof request.expectedCertificateIdentity !== 'string' ||
    request.expectedCertificateIdentity.trim() === ''
  ) {
    return blocked('missing_expected_identity', 'BLOCKED_NOT_CONFIGURED');
  }
  if (typeof request.sourceSha !== 'string' || !GIT_SHA_RE.test(request.sourceSha)) {
    return blocked('unknown_source_provenance', 'BLOCKED_CERTIFICATE_UNAVAILABLE');
  }
  if (
    typeof request.expectedArtifactSha256 !== 'string' ||
    !SHA256_RE.test(request.expectedArtifactSha256.trim().toLowerCase())
  ) {
    return blocked('artifact_digest_mismatch', 'BLOCKED_CERTIFICATE_UNAVAILABLE');
  }

  // A revoked certificate is terminal regardless of anything else.
  if (observation.certificateRevoked === true) {
    return blocked('certificate_revoked', 'BLOCKED_REVOKED');
  }
  if (observation.observedSigningIdentity == null) {
    return blocked('certificate_unavailable', 'BLOCKED_CERTIFICATE_UNAVAILABLE');
  }
  if (observation.observedSigningIdentity !== request.expectedCertificateIdentity) {
    return blocked('identity_mismatch', 'BLOCKED_IDENTITY_MISMATCH');
  }
  if (observation.signatureVerified !== true) {
    return blocked('signature_verification_failed', 'BLOCKED_SIGNATURE_INVALID');
  }

  const thumbprint = observation.observedThumbprint;
  const signatureSha = observation.observedSignatureSha256;
  if (
    typeof thumbprint !== 'string' ||
    thumbprint.trim() === '' ||
    typeof signatureSha !== 'string' ||
    !SHA256_RE.test(signatureSha.trim().toLowerCase())
  ) {
    return blocked('signature_verification_failed', 'BLOCKED_SIGNATURE_INVALID');
  }

  return {
    status: 'READY_FOR_PROVISIONED_IDENTITY',
    evidence: {
      certificateThumbprint: thumbprint.trim(),
      signingIdentity: observation.observedSigningIdentity,
      signatureSha256: signatureSha.trim().toLowerCase(),
    },
    detail: 'workload identity matched and the signature verified',
  };
}

function blocked(mode: SigningFailureMode, status: SigningReadinessStatus): SigningJobResult {
  return { status, evidence: null, detail: mode };
}

export const AZURE_SIGNING_READINESS = Object.freeze({
  READINESS_SOURCE_READY: true,
  LIVE_SIGNING_CONFIGURED: false,
  AZURE_ARTIFACT_SIGNING_LIVE: false,
  PRODUCTION_SIGNING_AUTHORITY: 'AZURE_ARTIFACT_SIGNING',
  PRIVATE_PFX_IN_REPO: false,
  PRIVATE_PFX_SUPPORTED_BY_CONTRACT: false,
  LONG_LIVED_SIGNING_SECRET_SUPPORTED: false,
  GITHUB_OIDC_FIRST: true,
  ELECTRON_BUILDER_AZURE_BETA_ADAPTER_CANONICAL: false,
  ENTRA_TENANT_CREATED: false,
  SERVICE_PRINCIPAL_CREATED: false,
  /** Identity, revocation and verification failures are all hard failures. */
  REVOCATION_FAIL_CLOSED: true,
  IDENTITY_MISMATCH_FAIL_CLOSED: true,
  SIGNATURE_VERIFICATION_FAIL_CLOSED: true,
  ALL_SIGNING_FAILURE_MODES,
} as const);
