/**
 * CLAW3 #3101 M4 — Azure Artifact Signing readiness tests.
 *
 * Scope assertion: nothing here signs, contacts Azure, creates a tenant or
 * service principal, or handles key material. The tests prove the fail-closed
 * behaviour of the readiness contract and the absence of a private-key path.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  ALL_SIGNING_FAILURE_MODES,
  AZURE_SIGNING_READINESS,
  UnconfiguredAzureArtifactSigningAdapter,
  evaluateSigningReadiness,
  type SigningJobRequest,
  type SigningObservation,
} from '../src/contract/azure-signing-readiness.js';

const ARTIFACT_SHA = 'c'.repeat(64);
const SIGNATURE_SHA = 'd'.repeat(64);
const SOURCE_SHA = 'a'.repeat(40);
const IDENTITY = 'padiem-release@project';

function job(overrides: Partial<SigningJobRequest> = {}): SigningJobRequest {
  return {
    artifactPath: 'dist-package/Padiem-0.2.0-x64-setup.exe',
    expectedArtifactSha256: ARTIFACT_SHA,
    sourceSha: SOURCE_SHA,
    channel: 'internal',
    federatedToken: 'oidc.jwt.token',
    tenantId: '00000000-0000-0000-0000-000000000000',
    signingProfile: 'padiem-release',
    expectedCertificateIdentity: IDENTITY,
    ...overrides,
  } as SigningJobRequest;
}

function observation(overrides: Partial<SigningObservation> = {}): SigningObservation {
  return {
    request: job(),
    observedSigningIdentity: IDENTITY,
    observedThumbprint: 'ABC123DEF456',
    observedSignatureSha256: SIGNATURE_SHA,
    signatureVerified: true,
    ...overrides,
  } as SigningObservation;
}

test('a fully provisioned, verified signing run is ready', () => {
  const result = evaluateSigningReadiness(observation());
  assert.equal(result.status, 'READY_FOR_PROVISIONED_IDENTITY');
  assert.ok(result.evidence);
  assert.equal(result.evidence?.signingIdentity, IDENTITY);
  assert.equal(result.evidence?.signatureSha256, SIGNATURE_SHA);
});

test('a missing workload identity token fails closed', () => {
  for (const bad of ['', '   ', null, undefined]) {
    const result = evaluateSigningReadiness(observation({ request: job({ federatedToken: bad as never }) }));
    assert.equal(result.status, 'BLOCKED_NO_WORKLOAD_IDENTITY', String(bad));
    assert.equal(result.evidence, null);
  }
});

test('a missing tenant fails closed', () => {
  const result = evaluateSigningReadiness(observation({ request: job({ tenantId: '' }) }));
  assert.equal(result.status, 'BLOCKED_NO_WORKLOAD_IDENTITY');
});

test('a missing signing profile or expected identity fails closed', () => {
  assert.equal(
    evaluateSigningReadiness(observation({ request: job({ signingProfile: '' }) })).status,
    'BLOCKED_NOT_CONFIGURED',
  );
  assert.equal(
    evaluateSigningReadiness(observation({ request: job({ expectedCertificateIdentity: '' }) }))
      .status,
    'BLOCKED_NOT_CONFIGURED',
  );
});

test('unknown source provenance is refused — an unreproducible release is not signable', () => {
  for (const bad of ['', 'main', 'abc1234', 'z'.repeat(40)]) {
    const result = evaluateSigningReadiness(observation({ request: job({ sourceSha: bad }) }));
    assert.equal(result.status, 'BLOCKED_CERTIFICATE_UNAVAILABLE', bad);
    assert.equal(result.detail, 'unknown_source_provenance');
  }
});

test('a malformed artifact digest is refused', () => {
  const result = evaluateSigningReadiness(
    observation({ request: job({ expectedArtifactSha256: 'nope' }) }),
  );
  assert.equal(result.status, 'BLOCKED_CERTIFICATE_UNAVAILABLE');
  assert.equal(result.detail, 'artifact_digest_mismatch');
});

test('a revoked certificate is a hard failure regardless of a valid signature', () => {
  const result = evaluateSigningReadiness(observation({ certificateRevoked: true }));
  assert.equal(result.status, 'BLOCKED_REVOKED');
  assert.equal(result.evidence, null);
});

test('an unavailable certificate is a hard failure', () => {
  const result = evaluateSigningReadiness(
    observation({ observedSigningIdentity: null }),
  );
  assert.equal(result.status, 'BLOCKED_CERTIFICATE_UNAVAILABLE');
  assert.equal(result.evidence, null);
});

test('a signature made by an unexpected identity is refused', () => {
  const result = evaluateSigningReadiness(
    observation({ observedSigningIdentity: 'attacker@evil-project' }),
  );
  assert.equal(result.status, 'BLOCKED_IDENTITY_MISMATCH');
  assert.equal(result.evidence, null);
});

test('an unverified signature is refused', () => {
  for (const bad of [false, undefined, null]) {
    const result = evaluateSigningReadiness(observation({ signatureVerified: bad as never }));
    assert.equal(result.status, 'BLOCKED_SIGNATURE_INVALID', String(bad));
    assert.equal(result.evidence, null);
  }
});

test('incomplete signature evidence is refused even after verification', () => {
  const result = evaluateSigningReadiness(
    observation({ observedThumbprint: '', observedSignatureSha256: 'bad' }),
  );
  assert.equal(result.status, 'BLOCKED_SIGNATURE_INVALID');
  assert.equal(result.evidence, null);
});

test('a non-object observation or request fails closed', () => {
  assert.equal(
    evaluateSigningReadiness(null as never).status,
    'BLOCKED_NOT_CONFIGURED',
  );
  assert.equal(
    evaluateSigningReadiness({ request: null } as never).status,
    'BLOCKED_NOT_CONFIGURED',
  );
});

test('every failure mode is a hard failure that yields no evidence', () => {
  // A sweep proving no failure mode can leak a success verdict.
  const broken: SigningObservation[] = [
    observation({ request: job({ federatedToken: '' }) }),
    observation({ request: job({ tenantId: '' }) }),
    observation({ request: job({ signingProfile: '' }) }),
    observation({ request: job({ expectedCertificateIdentity: '' }) }),
    observation({ request: job({ sourceSha: 'main' }) }),
    observation({ request: job({ expectedArtifactSha256: 'x' }) }),
    observation({ observedSigningIdentity: 'someone-else' }),
    observation({ certificateRevoked: true }),
    observation({ observedSigningIdentity: null }),
    observation({ signatureVerified: false }),
  ];
  for (const item of broken) {
    const result = evaluateSigningReadiness(item);
    assert.notEqual(result.status, 'READY_FOR_PROVISIONED_IDENTITY');
    assert.equal(result.evidence, null);
    assert.ok(
      ALL_SIGNING_FAILURE_MODES.includes(result.detail as never),
      `undocumented failure detail: ${result.detail}`,
    );
  }
});

test('the shipped adapter is unconfigured and refuses every request without I/O', () => {
  const adapter = new UnconfiguredAzureArtifactSigningAdapter();
  assert.equal(adapter.isConfigured(), false);
  assert.equal(adapter.liveSigningConfigured, false);
  const result = adapter.sign(job());
  assert.equal(result.status, 'BLOCKED_NOT_CONFIGURED');
  assert.equal(result.evidence, null);
  assert.match(result.detail, /no Azure Artifact Signing adapter is configured/);
});

test('SigningJobRequest exposes no private-key or long-lived-secret field', () => {
  // Type-shape proof, not a text match. A raw substring scan would false-positive
  // on the module's own NEGATIVE declarations (`PRIVATE_PFX_SUPPORTED_BY_CONTRACT
  // = false`) and on the comment listing the fields that are deliberately absent.
  // What matters is that the request interface itself cannot carry key material.
  const forbidden = [
    'pfx',
    'pfxPath',
    'pfxPassword',
    'certificateFile',
    'privateKey',
    'private_key',
    'keystore',
    'keystorePassword',
    'clientSecret',
    'signingSecret',
    'password',
  ];
  for (const field of Object.keys(job())) {
    assert.equal(
      forbidden.some((bad) => field.toLowerCase().includes(bad.toLowerCase())),
      false,
      `SigningJobRequest must not carry ${field}`,
    );
  }
  // And the compiled type surface must not have grown such a field either.
  const declared = readSigningSource().match(
    /export interface SigningJobRequest \{([\s\S]*?)\n\}/,
  );
  assert.ok(declared, 'SigningJobRequest interface must exist');
  const body = declared[1] ?? '';
  for (const bad of ['pfx', 'privatekey', 'certificatefile', 'clientsecret', 'signingsecret']) {
    assert.equal(
      body.toLowerCase().includes(bad),
      false,
      `SigningJobRequest interface must not declare ${bad}`,
    );
  }
});

test('the signing contract asserts the absence of key material structurally', () => {
  // The flags are part of the exported contract, so the absence claim is
  // machine-checkable rather than only written in a comment.
  assert.equal(AZURE_SIGNING_READINESS.PRIVATE_PFX_SUPPORTED_BY_CONTRACT, false);
  assert.equal(AZURE_SIGNING_READINESS.LONG_LIVED_SIGNING_SECRET_SUPPORTED, false);
  assert.equal(AZURE_SIGNING_READINESS.PRIVATE_PFX_IN_REPO, false);
});

test('the readiness contract claims no live signing and no cloud mutation', () => {
  assert.equal(AZURE_SIGNING_READINESS.LIVE_SIGNING_CONFIGURED, false);
  assert.equal(AZURE_SIGNING_READINESS.AZURE_ARTIFACT_SIGNING_LIVE, false);
  assert.equal(AZURE_SIGNING_READINESS.PRIVATE_PFX_IN_REPO, false);
  assert.equal(AZURE_SIGNING_READINESS.PRIVATE_PFX_SUPPORTED_BY_CONTRACT, false);
  assert.equal(AZURE_SIGNING_READINESS.LONG_LIVED_SIGNING_SECRET_SUPPORTED, false);
  assert.equal(AZURE_SIGNING_READINESS.ENTRA_TENANT_CREATED, false);
  assert.equal(AZURE_SIGNING_READINESS.SERVICE_PRINCIPAL_CREATED, false);
  assert.equal(AZURE_SIGNING_READINESS.ELECTRON_BUILDER_AZURE_BETA_ADAPTER_CANONICAL, false);
  assert.equal(AZURE_SIGNING_READINESS.PRODUCTION_SIGNING_AUTHORITY, 'AZURE_ARTIFACT_SIGNING');
  assert.equal(AZURE_SIGNING_READINESS.GITHUB_OIDC_FIRST, true);
  assert.equal(AZURE_SIGNING_READINESS.REVOCATION_FAIL_CLOSED, true);
  assert.equal(AZURE_SIGNING_READINESS.IDENTITY_MISMATCH_FAIL_CLOSED, true);
  assert.equal(AZURE_SIGNING_READINESS.SIGNATURE_VERIFICATION_FAIL_CLOSED, true);
});

test('the readiness module performs no network or process work', () => {
  const source = readSigningSource();
  for (const forbidden of ['fetch(', 'https://', 'child_process', 'execSync', 'spawn(']) {
    assert.equal(
      source.includes(forbidden),
      false,
      `readiness contract must not perform live work: ${forbidden}`,
    );
  }
});

/**
 * Read the TypeScript SOURCE, not the compiled output.
 *
 * These assertions are about the shape of the source text, so they must read
 * the .ts file. The compiled test lives in `dist/tests/`, so the source sits at
 * `../../src/contract/` relative to this module.
 */
function readSigningSource(): string {
  const url = new URL('../../src/contract/azure-signing-readiness.ts', import.meta.url);
  return readFileSync(url, 'utf8');
}
