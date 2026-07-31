/*  outbound-deadline.js  —  bounded outbound GitHub synchronization (Issue #339)
 *
 *  Every outbound GitHub call (installation-token exchange, GraphQL request and
 *  response-body read) and the overall synchronization is wrapped in a fixed
 *  deadline so a stalled upstream can never hold the client connection open.
 *
 *  Deadlines are enforced with a timer race (not solely AbortSignal) so a fetch
 *  implementation that ignores cancellation is still bounded. Losing promises
 *  are guarded against unhandled rejection, and every timer is cleared in a
 *  finally block so no timer leaks.
 *
 *  Safe stage logs carry ONLY { event, stage, result, elapsed } — never raw
 *  errors, URLs, tokens, JWTs, keys, IDs or stack traces.
 */

export const OUTBOUND_DEADLINES = Object.freeze({
  installationTokenRequestMs: 8000,
  installationTokenBodyMs: 5000,
  graphqlRequestMs: 12000,
  graphqlBodyMs: 6000,
  // Foreground refresh budget used ONLY when a valid last-good snapshot already
  // exists. If a refresh does not finish within this budget the stale snapshot is
  // returned immediately so the browser never waits on a slow upstream. Must stay
  // below the client request deadline minus the network margin (see TIMEOUT_CONTRACT).
  staleRefreshBudgetMs: 6000,
  // Full refresh budget used when NO usable snapshot exists (cold start). The
  // client may time out and retry on this path; there is no snapshot to serve fast.
  totalSyncMs: 24000,
  handlerBackstopMs: 28000,
});

/*  Timeout contract (Issue #345).
 *
 *  These values are mirrored by the browser client (github-live-status.js
 *  REQUEST_TIMEOUT_MS). The client and the Pages Functions bundle cannot share a
 *  module, so the contract is fixed here, in the client comment, and by the
 *  regression test `timeout contract keeps the client deadline above the server
 *  foreground budget`. The invariants are:
 *
 *    1. staleRefreshBudgetMs + networkMarginMs <= clientRequestDeadlineMs
 *       (a stale snapshot is always served before the client gives up)
 *    2. handlerBackstopMs >= totalSyncMs
 *       (the handler backstop never fires before the cold-start sync budget)
 */
export const TIMEOUT_CONTRACT = Object.freeze({
  serverStaleRefreshBudgetMs: OUTBOUND_DEADLINES.staleRefreshBudgetMs,
  serverTotalSyncMs: OUTBOUND_DEADLINES.totalSyncMs,
  handlerBackstopMs: OUTBOUND_DEADLINES.handlerBackstopMs,
  clientRequestDeadlineMs: 12000,
  networkMarginMs: 2000,
});

const defaultTimers = Object.freeze({
  setTimeout: (handler, ms) => setTimeout(handler, ms),
  clearTimeout: (id) => clearTimeout(id),
});

export class OutboundTimeoutError extends Error {
  constructor(stage) {
    super("Outbound GitHub operation exceeded its deadline.");
    this.name = "OutboundTimeoutError";
    this.stage = stage;
  }
}

export function createDeadlineRunner(timers = defaultTimers) {
  async function runWithDeadline(promise, timeoutMs, stage) {
    let timer;
    const deadline = new Promise((_, reject) => {
      timer = timers.setTimeout(() => reject(new OutboundTimeoutError(stage)), timeoutMs);
    });
    const tracked = Promise.resolve(promise);
    tracked.catch(() => {});
    try {
      return await Promise.race([tracked, deadline]);
    } finally {
      timers.clearTimeout(timer);
    }
  }

  async function fetchWithDeadline(fetchImpl, url, init, timeoutMs, stage, AbortControllerImpl = AbortController) {
    const controller = new AbortControllerImpl();
    let timer;
    const deadline = new Promise((_, reject) => {
      timer = timers.setTimeout(() => {
        try { controller.abort(); } catch { /* ignore */ }
        reject(new OutboundTimeoutError(stage));
      }, timeoutMs);
    });
    const request = Promise.resolve().then(() => fetchImpl(url, { ...init, signal: controller.signal }));
    request.catch(() => {});
    try {
      return await Promise.race([request, deadline]);
    } finally {
      timers.clearTimeout(timer);
    }
  }

  function readJsonWithDeadline(response, timeoutMs, stage) {
    return runWithDeadline(Promise.resolve().then(() => response.json()), timeoutMs, stage);
  }

  return Object.freeze({ runWithDeadline, fetchWithDeadline, readJsonWithDeadline });
}

export function createStageLogger(log = (line) => console.log(line), now = () => Date.now()) {
  return function logStage(stage, result, startedAtMs) {
    try {
      const elapsed = Math.max(0, Math.round(now() - startedAtMs));
      log(JSON.stringify({ event: "portfolio_github_sync_stage", stage, result, elapsed }));
    } catch { /* never let logging break the request */ }
  };
}
