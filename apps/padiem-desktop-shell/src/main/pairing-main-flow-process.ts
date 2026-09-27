/**
 * #3140 — the main-process owner of the pairing main flow.
 *
 * The supervised runner process is deliberately not where this lives. #3083
 * pins `CHILD_PROCESS_USED_ONLY_IN_MAIN`, and #3081 pins the runner as a leaf
 * under the Job Object, so a runner that spawned a child would break both
 * invariants to gain nothing. Instead the **main process** starts the pairing
 * main flow — the existing #3095 pairing runner composed with the existing
 * #3014 resident host — and hands it the one bounded handoff over its stdin.
 *
 *   CHILD_PROCESS_USED_ONLY_IN_MAIN=YES
 *   PAIRING_CODE_DESTINATION=pairing-main-flow process only
 *   PAIRING_AUTHORITY_IMPLEMENTED=NO   <-- #3080
 *   RESIDENT_HOST_IMPLEMENTED=NO       <-- #3014
 *   EXECUTION_AUTHORITY_IMPLEMENTED=NO <-- P01 + the KAgent stack
 *   HANDOFF_ONCE=YES
 *   PUBLIC_INBOUND_PORT=0
 *   PRODUCTION_MUTATION=0
 *
 * The flow speaks bounded, secret-free lines on stdout, and the main process
 * keeps only the last one. The pairing code is written to the child's stdin and
 * nowhere else: not to the renderer, not to a log, not to disk.
 */

import { spawn, type ChildProcess } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';

export const PAIRING_MAIN_FLOW_CONTRACT = Object.freeze({
  CHILD_PROCESS_USED_ONLY_IN_MAIN: true,
  PAIRING_AUTHORITY_IMPLEMENTED: false,
  RESIDENT_HOST_IMPLEMENTED: false,
  EXECUTION_AUTHORITY_IMPLEMENTED: false,
  SECOND_PAIRING_AUTHORITY: 0,
  SECOND_RESIDENT_HOST: 0,
  PUBLIC_INBOUND_PORT: 0,
  PRODUCTION_MUTATION: 0,
  HANDOFF_ONCE: true,
  PAIRING_CODE_LOGGED: 0,
  PAIRING_CODE_PERSISTED: 0,
} as const);

export const MAX_MAIN_FLOW_LINE_CHARS = 4_096;

export interface PairingMainFlowOptions {
  /** The Python that owns the #3095/#3014 composition. */
  readonly pythonExecutable: string;
  /** The kagent project root the module is imported from. */
  readonly projectRoot: string;
  readonly maxLines?: number;
}

export interface PairingMainFlowStatus {
  readonly started: boolean;
  readonly running: boolean;
  readonly exitCode: number | null;
  readonly handoffWritten: boolean;
  /** Bounded, secret-free status lines the flow reported. */
  readonly lines: readonly string[];
}

export class PairingMainFlowProcess {
  readonly #child: ChildProcess | null;
  readonly #maxLines: number;
  readonly #lines: string[] = [];
  readonly #settleListeners = new Set<() => void>();
  #handoffWritten = false;
  #running: boolean;

  constructor(options: PairingMainFlowOptions) {
    this.#maxLines = options.maxLines ?? 50;
    this.#running = false;
    this.#child = spawn(options.pythonExecutable, ['-m', 'kagent.local_agent_pairing_main_flow'], {
      cwd: options.projectRoot,
      shell: false,
      stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, PYTHONUNBUFFERED: '1' },
    });
    this.#running = true;
    const capture = (chunk: unknown): void => {
      for (const line of String(chunk).split(/\r?\n/)) {
        if (line.trim().length === 0) continue;
        this.#lines.push(line);
        if (this.#lines.length > this.#maxLines) this.#lines.shift();
      }
    };
    this.#child.stdout?.on('data', capture);
    // stderr is captured into the same bounded buffer rather than inherited,
    // so a traceback can never reach the console unredacted.
    this.#child.stderr?.on('data', capture);
    const settle = (): void => {
      this.#running = false;
      for (const listener of [...this.#settleListeners]) listener();
      this.#settleListeners.clear();
    };
    this.#child.once('exit', settle);
    this.#child.once('error', settle);
  }

  /**
   * Writes the one handoff envelope. Bounded, single-use, and truthful: a
   * refused write is reported rather than assumed.
   */
  writeHandoff(line: string): boolean {
    if (!this.#running || this.#handoffWritten) return false;
    if (typeof line !== 'string' || line.length === 0) return false;
    if (line.length > MAX_MAIN_FLOW_LINE_CHARS) return false;
    if (/[\r\n]/.test(line)) return false;
    const stdin = this.#child?.stdin;
    if (!stdin || stdin.destroyed || !stdin.writable) return false;
    try {
      stdin.write(`${line}\n`);
      stdin.end();
      this.#handoffWritten = true;
      return true;
    } catch {
      return false;
    }
  }

  isRunning(): boolean {
    return this.#running;
  }

  /** Registers a one-shot settlement listener (used by evidence capture). */
  onSettled(listener: () => void): () => void {
    this.#settleListeners.add(listener);
    return () => this.#settleListeners.delete(listener);
  }

  status(): PairingMainFlowStatus {
    return Object.freeze({
      started: this.#child !== null,
      running: this.#running,
      exitCode: this.#child?.exitCode ?? null,
      handoffWritten: this.#handoffWritten,
      lines: [...this.#lines],
    });
  }

  /** Bounded, secret-free diagnostics. Never carries the pairing code. */
  safe_dict(): Record<string, unknown> {
    const status = this.status();
    return {
      ...PAIRING_MAIN_FLOW_CONTRACT,
      started: status.started,
      running: status.running,
      handoffWritten: status.handoffWritten,
      status_line_count: status.lines.length,
    };
  }
}

/** Resolves the Python that owns the #3095/#3014 composition. */
export function resolvePairingMainFlowPython(
  options: { readonly pythonExecutable?: string; readonly projectRoot?: string } = {},
): { readonly pythonExecutable: string; readonly projectRoot: string } | null {
  const projectRoot = options.projectRoot ?? process.env.PADIEM_AGENT_PROJECT_ROOT;
  if (!projectRoot) return null;
  const candidate = options.pythonExecutable ?? process.env.PADIEM_PYTHON ?? 'python';
  if (candidate !== 'python' && !existsSync(candidate)) return null;
  return { pythonExecutable: candidate, projectRoot: path.resolve(projectRoot) };
}
