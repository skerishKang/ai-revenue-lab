/**
 * CLAW4 #3083 — production `RunnerProcessPort` for a separate headless runner.
 *
 * This is the ONLY module in the desktop shell permitted to import
 * `node:child_process`. It is imported exclusively by the Electron main
 * process, never by the preload script and never by the renderer.
 *
 *   CHILD_PROCESS_USED_ONLY_IN_MAIN=YES
 *   SHELL_EXECUTION_USED=NO            (shell:false, no shell host)
 *   PROCESS_TREE_KILL_IMPLEMENTED=NO   (direct process only; #3081 owns Job Object)
 */

import { spawn } from 'node:child_process';
import type { ChildProcess } from 'node:child_process';

import type {
  RunnerExitResult,
  RunnerProcessHandle,
  RunnerProcessPort,
  RunnerSpawnSpec,
} from './runner-supervisor.js';

export interface BoundedRunnerOutput {
  readonly lines: readonly string[];
  readonly maxLines: number;
}

/**
 * #3140 stall diagnosis: bounded per-stream observation of a supervised child.
 *
 * Timing is what makes a silent stall visible: if the child is alive, the pipes
 * are attached, and no line ever arrives, the last observed moment says where
 * the gap is. Nothing secret can appear here: only counts, timestamps and a
 * bounded stderr tail that the projection layer redacts.
 */
export interface RunnerProcessObservation {
  readonly pid: number;
  readonly spawn_at: string;
  readonly stdout_lines: number;
  readonly stderr_lines: number;
  readonly first_stdout_at: string | null;
  readonly first_stderr_at: string | null;
  readonly last_line_at: string | null;
  readonly exited_at: string | null;
  readonly exit_code: number | null;
  readonly exit_signal: string | null;
  readonly stdout_capture_attached: boolean;
  readonly stderr_capture_attached: boolean;
  readonly stderr_tail: readonly string[];
}

const MAX_STDERR_TAIL = 60;
const MAX_STDERR_LINE_CHARS = 400;

const DEFAULT_MAX_LINES = 200;

/**
 * #3140: the widest line the main process writes to a supervised child.
 *
 * The pairing handoff envelope is a bounded JSON object — a 32-character code,
 * a correlation ref and a contract version — so this leaves headroom without
 * becoming a pipe.
 */
export const MAX_SUPERVISED_LINE_CHARS = 4096;

class NodeRunnerProcessHandle implements RunnerProcessHandle {
  readonly pid: number;
  readonly #child: ChildProcess;
  readonly #exited: Promise<RunnerExitResult>;
  readonly #listeners = new Set<(result: RunnerExitResult) => void>();
  #result: RunnerExitResult | null = null;
  readonly #lines: string[] = [];
  readonly #maxLines: number;
  readonly #spawnAtMs = Date.now();
  readonly #stderrTail: string[] = [];
  #stdoutLines = 0;
  #stderrLines = 0;
  #firstStdoutAtMs: number | null = null;
  #firstStderrAtMs: number | null = null;
  #lastLineAtMs: number | null = null;
  #exitedAtMs: number | null = null;
  #stdoutAttached = false;
  #stderrAttached = false;

