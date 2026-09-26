/**
 * #3103 — secret-free support bundle, bounded export, and the #3082 health seam.
 *
 * The bundle is built and exported through the real `diagnostics-exporter`
 * product path. Secret fixtures are assembled from fragments so the repository
 * stays scanner-clean while the negative assertions stay real.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  BUNDLE_SECTIONS,
  BUNDLE_SECTION_IDS,
  SUPPORT_BUNDLE_CONTRACT,
  SupportBundleError,
  buildSupportBundle,
  exportSupportBundleText,
  redactSupportBundleText,
  serializeSupportBundle,
  supportBundleFileName,
  type SupportBundleInput,
} from '../src/contract/support-bundle.js';
import { DIAGNOSTIC_BOUNDS } from '../src/contract/diagnostic-codes.js';
import {
  DURABLE_STORE_SEAM,
  DurableStoreHealthError,
  coerceDurableStoreHealth,
  unimplementedDurableStoreHealth,
  unimplementedDurableStoreHealthPort,
  type DurableStoreHealthPort,
} from '../src/contract/durable-store-health-seam.js';
import {
  buildFirstRunHealthReport,
  type FirstRunHealthReport,
  type FirstRunProbeInput,
} from '../src/contract/first-run-health.js';
import {
  buildAndExportSupportBundle,
  buildDesktopDiagnostics,
  exportSupportBundle,
  type DiagnosticsProbeInput,
} from '../src/main/diagnostics-exporter.js';
import { resolveRunnerHostMode, type RunnerHostModeInput } from '../src/main/runner-host-mode.js';
import {
  windowsProtocolRegistrationPlan,
  type ProtocolRegistrationInput,
} from '../src/main/protocol-registration.js';

/** Credential-shaped fixtures, assembled from fragments so scanning stays clean. */
const DEVICE_CREDENTIAL = ['padi', 'dev', 'A1B2C3D4E5F6A7B8C9D0E1F2'].join('_');
const PAIRING_TOKEN = ['pair', '01HQZX', '9K2MNP4R'].join('-');
const BEARER_TOKEN = ['Bearer', 'eyJhbGciOi', 'JIUzI1NiJ9.payload.sig'].join(' ');

const GENERATED_AT = '2026-09-26T08:00:00.000Z';
const GENERATED_AT_MS = 1_789_000_000_000;

const RUNNER_INPUT: RunnerHostModeInput = {
  execPath: 'C:\\Program Files\\Padiem\\Padiem.exe',
  electronVersion: '44.4.5',
  runnerExecutableOverride: undefined,
  platform: 'win32',
};

const PROTOCOL_INPUT: ProtocolRegistrationInput = {
  platform: 'win32',
  packaged: true,
  defaultApp: false,
  execPath: 'C:\\Program Files\\Padiem\\Padiem.exe',
  appPath: 'C:\\Program Files\\Padiem\\resources\\app',
};

function firstRunInput(overrides: Partial<FirstRunProbeInput> = {}): FirstRunProbeInput {
  return {
    runnerHostMode: resolveRunnerHostMode(RUNNER_INPUT).mode,
    protocolRegistrationAction: windowsProtocolRegistrationPlan(PROTOCOL_INPUT).action,
    protocolRegistered: true,
    appDataWritable: true,
    credentialStoreAvailable: true,
    brokerRouteConfigReady: true,
    updateRequired: false,
    compatibilityReason: 'COMPATIBLE',
    generatedAtMs: GENERATED_AT_MS,
    ...overrides,
  };
}

function firstRun(overrides: Partial<FirstRunProbeInput> = {}): FirstRunHealthReport {
  return buildFirstRunHealthReport(firstRunInput(overrides));
}


