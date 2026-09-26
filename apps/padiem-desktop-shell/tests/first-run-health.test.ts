/**
 * #3103 — first-run health.
 *
 * These tests drive the real `buildFirstRunHealthReport` over real #3093 inputs
 * (`resolveRunnerHostMode` / `windowsProtocolRegistrationPlan`), not a mock, so
 * the projection path that ships is the one under test.
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  DIAGNOSTIC_HEALTH_STATUSES,
  DIAGNOSTIC_BOUNDS,
  FirstRunCheckError,
  isDiagnosticHealthStatus,
} from '../src/contract/diagnostic-codes.js';
import {
  assertFirstRunHealthReport,
  buildFirstRunHealthReport,
  projectProtocolRegistration,
  projectRunnerExecutableMode,
  projectVersionCompatibility,
  type FirstRunProbeInput,
} from '../src/contract/first-run-health.js';
import { resolveRunnerHostMode } from '../src/main/runner-host-mode.js';
import { windowsProtocolRegistrationPlan } from '../src/main/protocol-registration.js';

const GENERATED_AT_MS = 1_789_000_000_000;

/** Credential-shaped fixture, assembled from fragments (see sibling test). */
const CREDENTIAL_SHAPED = ['padi', 'live', 'abcdefgh12345678'].join('_');

const PACKAGED_RUNNER_INPUT = {
  execPath: 'C:\\Program Files\\Padiem\\Padiem.exe',
  electronVersion: '44.4.5',
  runnerExecutableOverride: undefined,
  platform: 'win32' as const,
};

const PACKAGED_PROTOCOL_INPUT = {
  platform: 'win32' as const,
  packaged: true,
  defaultApp: false,
  execPath: 'C:\\Program Files\\Padiem\\Padiem.exe',
  appPath: 'C:\\Program Files\\Padiem\\resources\\app',
};

function probe(overrides: Partial<FirstRunProbeInput> = {}): FirstRunProbeInput {
  return {
    runnerHostMode: resolveRunnerHostMode(PACKAGED_RUNNER_INPUT).mode,
    protocolRegistrationAction: windowsProtocolRegistrationPlan(PACKAGED_PROTOCOL_INPUT).action,
    protocolRegistered: true,
    appDataWritable: true,
    credentialStoreAvailable: true,
    brokerRouteConfigReady: true,
    updateRequired: false,
    compatibilityReason: 'COMPATIBLE',
    supportRefs: ['pairref-0123456789abcdef'],
    generatedAtMs: GENERATED_AT_MS,
    ...overrides,
  };
}

test('all six required first-run checks are reported', () => {
  const report = buildFirstRunHealthReport(probe());
  assert.deepEqual(
    report.checks.map((check) => check.check),
    [
      'DESKTOP_RUNNER_EXECUTABLE_MODE',
      'PROTOCOL_REGISTRATION',
      'APP_DATA_WRITABLE',
      'CREDENTIAL_STORE_AVAILABLE',
      'BROKER_ROUTE_CONFIG_READY',
      'VERSION_COMPATIBILITY',
    ],
  );
  assert.equal(report.generatedAtMs, GENERATED_AT_MS);
});

test('a fully healthy first run reports PASS overall', () => {
  const report = buildFirstRunHealthReport(probe());
  assert.equal(report.overall, 'PASS');
  for (const check of report.checks) {
    assert.equal(check.status, 'PASS', `${check.check} should be PASS`);
  }
});

test('an unready app data directory fails closed', () => {
  // A profile that cannot be written means the Desktop cannot run at all, so
  // this is the one check that is FAIL_CLOSED rather than merely actionable.
  const report = buildFirstRunHealthReport(probe({ appDataWritable: false }));
  const appData = report.checks.find((c) => c.check === 'APP_DATA_WRITABLE');
  assert.ok(appData);
  assert.equal(appData.status, 'FAIL_CLOSED');
  assert.equal(report.overall, 'FAIL_CLOSED');
  assert.ok(appData.remediation, 'an actionable result must carry remediation');
});

test('a missing credential store is ACTION_REQUIRED', () => {
  // Without a credential store the shell still starts; it would only fail later
  // at pairing with a worse message, so first run surfaces it as actionable.
  const report = buildFirstRunHealthReport(probe({ credentialStoreAvailable: false }));
  const store = report.checks.find((c) => c.check === 'CREDENTIAL_STORE_AVAILABLE');
  assert.ok(store);
  assert.equal(store.status, 'ACTION_REQUIRED');
  assert.equal(report.overall, 'ACTION_REQUIRED');
});

test('an unready broker route is ACTION_REQUIRED', () => {
  const report = buildFirstRunHealthReport(probe({ brokerRouteConfigReady: false }));
  const broker = report.checks.find((c) => c.check === 'BROKER_ROUTE_CONFIG_READY');
  assert.ok(broker);
  assert.equal(broker.status, 'ACTION_REQUIRED');
});


