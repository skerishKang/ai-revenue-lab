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

import { BrowserWindow, app, dialog, ipcMain } from 'electron';
import { fileURLToPath } from 'node:url';
import {existsSync, writeFileSync } from 'node:fs';
import path from 'node:path';

import { IPC_CHANNELS, type IpcChannel } from '../contract/ipc.js';
import { redactEvidenceLine } from '../contract/safe-log-projection.js';
import { ShellController } from '../supervisor/shell-controller.js';
import { NodeRunnerProcessPort } from '../supervisor/production-runner-process-port.js';
import {
  HeadlessRunnerSupervisor,
  type RunnerSpawnSpec,
} from '../supervisor/runner-supervisor.js';
import { registerWindowsProtocolClient } from './protocol-registration.js';
import { acquireSingleInstanceOwnership } from './single-instance.js';
import { PairingHandoffConsumer } from './pairing-handoff-consumer.js';
import { resolveRunnerHostMode } from './runner-host-mode.js';
import { LocalWorkspaceController } from '../workspace/local-workspace.js';
import { createElectronBrowserOpenViewPort } from '../browser/browser-open-electron-view.js';
import { composeTrustedBrowserOpen } from '../browser/browser-open-composition.js';
import {
  CanonicalConversationController,
} from '../conversation/canonical-conversation.js';
import {
  CanonicalRunController,
} from '../run/canonical-run.js';
import {
  createDesktopCanonicalConversationPort,
} from '../conversation/desktop-canonical-conversation-port.js';
import {
  createResidentDeviceSessionMaterialProvider,
} from '../conversation/resident-device-session-material.js';

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
  const packagedRunnerRoot =
    process.resourcesPath && fsExists(path.join(process.resourcesPath, 'runner'))
      ? path.join(process.resourcesPath, 'runner')
      : null;
  const runnerRoot = process.env.PADIEM_RUNNER_ROOT
    ? path.resolve(process.env.PADIEM_RUNNER_ROOT)
    : packagedRunnerRoot ?? path.join(__dirname_, '..', 'runner');
  // #3093 (reopen): a packaged build must not take the runner's working
  // directory from the asar archive — a process cannot chdir into the virtual
  // asar file system and the spawn fails with ENOENT (measured: the packaged
  // supervisor reported CRASHED). The resources directory is a real path in a
  // packaged build; a source checkout keeps its real dist/src.
  const cwd = packagedRunnerRoot ? process.resourcesPath : path.join(__dirname_, '..');
  return {
    executablePath: runnerHostMode.executablePath,
    args: [path.join(runnerRoot, 'headless-runner.js')],
    cwd,
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

export const localWorkspace = new LocalWorkspaceController(async () => {
  const result = await dialog.showOpenDialog({
    title: 'Choose a Padiem work folder',
    properties: ['openDirectory'],
  });
  if (result.canceled || result.filePaths.length !== 1) {
    return null;
  }
  return result.filePaths[0] ?? null;
});

/**
 * #3436 B2c/B2d — canonical conversation consumer over the authenticated port.
 *
 * The main process composes the authenticated canonical conversation port: it
 * presents the canonical Local Agent Broker device session to the padiem-chat
 * GET-only Desktop conversation surface and reads the same canonical
 * conversations the Web reads. B2d replaces the B2c placeholder provider with
 * the trusted resident boundary: each call asks the supervised resident host
 * for a bounded projection of the session state it already holds — the host's
 * own canonical session and the existing protected credential store — over the
 * existing stdio line channel. The provider stays main-process-only
 * (RENDERER_DEVICE_CREDENTIAL=0, RENDERER_SESSION_ID=0, RENDERER_MATERIAL_API=0);
 * no session is opened by the Desktop (DESKTOP_SESSION_OPEN=0) and nothing is
 * persisted (RAW_CREDENTIAL_SECOND_PERSISTENCE=0). Without an online resident
 * every call is null, and the surface keeps the exact B2b fail-closed
 * presentation — "canonical conversation unavailable", never a temporary local
 * conversation. The chat base URL is a named trusted input, never inherited
 * request content.
 */
export const canonicalConversations = new CanonicalConversationController(
  createDesktopCanonicalConversationPort({
    chatBaseUrl: process.env.PADIEM_CHAT_BASE_URL ?? null,
    materialProvider: createResidentDeviceSessionMaterialProvider({
      boundary: {
        sendResidentLine: (line: string) => supervisor.sendResidentLine(line),
        takeResidentMaterialLine: () => supervisor.takeResidentMaterialLine(),
        residentRunning: () => supervisor.residentSnapshot().running,
      },
    }),
  }),
);

/**
 * #3436 B3a — canonical run consumer.
 *
 * Left on the fail-closed unconfigured port: the Desktop holds no canonical
 * Padiem session credential in this slice, so every run surface reads as
 * "canonical run unavailable" instead of minting or caching a local one. A
 * future authenticated transport (B2c's credential/session work) is a
 * main-process-only swap here.
 */
export const canonicalRuns = new CanonicalRunController();

/**
 * #3611 — the trusted-main `browser.open` composition.
 *
 * The ephemeral view owner is the *only* Electron-touching browser module, and it
 * is created here, in the trusted main process, exactly once. The canonical
 * redemption port is deliberately left unconfigured: the desktop owns no durable
 * store, so the one-shot authority stays with the agent-side canonical store and
 * an unwired build fails closed instead of opening a browser on its own say-so.
 */
export const browserOpen = composeTrustedBrowserOpen({
  view: createElectronBrowserOpenViewPort(),
});

export const controller = new ShellController({
  supervisor,
  boundedLogLines: () => processPort.boundedActiveOutput().lines,
  workspace: localWorkspace,
  conversations: canonicalConversations,
  runs: canonicalRuns,
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
  // #3471: this privileged WebContents is a packaged local UI only. Electron's
  // will-navigate event is for renderer/page initiated navigation (the initial
  // main-process loadFile below is not a renderer navigation), so deny every
  // attempt instead of carrying the preload bridge onto another document.
  window.webContents.on('will-navigate', (event) => event.preventDefault());
  window.webContents.on('will-redirect', (event) => event.preventDefault());
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  void window.loadFile(path.join(__dirname_, '..', 'renderer', 'index.html'));
  mainWindow = window;
  return window;
}

let handlersRegistered = false;


/**
 * #3140 — the resident host process, spawned and reaped by the supervisor.
 *
 * It is a real product process, so it goes through the same `RunnerProcessPort`
 * as the runner and the same `shutdownRunner()` path; nothing in the shell
 * spawns a child outside that port. The environment is the bounded config
 * projection only, never the shell's whole environment.
 */
function residentSpec(): RunnerSpawnSpec | null {
  const projectRoot = process.env.PADIEM_AGENT_PROJECT_ROOT;
  if (!projectRoot) return null;
  const python = process.env.PADIEM_PYTHON ?? 'python';
  // #3140 stall diagnosis: read once, so the resident env stays a named list
  // with each variable referenced exactly once.
  const phaseDumpAfterSeconds = process.env.PADIEM_3140_PHASE_DUMP_AFTER_SECONDS;
  return {
    executablePath: python,
    args: ['-m', 'kagent.local_agent_resident_process'],
    cwd: path.resolve(projectRoot),
    // Named trusted inputs only — never `...process.env`. The resident refuses
    // to invent a broker, so everything it is allowed to know is listed here.
    env: {
      PYTHONUNBUFFERED: '1',
      PADIEM_AGENT_PROJECT_ROOT: path.resolve(projectRoot),
      ...(process.env.PADIEM_AGENT_DEVICE_ID ? { PADIEM_AGENT_DEVICE_ID: process.env.PADIEM_AGENT_DEVICE_ID } : {}),
      ...(process.env.PADIEM_AGENT_AUTHORITY_REF ? { PADIEM_AGENT_AUTHORITY_REF: process.env.PADIEM_AGENT_AUTHORITY_REF } : {}),
      ...(process.env.PADIEM_AGENT_REQUEST_PORT ? { PADIEM_AGENT_REQUEST_PORT: process.env.PADIEM_AGENT_REQUEST_PORT } : {}),
      // The client port connects to the shared broker owner; the resident is
      // given the URL as a named trusted input, never as inherited environment.
      ...(process.env.PADIEM_AGENT_BROKER_URL ? { PADIEM_AGENT_BROKER_URL: process.env.PADIEM_AGENT_BROKER_URL } : {}),
      // #3140 review item 2: the credential store is a persistent protected
      // path, so it travels in the projection rather than being invented.
      ...(process.env.PADIEM_AGENT_CREDENTIAL_DIR ? { PADIEM_AGENT_CREDENTIAL_DIR: process.env.PADIEM_AGENT_CREDENTIAL_DIR } : {}),
      // #3140 stall diagnosis: opt-in, bounded stack reporting while no phase
      // completes. Absent by default, so a normal run is unchanged.
      ...(phaseDumpAfterSeconds
        ? { PADIEM_3140_PHASE_DUMP_AFTER_SECONDS: phaseDumpAfterSeconds }
        : {}),
    },
    shell: false,
    stdio: 'pipe',
  };
}

const HANDOFF_ACK_TIMEOUT_MS = 30_000;
const HANDOFF_ACK_CONTRACT = 'claw-desktop-pairing-ack.v1';

function parseHandoffAck(line: string): { acknowledged: boolean; handoffMarker: string | null } {
  try {
    const parsed = JSON.parse(line) as Record<string, unknown>;
    if (parsed.event !== 'handoff_ack' || parsed.contract_version !== HANDOFF_ACK_CONTRACT) {
      return { acknowledged: false, handoffMarker: null };
    }
    const marker = parsed.handoff_marker;
    if (typeof marker !== 'string' || marker.length === 0 || marker.length > 64) {
      return { acknowledged: false, handoffMarker: null };
    }
    return { acknowledged: true, handoffMarker: marker };
  } catch {
    return { acknowledged: false, handoffMarker: null };
  }
}

async function ensureResidentProcess(): Promise<boolean> {
  if (supervisor.residentSnapshot().running) return true;
  const spec = residentSpec();
  if (!spec) return false;
  await supervisor.startResident(spec);
  supervisor.onResidentSettled(() => {
    try {
      recordPairingHandoffEvidence(lastHandoffOutcome);
    } catch {
      // Evidence capture must never disturb shutdown.
    }
  });
  return true;
}

let lastHandoffOutcome = 'no_pending_handoff';

export const pairingHandoffConsumer = new PairingHandoffConsumer({
  source: controller,
  deliver: async (line: string) => {
    if (!supervisor.sendResidentLine(line)) {
      return { acknowledged: false, handoffMarker: null };
    }
    // #3140 review A: a written line is not an acknowledgement. Wait for the
    // resident's own bounded, secret-free ACK and accept only a matching one.
    const deadline = Date.now() + HANDOFF_ACK_TIMEOUT_MS;
    while (Date.now() < deadline) {
      if (!supervisor.residentSnapshot().running) {
        return { acknowledged: false, handoffMarker: null };
      }
      // #3140 review D: the resident's own projection, never the runner's.
      for (const line2 of [...supervisor.boundedResidentOutput().lines].reverse()) {
        if (!line2.includes('handoff_ack')) continue;
        return parseHandoffAck(line2);
      }
      await new Promise((resolve) => setTimeout(resolve, 200));
    }
    return { acknowledged: false, handoffMarker: null };
  },
  isRunnerLive: () => residentSpec() !== null,
});

let evidenceFlushTimer: NodeJS.Timeout | null = null;

/**
 * #3140 stall diagnosis: keep the evidence marker current while the flow runs.
 *
 * The marker is otherwise written only when the handoff settles, so a stall
 * after the last write (including a stall stack reported on the child's stderr)
 * would never reach the evidence file. Bounded to a one-second cadence and only
 * active when an evidence marker was asked for.
 */
/** The one place the evidence marker path is read from the environment. */
function evidenceMarkerPath(): string | undefined {
  return process.env.PADIEM_3140_EVIDENCE_MARKER;
}

function startEvidenceFlush(): void {
  if (!evidenceMarkerPath()) return;
  if (evidenceFlushTimer) return;
  evidenceFlushTimer = setInterval(() => {
    if (!lastHandoffOutcome) return;
    recordPairingHandoffEvidence(lastHandoffOutcome);
  }, 1000);
  evidenceFlushTimer.unref?.();
}

export async function deliverPendingPairingHandoff(): Promise<void> {
  if (!(await ensureResidentProcess())) {
    lastHandoffOutcome = 'runner_unavailable';
    recordPairingHandoffEvidence(lastHandoffOutcome);
    return;
  }
  startEvidenceFlush();
  lastHandoffOutcome = await pairingHandoffConsumer.deliverPending();
  recordPairingHandoffEvidence(lastHandoffOutcome);
}

/**
 * #3140 stall diagnosis: bounded, secret-free observation projection.
 *
 * Every persisted diagnostic line is projected through the same credential
 * redaction plus pairing-code masking, so a child mistake cannot turn the
 * evidence marker into a secret persistence channel.
 */
function redactObservation(
  observation: Record<string, unknown> | null,
): Record<string, unknown> | null {
  if (!observation) return null;
  const tail = Array.isArray(observation.stderr_tail) ? observation.stderr_tail : [];
  return {
    ...observation,
    stderr_tail: tail.map((line) => redactEvidenceLine(String(line))),
  };
}

function recordPairingHandoffEvidence(outcome: string): void {
  const markerPath = evidenceMarkerPath();
  if (!markerPath) return;
  try {
    writeFileSync(
      markerPath,
      `${JSON.stringify(
        {
          handoff_outcome: outcome,
          handoff_delivered: outcome === 'delivered',
          consumer: pairingHandoffConsumer.stats(),
          main_flow_running: supervisor.residentSnapshot().running,
          main_flow_lines: supervisor
            .boundedResidentOutput()
            .lines.filter(
              (line) =>
                !line.includes('pairing_code"') &&
                // #3436 B2d: a material response is never evidence; the
                // capture layer already redacts it, this keeps the raw event
                // name itself out of the bundle too.
                !line.includes('desktop_device_session_material'),
            )
            .map((line) => redactEvidenceLine(String(line))),
          // #3140 stall diagnosis: per-stream timing for the resident child, so a
          // silent stall can be located instead of guessed at.
          resident_observation: redactObservation(supervisor.residentObservation()),
          marker_written_at: new Date().toISOString(),
        },
        null,
        2,
      )}
`,
      { encoding: 'utf8' },
    );
  } catch {
    // Evidence capture must never disturb the product path.
  }
}

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
    void controller.pairingDeepLinkSubmit({ deepLink: url }).then(() => deliverPendingPairingHandoff());
  });
  for (const argv of process.argv.slice(1)) {
    if (argv.toLowerCase().startsWith('padiem://')) {
      void controller.pairingDeepLinkSubmit({ deepLink: argv }).then(() => deliverPendingPairingHandoff());
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
    // #3140 review B: a forwarded deep link is accepted by the same seam and
    // then gets the same delivery orchestration as an open-url / argv link.
    forwardDeepLink: (deepLink) => {
      void controller
        .pairingDeepLinkSubmit({ deepLink })
        .then(() => deliverPendingPairingHandoff());
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
  await supervisor.stopResident();
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