function bundleInput(overrides: Partial<SupportBundleInput> = {}): SupportBundleInput {
  return {
    generatedAt: GENERATED_AT,
    appVersion: '0.1.0',
    buildId: 'build-3103',
    platform: 'win32',
    arch: 'x64',
    electronMajor: 44,
    deviceState: 'PAIRED',
    deviceStatus: 'PASS',
    deviceCode: 'device_paired',
    deviceSummary: 'device is paired and ready',
    credentialGeneration: 3,
    lastSuccessfulSessionAt: GENERATED_AT,
    lastSuccessfulHeartbeatAt: GENERATED_AT,
    pairingCategory: 'paired',
    pairingStatus: 'PASS',
    pairingCode: 'pairing.paired',
    pairingSummary: 'pairing is active',
    updateRequired: false,
    updateStatus: 'PASS',
    updateCode: 'update_not_required',
    updateSummary: 'this build is current',
    runnerLifecycleState: 'running',
    runnerHostMode: resolveRunnerHostMode(RUNNER_INPUT).mode,
    protocolRegistrationAction: windowsProtocolRegistrationPlan(PROTOCOL_INPUT).action,
    protocolRegistered: true,
    runnerStatus: 'PASS',
    runnerCode: 'runner.explicit_executable',
    runnerSummary: 'the local runner host mode is resolved',
    durableStoreHealth: unimplementedDurableStoreHealth(),
    compatibilityReason: 'COMPATIBLE',
    compatibilityStatus: 'PASS',
    compatibilityCode: 'compatibility.compatible',
    compatibilitySummary: 'runtime/host contract compatibility is satisfied',
    supportRefs: ['pairref-0123456789abcdef'],
    firstRun: firstRun(),
    ...overrides,
  };
}

/** The main-process probe input, with the #3093 sources left to be resolved. */
function probeInput(overrides: Partial<DiagnosticsProbeInput> = {}): DiagnosticsProbeInput {
  return {
    appVersion: '0.1.0',
    buildId: 'build-3103',
    platform: 'win32',
    arch: 'x64',
    electronMajor: 44,
    runnerHostModeInput: RUNNER_INPUT,
    protocolRegistrationInput: PROTOCOL_INPUT,
    deviceLifecycle: {
      state: 'ONLINE',
      sinceRevision: 4,
      reason: 'runner reported ready',
      evidenceBacked: true,
    },
    protocolRegistered: true,
    credentialGeneration: 3,
    lastSuccessfulSessionAt: GENERATED_AT,
    lastSuccessfulHeartbeatAt: GENERATED_AT,
    pendingPairingCode: null,
    updateRequired: false,
    runnerLifecycleState: 'running',
    compatibilityReason: 'COMPATIBLE',
    appDataWritable: true,
    credentialStoreAvailable: true,
    brokerRouteConfigReady: true,
    now: new Date(GENERATED_AT),
    supportRefs: ['pairref-0123456789abcdef'],
    ...overrides,
  };
}


// ---------------------------------------------------------------------------
// Bundle shape and required diagnostic coverage
// ---------------------------------------------------------------------------

test('the bundle contains every required diagnostic section', () => {
  const bundle = buildSupportBundle(bundleInput());
  for (const section of BUNDLE_SECTION_IDS) {
    assert.ok(
      bundle.sections.some((entry) => entry.id === section),
      `missing section ${section}`,
    );
  }
  const text = serializeSupportBundle(bundle);
  // Asserted against the *serialised* keys, not the builder input names: a
  // value that is accepted but never written out helps the user not at all.
  for (const needle of [
    '"appVersion"',
    '"lastSuccessfulSessionAt"',
    '"lastSuccessfulHeartbeatAt"',
    '"id": "pairing"',
    '"healthCategory"',
    '"firstRun"',
    '"supportRefs"',
  ]) {
    assert.ok(text.includes(needle), `bundle is missing ${needle}`);
  }
});

test('the bundle projects the first-run report and correlation refs', () => {
  // These two are the point of the bundle for an alpha user: the six first-run
  // checks must be individually readable, and support must be able to join a
  // report to a session. Asserted on the serialised text, not just the object,
  // because a value that is built but not serialised helps nobody.
  const bundle = buildSupportBundle(bundleInput());
  const payload = JSON.parse(serializeSupportBundle(bundle)) as {
    firstRun: { overall: string; checks: { code: string }[] };
    supportRefs: string[];
  };
  assert.equal(payload.firstRun.overall, firstRun().overall);
  assert.equal(payload.firstRun.checks.length, firstRun().checks.length);
  assert.deepEqual(payload.supportRefs, ['pairref-0123456789abcdef']);
  // A hand-built bundle cannot smuggle an unsafe ref past the serialiser.
  const tampered = { ...bundle, supportRefs: ['not a safe ref'] };
  assert.throws(() => serializeSupportBundle(tampered), SupportBundleError);
});

