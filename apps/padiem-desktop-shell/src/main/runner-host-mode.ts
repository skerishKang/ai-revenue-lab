/**
 * CLAW2 #3093 — explicit runner host mode.
 *
 * #3083's supervisor launches the headless runner as a **separate process**.
 * Under a packaged Electron build `process.execPath` is the Electron GUI
 * binary, not Node — spawning `electron.exe headless-runner.js` without
 * `ELECTRON_RUN_AS_NODE=1` would start a *second full Electron app*, not a
 * runner. Conversely, the integration tests run under plain Node, where
 * `process.execPath` is `node.exe`; that path is legitimate for tests but must
 * never be assumed in production.
 *
 * This module makes the choice explicit instead of implicit. Exactly one mode
 * wins, in this precedence:
 *
 *   1. `PADIEM_RUNNER_EXECUTABLE` — an operator-provided runner binary
 *      (absolute path only). Used verbatim; no Electron node-mode env is added,
 *      because a dedicated runner executable is already a node host.
 *   2. `electron-run-as-node` — the shell is itself running under Electron
 *      (`process.versions.electron` present). The runner is the same Electron
 *      binary with `ELECTRON_RUN_AS_NODE=1`, the documented Electron-as-Node
 *      host mode.
 *   3. `plain-node` — source checkout / test host, where execPath is Node.
 *      Marked as such so production code paths can assert they are not here.
 *
 *   RUNNER_NODE_MODE_EXPLICIT=YES
 *   TEST_ONLY_EXEC_PATH_ASSUMPTION=NO
 *   RUNNER_SPAWN_SHELL=NO               (unchanged: shell:false everywhere)
 */

export const ELECTRON_RUN_AS_NODE_ENV = 'ELECTRON_RUN_AS_NODE';

export interface RunnerHostModeInput {
  /** `process.execPath` of the Electron main process. */
  readonly execPath: string;
  /** `process.versions.electron` — present only under Electron. */
  readonly electronVersion: string | undefined;
  /** `process.env.PADIEM_RUNNER_EXECUTABLE` — operator override, if any. */
  readonly runnerExecutableOverride: string | undefined;
  readonly platform: NodeJS.Platform;
}

export type RunnerHostModeName = 'explicit-executable' | 'electron-run-as-node' | 'plain-node';

export interface RunnerHostMode {
  readonly mode: RunnerHostModeName;
  readonly executablePath: string;
  /** Extra env entries the spawn spec must carry for this mode. */
  readonly env: Readonly<Record<string, string>>;
  /** True when this mode is only valid outside a packaged production build. */
  readonly testOrDevOnly: boolean;
  readonly reason: string;
}

function isAbsoluteForPlatform(platform: NodeJS.Platform, candidate: string): boolean {
  if (platform === 'win32') {
    // drive-letter (C:\...), UNC (\\server\share), or POSIX-style absolute.
    return /^[a-zA-Z]:[\\/]/.test(candidate) || candidate.startsWith('\\\\') || candidate.startsWith('/');
  }
  return candidate.startsWith('/');
}

/**
 * Pure decision function. `main.ts` calls it once at startup and the result is
 * frozen into the spawn spec, so the supervisor never has to guess what its
 * executable actually is.
 */
export function resolveRunnerHostMode(input: RunnerHostModeInput): RunnerHostMode {
  const override = input.runnerExecutableOverride?.trim();
  if (override !== undefined && override.length > 0) {
    if (!isAbsoluteForPlatform(input.platform, override)) {
      throw new Error(
        'PADIEM_RUNNER_EXECUTABLE must be an absolute path; refusing a PATH-resolved runner binary',
      );
    }
    return {
      mode: 'explicit-executable',
      executablePath: override,
      env: {},
      testOrDevOnly: false,
      reason: 'operator-provided runner executable is used verbatim without node-mode env',
    };
  }
  if (input.electronVersion !== undefined) {
    return {
      mode: 'electron-run-as-node',
      executablePath: input.execPath,
      env: { [ELECTRON_RUN_AS_NODE_ENV]: '1' },
      testOrDevOnly: false,
      reason: `running under Electron ${input.electronVersion}; the runner reuses the Electron binary in ELECTRON_RUN_AS_NODE=1 host mode`,
    };
  }
  return {
    mode: 'plain-node',
    executablePath: input.execPath,
    env: {},
    testOrDevOnly: true,
    reason: 'not under Electron: source-checkout or test host; execPath is plain Node',
  };
}

export const RUNNER_HOST_MODE_CONTRACT = Object.freeze({
  MODES: ['explicit-executable', 'electron-run-as-node', 'plain-node'] as const,
  OVERRIDE_ENV: 'PADIEM_RUNNER_EXECUTABLE',
  NODE_MODE_ENV: ELECTRON_RUN_AS_NODE_ENV,
  OVERRIDE_MUST_BE_ABSOLUTE: true,
  IMPLICIT_EXEC_PATH_ASSUMPTION: false,
} as const);
