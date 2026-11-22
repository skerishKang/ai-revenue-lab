/* #8090: one /api/admin/session read per auth epoch, shared by the
 * first-screen consumers (admin-entry.js, chat-feedback-module.js). The
 * server-attested role cannot change without a new session, so one answered
 * signed-in read is reused; a sign-out, or a login whose cached answer came
 * from a guest-era read, invalidates it — and the next reader starts one
 * fresh fetch that concurrent callers join (#8003's shared-read shape from
 * pc-connect-flow.js). A guest or failed reply is never cached: it answers
 * the caller once and the next reader tries again. */
(() => {
  "use strict";
  let generation = 0;
  let inFlight = null;
  let cache = null; // { status, data } from an answered signed-in read only

  async function fetchSession() {
    try {
      const response = await fetch("/api/admin/session", {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
        cache: "no-store",
      });
      const data = await response.json().catch(() => null);
      return { status: response.status, data };
    } catch (_) {
      return { status: 0, data: null };
    }
  }

  function read() {
    if (cache) return Promise.resolve(cache);
    if (inFlight) return inFlight;
    const epoch = generation;
    inFlight = fetchSession().then((reply) => {
      // The reply still reaches its own callers even if the epoch moved —
      // only its promotion to the shared answer is generation-guarded, so a
      // read begun before a sign-out never becomes the cached session answer.
      if (epoch === generation) {
        inFlight = null;
        if (reply.status === 200 && reply.data && reply.data.authenticated === true) {
          cache = reply;
        }
      }
      return reply;
    });
    return inFlight;
  }

  function invalidate() {
    generation += 1;
    inFlight = null;
    cache = null;
  }

  window.addEventListener("padiem:auth-state", (event) => {
    if (event?.detail?.authenticated !== true) {
      // Sign-out: a stale admin answer must never survive it, and the two
      // consumers apply signed-out locally from the same event.
      invalidate();
      return;
    }
    if (cache && !(cache.data && cache.data.authenticated === true)) {
      // A login after a guest-era answer: the cached reply cannot describe
      // this session, so the next reader starts one fresh shared fetch.
      invalidate();
    }
  });

  window.PadiemAdminSession = Object.freeze({
    read,
    refresh: () => { invalidate(); return read(); },
    invalidate,
    current: () => cache,
  });
})();
