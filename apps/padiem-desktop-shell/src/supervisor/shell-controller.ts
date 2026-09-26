/**
 * CLAW4 #3083 — Electron-main-side shell controller.
 *
 * Owns the authoritative projection the renderer is allowed to see. Every
 * channel handler is dispatched through the static allowlist, so an unknown or
 * wildcard channel can never reach a handler.
 *
 *   DISPATCH_VIA_STATIC_ALLOWLIST=YES
 *   GENERIC_INVOKE_COMMAND_ARGS=NO
 *   RENDERER_CANNOT_SET_DEVICE_STATE=NO
 *   RUNNER_EXECUTION_AUTHORITY=NO
 */

import {
  DEVICE_LIFECYCLE_STATES,
  initialDeviceLifecycleProjection,
  projectDeviceLifecycle,
  type DeviceLifecycleProjection,
  type DeviceLifecycleState,
} from '../contract/device-lifecycle.js';
import {
  IPC_CHANNELS,
  IpcContractError,
  assertAllowedIpcChannel,
  type BoundedLogRequest,
  type BoundedLogResponse,
  type IpcChannel,
  type PairingDeepLinkRequest,
  type PairingDeepLinkResponse,
  type RunnerHealthResponse,
  type RunnerStartRequest,
  type RunnerStartResponse,
  type RunnerStopRequest,
  type RunnerStopResponse,
  type ShellStatus,
} from '../contract/ipc.js';
import {
  pairingHandoffConsumedMarker,
  parsePairingDeepLink,
  takePairingCodeTransfer,
} from '../contract/pairing-deeplink.js';
import { projectBoundedLog } from '../contract/safe-log-projection.js';
import type { RunnerSupervisor } from './runner-supervisor.js';

/**
 * #3095: how many spent-handoff markers one shell session remembers.
 * Bounded so the replay ledger cannot become unbounded application state.
 */
const PAIRING_HANDOFF_LEDGER_LIMIT = 32;

export interface ShellControllerOptions {
  readonly supervisor: RunnerSupervisor;
  readonly boundedLogLines: () => readonly string[];
  readonly now?: () => number;
}

export type IpcHandler = (request: unknown) => Promise<unknown> | unknown;

export class ShellController {
  readonly #supervisor: RunnerSupervisor;
  readonly #boundedLogLines: () => readonly string[];
  readonly #now: () => number;
  #device: DeviceLifecycleProjection = initialDeviceLifecycleProjection();
  #pairingSeamAccepted = false;
  /**
   * #3095: the single bounded pairing handoff awaiting the trusted runner.
   *
   * Held in the main process only, consumed exactly once, never logged, never
   * persisted, and never projected to the renderer.
   */
  #lastPairingHandoff: { pairingCode: string; correlationRef: string } | null = null;
  /**
   * #3095 replay ledger.
   *
   * Marks already-consumed handoffs so replaying the same deep link cannot hand
   * the runner a pairing code twice. Only a bounded, non-reversible marker is
   * retained — never the code — and the ledger is bounded so it cannot grow
   * without limit. The canonical broker still rejects a reused challenge; this
   * ledger stops the shell from re-offering a spent handoff in the first place.
   */
  #consumedPairingHandoffs = new Set<string>();

  #presenceNote = 'no headless runner observation yet';

  constructor(options: ShellControllerOptions) {
    this.#supervisor = options.supervisor;
    this.#boundedLogLines = options.boundedLogLines;
    this.#now = options.now ?? (() => Date.now());
  }

  /** The complete, closed handler map. Keys are statically known. */
  handlers(): Readonly<Record<IpcChannel, IpcHandler>> {
    return Object.freeze({
      'padiem:shell:get-status': () => this.getStatus(),
      'padiem:shell:runner-start': (request) => this.runnerStart(request),
      'padiem:shell:runner-stop': (request) => this.runnerStop(request),
      'padiem:shell:runner-health': () => this.runnerHealth(),
      'padiem:shell:pairing-deeplink-submit': (request) => this.pairingDeepLinkSubmit(request),
      'padiem:shell:get-bounded-log': (request) => this.getBoundedLog(request),
    });
  }

  /** Allowlisted dispatch. Anything not in the static allowlist is refused. */
  async dispatch(channel: unknown, request: unknown): Promise<unknown> {
    const allowed = assertAllowedIpcChannel(channel);
    const handler = this.handlers()[allowed];
    return handler(request);
  }

