/**
 * CLAW4 #3083 — typed headless runner supervisor PORT + supervisor.
 *
 * Authority boundary:
 *
 *   RUNNER_IS_SEPARATE_PROCESS=YES
 *   SUPERVISOR_IS_NOT_EXECUTION_AUTHORITY=YES
 *   RUNNER_EXECUTION_SEMANTICS_REIMPLEMENTED=NO
 *   WINDOWS_JOB_OBJECT_IMPLEMENTED=NO   <-- owned by #3081 (CLAW2)
 *   PAIRING_AUTHORITY_IMPLEMENTED=NO    <-- owned by #3080 (CLAW1)
 *
 * The supervisor owns *lifecycle* only: start once, health, truthful crash
 * state, explicit stop, and shutdown cleanup. It never decides whether a task
 * is authorised — that remains P01, reached inside the runner process.
 */

import type { RunnerLifecycleState } from '../contract/ipc.js';

export interface RunnerExitResult {
  readonly code: number | null;
  readonly signal: string | null;
}

export interface RunnerProcessHandle {
  readonly pid: number;
  isAlive(): boolean;
  kill(signal?: 'SIGTERM' | 'SIGKILL'): void;
  /** Resolves when the process has exited, or after `timeoutMs` elapses. */
  waitForExit(timeoutMs: number): Promise<RunnerExitResult>;
  /** Registers a one-shot exit listener; returns an unsubscribe function. */
  onExit(listener: (result: RunnerExitResult) => void): () => void;
}

/**
 * The single seam through which the shell may start the headless runner.
 *
 * The production implementation lives in `production-runner-process-port.ts`
 * and is the ONLY place in the shell allowed to touch `child_process`.
 */
export interface RunnerProcessPort {
  /** Must reject when a runner is already running for this shell instance. */
  spawnRunner(spec: RunnerSpawnSpec): Promise<RunnerProcessHandle>;
}

export interface RunnerSpawnSpec {
  readonly executablePath: string;
  readonly args: readonly string[];
  readonly cwd: string;
  readonly env: Readonly<Record<string, string>>;
  /** No shell is ever used. Explicit and non-negotiable. */
  readonly shell: false;
  readonly stdio: 'pipe';
}

export interface RunnerSupervisorSnapshot {
  readonly state: RunnerLifecycleState;
  readonly pid: number | null;
  readonly startedAtMs: number | null;
  readonly lastExitCode: number | null;
  readonly lastExitSignal: string | null;
  readonly startCount: number;
  readonly stopCount: number;
  readonly orphanPrevented: true;
  readonly jobObjectImplementedHere: false;
}

export interface RunnerSupervisor {
  start(nowMs: number): Promise<RunnerSupervisorSnapshot>;
  health(nowMs: number): Promise<RunnerSupervisorSnapshot>;
  stop(): Promise<RunnerSupervisorSnapshot>;
  /** Called on Electron `before-quit` / window-all-closed. Must not orphan. */
  shutdown(): Promise<RunnerSupervisorSnapshot>;
  snapshot(): RunnerSupervisorSnapshot;
}

export class RunnerSupervisorError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = 'RunnerSupervisorError';
    this.code = code;
  }
}

export interface HeadlessRunnerSupervisorOptions {
  readonly port: RunnerProcessPort;
  readonly spec: RunnerSpawnSpec;
  readonly shutdownGraceMs?: number;
  readonly now?: () => number;
}

const DEFAULT_SHUTDOWN_GRACE_MS = 5000;

export class HeadlessRunnerSupervisor implements RunnerSupervisor {
  readonly #port: RunnerProcessPort;
  readonly #spec: RunnerSpawnSpec;
  readonly #graceMs: number;
  readonly #now: () => number;

  #handle: RunnerProcessHandle | null = null;
  #state: RunnerLifecycleState = 'STOPPED';
  #startedAtMs: number | null = null;
  #lastExitCode: number | null = null;
  #lastExitSignal: string | null = null;
  #startCount = 0;
  #stopCount = 0;
  #unsubscribeExit: (() => void) | null = null;

  constructor(options: HeadlessRunnerSupervisorOptions) {
    if (options.spec.shell !== false) {
      throw new RunnerSupervisorError(
        'SHELL_EXECUTION_FORBIDDEN',
        'runner spawn spec must declare shell=false',
      );
    }
    this.#port = options.port;
    this.#spec = options.spec;
    this.#graceMs = options.shutdownGraceMs ?? DEFAULT_SHUTDOWN_GRACE_MS;
    this.#now = options.now ?? (() => Date.now());
  }

