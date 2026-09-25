/**
 * CLAW4 #3083 — Padiem headless runner process (M1 stub).
 *
 * This process is deliberately SEPARATE from the Electron main process and from
 * the renderer. In M1 it is a supervised lifecycle stub only:
 *
 *   RUNNER_EXECUTION_SEMANTICS_IMPLEMENTED=NO
 *   RUNNER_IS_EXECUTION_AUTHORITY=NO   (P01 + the KAgent/B54 stack remain the
 *                                      only execution authority; wiring them in
 *                                      is a later M-slices decision)
 *   RUNNER_LISTENS_ON_SOCKET=NO
 *   RUNNER_OPENS_INBOUND_PORT=NO
 *
 * It prints a bounded readiness line to stdout, then idles until it is asked to
 * terminate. The Electron main process supervises it and must never orphan it.
 */

const READY_LINE = 'padiem-headless-runner ready';

function log(line: string): void {
  process.stdout.write(`${line}\n`);
}

export interface HeadlessRunnerOptions {
  readonly heartbeatMs?: number;
}

export function startHeadlessRunner(options: HeadlessRunnerOptions = {}): NodeJS.Timeout {
  const heartbeatMs = options.heartbeatMs ?? 30_000;
  log(READY_LINE);
  const timer = setInterval(() => {
    log(`padiem-headless-runner heartbeat pid=${process.pid}`);
  }, heartbeatMs);
  if (typeof timer.unref === 'function') {
    // Keep the event loop alive for the process lifetime regardless.
    timer.ref();
  }
  return timer;
}

const shutdown = (signal: string) => {
  log(`padiem-headless-runner shutdown signal=${signal}`);
  process.exit(0);
};

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));

startHeadlessRunner();

export { READY_LINE };
