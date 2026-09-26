/**
 * CLAW3 #3101 M2/G2 — installed-version authority, update/rollback tests.
 *
 * These call the real `evaluateVersionTransition`. No mock stands in for the
 * version or compatibility path: a stubbed decision function would assert
 * nothing about the contract under test.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  ALLOWED_VERSION_DECISIONS,
  DURABLE_RUN_SEPARATION,
  INSTALLED_VERSION_AUTHORITY,
  compareVersions,
  evaluateVersionTransition,
  isInstallAllowed,
  normaliseSha,
  parseVersion,
  type ReleaseCompatibility,
  type VersionTransitionRequest,
} from '../src/contract/release-version-transition.js';

const COMPAT: ReleaseCompatibility = Object.freeze({
  minSchemaVersion: '0.1.0',
  maxSchemaVersion: '2.0.0',
  minRuntimeMajor: 22,
  rollbackEligible: true,
});

const SHA_A = 'a'.repeat(64);
const SHA_B = 'b'.repeat(64);

function request(overrides: Partial<VersionTransitionRequest> = {}): VersionTransitionRequest {
  return {
    installedVersion: '0.1.0',
    targetVersion: '0.2.0',
    compatibility: COMPAT,
    ...overrides,
  } as VersionTransitionRequest;
}

test('version parsing accepts only exact three-part semver', () => {
  assert.deepEqual(parseVersion('1.2.3'), { major: 1, minor: 2, patch: 3 });
  assert.deepEqual(parseVersion('0.0.0'), { major: 0, minor: 0, patch: 0 });
  for (const bad of ['1.2', '1.2.3.4', 'v1.2.3', '01.2.3', '1.2.3-rc1', '', 'x', null, 42]) {
    assert.equal(parseVersion(bad as unknown), null, `expected null for ${String(bad)}`);
  }
});

test('version comparison is numeric per component, not lexical', () => {
  const a = parseVersion('0.10.0')!;
  const b = parseVersion('0.9.0')!;
  assert.equal(compareVersions(a, b), 1, '0.10.0 must sort above 0.9.0');
  assert.equal(compareVersions(b, a), -1);
  assert.equal(compareVersions(a, a), 0);
});

test('a supported upgrade is authorised and installs app bytes only', () => {
  const verdict = evaluateVersionTransition(request());
  assert.equal(verdict.decision, 'INSTALL');
  assert.equal(verdict.mayInstallAppBytes, true);
  assert.equal(verdict.mayReplayLocalRun, false);
  assert.equal(verdict.mayRewriteDurableRunState, false);
  assert.equal(isInstallAllowed(verdict.decision), true);
});

test('unknown installed version fails closed', () => {
  for (const bad of [null, undefined, '', 'unknown', 'not-a-version']) {
    const verdict = evaluateVersionTransition(request({ installedVersion: bad as never }));
    assert.equal(verdict.decision, 'REJECT_UNKNOWN_INSTALLED_VERSION', String(bad));
    assert.equal(verdict.mayInstallAppBytes, false);
  }
});

test('unknown target version fails closed', () => {
  for (const bad of [null, undefined, '', 'latest', '0.2']) {
    const verdict = evaluateVersionTransition(request({ targetVersion: bad as never }));
    assert.equal(verdict.decision, 'REJECT_UNKNOWN_TARGET_VERSION', String(bad));
    assert.equal(verdict.mayInstallAppBytes, false);
  }
});

test('an undeclared compatibility contract fails closed rather than assuming', () => {
  for (const bad of [null, undefined, {} as ReleaseCompatibility]) {
    const verdict = evaluateVersionTransition(request({ compatibility: bad as never }));
    assert.equal(verdict.decision, 'REJECT_INCOMPATIBLE_SCHEMA', String(bad));
    assert.equal(verdict.mayInstallAppBytes, false);
  }
});

test('an unreadable or inverted schema range fails closed', () => {
  const unreadable = evaluateVersionTransition(
    request({ compatibility: { ...COMPAT, minSchemaVersion: 'x' } }),
  );
  assert.equal(unreadable.decision, 'REJECT_INCOMPATIBLE_SCHEMA');

  const inverted = evaluateVersionTransition(
    request({ compatibility: { ...COMPAT, minSchemaVersion: '3.0.0', maxSchemaVersion: '1.0.0' } }),
  );
  assert.equal(inverted.decision, 'REJECT_INCOMPATIBLE_SCHEMA');
  assert.match(inverted.reason, /inverted/);
});

test('an unreadable runtime floor fails closed', () => {
  for (const bad of [0, -1, 1.5, 'twenty-two']) {
    const verdict = evaluateVersionTransition(
      request({ compatibility: { ...COMPAT, minRuntimeMajor: bad as never } }),
    );
    assert.equal(verdict.decision, 'REJECT_INCOMPATIBLE_RUNTIME', String(bad));
  }
});

test('schema incompatibility blocks the install', () => {
  // Installed 0.1.0 is below this release's declared floor.
  const verdict = evaluateVersionTransition(
    request({
      installedVersion: '0.0.5',
      targetVersion: '0.2.0',
      compatibility: { ...COMPAT, minSchemaVersion: '0.1.0' },
    }),
  );
  assert.equal(verdict.decision, 'REJECT_INCOMPATIBLE_SCHEMA');
  assert.equal(verdict.mayInstallAppBytes, false);
});

test('an upgrade beyond the declared schema ceiling is refused', () => {
  const verdict = evaluateVersionTransition(
    request({
      installedVersion: '0.1.0',
      targetVersion: '0.2.0',
      compatibility: { ...COMPAT, minSchemaVersion: '0.2.0', maxSchemaVersion: '0.9.0' },
    }),
  );
  assert.equal(verdict.decision, 'REJECT_INCOMPATIBLE_SCHEMA');
});

test('a downgrade without explicit rollback intent is refused', () => {
  const verdict = evaluateVersionTransition(
    request({ installedVersion: '0.2.0', targetVersion: '0.1.0' }),
  );
  assert.equal(verdict.decision, 'REJECT_UNSUPPORTED_DOWNGRADE');
  assert.equal(verdict.mayInstallAppBytes, false);
});

test('a downgrade of a rollback-ineligible release is refused even with intent', () => {
  const verdict = evaluateVersionTransition(
    request({
      installedVersion: '0.2.0',
      targetVersion: '0.1.0',
      intent: 'rollback',
      compatibility: { ...COMPAT, rollbackEligible: false },
    }),
  );
  assert.equal(verdict.decision, 'REJECT_UNSUPPORTED_DOWNGRADE');
  assert.match(verdict.reason, /not rollback eligible/);
});

test('an explicit rollback to an eligible release installs bytes only', () => {
  const verdict = evaluateVersionTransition(
    request({ installedVersion: '0.2.0', targetVersion: '0.1.0', intent: 'rollback' }),
  );
  assert.equal(verdict.decision, 'INSTALL');
  assert.equal(verdict.mayInstallAppBytes, true);
});

test('ROLLBACK_REPLAYS_LOCAL_RUN is NO — rollback never authorises replay', () => {
  const rollback = evaluateVersionTransition(
    request({ installedVersion: '0.2.0', targetVersion: '0.1.0', intent: 'rollback' }),
  );
  assert.equal(rollback.mayReplayLocalRun, false);
  assert.equal(rollback.mayRewriteDurableRunState, false);
  assert.equal(INSTALLED_VERSION_AUTHORITY.ROLLBACK_REPLAYS_LOCAL_RUN, false);
  assert.equal(INSTALLED_VERSION_AUTHORITY.UPDATE_REPLAYS_TERMINAL_RUN, false);
});

test('no decision can ever authorise replay or durable-state rewrite', () => {
  const cases: VersionTransitionRequest[] = [
    request(),
    request({ installedVersion: '0.2.0', targetVersion: '0.1.0', intent: 'rollback' }),
    request({ installedVersion: 'nope' }),
    request({ compatibility: null as never }),
    request({ targetVersion: 'nope' }),
  ];
  for (const c of cases) {
    const verdict = evaluateVersionTransition(c);
    assert.equal(verdict.mayReplayLocalRun, false);
    assert.equal(verdict.mayRewriteDurableRunState, false);
  }
});

test('the same version is never a publishable transition', () => {
  const verdict = evaluateVersionTransition(
    request({ installedVersion: '0.1.0', targetVersion: '0.1.0' }),
  );
  assert.equal(verdict.decision, 'REJECT_SAME_VERSION_REPUBLISH');
  assert.equal(verdict.mayInstallAppBytes, false);
});

test('a different artifact claiming the installed version is refused', () => {
  const verdict = evaluateVersionTransition(
    request({
      installedVersion: '0.1.0',
      targetVersion: '0.1.0',
      installedArtifactSha256: SHA_A,
      targetArtifactSha256: SHA_B,
    }),
  );
  assert.equal(verdict.decision, 'REJECT_IDENTITY_MISMATCH');
  assert.match(verdict.reason, /silent overwrite refused/);
});

test('an identical re-claim of the installed version is still refused', () => {
  const verdict = evaluateVersionTransition(
    request({
      installedVersion: '0.1.0',
      targetVersion: '0.1.0',
      installedArtifactSha256: SHA_A,
      targetArtifactSha256: SHA_A,
    }),
  );
  assert.equal(verdict.decision, 'REJECT_SAME_VERSION_REPUBLISH');
});

test('every emitted decision is inside the closed contract set', () => {
  const cases = [
    request(),
    request({ installedVersion: 'bad' }),
    request({ targetVersion: 'bad' }),
    request({ compatibility: null as never }),
    request({ installedVersion: '0.2.0', targetVersion: '0.1.0' }),
    request({ installedVersion: '0.1.0', targetVersion: '0.1.0' }),
  ];
  for (const c of cases) {
    const verdict = evaluateVersionTransition(c);
    assert.ok(
      ALLOWED_VERSION_DECISIONS.includes(verdict.decision),
      `decision leaked outside the contract: ${verdict.decision}`,
    );
  }
});

test('a non-object request fails closed', () => {
  for (const bad of [null, undefined, 'request', 7]) {
    const verdict = evaluateVersionTransition(bad as never);
    assert.equal(verdict.mayInstallAppBytes, false);
    assert.ok(ALLOWED_VERSION_DECISIONS.includes(verdict.decision));
  }
});

test('INSTALLED_VERSION_AUTHORITY_COUNT is exactly 1', () => {
  assert.equal(INSTALLED_VERSION_AUTHORITY.AUTHORITY_COUNT, 1);
  assert.equal(INSTALLED_VERSION_AUTHORITY.DECISION_FUNCTION, 'evaluateVersionTransition');
});

test('the version authority declares its separation from durable run truth', () => {
  assert.equal(DURABLE_RUN_SEPARATION.versionAuthorityOwnsDurableState, false);
  assert.equal(DURABLE_RUN_SEPARATION.versionTransitionReadsDurableStore, false);
  assert.equal(DURABLE_RUN_SEPARATION.terminalRunBecomesReplayCandidate, false);
  assert.equal(DURABLE_RUN_SEPARATION.brokerCommandStateOwnedHere, false);
  assert.equal(DURABLE_RUN_SEPARATION.conversationOrTaskStateOwnedHere, false);
  assert.equal(INSTALLED_VERSION_AUTHORITY.DURABLE_STATE_READ_BY_VERSION_AUTHORITY, false);
  assert.equal(INSTALLED_VERSION_AUTHORITY.IMPORTS_3082_STORE_INTERNALS, false);
});

test('the module imports no #3082 durable-run store internals', () => {
  // Structural, not a comment: the source must not reach into a durable store
  // or a broker module. #3082 is unmerged, so coupling here would be premature.
  const url = new URL('../../src/contract/release-version-transition.ts', import.meta.url);
  const source = readFileSyncSafe(url);
  assert.ok(source.length > 0, 'source must be readable');
  for (const forbidden of [
    'local_agent_durable_run',
    'durable_run_store',
    'local_agent_broker',
    'windows_local_executor',
    'kagent',
  ]) {
    assert.equal(
      source.includes(forbidden),
      false,
      `version authority must not import or name ${forbidden}`,
    );
  }
});

test('sha normalisation accepts only a full lowercase-or-uppercase digest', () => {
  assert.equal(normaliseSha(SHA_A.toUpperCase()), SHA_A);
  assert.equal(normaliseSha(` ${SHA_A} `), SHA_A);
  for (const bad of [SHA_A.slice(0, 63), 'g'.repeat(64), '', null, 12]) {
    assert.equal(normaliseSha(bad as unknown), null, String(bad));
  }
});

function readFileSyncSafe(url: URL): string {
  return readFileSync(url, 'utf8');
}

/**
 * Read the TypeScript SOURCE. These assertions describe the shape of the source
 * text, so they must not read the compiled output. The compiled test lives in
 * `dist/tests/`, so the source is at `../../src/contract/`.
 */
function readVersionSource(): string {
  return readFileSync(
    new URL('../../src/contract/release-version-transition.ts', import.meta.url),
    'utf8',
  );
}
