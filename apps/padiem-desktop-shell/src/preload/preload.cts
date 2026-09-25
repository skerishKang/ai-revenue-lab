/**
 * CLAW4 #3083 — Electron preload (CommonJS, sandbox-compatible).
 *
 * Exposes exactly one frozen, narrow, typed object on `window.padiemShell`.
 *
 * There is deliberately:
 *   NO generic invoke(command, args)
 *   NO arbitrary channel passthrough
 *   NO ipcRenderer exposure
 *   NO child_process / fs / shell access
 *   NO credential storage or broker/session minting
 *
 * Channel strings are literals here so this file stays dependency-free in a
 * sandboxed preload context; `tests/preload-surface.test.ts` asserts they are
 * byte-identical to the canonical `IPC_CHANNELS` allowlist.
 */

import { contextBridge, ipcRenderer } from 'electron';

const CHANNELS = {
  GET_STATUS: 'padiem:shell:get-status',
  RUNNER_START: 'padiem:shell:runner-start',
  RUNNER_STOP: 'padiem:shell:runner-stop',
  RUNNER_HEALTH: 'padiem:shell:runner-health',
  PAIRING_DEEPLINK_SUBMIT: 'padiem:shell:pairing-deeplink-submit',
  GET_BOUNDED_LOG: 'padiem:shell:get-bounded-log',
} as const;

export const PADIEM_SHELL_API = {
  CHANNELS,
  getStatus: () => ipcRenderer.invoke(CHANNELS.GET_STATUS),
  runnerStart: () =>
    ipcRenderer.invoke(CHANNELS.RUNNER_START, { requestedBy: 'renderer-shell' }),
  runnerStop: () =>
    ipcRenderer.invoke(CHANNELS.RUNNER_STOP, { requestedBy: 'renderer-shell' }),
  runnerHealth: () => ipcRenderer.invoke(CHANNELS.RUNNER_HEALTH),
  submitPairingDeepLink: (deepLink: string) =>
    ipcRenderer.invoke(CHANNELS.PAIRING_DEEPLINK_SUBMIT, { deepLink }),
  getBoundedLog: (maxLines?: number) =>
    ipcRenderer.invoke(CHANNELS.GET_BOUNDED_LOG, maxLines === undefined ? {} : { maxLines }),
} as const;

if (process.contextIsolated) {
  contextBridge.exposeInMainWorld('padiemShell', PADIEM_SHELL_API);
} else {
  // contextIsolation is mandatory; this branch exists only so a misconfigured
  // window fails loudly in development instead of silently exposing the API.
  throw new Error('padiem desktop shell requires contextIsolation=true');
}
