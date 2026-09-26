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
  type SupportBundle,
  type SupportBundleInput,
  type SupportBundleScalar,
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
// First-run session activity: a first run legitimately has no session yet
// ---------------------------------------------------------------------------
//
// These are the regression tests for the blocker CENTRAL raised on #3117. A
// brand-new assisted alpha install has no successful session and no heartbeat
// yet, and the bundle is the thing that user needs most in exactly that state.
// `buildSupportBundle` used to route both nullable fields through the strict
// `requireIsoTimestamp`, so the first-run export threw
// `lastSuccessfulSessionAt must be an ISO-8601 UTC timestamp or null` — an
// error message that even documented the contract the code was violating.

test('a first run with no session and no heartbeat still builds a bundle', () => {
  const bundle = buildSupportBundle(
    bundleInput({ lastSuccessfulSessionAt: null, lastSuccessfulHeartbeatAt: null }),
  );
  const session = bundle.sections.find((section) => section.id === 'session_activity');
  assert.ok(session, 'session_activity section must be present');
  assert.equal(session.values.lastSuccessfulSessionAt, null);
  assert.equal(session.values.lastSuccessfulHeartbeatAt, null);
});

test('no session yet is preserved as null rather than dropped or invented', () => {
  // A missing session is a *fact about the device*. It must not be replaced by
  // the export time, a placeholder, or an absent key: all three would tell
  // support something false about what the device has actually done.
  const bundle = buildSupportBundle(
    bundleInput({ lastSuccessfulSessionAt: null, lastSuccessfulHeartbeatAt: GENERATED_AT }),
  );
  const session = bundle.sections.find((section) => section.id === 'session_activity');
  assert.ok(session);
  assert.equal(session.values.lastSuccessfulSessionAt, null);
  assert.ok(
    'lastSuccessfulSessionAt' in session.values,
    'a null session must stay an explicit key, not disappear from the projection',
  );
  assert.notEqual(session.values.lastSuccessfulSessionAt, GENERATED_AT);
  assert.equal(session.values.lastSuccessfulHeartbeatAt, GENERATED_AT);
});

test('no heartbeat yet is preserved as null too', () => {
  const bundle = buildSupportBundle(
    bundleInput({ lastSuccessfulSessionAt: GENERATED_AT, lastSuccessfulHeartbeatAt: null }),
  );
  const session = bundle.sections.find((section) => section.id === 'session_activity');
  assert.ok(session);
  assert.equal(session.values.lastSuccessfulHeartbeatAt, null);
  assert.equal(session.values.lastSuccessfulSessionAt, GENERATED_AT);
});

test('a malformed non-null timestamp is still refused, not normalised', () => {
  // "we have no session" and "the session time is garbage" are different
  // conditions. Making the field nullable must not have turned the strict
  // validator into an accept-anything pass-through.
  for (const bad of [
    '2026-09-26 12:00:00Z', // space instead of T
    '2026-09-26T12:00:00', // no zone designator
    '2026-09-26T12:00:00+09:00', // non-UTC offset
    'yesterday',
    '2026-13-45T99:99:99Z', // not a real instant
    '',
  ]) {
    assert.throws(
      () =>
        buildSupportBundle(
          bundleInput({ lastSuccessfulSessionAt: bad, lastSuccessfulHeartbeatAt: null }),
        ),
      SupportBundleError,
      `a malformed session timestamp must be refused: ${JSON.stringify(bad)}`,
    );
  }
  // The same holds for the heartbeat field, independently.
  assert.throws(
    () =>
      buildSupportBundle(
        bundleInput({ lastSuccessfulSessionAt: null, lastSuccessfulHeartbeatAt: 'nope' }),
      ),
    SupportBundleError,
  );
});