test('the bundle is local-only and never auto-uploads', () => {
  assert.equal(SUPPORT_BUNDLE_CONTRACT.LOCAL_ONLY, true);
  assert.equal(SUPPORT_BUNDLE_CONTRACT.AUTO_UPLOAD, false);
  // Counters, not booleans: the handoff states these as `TELEMETRY_UPLOAD=0`,
  // so a count of zero is the asserted form and `false` is not interchangeable.
  assert.equal(SUPPORT_BUNDLE_CONTRACT.TELEMETRY_UPLOAD, 0);
  assert.equal(SUPPORT_BUNDLE_CONTRACT.SECRET_OUTPUT, 0);
  assert.equal(SUPPORT_BUNDLE_CONTRACT.RAW_TASK_PAYLOAD, 0);
  assert.equal(SUPPORT_BUNDLE_CONTRACT.RAW_STDOUT_STDERR, 0);
  assert.equal(SUPPORT_BUNDLE_CONTRACT.RAW_ARGV, 0);
});

// ---------------------------------------------------------------------------
// SECRET_OUTPUT = 0 — the core negative tests
// ---------------------------------------------------------------------------

test('a healthy bundle contains no secret of any shape', () => {
  const text = exportSupportBundleText(bundleInput());
  for (const secret of [DEVICE_CREDENTIAL, PAIRING_TOKEN, BEARER_TOKEN]) {
    assert.ok(!text.includes(secret), 'a secret leaked into the bundle');
  }
  assert.ok(!/padi_(dev|live)_[A-Za-z0-9]{8,}/.test(text));
  assert.ok(!/Bearer\s+\S+/.test(text));
});

