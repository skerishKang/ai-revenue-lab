/**
 * #3103 — main-process Desktop diagnostics exporter.
 *
 * This is the wiring layer, not a second contract. It reads the *existing*
 * canonical sources — #3083 device lifecycle, #3093 runner host mode and
 * Windows protocol registration, #3095 pairing category, the #3082 durable
 * store health seam and the embedded-runtime compatibility reason — and feeds
 * them into `buildFirstRunHealthReport` and `buildSupportBundle`.
 *
 * Three rules govern this file:
 *
 * 1. **It decides nothing.** Every health status and every category already
 *    belongs to the contract modules or to #3082's seam. This module only
 *    projects, so a diagnostic change can never become a health authority.
 * 2. **It reads no secret.** A pairing code reaches this file only to be
 *    reduced to its support-safe `consumed-<hex>` marker; nothing else here can
 *    see a credential, a token or command output. There is no argv, stdout or
 *    stderr parameter to pass, by design.
 * 3. **It never uploads.** `exportSupportBundle` writes one local file and
 *    returns its path. There is no network call, no telemetry and no retry.
 *
 * The probes are injected so the product path can be exercised in tests without
 * Electron, a credential store or a filesystem.
 */

import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';

import {
  DIAGNOSTIC_BOUNDS,
  type DiagnosticHealthStatus,
} from '../contract/diagnostic-codes.js';
import {
  type DurableStoreHealth,
  type DurableStoreHealthPort,
  unimplementedDurableStoreHealthPort,
} from '../contract/durable-store-health-seam.js';
import {
  type DeviceLifecycleProjection,
  projectDeviceLifecycle,
} from '../contract/device-lifecycle.js';
import {
  type FirstRunHealthReport,
  buildFirstRunHealthReport,
} from '../contract/first-run-health.js';
import { pairingHandoffConsumedMarker } from '../contract/pairing-deeplink.js';
import {
  type SupportBundle,
  buildSupportBundle,
  serializeSupportBundle,
  supportBundleFileName,
} from '../contract/support-bundle.js';
import { windowsProtocolRegistrationPlan, type ProtocolRegistrationInput } from './protocol-registration.js';
import { resolveRunnerHostMode, type RunnerHostModeInput } from './runner-host-mode.js';

/** What the main process must tell us, all already canonical or already safe. */
export interface DiagnosticsProbeInput {
  readonly appVersion: string;
  readonly buildId: string;
  readonly platform: string;
  readonly arch: string;
  readonly electronMajor: number;
  /** #3093 `resolveRunnerHostMode` input, resolved here so the real path runs. */
  readonly runnerHostModeInput: RunnerHostModeInput;
  /** #3093 `windowsProtocolRegistrationPlan` input, likewise resolved here. */
  readonly protocolRegistrationInput: ProtocolRegistrationInput;
  /** #3083 device lifecycle projection as it stands right now. */
  readonly deviceLifecycle: DeviceLifecycleProjection;
  /** `true` only when `registerWindowsProtocolClient` actually succeeded. */
  readonly protocolRegistered: boolean;
  /** Bounded integer generation counter. Never the credential. */
  readonly credentialGeneration: number;
  readonly lastSuccessfulSessionAt: string | null;
  readonly lastSuccessfulHeartbeatAt: string | null;
  /**
   * A raw #3095 pairing code, if one is pending. It is reduced to its
   * support-safe marker immediately and never projected or logged.
   */
  readonly pendingPairingCode: string | null;
  readonly updateRequired: boolean;
  /** #3093 runner lifecycle state, projected as a category. */
  readonly runnerLifecycleState: unknown;
  /** `compatibility.py` `REASON_*` code, or `null` when not yet evaluated. */
  readonly compatibilityReason: unknown;
  /** Local probe results. */
  readonly appDataWritable: boolean;
  readonly credentialStoreAvailable: boolean;
  readonly brokerRouteConfigReady: boolean;
  /** Caller-supplied clock, so a bundle is byte-deterministic under test. */
  readonly now: Date;
  /** Optional support-safe refs (e.g. an #3095 `pairref-`). */
  readonly supportRefs?: readonly string[];
}

/**
 * Maps a #3082 durable-store seam result onto the bundle's health status.
 * This is a *presentation* mapping of the seam's own category: the seam owns
 * the verdict, and no store schema, recovery rule or replay rule is read here.
 */
function durableStoreStatus(health: DurableStoreHealth): DiagnosticHealthStatus {
  return health.status;
}

/** Finds one first-run check by its canonical name. */
function checkNamed(
  report: FirstRunHealthReport,
  check: FirstRunHealthReport['checks'][number]['check'],
): FirstRunHealthReport['checks'][number] | undefined {
  return report.checks.find((entry) => entry.check === check);
}

/**
 * Builds the first-run health report and the support bundle from canonical
 * inputs. Pure apart from awaiting the #3082 seam probe, so it is directly
 * testable and has no side effects.
 */