  getStatus(): ShellStatus {
    const runner = this.#supervisor.snapshot();
    return Object.freeze({
      deviceState: this.#device.state,
      deviceStateRevision: this.#device.sinceRevision,
      runnerState: runner.state,
      runnerPid: runner.pid,
      pairingSeamAccepted: this.#pairingSeamAccepted,
      presenceNote: this.#presenceNote,
      authoritativeTruthOwner: '#3080' as const,
      rendererMayDeclareOnline: false as const,
    });
  }

  deviceProjection(): DeviceLifecycleProjection {
    return this.#device;
  }

  async runnerStart(request: unknown): Promise<RunnerStartResponse> {
    if (!isRendererShellRequest(request)) {
      return Object.freeze({
        ok: false,
        state: this.#supervisor.snapshot().state,
        pid: null,
        reason: 'runner start request rejected: not a renderer shell request',
      });
    }
    try {
      const snapshot = await this.#supervisor.start(this.#now());
      this.#applyRunnerState(snapshot.state);
      return Object.freeze({
        ok: true,
        state: snapshot.state,
        pid: snapshot.pid,
        reason: 'headless runner started as a separate process',
      });
    } catch (error) {
      return Object.freeze({
        ok: false,
        state: this.#supervisor.snapshot().state,
        pid: null,
        reason: error instanceof Error ? error.message : String(error),
      });
    }
  }

  async runnerStop(request: unknown): Promise<RunnerStopResponse> {
    if (!isRendererShellRequest(request)) {
      return Object.freeze({
        ok: false,
        state: this.#supervisor.snapshot().state,
        pid: null,
        reason: 'runner stop request rejected: not a renderer shell request',
      });
    }
    const snapshot = await this.#supervisor.stop();
    this.#applyRunnerState(snapshot.state);
    return Object.freeze({
      ok: true,
      state: snapshot.state,
      pid: snapshot.pid,
      reason: 'headless runner stopped; no orphan process remains',
    });
  }

  async runnerHealth(): Promise<RunnerHealthResponse> {
    const snapshot = await this.#supervisor.health(this.#now());
    this.#applyRunnerState(snapshot.state);
    return Object.freeze({
      state: snapshot.state,
      pid: snapshot.pid,
      alive: snapshot.pid !== null && snapshot.state === 'RUNNING',
      checkedAtMs: this.#now(),
      lastExitCode: snapshot.lastExitCode,
      lastExitSignal: snapshot.lastExitSignal,
    });
  }