test('the real product export path succeeds on a first run with both timestamps null', async () => {
  // This is the end-to-end case CENTRAL asked for: not the contract function in
  // isolation, but the actual exporter a user triggers. Before the fix this
  // threw for the one user who most needs a support bundle — a brand-new
  // install with no session and no heartbeat yet.
  const directory = mkdtempSync(join(tmpdir(), 'padiem-first-run-'));
  try {
    const exported = await buildAndExportSupportBundle(
      probeInput({ lastSuccessfulSessionAt: null, lastSuccessfulHeartbeatAt: null }),
      directory,
    );
    const written = JSON.parse(readFileSync(join(directory, exported.fileName), 'utf8'));
    const session = written.sections.find((section: { id: string }) => section.id === 'session_activity');
    assert.ok(session, 'session_activity must be present in the exported file');
    assert.equal(session.values.lastSuccessfulSessionAt, null);
    assert.equal(session.values.lastSuccessfulHeartbeatAt, null);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

// ---------------------------------------------------------------------------
// `undefined` is not `null` — the fail-closed half of the same contract
// ---------------------------------------------------------------------------
//
// The first-run fix above made both session timestamps nullable. The second
// review found the fix went one step too far in the other direction:
//
//     if (candidate === null || candidate === undefined) return null;
//
// That treats "the caller did not supply this field" as "this device has never
// had a session". Those are different states, and only one of them is true, so
// the coercion destroys the signal that separates broken instrumentation from a
// brand-new install — silently, in the file the user hands to support as
// evidence. `SupportBundleInput` types the fields `string | null`, so TypeScript
// never catches it; only the runtime validator can, which is why the cases below
// construct objects that genuinely lack the property.

/**
 * Removes a property from a copy, for real, at runtime.
 *
 * The whole point is that the result genuinely has no such key — so the
 * builder reads `undefined` from a property lookup that misses, which is the
 * exact shape a real caller produces. A `Partial<SupportBundleInput>` spread
 * would also work but reads as a compile-time concern, and the compile-time
 * type is the thing that is *not* being tested here.
 */
function withoutProperty(source: object, property: string): Record<string, unknown> {
  const clone: Record<string, unknown> = { ...(source as Record<string, unknown>) };
  delete clone[property];
  return clone;
}

/** The same omission, reached through a wire round-trip instead of a spread. */
function withoutPropertyOverTheWire(source: object, property: string): Record<string, unknown> {
  const wire = JSON.parse(JSON.stringify(source)) as Record<string, unknown>;
  delete wire[property];
  return wire;
}

test('an explicitly passed undefined session timestamp is refused, not read as null', () => {
  // The property exists and its value is `undefined`. A `Partial` override is
  // the everyday way this reaches production: a caller merges defaults and
  // forgets the key, and the merge produces `undefined` rather than an absence.
  assert.throws(
    () =>
      buildSupportBundle(
        bundleInput({
          lastSuccessfulSessionAt: undefined as unknown as string | null,
        }),
      ),
    (error: unknown) => {
      assert.ok(error instanceof SupportBundleError, 'must fail as a SupportBundleError');
      assert.match(error.message, /lastSuccessfulSessionAt/);
      return true;
    },
    'an explicit undefined must be refused, not coerced to null',
  );
});

test('an explicitly passed undefined heartbeat timestamp is refused too', () => {
  assert.throws(
    () =>
      buildSupportBundle(
        bundleInput({
          lastSuccessfulHeartbeatAt: undefined as unknown as string | null,
        }),
      ),
    (error: unknown) => {
      assert.ok(error instanceof SupportBundleError);
      assert.match(error.message, /lastSuccessfulHeartbeatAt/);
      return true;
    },
  );
});

test('a missing session property is refused at the runtime boundary', () => {
  // Built by actually deleting the key, so the builder performs a property
  // lookup that misses. A compile-time error test cannot prove this: the
  // property is absent at runtime and present in the declared type, and the
  // declared type is exactly what a JavaScript caller does not consult.
  const missing = withoutProperty(bundleInput(), 'lastSuccessfulSessionAt');
  assert.equal(
    'lastSuccessfulSessionAt' in missing,
    false,
    'the fixture must genuinely lack the property, not carry an undefined value',
  );
  assert.throws(() => buildSupportBundle(missing as unknown as SupportBundleInput), (error: unknown) => {
    assert.ok(error instanceof SupportBundleError);
    assert.match(error.message, /lastSuccessfulSessionAt/);
    return true;
  });
});

test('a missing heartbeat property is refused, over a wire round-trip', () => {
  // A second, independent construction: JSON serialisation is what a real
  // renderer→main IPC payload goes through, and it silently drops an
  // `undefined`-valued key on the way. So the omission this test proves is
  // reachable in production without a single TypeScript violation.
  const missing = withoutPropertyOverTheWire(bundleInput(), 'lastSuccessfulHeartbeatAt');
  assert.equal('lastSuccessfulHeartbeatAt' in missing, false);
  assert.throws(() => buildSupportBundle(missing as unknown as SupportBundleInput), (error: unknown) => {
    assert.ok(error instanceof SupportBundleError);
    assert.match(error.message, /lastSuccessfulHeartbeatAt/);
    return true;
  });
});

test('a missing timestamp is not silently substituted by the export time', () => {
  // The specific harm: if the refusal is ever downgraded back into a coercion,
  // the invented value is almost always *plausible*, so nobody downstream can
  // tell. Asserted as a negative so a future "helpfully fill it in" change has
  // something to trip over.
  const missing = withoutProperty(bundleInput(), 'lastSuccessfulSessionAt');
  let serialised: string | null = null;
  try {
    serialised = exportSupportBundleText(missing as unknown as SupportBundleInput);
  } catch {
    // Expected: the builder refuses before anything reaches the serialiser.
  }
  assert.equal(serialised, null, 'a missing session must never produce bundle text');
});

test('the product export path fails closed when the probe omits a timestamp', async () => {
  // The same omission, one layer up, at the exporter a user actually triggers.
  // A `DiagnosticsProbeInput` built by merging partials in the main process is
  // the realistic origin, and the user must get a refusal rather than a file
  // claiming their Desktop has never run a session.
  const directory = mkdtempSync(join(tmpdir(), 'padiem-missing-session-'));
  try {
    const omitted = withoutProperty(probeInput(), 'lastSuccessfulSessionAt');
    await assert.rejects(
      buildAndExportSupportBundle(omitted as unknown as DiagnosticsProbeInput, directory),
      (error: unknown) => {
        assert.ok(error instanceof SupportBundleError);
        assert.match(error.message, /lastSuccessfulSessionAt/);
        return true;
      },
    );
    assert.deepEqual(
      readdirSync(directory),
      [],
      'a refused export must leave no file on the user\'s disk',
    );
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test('a wrong-typed timestamp is refused rather than coerced', () => {
  // `null` is the only non-string accepted. A number, boolean or object is a
  // caller error of the same family and must not become a string either.
  for (const wrongType of [1_789_000_000_000, true, {}, []] as unknown[]) {
    assert.throws(
      () =>
        buildSupportBundle(
          bundleInput({ lastSuccessfulSessionAt: wrongType as unknown as string | null }),
        ),
      SupportBundleError,
      `a ${typeof wrongType} session timestamp must be refused`,
    );
  }
});

test('a valid timestamp is preserved exactly, not reformatted', () => {
  // The other end of the contract: rejecting `undefined` must not have made
  // the validator lossy for a genuine instant. The exact input string is what
  // reaches the exported file, so support reads the timestamp the device
  // actually recorded.
  const bundle = buildSupportBundle(bundleInput({ lastSuccessfulSessionAt: GENERATED_AT }));
  const session = bundle.sections.find((section) => section.id === 'session_activity');
  assert.equal(session?.values.lastSuccessfulSessionAt, GENERATED_AT);
  assert.ok(serializeSupportBundle(bundle).includes(GENERATED_AT));
});

// ---------------------------------------------------------------------------
// Every projected scalar fails closed the same way — the third review
// ---------------------------------------------------------------------------
//
// The timestamp fix above left the same coercion in `boundedScalar`, which
// projects every other section value:
//
//     if (value === null || value === undefined) return null;
//
// Identical defect, larger blast radius. `null` on a projected field is a
// device fact (a reconciliation count for a store that is not wired yet); an
// `undefined` is a caller that failed to build the projection it is asking to
// export. Coercing the second into the first silently removes a row from the
// file support reads as complete evidence — and does so for every section at
// once. So the same rule applies here: `null` is preserved, `undefined` and a
// missing required field are refused, and a wrong type is refused.

test('an explicitly undefined app version is refused, not read as null', () => {
  // Present with the value `undefined` — the shape a partial merge produces.
  assert.throws(
    () => buildSupportBundle(bundleInput({ appVersion: undefined as unknown as string })),
    (error: unknown) => {
      assert.ok(error instanceof SupportBundleError);
      assert.match(error.message, /app\.appVersion/);
      return true;
    },
    'an undefined app version must be refused, not coerced to null',
  );
});

test('a missing build id is refused at the runtime boundary', () => {
  // The key is genuinely deleted, so the builder performs a property lookup
  // that misses. TypeScript cannot catch this: the property is absent at
  // runtime and required in the declared type, and the declared type is what a
  // JavaScript caller does not consult.
  const missing = withoutProperty(bundleInput(), 'buildId');
  assert.equal('buildId' in missing, false);
  assert.throws(() => buildSupportBundle(missing as unknown as SupportBundleInput), (error: unknown) => {
    assert.ok(error instanceof SupportBundleError);
    assert.match(error.message, /buildId/);
    return true;
  });
});

test('an explicitly undefined required summary is refused too', () => {
  // A summary is the one field a support engineer actually reads as prose.
  // Dropping it silently would be the least visible omission of all.
  assert.throws(
    () => buildSupportBundle(bundleInput({ deviceSummary: undefined as unknown as string })),
    (error: unknown) => {
      assert.ok(error instanceof SupportBundleError);
      assert.match(error.message, /device_lifecycle\.summary/);
      return true;
    },
  );
});

test('a missing runner summary is refused over a wire round-trip', () => {
  // JSON is what a renderer→main payload crosses, and it drops an
  // `undefined`-valued key on the way. So this omission is reachable in
  // production without a single TypeScript violation, and the builder has to
  // catch it at the boundary.
  const missing = withoutPropertyOverTheWire(bundleInput(), 'runnerSummary');
  assert.equal('runnerSummary' in missing, false);
  assert.throws(() => buildSupportBundle(missing as unknown as SupportBundleInput), (error: unknown) => {
    assert.ok(error instanceof SupportBundleError);
    assert.match(error.message, /runner_health\.summary/);
    return true;
  });
});

test('the product export path refuses a missing build id and writes nothing', async () => {
  // One layer up, at the exporter a user actually triggers, with the same
  // refusal and the same absence of an artifact.
  const directory = mkdtempSync(join(tmpdir(), 'padiem-missing-buildid-'));
  try {
    const omitted = withoutProperty(probeInput(), 'buildId');
    await assert.rejects(
      buildAndExportSupportBundle(omitted as unknown as DiagnosticsProbeInput, directory),
      (error: unknown) => {
        assert.ok(error instanceof SupportBundleError);
        assert.match(error.message, /buildId/);
        return true;
      },
    );
    assert.deepEqual(
      readdirSync(directory),
      [],
      'a refused export must leave no file on the user\'s disk',
    );
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test('a wrong-typed projected value is refused rather than coerced', () => {
  // The tightening must not have made `boundedScalar` lossy in the other
  // direction either: an object or array offered as a scalar is an unbounded
  // tree, and a finite-number violation is a caller error of the same family.
  for (const wrongType of [{}, [], Number.NaN] as unknown[]) {
    assert.throws(
      () => buildSupportBundle(bundleInput({ appVersion: wrongType as unknown as string })),
      SupportBundleError,
      `a ${Array.isArray(wrongType) ? 'array' : typeof wrongType} app version must be refused`,
    );
  }
});

test('legitimate nulls still pass alongside the required-scalar tightening', () => {
  // The tightening is about `undefined`, not about `null`. All three genuine
  // nulls a first-run Desktop produces must survive: no session yet, no
  // heartbeat yet, and a durable store that is not wired yet.
  const bundle = buildSupportBundle(
    bundleInput({
      lastSuccessfulSessionAt: null,
      lastSuccessfulHeartbeatAt: null,
      durableStoreHealth: unimplementedDurableStoreHealth(),
    }),
  );
  const session = bundle.sections.find((section) => section.id === 'session_activity');
  const durable = bundle.sections.find((section) => section.id === 'durable_store');
  assert.equal(session?.values.lastSuccessfulSessionAt, null);
  assert.equal(session?.values.lastSuccessfulHeartbeatAt, null);
  assert.equal(durable?.values.reconciliationCount, null);
  // Asserted on the serialised text as well, so the nulls are present in the
  // file the user exports, not merely in the in-memory object.
  const text = serializeSupportBundle(bundle);
  assert.ok(text.includes('"lastSuccessfulSessionAt": null'));
  assert.ok(text.includes('"lastSuccessfulHeartbeatAt": null'));
  assert.ok(text.includes('"reconciliationCount": null'));
});

test('an optional app-section key stays legitimately absent', () => {
  // `bundleAppVersion` and `runnerAppVersion` are allowlisted but not supplied
  // by the builder, because they depend on what is actually installed. The
  // tightening must not have turned "absent because optional" into a refusal.
  const bundle = buildSupportBundle(bundleInput());
  const app = bundle.sections.find((section) => section.id === 'app');
  assert.ok(app);
  assert.equal('bundleAppVersion' in app.values, false);
  assert.equal('runnerAppVersion' in app.values, false);
  assert.equal('appVersion' in app.values, true);
});

// ---------------------------------------------------------------------------
// The serializer is the same runtime trust boundary — the fourth review
// ---------------------------------------------------------------------------
//
// `serializeSupportBundle` is exported, is called directly by
// `exportSupportBundle`, and accepts any object shaped like a bundle. It already
// re-validated refs and the first-run report for exactly that reason. But its
// section loop was:
//
//     if (value !== undefined) values[key] = value;
//
// so a hand-built or runtime-tampered bundle could delete a required section
// value and the serializer quietly omitted the row — the same fail-open the
// builder had just been closed against, one boundary later, on the bytes that
// actually reach the user's disk. The required-vs-optional contract now applies
// on both sides of the boundary.

/**
 * Returns a copy of a bundle with one section's values edited in place, the way
 * a runtime tamper would. The real sections are frozen, so a genuine tamper has
 * to rebuild them; this helper does exactly that and hands back an untyped
 * object the way a JavaScript caller would.
 */
function withTamperedSectionValues(
  bundle: SupportBundle,
  sectionId: string,
  mutate: (values: Record<string, SupportBundleScalar>) => void,
): SupportBundle {
  const sections = bundle.sections.map((section) => {
    if (section.id !== sectionId) {
      return section;
    }
    const values = { ...section.values } as Record<string, SupportBundleScalar>;
    mutate(values);
    return { ...section, values };
  });
  return { ...bundle, sections } as unknown as SupportBundle;
}

test('the serializer refuses a bundle whose required section value was removed', () => {
  // The key is genuinely deleted from the section's values, so the serializer
  // performs a property lookup that misses — the hand-built shape, not a
  // compile-time fiction.
  const bundle = buildSupportBundle(bundleInput());
  const tampered = withTamperedSectionValues(bundle, 'app', (values) => {
    delete values.appVersion;
  });
  assert.throws(
    () => serializeSupportBundle(tampered),
    (error: unknown) => {
      assert.ok(error instanceof SupportBundleError);
      assert.match(error.message, /app\.appVersion/);
      return true;
    },
    'a missing required section value must be refused, not omitted',
  );
});

test('the serializer refuses an explicitly undefined required section value', () => {
  const bundle = buildSupportBundle(bundleInput());
  const tampered = withTamperedSectionValues(bundle, 'app', (values) => {
    values.buildId = undefined as unknown as string;
  });
  assert.throws(
    () => serializeSupportBundle(tampered),
    (error: unknown) => {
      assert.ok(error instanceof SupportBundleError);
      assert.match(error.message, /app\.buildId/);
      return true;
    },
  );
});

test('the serializer refuses a tampered non-scalar value outright', () => {
  // The re-validation is the builder's own validator, so a hand-built bundle
  // cannot smuggle an unbounded tree into a scalar slot either. Tampered at the
  // projected key (`summary`), not the builder-input name (`runnerSummary`):
  // only allowlisted keys are read, which is itself the projection guarantee.
  const bundle = buildSupportBundle(bundleInput());
  const tampered = withTamperedSectionValues(bundle, 'runner_health', (values) => {
    values.summary = { nested: 'unbounded' } as unknown as string;
  });
  assert.throws(
    () => serializeSupportBundle(tampered),
    (error: unknown) => {
      assert.ok(error instanceof SupportBundleError);
      assert.match(error.message, /runner_health\.summary/);
      return true;
    },
  );
});

test('the serializer still allows genuinely optional app values to be absent', () => {
  // The tightening is about required values, not about the two app-section
  // keys that depend on what is installed. Absent optional keys stay absent,
  // and a hand-built bundle may still legitimately carry one.
  const bundle = buildSupportBundle(bundleInput());
  const text = serializeSupportBundle(bundle);
  assert.ok(!text.includes('"bundleAppVersion"'));
  assert.ok(!text.includes('"runnerAppVersion"'));
  const withBundleVersion = withTamperedSectionValues(bundle, 'app', (values) => {
    values.bundleAppVersion = '0.1.0';
  });
  assert.ok(serializeSupportBundle(withBundleVersion).includes('"bundleAppVersion": "0.1.0"'));
});

test('the serializer preserves legitimate nulls in required section values', () => {
  // The first-run nulls and the unwired-store count are device facts, and they
  // must survive the serializer as `null` — not as an omitted key, which would
  // read as missing evidence rather than as "none".
  const bundle = buildSupportBundle(
    bundleInput({
      lastSuccessfulSessionAt: null,
      lastSuccessfulHeartbeatAt: null,
      durableStoreHealth: unimplementedDurableStoreHealth(),
    }),
  );
  const text = serializeSupportBundle(bundle);
  assert.ok(text.includes('"lastSuccessfulSessionAt": null'));
  assert.ok(text.includes('"lastSuccessfulHeartbeatAt": null'));
  assert.ok(text.includes('"reconciliationCount": null'));
});

test('exportSupportBundle writes no file when a required section value was tampered away', () => {
  // The whole point of closing this at the serializer: `exportSupportBundle`
  // hands a caller-supplied bundle straight to it, so a tampered bundle must be
  // refused before `mkdirSync`, and must leave nothing on the user's disk.
  const directory = mkdtempSync(join(tmpdir(), 'padiem-tampered-export-'));
  try {
    const bundle = buildSupportBundle(bundleInput());
    const tampered = withTamperedSectionValues(bundle, 'app', (values) => {
      delete values.buildId;
    });
    assert.throws(
      () => exportSupportBundle(tampered, directory),
      (error: unknown) => {
        assert.ok(error instanceof SupportBundleError);
        assert.match(error.message, /app\.buildId/);
        return true;
      },
    );
    assert.deepEqual(
      readdirSync(directory),
      [],
      'a refused tampered export must leave no file on the user\'s disk',
    );
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

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