  snapshot(): RunnerSupervisorSnapshot {
    return Object.freeze({
      state: this.#state,
      pid: this.#handle?.pid ?? null,
      startedAtMs: this.#startedAtMs,
      lastExitCode: this.#lastExitCode,
      lastExitSignal: this.#lastExitSignal,
      startCount: this.#startCount,
      stopCount: this.#stopCount,
      orphanPrevented: true as const,
      jobObjectImplementedHere: false as const,
    });
  }

  async start(nowMs: number = this.#now()): Promise<RunnerSupervisorSnapshot> {
    if (this.#state === 'RUNNING' || this.#state === 'STARTING') {
      throw new RunnerSupervisorError(
        'DUPLICATE_RUNNER_START',
        `runner already ${this.#state}; duplicate start refused`,
      );
    }
    if (this.#state === 'STOPPING') {
      throw new RunnerSupervisorError(
        'STOP_IN_PROGRESS',
        'runner stop is in progress; start refused until it settles',
      );
    }
    this.#state = 'STARTING';
    try {
      const handle = await this.#port.spawnRunner(this.#spec);
      this.#handle = handle;
      this.#startedAtMs = nowMs;
      this.#startCount += 1;
      this.#state = 'RUNNING';
      this.#watchExit(handle);
      return this.snapshot();
    } catch (error) {
      this.#state = 'STOPPED';
      this.#handle = null;
      throw new RunnerSupervisorError(
        'SPAWN_FAILED',
        `headless runner spawn failed: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  }

  async health(nowMs: number = this.#now()): Promise<RunnerSupervisorSnapshot> {
    void nowMs;
    const handle = this.#handle;
    if (!handle) {
      if (this.#state === 'RUNNING' || this.#state === 'STARTING') {
        this.#state = 'STOPPED';
      }
      return this.snapshot();
    }
    if (!handle.isAlive()) {
      // Truthful state, not an optimistic "still running".
      this.#state = this.#state === 'STOPPING' ? 'STOPPED' : 'CRASHED';
      return this.snapshot();
    }
    if (this.#state === 'CRASHED') {
      this.#state = 'STOPPED';
    }
    return this.snapshot();
  }

  async stop(): Promise<RunnerSupervisorSnapshot> {
    const handle = this.#handle;
    if (!handle) {
      this.#state = 'STOPPED';
      return this.snapshot();
    }
    if (this.#state === 'STOPPING') {
      return this.snapshot();
    }
    this.#state = 'STOPPING';
    this.#stopCount += 1;

    const exited = await waitForExitOrTimeout(handle, this.#graceMs);
    this.#lastExitCode = exited.code;
    this.#lastExitSignal = exited.signal;

    if (handle.isAlive()) {
      handle.kill('SIGKILL');
      const forced = await waitForExitOrTimeout(handle, this.#graceMs);
      this.#lastExitCode = forced.code;
      this.#lastExitSignal = forced.signal;
    }

    this.#unsubscribeExit?.();
    this.#unsubscribeExit = null;
    this.#handle = null;
    this.#state = 'STOPPED';
    return this.snapshot();
  }

  async shutdown(): Promise<RunnerSupervisorSnapshot> {
    return this.stop();
  }

  #watchExit(handle: RunnerProcessHandle): void {
    this.#unsubscribeExit?.();
    this.#unsubscribeExit = handle.onExit((result) => {
      if (this.#handle !== handle) {
        return;
      }
      this.#lastExitCode = result.code;
      this.#lastExitSignal = result.signal;
      this.#handle = null;
      this.#unsubscribeExit = null;
      // An exit we did not ask for is a crash and must be reported truthfully.
      this.#state = this.#state === 'STOPPING' ? 'STOPPED' : 'CRASHED';
    });
  }
}

async function waitForExitOrTimeout(
  handle: RunnerProcessHandle,
  timeoutMs: number,
): Promise<RunnerExitResult> {
  return new Promise<RunnerExitResult>((resolve) => {
    let settled = false;
    const finish = (result: RunnerExitResult) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      unsubscribe();
      resolve(result);
    };
    const unsubscribe = handle.onExit(finish);
    // Deliberately NOT unref'd: an in-flight stop is real pending work and must
    // keep the event loop alive until it settles, otherwise the process can exit
    // with a half-stopped runner.
    const timer = setTimeout(() => finish({ code: null, signal: null }), timeoutMs);
  });
}
