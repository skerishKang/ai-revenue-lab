/**
 * CLAW4 #3083 — Electron main process.
 *
 * Responsibilities:
 *   - create the BrowserWindow with strict contextIsolation
 *   - register exactly the allowlisted IPC handlers
 *   - supervise the separate headless runner process
 *   - clean shutdown without orphaning the runner
 *   - bounded `padiem://` deep-link intake
 *
 * It is NOT:
 *   - a P01 replacement (approval authority stays in the runner/P01 stack)
 *   - a broker authority (#3080)
 *   - a second execution authority
 */

import { BrowserWindow, app, ipcMain } from 'electron';
import { fileURLToPath } from 'node:url';
import { existsSync, writeFileSync } from 'node:fs';
import path from 'node:path';

import { IPC_CHANNELS, type IpcChannel } from '../contract/ipc.js';
import { ShellController } from '../supervisor/shell-controller.js';
import { NodeRunnerProcessPort } from '../supervisor/production-runner-process-port.js';
import { HeadlessRunnerSupervisor } from '../supervisor/runner-supervisor.js';
import { registerWindowsProtocolClient } from './protocol-registration.js';
import { acquireSingleInstanceOwnership } from './single-instance.js';
import { resolveRunnerHostMode } from './runner-host-mode.js';
import { PairingHandoffConsumer } from './pairing-handoff-consumer.js';
import {
  PairingMainFlowProcess,
  resolvePairingMainFlowPython,
} from './pairing-main-flow-process.js';

const __dirname_ = path.dirname(fileURLToPath(import.meta.url));

/**
 * Window security posture. These values are asserted by tests, so they are
 * written out explicitly rather than left to Electron defaults.
 */
export const WINDOW_SECURITY = Object.freeze({
  contextIsolation: true,
  nodeIntegration: false,
  sandbox: true,
  webSecurity: true,
  allowRunningInsecureContent: false,
  experimentalFeatures: false,
  enableRemoteModule: false,
  spellcheck: false,
} as const);

const processPort = new NodeRunnerProcessPort();

/**
 * #3093 — the runner host is chosen explicitly, never by assuming that
 * `process.execPath` is Node. Under a packaged Electron build execPath is the
 * Electron GUI binary, so the runner reuses it in `ELECTRON_RUN_AS_NODE=1`
 * host mode unless the operator pins `PADIEM_RUNNER_EXECUTABLE` to a dedicated
 * runner binary. The plain-node branch exists only for source-checkout and
 * test hosts and is marked as such.
 */
export const runnerHostMode = resolveRunnerHostMode({
  execPath: process.execPath,
  electronVersion: process.versions.electron,
  runnerExecutableOverride: process.env.PADIEM_RUNNER_EXECUTABLE,
  platform: process.platform,
});

/**
 * M1 shell default: the headless runner is launched from the packaged
 * `resources/runner` folder in production and from `dist/runner` in a source
 * checkout. There is no shell, no elevation, and no user-supplied argv.
 */
function runnerSpawnSpec(): {
  executablePath: string;
  args: readonly string[];
  cwd: string;
  env: Record<string, string>;
  shell: false;
  stdio: 'pipe';
} {
  // Packaged builds ship the runner under `resources/runner`; a source checkout
  // runs the compiled runner from `dist/src/runner`.
  const runnerRoot = process.env.PADIEM_RUNNER_ROOT
    ? path.resolve(process.env.PADIEM_RUNNER_ROOT)
    : process.resourcesPath && fsExists(path.join(process.resourcesPath, 'runner'))
      ? path.join(process.resourcesPath, 'runner')
      : path.join(__dirname_, '..', 'runner');
  return {
    executablePath: runnerHostMode.executablePath,
    args: [path.join(runnerRoot, 'headless-runner.js')],
    cwd: path.join(__dirname_, '..'),
    env: {
      PADIEM_SHELL: 'padiem-desktop-shell',
      PADIEM_RUNNER_ROOT: runnerRoot,
      ...runnerHostMode.env,
    },
    shell: false,
    stdio: 'pipe',
  };
}

function fsExists(candidate: string): boolean {
  try {
    return existsSync(candidate);
  } catch {
    return false;
  }
}

