/**
 * CLAW4 #3083 — renderer-facing type re-exports.
 *
 * The renderer re-uses the exact contract types the main process enforces, so
 * a projection can never be reshaped on its way to the UI.
 */

export type {
  BoundedLogResponse,
  PairingDeepLinkResponse,
  RunnerHealthResponse,
  RunnerStartResponse,
  RunnerStopResponse,
  ShellStatus,
} from '../contract/ipc.js';

export type { DeviceLifecycleState } from '../contract/device-lifecycle.js';