test('a raw #3095 pairing code never reaches the exported file', async () => {
  // `pendingPairingCode` is the real raw code the main process holds. The
  // exporter must reduce it to its support-safe marker and never project it.
  const directory = mkdtempSync(join(tmpdir(), 'padiem-bundle-'));
  try {
    const exported = await buildAndExportSupportBundle(
      probeInput({ pendingPairingCode: PAIRING_TOKEN }),
      directory,
    );
    const onDisk = readFileSync(exported.filePath, 'utf8');
    for (const secret of [PAIRING_TOKEN, DEVICE_CREDENTIAL]) {
      assert.ok(!onDisk.includes(secret), 'a raw secret reached the exported file');
    }
    // The marker is support-safe and lets support correlate without the code.
    assert.ok(onDisk.includes('consumed-'));
    // Exactly one artifact, and it is local.
    assert.deepEqual(readdirSync(directory), [exported.fileName]);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test('stdout, stderr, argv and env have no representation in the bundle schema', () => {
  const text = exportSupportBundleText(bundleInput());
  for (const forbidden of ['stdout', 'stderr', 'argv', 'commandLine', 'env']) {
    assert.ok(!text.includes(`"${forbidden}"`), `bundle exposes ${forbidden}`);
  }
});

test('the raw text guard refuses credential-shaped content outright', () => {
  // The guard is fail-closed, not a scrubber: a redacted string would still hand
  // the user a file that *looked* exportable while having silently dropped
  // evidence. Refusing means no artifact is written at all.
  assert.throws(
    () =>
      redactSupportBundleText(
        `token=${DEVICE_CREDENTIAL} pair=${PAIRING_TOKEN} auth="${BEARER_TOKEN}"`,
      ),
    SupportBundleError,
  );
  // A legitimate bounded value must survive, or the guard would be useless.
  assert.equal(
    redactSupportBundleText('{"buildId":"build-3103","ref":"consumed-0123456789abcdef"}'),
    '{"buildId":"build-3103","ref":"consumed-0123456789abcdef"}',
  );
});

test('an exception string is never projected as a diagnostic value', () => {
  // A thrown error carrying a secret must not become a summary or a code. The
  // check happens on serialised output, so the refusal is asserted through the
  // real export path rather than at the builder boundary.
  assert.throws(
    () =>
      exportSupportBundleText(
        bundleInput({ deviceSummary: `boom: ${DEVICE_CREDENTIAL} ${BEARER_TOKEN}` }),
      ),
    SupportBundleError,
  );
});

// ---------------------------------------------------------------------------
// The #3082 seam: projected, never duplicated
// ---------------------------------------------------------------------------

test('the #3082 seam is projected as a health category, not re-implemented', async () => {
  // The seam exists so #3103 can report durable-store health while #3082 is
  // still unmerged. It must project a *category* and nothing else: no schema,
  // no record, no recovery or replay authority, no second implementation.
  assert.equal(DURABLE_STORE_SEAM.METHOD_COUNT, 1);
  assert.equal(DURABLE_STORE_SEAM.SCHEMA_DUPLICATION, 0);
  assert.equal(DURABLE_STORE_SEAM.RECOVERY_AUTHORITY, 0);
  assert.equal(DURABLE_STORE_SEAM.REPLAY_AUTHORITY, 0);
  assert.equal(DURABLE_STORE_SEAM.CLASSIFICATION_AUTHORITY, 0);
  assert.equal(DURABLE_STORE_SEAM.WRITE_AUTHORITY, 0);
  assert.equal(DURABLE_STORE_SEAM.CONCRETE_STORE_IMPLEMENTED_IN_THIS_CHANGE, false);

  // A wired #3082 port is projected through the real exporter path.
  const wired: DurableStoreHealthPort = {
    probe: async () => ({
      category: 'REQUIRES_RECONCILIATION',
      status: 'ACTION_REQUIRED',
      summary: 'two persisted runs are awaiting reconciliation',
      reconciliationCount: 2,
    }),
  };
  const { bundle } = await buildDesktopDiagnostics(probeInput(), wired);
  const durable = bundle.sections.find((entry) => entry.id === BUNDLE_SECTIONS.DURABLE_STORE);
  assert.ok(durable, 'the bundle must carry a durable_store section');
  assert.equal(durable.values.healthCategory, 'REQUIRES_RECONCILIATION');
  assert.equal(durable.values.status, 'ACTION_REQUIRED');
  assert.equal(durable.values.reconciliationCount, 2);
  // Only the category and a bounded count cross the seam: no record identity,
  // no row content, and nothing a #3082 schema change could invalidate.
  const text = serializeSupportBundle(bundle);
  assert.ok(!/command_id|run_id|request_fingerprint|user_version|claw_durable_run/i.test(text));
  // And an unacknowledged reconciliation must not read as a green light.
  assert.equal(bundle.overall, 'ACTION_REQUIRED');
});

test('an unwired or unknown durable store fails closed rather than reporting healthy', async () => {
  // The default build has no store, and says so.
  const { bundle } = await buildDesktopDiagnostics(probeInput());
  const durable = bundle.sections.find((entry) => entry.id === BUNDLE_SECTIONS.DURABLE_STORE);
  assert.equal(durable?.values.healthCategory, 'NOT_IMPLEMENTED');
  assert.equal(durable?.values.reconciliationCount, null);

  // A store that returns something outside the closed set has failed closed, and
  // that must never be coerced into `PASS`.
  for (const bad of [{ category: 'MOSTLY_FINE', status: 'PASS' }, { category: 'AVAILABLE' }]) {
    assert.throws(() => coerceDurableStoreHealth(bad), DurableStoreHealthError);
  }
  // An unrecognised status on a valid category is equally a refusal.
  assert.throws(
    () => coerceDurableStoreHealth({ category: 'AVAILABLE', status: 'PROBABLY_FINE' }),
    DurableStoreHealthError,
  );
  // A non-integer or negative count is dropped to `null` rather than trusted.
  assert.equal(
    coerceDurableStoreHealth({
      category: 'AVAILABLE',
      status: 'PASS',
      summary: 'store opened cleanly',
      reconciliationCount: -1,
    }).reconciliationCount,
    null,
  );
});

// ---------------------------------------------------------------------------
// Determinism and bounding
// ---------------------------------------------------------------------------

test('exporting the same facts twice is byte-identical', async () => {
  // Determinism is what makes a user's bug report diffable against the next
  // build. It is asserted through the real export path, not the serialiser, so
  // a nondeterministic file name or trailing byte would fail here.
  const directory = mkdtempSync(join(tmpdir(), 'padiem-bundle-'));
  try {
    const first = await buildAndExportSupportBundle(probeInput(), directory);
    const second = await buildAndExportSupportBundle(probeInput(), directory);
    assert.equal(first.fileName, second.fileName);
    assert.equal(first.byteLength, second.byteLength);
    assert.equal(readFileSync(first.filePath, 'utf8'), readFileSync(second.filePath, 'utf8'));
    // The name is a function of `generatedAt` alone, so a later export lands
    // beside the earlier one instead of silently overwriting a snapshot the
    // user may already have attached to a bug report.
    const later = await buildAndExportSupportBundle(
      probeInput({ now: new Date(Date.parse(GENERATED_AT) + 60_000) }),
      directory,
    );
    assert.notEqual(later.fileName, first.fileName);
    assert.deepEqual(readdirSync(directory).sort(), [first.fileName, later.fileName].sort());
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test('an over-long ref list is refused instead of silently truncated', () => {
  const refs = Array.from(
    { length: DIAGNOSTIC_BOUNDS.MAX_SUPPORT_REFS + 1 },
    (_, index) => `consumed-${index.toString(16).padStart(16, '0')}`,
  );
  assert.throws(() => buildSupportBundle(bundleInput({ supportRefs: refs })), SupportBundleError);
  // Exactly at the bound is still accepted, so the limit is a real ceiling.
  const atLimit = refs.slice(0, DIAGNOSTIC_BOUNDS.MAX_SUPPORT_REFS);
  assert.equal(buildSupportBundle(bundleInput({ supportRefs: atLimit })).supportRefs.length, atLimit.length);
});

// --- source-level authority duplication guard ---------------------------------
//
// #3103 must project #3082 health, never re-implement it. A behavioural test
// cannot catch an unused duplicate helper, so this reads the actual #3103
// sources and asserts the forbidden authority words are absent. #3082 has not
// merged, so these sources must not know its internal vocabulary at all: if
// they ever do, this test fails first and forces a review of whether #3103 has
// started copying an unmerged schema instead of using the seam.

// Tests run from `dist/tests`, so the `src` root lives two levels up. This
// matches the convention already used by `desktop-integration-3093.test.ts`.
const srcRoot = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'src');
const DIAGNOSTIC_SOURCES = [
  'contract/diagnostic-codes.ts',
  'contract/durable-store-health-seam.ts',
  'contract/first-run-health.ts',
  'contract/support-bundle.ts',
  'main/diagnostics-exporter.ts',
];

function readSource(relativePath: string): string {
  return readFileSync(join(srcRoot, ...relativePath.split('/')), 'utf8');
}

/** Strips comments so a doc comment naming a forbidden word is not a hit. */
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/^\s*\/\/.*$/gm, ' ');
}

test('no #3103 source duplicates #3082 internal storage vocabulary', () => {
  // #3082's on-disk schema. Projecting a *health category* is the whole
  // requirement; naming its tables, columns or recovery states would be a
  // second authority, and a second recovery/replay authority is the specific
  // thing #3103 is forbidden from becoming.
  const forbidden = [
    'claw_durable_run',
    'user_version',
    'command_id',
    'run_id',
    'tool_request_ref',
    'request_fingerprint',
    'durable_run_records',
    'DurableRunStore',
    'DurableRunRecord',
    'DurableRunRecoveryClass',
    'recover(',
    'replay_candidate',
    'execution_authority',
  ];
  for (const relativePath of DIAGNOSTIC_SOURCES) {
    const code = stripComments(readSource(relativePath));
    for (const token of forbidden) {
      assert.ok(
        !code.includes(token),
        `${relativePath} must not reference #3082 internals: found ${token}`,
      );
    }
  }
});

test('no #3103 source grants execution, admission or replay authority', () => {
  // Diagnostics are read-only by construction. A diagnostic module that can
  // start, admit or replay a run would be a far larger change than #3103 is
  // authorised to make, so the words are banned outright.
  const forbidden = [
    'child_process',
    'spawn(',
    'exec(',
    'execFile(',
    'fetch(',
    'XMLHttpRequest',
    'net.connect',
    'https.request',
    'telemetry',
  ];
  for (const relativePath of DIAGNOSTIC_SOURCES) {
    const code = stripComments(readSource(relativePath));
    for (const token of forbidden) {
      assert.ok(
        !code.includes(token),
        `${relativePath} must stay local-only and side-effect free: found ${token}`,
      );
    }
  }
});

test('no #3103 source writes to a secret, credential or env store', () => {
  // Secret-free is proven on the exported text, but the real guarantee is that
  // no diagnostic path can *reach* a secret to leak one.
  const forbidden = ['process.env', 'keytar', 'safeStorage', 'writeFileSync(credentials'];
  for (const relativePath of DIAGNOSTIC_SOURCES) {
    const code = stripComments(readSource(relativePath));
    for (const token of forbidden) {
      assert.ok(
        !code.includes(token),
        `${relativePath} must not read secrets or the environment: found ${token}`,
      );
    }
  }
  // The one write the exporter is allowed, and it is the bundle file itself.
  const exporter = readSource('main/diagnostics-exporter.ts');
  const writes = exporter.match(/writeFileSync\(/g) ?? [];
  assert.equal(writes.length, 1, 'the exporter must have exactly one write, the bundle file');
});

