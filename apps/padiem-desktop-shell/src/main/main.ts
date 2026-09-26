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
import { existsSync } from 'node:fs';
import path from 'node:path';

import { IPC_CHANNELS, type IpcChannel } from '../contract/ipc.js';
import { ShellController } from '../supervisor/shell-controller.js';
import { NodeRunnerProcessPort } from '../supervisor/production-runner-process-port.js';
import { HeadlessRunnerSupervisor } from '../supervisor/runner-supervisor.js';
import { registerWindowsProtocolClient } from './protocol-registration.js';
import { acquireSingleInstanceOwnership } from './single-instance.js';
import { resolveRunnerHostMode } from './runner-host-mode.js';

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
    ipcMain.handle(channel, (_event, request: unknown) => handler(request));
  }
  handlersRegistered = true;
}

/** Bounded `padiem://` intake. #3080 owns what happens after acceptance. */
export function registerDeepLinkHandling(): void {
  app.on('open-url', (event, url) => {
    event.preventDefault();
    void controller.pairingDeepLinkSubmit({ deepLink: url });
  });
  for (const argv of process.argv.slice(1)) {
    if (argv.toLowerCase().startsWith('padiem://')) {
      void controller.pairingDeepLinkSubmit({ deepLink: argv });
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
