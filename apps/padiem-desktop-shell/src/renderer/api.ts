/**
 * CLAW4 #3083 — renderer-side view of the narrow preload API.
 *
 * The renderer has NO node integration. It can only call the six allowlisted
 * methods below; there is no generic invoke and no channel parameter.
 */

import type {
  BoundedLogResponse,
  PairingDeepLinkResponse,
  RunnerHealthResponse,
  RunnerStartResponse,
  RunnerStopResponse,
  ShellStatus,
} from '../contract/ipc.js';

export interface PadiemShellApi {
  getStatus(): Promise<ShellStatus>;
  runnerStart(): Promise<RunnerStartResponse>;
  runnerStop(): Promise<RunnerStopResponse>;
  runnerHealth(): Promise<RunnerHealthResponse>;
  submitPairingDeepLink(deepLink: string): Promise<PairingDeepLinkResponse>;
  getBoundedLog(maxLines?: number): Promise<BoundedLogResponse>;
}

declare global {
  interface Window {
    padiemShell?: PadiemShellApi;
  }
}

export class RendererAuthorityError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'RendererAuthorityError';
  }
}

/**
 * Resolves the preload API or fails closed.
 *
 * There is deliberately no fallback stub: without the preload bridge the shell
 * has no capability at all, which is the correct security posture.
 */
export function requireShellApi(): PadiemShellApi {
  const api = typeof window === 'undefined' ? undefined : window.padiemShell;
  if (!api) {
    throw new RendererAuthorityError(
      'padiemShell preload bridge unavailable; renderer has no authority',
    );
  }
  return api;
}