export const supervisor = new HeadlessRunnerSupervisor({
  port: processPort,
  spec: runnerSpawnSpec(),
});

export const controller = new ShellController({
  supervisor,
  boundedLogLines: () => processPort.boundedActiveOutput().lines,
});

/**
 * #3140 — the main-process consumer of the bounded pairing handoff.
 *
 * #3095 left the handoff armed with no main-flow caller; this is that caller.
 * It drains the one-shot handoff into the pairing main flow — the existing
 * #3095 runner composed with the existing #3014 resident host — and keeps no
 * copy of the code. The pairing authority stays #3080's, the resident host
 * stays #3014's and execution authority stays with P01: this wiring decides
 * nothing.
 *
 * The main process owns the child because #3083 pins `CHILD_PROCESS_USED_ONLY_IN_MAIN`.
 */
let pairingMainFlow: PairingMainFlowProcess | null = null;

function pairingMainFlowProcess(): PairingMainFlowProcess | null {
  if (pairingMainFlow) return pairingMainFlow;
  const resolved = resolvePairingMainFlowPython();
  if (!resolved) return null;
  pairingMainFlow = new PairingMainFlowProcess(resolved);
  // Re-record on exit so the evidence carries the flow's *result* — the
  // canonical session/poll path — and not only the fact of delivery.
  pairingMainFlow.onSettled(() => recordPairingHandoffEvidence(lastHandoffOutcome));
  return pairingMainFlow;
}

let lastHandoffOutcome = 'no_pending_handoff';

export const pairingHandoffConsumer = new PairingHandoffConsumer({
  source: controller,
  // Starting the flow is the delivery's own business: `isRunnerLive` only
  // reports that the destination exists, so no child is spawned for a deep
  // link that carries no handoff.
  deliver: (line) => pairingMainFlowProcess()?.writeHandoff(line) ?? false,
  isRunnerLive: () => resolvePairingMainFlowPython() !== null,
});

/**
 * Delivers a pending handoff exactly once, starting the pairing main flow if
 * it is not already running.
 *
 * Called on every deep link and once more when the runner starts, so a link
 * that arrives before the flow exists is still delivered — the handoff stays
 * armed until it can actually be sent, and is never burned by a missing
 * destination.
 */
export function deliverPendingPairingHandoff(): void {
  lastHandoffOutcome = pairingHandoffConsumer.deliverPending();
  recordPairingHandoffEvidence(lastHandoffOutcome);
}

/**
 * #3140 — evidence-only marker.
 *
 * Off unless `PADIEM_3140_EVIDENCE_MARKER` names a file, so the product never
 * writes this in normal operation. The payload is secret-free by construction:
 * a delivery outcome, counts and a non-reversible marker. The pairing code is
 * never part of it, which is what makes the file safe to hand to a test.
 */
function recordPairingHandoffEvidence(outcome: string): void {
  const markerPath = process.env.PADIEM_3140_EVIDENCE_MARKER;
  if (!markerPath) return;
  const flow = pairingMainFlow?.status() ?? null;
  try {
    writeFileSync(
      markerPath,
      `${JSON.stringify(
        {
          handoff_outcome: outcome,
          handoff_delivered: outcome === 'delivered',
          consumer: pairingHandoffConsumer.stats(),
          main_flow_running: flow?.running ?? false,
          // Bounded, secret-free status lines the flow printed.
          main_flow_lines: (flow?.lines ?? []).filter((line) => !line.includes('pairing_code"')),
        },
        null,
        2,
      )}\n`,
      { encoding: 'utf8' },
    );
  } catch {
    // Evidence capture must never disturb the product path.
  }
}

let mainWindow: BrowserWindow | null = null;

export function createMainWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: 1100,
    height: 760,
    minWidth: 900,
    minHeight: 600,
    show: false,
    webPreferences: {
      ...WINDOW_SECURITY,
      preload: path.join(__dirname_, '..', 'preload', 'preload.cjs'),
    },
  });
  window.once('ready-to-show', () => window.show());
  // The shell never navigates to remote content and never opens windows.
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  void window.loadFile(path.join(__dirname_, '..', 'renderer', 'index.html'));
  mainWindow = window;
  return window;
}

let handlersRegistered = false;

