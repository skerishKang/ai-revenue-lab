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

const DEFAULT_MAX_LINES = 200;

class NodeRunnerProcessHandle implements RunnerProcessHandle {
  readonly pid: number;
  readonly #child: ChildProcess;
  readonly #exited: Promise<RunnerExitResult>;
  readonly #listeners = new Set<(result: RunnerExitResult) => void>();
  #result: RunnerExitResult | null = null;
  readonly #lines: string[] = [];
  readonly #maxLines: number;

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
    const capture = (chunk: unknown) => {
      const text = String(chunk);
      for (const line of text.split(/\r?\n/)) {
        if (line.length === 0) continue;
        this.#lines.push(line);
        if (this.#lines.length > this.#maxLines) this.#lines.shift();
      }
    };
    child.stdout?.on('data', capture);
    child.stderr?.on('data', capture);
  }

  #settle(result: RunnerExitResult): void {
    if (this.#result) return;
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

  /** Bounded, already-truncated raw lines — redaction happens in the projection layer. */
  boundedOutput(): BoundedRunnerOutput {
    return { lines: [...this.#lines], maxLines: this.#maxLines };
  }
}

export class NodeRunnerProcessPort implements RunnerProcessPort {
  readonly #maxLines: number;
  #active: NodeRunnerProcessHandle | null = null;

  constructor(maxLines: number = DEFAULT_MAX_LINES) {
    this.#maxLines = maxLines;
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