  async pairingDeepLinkSubmit(request: unknown): Promise<PairingDeepLinkResponse> {
    const typed = request as PairingDeepLinkRequest;
    if (typeof typed?.deepLink !== 'string') {
      return Object.freeze({
        accepted: false,
        kind: 'unknown' as const,
        correlationRef: null,
        reason: 'deep link payload rejected: expected a string field',
        pairingAuthorityOwnedBy: '#3080' as const,
        credentialStored: false as const,
        sessionMinted: false as const,
        pairingCodeTransferred: false as const,
        pairingCodePersisted: false as const,
        pairingCodeRendererDiagnostic: false as const,
      });
    }
    try {
      const parsed = parsePairingDeepLink(typed.deepLink);
      this.#pairingSeamAccepted = true;
      this.#transition('PAIRING', 'pairing_seam_accepted', 'padiem:// deep link accepted by the shell seam');
      // #3095: the bounded code is consumed here, in the main process, and is
      // never returned to the renderer. Only the boolean fact is reported.
      const pairingCode = takePairingCodeTransfer(parsed);
      let pairingCodeTransferred = false;
      if (pairingCode !== null) {
        const marker = pairingHandoffConsumedMarker(pairingCode);
        if (this.#consumedPairingHandoffs.has(marker)) {
          // A spent handoff is never re-armed: replaying the deep link must not
          // hand the runner the same one-time pairing code again. Reuses the
          // existing rejection trigger so no new lifecycle trigger is invented.
          this.#transition(
            'PAIRING',
            'pairing_seam_rejected',
            'padiem:// pairing handoff replay rejected by the shell seam',
          );
        } else {
          this.#lastPairingHandoff = {
            pairingCode,
            correlationRef: parsed.correlationRef,
          };
          pairingCodeTransferred = true;
        }
      }
      return Object.freeze({
        accepted: true,
        kind: parsed.kind,
        correlationRef: parsed.correlationRef,
        reason: `pairing seam accepted; canonical pairing is owned by #3080 (params: ${parsed.paramNames.join(',') || 'none'})`,
        pairingAuthorityOwnedBy: '#3080' as const,
        credentialStored: false as const,
        sessionMinted: false as const,
        pairingCodeTransferred,
        pairingCodePersisted: false as const,
        pairingCodeRendererDiagnostic: false as const,
      });
    } catch (error) {
      this.#transition('NOT_PAIRED', 'pairing_seam_rejected', 'padiem:// deep link rejected by the shell seam');
      return Object.freeze({
        accepted: false,
        kind: 'unknown' as const,
        correlationRef: null,
        reason: error instanceof Error ? error.message : String(error),
        pairingAuthorityOwnedBy: '#3080' as const,
        credentialStored: false as const,
        sessionMinted: false as const,
        pairingCodeTransferred: false as const,
        pairingCodePersisted: false as const,
        pairingCodeRendererDiagnostic: false as const,
      });
    }
  }

  /**
   * #3095: take the single bounded pairing handoff for the trusted runner.
   *
   * The handoff is consumed exactly once and the stored reference is dropped
   * immediately, so a replayed deep link cannot reuse an already-taken code.
   * Nothing here logs, persists, or projects the value to the renderer.
   */
  takePairingHandoffForRunner(): { pairingCode: string; correlationRef: string } | null {
    const handoff = this.#lastPairingHandoff;
    this.#lastPairingHandoff = null;
    if (handoff === null) {
      return null;
    }
    // Mark the handoff spent. Only a non-reversible marker is retained, and the
    // ledger is bounded so a long-lived session cannot grow it without limit.
    this.#consumedPairingHandoffs.add(pairingHandoffConsumedMarker(handoff.pairingCode));
    if (this.#consumedPairingHandoffs.size > PAIRING_HANDOFF_LEDGER_LIMIT) {
      const oldest = this.#consumedPairingHandoffs.values().next();
      if (!oldest.done) this.#consumedPairingHandoffs.delete(oldest.value);
    }
    return handoff;
  }

  getBoundedLog(request: unknown): BoundedLogResponse {
    const typed = (request ?? {}) as BoundedLogRequest;
    const maxLines =
      typeof typed.maxLines === 'number' ? typed.maxLines : undefined;
    return projectBoundedLog(this.#boundedLogLines(), maxLines);
  }

  /** Electron shutdown path: the runner must not outlive the app. */
  async shutdown(): Promise<void> {
    await this.#supervisor.shutdown();
    this.#applyRunnerState('STOPPED');
  }

  #applyRunnerState(state: string): void {
    if (state === 'RUNNING') {
      if (this.#device.state === 'ONLINE') {
        this.#presenceNote = 'runner healthy and device presence confirmed by the shell projection';
        return;
      }
      // A locally healthy runner is never proof that this device is paired or
      // reachable from Padiem Cloud. Until #3080 supplies the canonical server
      // projection, preserve the current non-ONLINE presentation state.
      this.#presenceNote =
        `headless runner is running locally, but device state remains ${this.#device.state}: canonical ONLINE presence is owned by #3080`;
      return;
    }
    this.#presenceNote =
      this.#device.state === 'ONLINE'
        ? `headless runner is ${state}; device presence is no longer confirmed`
        : `headless runner is ${state}`;
    if (this.#device.state === 'ONLINE') {
      this.#transition('OFFLINE', 'runner_unhealthy', `headless runner state: ${state}`);
    }
  }

  #transition(
    to: DeviceLifecycleState,
    trigger: Parameters<typeof projectDeviceLifecycle>[1],
    reason: string,
  ): void {
    if (!DEVICE_LIFECYCLE_STATES.includes(to)) {
      throw new IpcContractError(`refusing to project unknown device state: ${to}`);
    }
    try {
      this.#device = projectDeviceLifecycle(this.#device, trigger, to, reason);
    } catch {
      // Fail closed: an illegal presentation edge is simply not projected.
    }
  }
}

function isRendererShellRequest(request: unknown): request is RunnerStartRequest {
  return (
    typeof request === 'object' &&
    request !== null &&
    (request as RunnerStartRequest).requestedBy === 'renderer-shell'
  );
}

export const SHELL_CONTROLLER_CHANNELS = IPC_CHANNELS;