export function registerIpcHandlers(target: ShellController = controller): void {
  if (handlersRegistered) return;
  const handlers = target.handlers();
  for (const channel of IPC_CHANNELS) {
    const handler = handlers[channel as IpcChannel];
    // Static allowlist only: the channel name is a literal from the contract,
    // and the request object is validated inside the controller.
    ipcMain.handle(channel, async (_event, request: unknown) => {
      const result = await handler(request);
      // #3140: a deep link submitted from the renderer, or a runner that has
      // just started, is the moment a pending handoff can actually be
      // delivered. Wiring it here keeps `ShellController` a pure handler map
      // and invents no new lifecycle trigger.
      if (channel === 'padiem:shell:pairing-deeplink-submit' || channel === 'padiem:shell:runner-start') {
        deliverPendingPairingHandoff();
      }
      return result;
    });
  }
  handlersRegistered = true;
}

/** Bounded `padiem://` intake. #3080 owns what happens after acceptance. */
export function registerDeepLinkHandling(): void {
  app.on('open-url', (event, url) => {
    event.preventDefault();
    void controller.pairingDeepLinkSubmit({ deepLink: url }).then(deliverPendingPairingHandoff);
  });
  for (const argv of process.argv.slice(1)) {
    if (argv.toLowerCase().startsWith('padiem://')) {
      void controller.pairingDeepLinkSubmit({ deepLink: argv }).then(deliverPendingPairingHandoff);
    }
  }
}

/**
 * #3093 — Windows protocol registration for the running launch shape.
 * Packaged builds register the scheme directly; a dev launch (`electron
 * <app-dir>`, i.e. `process.defaultApp`) must register the Electron binary
 * together with the app directory argument. Non-Windows registers nothing.
 */
export function registerWindowsProtocol(): void {
  registerWindowsProtocolClient(app, {
    platform: process.platform,
    packaged: !defaultAppFlag(),
    defaultApp: defaultAppFlag(),
    execPath: process.execPath,
    appPath: app.getAppPath(),
  });
}

function defaultAppFlag(): boolean {
  return Boolean((process as { defaultApp?: boolean }).defaultApp);
}

/**
 * #3093 — single-instance ownership. The first process to claim the lock owns
 * the `padiem://` handoff; a later launch (which is how Windows delivers a
 * deep link to a running app) forwards its argv's `padiem://` entry to the
 * existing bounded intake and wakes the primary window. A non-owner quits
 * before creating any window or runner, so the shell can never end up with
 * two supervisors racing for one runner.
 */
export function acquireInstanceOwnership(): boolean {
  const outcome = acquireSingleInstanceOwnership({
    app,
    forwardDeepLink: (deepLink) => {
      void controller.pairingDeepLinkSubmit({ deepLink });
    },
    onNotOwner: () => {
      app.quit();
    },
    onSecondInstance: () => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        if (mainWindow.isMinimized()) mainWindow.restore();
        mainWindow.show();
        mainWindow.focus();
      }
    },
  });
  return outcome.owner;
}

let shutdownComplete = false;

/** Electron shutdown path — must never orphan the headless runner. */
export async function shutdownRunner(): Promise<void> {
  if (shutdownComplete) return;
  shutdownComplete = true;
  await controller.shutdown();
}

export function installLifecycleHooks(): void {
  const quit = async (event: Electron.Event) => {
    event.preventDefault();
    await shutdownRunner();
    app.quit();
  };
  app.on('before-quit', quit);
  app.on('window-all-closed', () => {
    void shutdownRunner().finally(() => {
      if (process.platform !== 'darwin') app.quit();
    });
  });
}

// Only run when Electron actually provides the runtime (never under `node --test`).
if (app && typeof app.whenReady === 'function' && process.versions.electron) {
  // #3093: ownership is claimed synchronously before any window or runner can
  // exist. A non-owner quits immediately, so exactly one shell process per
  // user session ever supervises a headless runner.
  if (acquireInstanceOwnership()) {
    void app.whenReady().then(() => {
      registerIpcHandlers();
      registerWindowsProtocol();
      registerDeepLinkHandling();
      installLifecycleHooks();
      createMainWindow();
    });
  }
}

export { mainWindow };