  constructor(child: ChildProcess, maxLines: number) {
    this.#child = child;
    this.pid = child.pid ?? -1;
    this.#maxLines = maxLines;
    this.#exited = new Promise<RunnerExitResult>((resolve) => {
      child.once('exit', (code, signal) => {
        this.#settle({ code, signal: signal ?? null });
      });
      child.once('error', () => {
        this.#settle({ code: null, signal: null });
      });
    });
    const capture = (stream: 'stdout' | 'stderr') => (chunk: unknown) => {
      const atMs = Date.now();
      const text = String(chunk);
      for (const line of text.split(/\r?\n/)) {
        if (line.length === 0) continue;
        this.#lines.push(line);
        if (this.#lines.length > this.#maxLines) this.#lines.shift();
        this.#lastLineAtMs = atMs;
        if (stream === 'stdout') {
          this.#stdoutLines += 1;
          if (this.#firstStdoutAtMs === null) this.#firstStdoutAtMs = atMs;
        } else {
          this.#stderrLines += 1;
          if (this.#firstStderrAtMs === null) this.#firstStderrAtMs = atMs;
          this.#stderrTail.push(line.slice(0, MAX_STDERR_LINE_CHARS));
          if (this.#stderrTail.length > MAX_STDERR_TAIL) this.#stderrTail.shift();
        }
      }
    };
    if (child.stdout) {
      this.#stdoutAttached = true;
      child.stdout.on('data', capture('stdout'));
    }
    if (child.stderr) {
      this.#stderrAttached = true;
      child.stderr.on('data', capture('stderr'));
    }
  }

  #settle(result: RunnerExitResult): void {
    if (this.#result) return;
    this.#exitedAtMs = Date.now();
    this.#result = result;
    for (const listener of [...this.#listeners]) {
      listener(result);
    }
    this.#listeners.clear();
  }

  isAlive(): boolean {
    return this.#result === null;
  }

  kill(signal: 'SIGTERM' | 'SIGKILL' = 'SIGTERM'): void {
    if (!this.isAlive()) return;
    try {
      this.#child.kill(signal);
    } catch {
      // Process already gone; the exit watcher will settle truthfully.
    }
  }

  async waitForExit(timeoutMs: number): Promise<RunnerExitResult> {
    if (this.#result) return this.#result;
    return new Promise<RunnerExitResult>((resolve) => {
      // Not unref'd: a pending wait means a runner may still be alive.
      const timer = setTimeout(() => {
        unsubscribe();
        resolve(this.#result ?? { code: null, signal: null });
      }, timeoutMs);
      const unsubscribe = this.onExit((result) => {
        clearTimeout(timer);
        resolve(result);
      });
    });
  }

  onExit(listener: (result: RunnerExitResult) => void): () => void {
    if (this.#result) {
      listener(this.#result);
      return () => undefined;
    }
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  }

  /**
   * #3140: writes one bounded line to the supervised child's stdin.
   *
   * Refused rather than truncated when the line is too long, contains a line
   * break, or the child is gone: a truncated pairing envelope would be a
   * different and wrong message. Never retried here — the caller is told
   * whether the write happened, which is what makes the handoff two-phase.
   */
  sendLine(line: string): boolean {
    if (!this.isAlive()) return false;
    if (typeof line !== 'string' || line.length === 0) return false;
    if (line.length > MAX_SUPERVISED_LINE_CHARS) return false;
    if (line.indexOf('\n') >= 0 || line.indexOf('\r') >= 0) return false;
    const stdin = this.#child.stdin;
    if (!stdin || stdin.destroyed || !stdin.writable) return false;
    try {
      stdin.write(`${line}\n`);
      return true;
    } catch {
      return false;
    }
  }

  /** Bounded, already-truncated raw lines — redaction happens in the projection layer. */
  boundedOutput(): BoundedRunnerOutput {
    return { lines: [...this.#lines], maxLines: this.#maxLines };
  }

  /** #3140 stall diagnosis: bounded per-stream timing for this child. */
  observation(): RunnerProcessObservation {
    return {
      pid: this.pid,
      spawn_at: new Date(this.#spawnAtMs).toISOString(),
      stdout_lines: this.#stdoutLines,
      stderr_lines: this.#stderrLines,
      first_stdout_at:
        this.#firstStdoutAtMs === null ? null : new Date(this.#firstStdoutAtMs).toISOString(),
      first_stderr_at:
        this.#firstStderrAtMs === null ? null : new Date(this.#firstStderrAtMs).toISOString(),
      last_line_at: this.#lastLineAtMs === null ? null : new Date(this.#lastLineAtMs).toISOString(),
      exited_at: this.#exitedAtMs === null ? null : new Date(this.#exitedAtMs).toISOString(),
      exit_code: this.#result?.code ?? null,
      exit_signal: this.#result?.signal ?? null,
      stdout_capture_attached: this.#stdoutAttached,
      stderr_capture_attached: this.#stderrAttached,
      stderr_tail: [...this.#stderrTail],
    };
  }
}

/**
 * #3140 review D — a dedicated bounded projection for the resident host.
 *
 * `boundedActiveOutput()` is the *runner's* output. Using it as resident
 * evidence would attribute one process's lines to another, so the resident
 * keeps its own bounded buffer and evidence reads only this.
 */
export function boundedResidentOutput(handle: RunnerProcessHandle | null): BoundedRunnerOutput {
  if (!handle || typeof handle.boundedOutput !== 'function') {
    return { lines: [], maxLines: DEFAULT_MAX_LINES };
  }
  return handle.boundedOutput();
}

/** #3140 stall diagnosis: the resident's per-stream observation, or null. */
export function residentProcessObservation(
  handle: RunnerProcessHandle | null,
): RunnerProcessObservation | null {
  const candidate = handle as { observation?: () => RunnerProcessObservation } | null;
  if (!candidate || typeof candidate.observation !== 'function') return null;
  try {
    return candidate.observation();
  } catch {
    return null;
  }
}

export class NodeRunnerProcessPort implements RunnerProcessPort {
  readonly #maxLines: number;
  #active: NodeRunnerProcessHandle | null = null;
  #residentActive = false;
  #residentHandle: NodeRunnerProcessHandle | null = null;
  // #3140 evidence race: a resident that exits quickly must still leave its
  // bounded output and observation readable, so the last view is captured at
  // exit instead of being lost when the handle reference is dropped.
  #residentSettledOutput: BoundedRunnerOutput | null = null;
  #residentSettledObservation: RunnerProcessObservation | null = null;

  constructor(maxLines: number = DEFAULT_MAX_LINES) {
    this.#maxLines = maxLines;
  }

  /**
   * #3140 — the resident host process, spawned through this same port.
   *
   * Deliberately the only spawn path in the shell: the pairing main flow is a
   * real product process, so it is started and reaped exactly like the runner
   * instead of through a module that bypassed the supervision invariant.
   */
  async spawnResident(spec: RunnerSpawnSpec): Promise<RunnerProcessHandle> {
    if (this.#residentActive) {
      throw new Error('a resident host is already running for this shell instance');
    }
    this.#residentActive = true;
    let handle: NodeRunnerProcessHandle;
    try {
      // #3140 review C: a shell host would turn this into a command-injection
      // surface, and inheriting the whole environment would hand the resident
      // every secret the shell holds. Both are refused outright; the resident
      // gets exactly the bounded config projection it was given.
      if (spec.shell !== false) {
        throw new Error('the resident host process must never be spawned through a shell');
      }
      handle = new NodeRunnerProcessHandle(
        spawn(spec.executablePath, spec.args, {
          cwd: spec.cwd,
          env: { ...spec.env },
          shell: false,
          stdio: spec.stdio,
        }),
        this.#maxLines,
      );
    } catch (error) {
      this.#residentActive = false;
      throw error;
    }
    handle.onExit(() => {
      // Capture before dropping the handle: the supervisor's own settle
      // snapshot runs after this listener, and the evidence marker reads
      // through this port.
      this.#residentSettledOutput = boundedResidentOutput(handle);
      this.#residentSettledObservation = residentProcessObservation(handle);
      this.#residentActive = false;
      this.#residentHandle = null;
    });
    this.#residentHandle = handle;
    return handle;
  }

  /** #3140 review D: the resident's own bounded output, not the runner's. */
  boundedResidentOutput(): BoundedRunnerOutput {
    if (this.#residentHandle) return boundedResidentOutput(this.#residentHandle);
    return this.#residentSettledOutput ?? boundedResidentOutput(null);
  }

  /** #3140 stall diagnosis: the resident's per-stream observation, or null. */
  residentObservation(): RunnerProcessObservation | null {
    if (this.#residentHandle) return residentProcessObservation(this.#residentHandle);
    return this.#residentSettledObservation;
  }

  async spawnRunner(spec: RunnerSpawnSpec): Promise<RunnerProcessHandle> {
    if (this.#active && this.#active.isAlive()) {
      throw new Error('a headless runner is already active for this shell instance');
    }
    if (spec.shell !== false) {
      throw new Error('runner spawn requires shell=false');
    }
    const child = spawn(spec.executablePath, [...spec.args], {
      cwd: spec.cwd,
      env: { ...spec.env },
      shell: false,
      stdio: 'pipe',
      windowsHide: true,
    });
    const handle = new NodeRunnerProcessHandle(child, this.#maxLines);
    this.#active = handle;
    handle.onExit(() => {
      if (this.#active === handle) {
        this.#active = null;
      }
    });
    return handle;
  }

  /** Bounded output of the active handle, for the safe log projection. */
  boundedActiveOutput(): BoundedRunnerOutput {
    if (!this.#active) return { lines: [], maxLines: this.#maxLines };
    return this.#active.boundedOutput();
  }
}
