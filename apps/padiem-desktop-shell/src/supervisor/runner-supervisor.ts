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
  /**
   * #3140: writes one bounded line to the supervised child's stdin, so the main
   * process reaches a supervised child without a second spawn path. Returns
   * false when the child is gone or the line was refused.
   */
  sendLine?(line: string): boolean;
  /**
   * #3140 review D: the child's own bounded output projection. Kept on the
   * handle so a caller can never reach another process' buffer by accident.
   */
  boundedOutput?(): { readonly lines: readonly string[]; readonly maxLines: number };
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
  /**
   * #3140: starts the resident host process through the same port. Optional so
   * a port double that does not model a resident host still type-checks; the
   * production port implements it.
   */
  spawnResident?(spec: RunnerSpawnSpec): Promise<RunnerProcessHandle>;
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
  #residentHandle: RunnerProcessHandle | null = null;
  // #3140 diagnostic: the handle is dropped on exit, so its bounded
  // output is retained here. Otherwise the evidence marker, which is read
  // after the resident is gone, would see nothing.
  #residentSettleListeners = new Set<() => void>();
  #residentSettledOutput: { readonly lines: readonly string[]; readonly maxLines: number } | null = null;
  #residentSettledObservation: Record<string, unknown> | null = null;
  #residentStartedAtMs: number | null = null;
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

  /**
   * #3140 — owns the resident host process alongside the runner.
   *
   * The pairing main flow is a real product process, so it is started through
   * the same port and supervised here rather than through a second raw spawn.
   * That is what makes `shutdownRunner()` cover it: the shell cannot quit while
   * a Python child is still running.
   */
  async startResident(
    spec: RunnerSpawnSpec,
    nowMs: number = this.#now(),
  ): Promise<void> {
    if (this.#residentHandle && this.#residentHandle.isAlive()) {
      throw new Error('a resident host is already running for this shell instance');
    }
    const spawn = this.#port.spawnResident;
    if (typeof spawn !== 'function') {
      throw new Error('this runner process port cannot start a resident host');
    }
    const handle = await spawn.call(this.#port, spec);
    this.#residentHandle = handle;
    this.#residentStartedAtMs = nowMs;
    this.#residentSettledOutput = null;
    this.#residentSettledObservation = null;
    handle.onExit(() => {
      // Snapshot before the handle is dropped, so the output survives exit.
      this.#residentSettledOutput = this.boundedResidentOutput();
      this.#residentSettledObservation = this.residentObservation();
      for (const listener of [...this.#residentSettleListeners]) listener();
      this.#residentSettleListeners.clear();
    });
  }

  /** Registers a one-shot listener for the resident settling. */
  onResidentSettled(listener: () => void): () => void {
    this.#residentSettleListeners.add(listener);
    return () => this.#residentSettleListeners.delete(listener);
  }

  /**
   * #3140 review D: the resident host's own bounded output. Evidence and
   * diagnostics must use this, never the runner's `boundedActiveOutput()`.
   */
  boundedResidentOutput(): { readonly lines: readonly string[]; readonly maxLines: number } {
    const port = this.#port as { boundedResidentOutput?: () => { lines: readonly string[]; maxLines: number } };
    const live = port.boundedResidentOutput ? port.boundedResidentOutput() : { lines: [], maxLines: 0 };
    // A settled resident keeps its bounded output, so a read after exit still
    // shows what it said.
    if (this.#residentHandle && this.#residentHandle.isAlive()) return live;
    return this.#residentSettledOutput ?? live;
  }

  /**
   * #3140 stall diagnosis: bounded per-stream timing for the resident host.
   *
   * Read through the port so the shell never reaches into a handle directly,
   * and keep the last reading after exit so a settled resident still explains
   * where it stopped.
   */
  residentObservation(): Record<string, unknown> | null {
    const port = this.#port as {
      residentObservation?: () => Record<string, unknown> | null;
    };
    const live = port.residentObservation ? port.residentObservation() : null;
    if (this.#residentHandle && this.#residentHandle.isAlive()) return live;
    return this.#residentSettledObservation ?? live;
  }

  /** Writes one bounded line to the supervised resident host. */
  sendResidentLine(line: string): boolean {
    const handle = this.#residentHandle;
    if (!handle || !handle.isAlive()) return false;
    return handle.sendLine ? handle.sendLine(line) : false;
  }

  /**
   * #3436 B2d — the live resident's raw session-material response line,
   * one-shot, or null. Read only by the main-process material provider; the
   * retained output buffer keeps only the redacted marker.
   */
  takeResidentMaterialLine(): string | null {
    const port = this.#port as { takeResidentMaterialLine?: () => string | null };
    return port.takeResidentMaterialLine ? port.takeResidentMaterialLine() : null;
  }

  /**
   * #3611 — the live resident's bounded browser-open redemption answer,
   * one-shot, or null. Read only by the main-process redemption port.
   */
  takeResidentBrowserOpenRedemptionLine(): string | null {
    const port = this.#port as {
      takeResidentBrowserOpenRedemptionLine?: () => string | null;
    };
    return port.takeResidentBrowserOpenRedemptionLine
      ? port.takeResidentBrowserOpenRedemptionLine()
      : null;
  }

  /**
   * #3669 — the live resident's bounded browser-control lease answer
   * (both request kinds share the event tag), one-shot, or null. Read only by
   * the main-process lease authority.
   */
  takeResidentBrowserControlLeaseLine(): string | null {
    const port = this.#port as {
      takeResidentBrowserControlLeaseLine?: () => string | null;
    };
    return port.takeResidentBrowserControlLeaseLine
      ? port.takeResidentBrowserControlLeaseLine()
      : null;
  }

  /** #3782: main-only approved command answer, always one-shot and volatile. */
  takeResidentBrowserControlCommandTakeLine(): string | null {
    const port = this.#port as {
      takeResidentBrowserControlCommandTakeLine?: () => string | null;
    };
    return port.takeResidentBrowserControlCommandTakeLine
      ? port.takeResidentBrowserControlCommandTakeLine()
      : null;
  }

  residentSnapshot(): { pid: number | null; running: boolean; startedAtMs: number | null } {
    const handle = this.#residentHandle;
    return {
      pid: handle ? handle.pid : null,
      running: Boolean(handle && handle.isAlive()),
      startedAtMs: this.#residentStartedAtMs,
    };
  }

  /** Stops the resident host. Awaited by the shell's shutdown path. */
  async stopResident(graceMs?: number): Promise<boolean> {
    const handle = this.#residentHandle;
    if (!handle) return true;
    if (!handle.isAlive()) {
      this.#residentHandle = null;
      return true;
    }
    const exited = await waitForExitOrTimeout(handle, graceMs ?? this.#graceMs);
    if (!exited) {
      handle.kill('SIGKILL');
      await waitForExitOrTimeout(handle, graceMs ?? this.#graceMs);
    }
    this.#residentHandle = null;
    return true;
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