export async function buildDesktopDiagnostics(
  input: DiagnosticsProbeInput,
  durableStore: DurableStoreHealthPort = unimplementedDurableStoreHealthPort(),
): Promise<{ firstRun: FirstRunHealthReport; bundle: SupportBundle }> {
  const hostMode = resolveRunnerHostMode(input.runnerHostModeInput);
  const protocolPlan = windowsProtocolRegistrationPlan(input.protocolRegistrationInput);
  const deviceLifecycle = input.deviceLifecycle;
  const durable = await durableStore.probe();

  // A pending pairing code is reduced to its support-safe marker and dropped.
  // The raw code is not read again anywhere in this file.
  const pairingMarker = input.pendingPairingCode
    ? pairingHandoffConsumedMarker(input.pendingPairingCode)
    : null;

  const firstRun = buildFirstRunHealthReport({
    runnerHostMode: hostMode.mode,
    protocolRegistrationAction: protocolPlan.action,
    protocolRegistered: input.protocolRegistered,
    appDataWritable: input.appDataWritable,
    credentialStoreAvailable: input.credentialStoreAvailable,
    brokerRouteConfigReady: input.brokerRouteConfigReady,
    updateRequired: input.updateRequired,
    compatibilityReason: input.compatibilityReason,
    supportRefs: input.supportRefs,
    generatedAtMs: input.now.getTime(),
  });

  const runnerModeCheck = checkNamed(firstRun, 'DESKTOP_RUNNER_EXECUTABLE_MODE');
  const protocolCheck = checkNamed(firstRun, 'PROTOCOL_REGISTRATION');
  const compatibilityCheck = checkNamed(firstRun, 'VERSION_COMPATIBILITY');

  const bundle = buildSupportBundle({
    generatedAt: input.now.toISOString(),
    appVersion: input.appVersion,
    buildId: input.buildId,
    platform: input.platform,
    arch: input.arch,
    electronMajor: input.electronMajor,
    deviceState: deviceLifecycle.state,
    deviceStatus: deviceLifecycle.evidenceBacked ? 'PASS' : 'WARN',
    deviceCode: `device_${deviceLifecycle.state.toLowerCase()}`,
    deviceSummary: deviceLifecycle.reason,
    credentialGeneration: input.credentialGeneration,
    lastSuccessfulSessionAt: input.lastSuccessfulSessionAt,
    lastSuccessfulHeartbeatAt: input.lastSuccessfulHeartbeatAt,
    pairingCategory: pairingMarker ? 'paired' : 'not_paired',
    pairingStatus: pairingMarker ? 'PASS' : 'WARN',
    pairingCode: pairingMarker ? 'pairing_present' : 'pairing_absent',
    pairingSummary: pairingMarker
      ? 'a pairing handoff was consumed in this session'
      : 'no pairing handoff has been consumed in this session',
    updateRequired: input.updateRequired,
    updateStatus: input.updateRequired ? 'ACTION_REQUIRED' : 'PASS',
    updateCode: input.updateRequired ? 'update_required' : 'update_not_required',
    updateSummary: input.updateRequired
      ? 'this build is behind and needs an update before it can be used'
      : 'this build is current',
    runnerLifecycleState: input.runnerLifecycleState,
    runnerHostMode: hostMode.mode,
    protocolRegistrationAction: protocolPlan.action,
    protocolRegistered: input.protocolRegistered,
    runnerStatus: runnerModeCheck?.status ?? 'WARN',
    runnerCode: protocolCheck?.code ?? 'runner_unknown',
    runnerSummary: protocolPlan.reason,
    durableStoreHealth: durable,
    compatibilityReason: input.compatibilityReason,
    compatibilityStatus: compatibilityCheck?.status ?? 'WARN',
    compatibilityCode: compatibilityCheck?.code ?? 'compatibility_unknown',
    compatibilitySummary:
      'runtime/host contract compatibility as reported by the embedded runtime',
    supportRefs: pairingMarker
      ? [pairingMarker, ...(input.supportRefs ?? [])].slice(0, DIAGNOSTIC_BOUNDS.MAX_SUPPORT_REFS)
      : input.supportRefs,
    firstRun,
  });

  return { firstRun, bundle };
}

/** The #3082 seam status a bundle will report, for callers that only need it. */
export function durableStoreHealthStatus(health: DurableStoreHealth): DiagnosticHealthStatus {
  return durableStoreStatus(health);
}

/**
 * Writes one support bundle to a local directory. This is the whole of
 * `USER_CAN_EXPORT_SUPPORT_BUNDLE`: a file the user chooses to share.
 *
 * There is deliberately no upload path, no telemetry and no background
 * transmission in this function.
 */
export function exportSupportBundle(bundle: SupportBundle, targetDirectory: string): SupportBundleExport {
  if (typeof targetDirectory !== 'string' || !targetDirectory.trim()) {
    throw new TypeError('targetDirectory must be a non-empty local path');
  }
  const directory = path.resolve(targetDirectory.trim());
  const text = serializeSupportBundle(bundle);
  const byteLength = Buffer.byteLength(text, 'utf8');
  if (byteLength > DIAGNOSTIC_BOUNDS.MAX_BUNDLE_BYTES) {
    throw new RangeError(
      `support bundle is ${byteLength} bytes, over the ${DIAGNOSTIC_BOUNDS.MAX_BUNDLE_BYTES} byte bound`,
    );
  }
  mkdirSync(directory, { recursive: true });
  const fileName = supportBundleFileName(bundle);
  const filePath = path.join(directory, fileName);
  writeFileSync(filePath, text, { encoding: 'utf8' });
  return Object.freeze({ bundle, fileName, filePath, byteLength });
}

/** Convenience: build then export in one local, side-effecting step. */
export async function buildAndExportSupportBundle(
  input: DiagnosticsProbeInput,
  targetDirectory: string,
  durableStore: DurableStoreHealthPort = unimplementedDurableStoreHealthPort(),
): Promise<SupportBundleExport> {
  const { bundle } = await buildDesktopDiagnostics(input, durableStore);
  return exportSupportBundle(bundle, targetDirectory);
}

export { projectDeviceLifecycle };


/** Result of one local export. */
export interface SupportBundleExport {
  readonly bundle: SupportBundle;
  readonly fileName: string;
  /** Absolute path on this machine. Nothing left the device. */
  readonly filePath: string;
  readonly byteLength: number;
}