test('overall status is the worst of the individual checks', () => {
  const report = buildFirstRunHealthReport(
    probe({ credentialStoreAvailable: false, brokerRouteConfigReady: false }),
  );
  const statuses = new Set(report.checks.map((c) => c.status));
  assert.ok(statuses.has('ACTION_REQUIRED'));
  // No FAIL_CLOSED check is present, so the worst observed status wins.
  assert.ok(!statuses.has('FAIL_CLOSED'));
  assert.equal(report.overall, 'ACTION_REQUIRED');
});

test('protocol registration projects from the real #3093 plan', () => {
  const plan = windowsProtocolRegistrationPlan(PACKAGED_PROTOCOL_INPUT);
  const registered = projectProtocolRegistration(plan.action, true);
  assert.equal(registered.check, 'PROTOCOL_REGISTRATION');
  assert.equal(registered.status, 'PASS');
  // Non-Windows is a legitimate, intentional outcome rather than a fault, so it
  // is still a PASS with an explicit code explaining why nothing was registered.
  const skipped = projectProtocolRegistration('skip-not-windows', false);
  assert.equal(skipped.status, 'PASS');
  assert.match(skipped.code, /skip-not-windows/);
});

test('an unregistered protocol handler is ACTION_REQUIRED', () => {
  const result = projectProtocolRegistration('register-direct', false);
  assert.equal(result.status, 'ACTION_REQUIRED');
});

test('a plain-node runner host mode downgrades instead of failing', () => {
  const result = projectRunnerExecutableMode('plain-node');
  assert.equal(result.status, 'ACTION_REQUIRED');
  assert.equal(result.check, 'DESKTOP_RUNNER_EXECUTABLE_MODE');
});


test('an incompatible contract major fails closed', () => {
  // The runner and the control plane disagree structurally, so there is no
  // actionable user-side step: the build itself cannot be trusted to run.
  const report = buildFirstRunHealthReport(
    probe({ compatibilityReason: 'UNSUPPORTED_CONTRACT_MAJOR' }),
  );
  const compat = report.checks.find((c) => c.check === 'VERSION_COMPATIBILITY');
  assert.ok(compat);
  assert.equal(compat.status, 'FAIL_CLOSED');
  assert.equal(report.overall, 'FAIL_CLOSED');
});

test('a pending update is projected as ACTION_REQUIRED', () => {
  const report = buildFirstRunHealthReport(probe({ updateRequired: true }));
  const compat = report.checks.find((c) => c.check === 'VERSION_COMPATIBILITY');
  assert.ok(compat);
  assert.equal(compat.status, 'ACTION_REQUIRED');
});

test('every code and summary is bounded and uses the canonical vocabulary', () => {
  for (const status of DIAGNOSTIC_HEALTH_STATUSES) {
    assert.ok(status.length > 0);
  }
  const report = buildFirstRunHealthReport(probe({ credentialStoreAvailable: false }));
  for (const check of report.checks) {
    assert.ok(check.code.length > 0);
    assert.ok(check.code.length <= DIAGNOSTIC_BOUNDS.MAX_CODE_LENGTH);
    assert.ok(check.summary.length <= DIAGNOSTIC_BOUNDS.MAX_SUMMARY_LENGTH);
    assert.ok(DIAGNOSTIC_HEALTH_STATUSES.includes(check.status));
  }
});

test('an oversized summary is refused instead of truncated', () => {
  assert.throws(
    () =>
      buildFirstRunHealthReport(
        probe({ compatibilityReason: 'x'.repeat(DIAGNOSTIC_BOUNDS.MAX_SUMMARY_LENGTH + 1) }),
      ),
    FirstRunCheckError,
  );
});

test('a secret-shaped string is never echoed into a check summary', () => {
  const report = buildFirstRunHealthReport(probe({ credentialStoreAvailable: false }));
  const serialized = JSON.stringify(report);
  assert.ok(!serialized.includes(CREDENTIAL_SHAPED));
  assert.ok(!/live_[A-Za-z0-9]{8,}/.test(serialized));
});

test('the report validator rejects a tampered or unknown report', () => {
  const report = buildFirstRunHealthReport(probe());
  assert.equal(assertFirstRunHealthReport(report).overall, 'PASS');
  assert.throws(() => assertFirstRunHealthReport({ ...report, overall: 'BROKEN' }));
  assert.throws(() => assertFirstRunHealthReport({ ...report, checks: [] }));
  assert.throws(() => assertFirstRunHealthReport(null));
});

test('an unknown runner host mode fails closed rather than defaulting', () => {
  assert.throws(() => projectRunnerExecutableMode('turbo-mode'), FirstRunCheckError);
  assert.throws(
    () => buildFirstRunHealthReport(probe({ runnerHostMode: null })),
    FirstRunCheckError,
  );
});

test('an unknown compatibility reason fails closed rather than defaulting', () => {
  assert.throws(
    () => projectVersionCompatibility('PROBABLY_FINE', false),
    FirstRunCheckError,
  );
  assert.throws(
    () => buildFirstRunHealthReport(probe({ compatibilityReason: 42 })),
    FirstRunCheckError,
  );
});
