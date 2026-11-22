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

  // #8312: the /admin gate sends the member here with ?admin_return=1 so the
  // first screen opens its own login flow, and a completed sign-in returns to
  // /admin. The ask lives in one module variable for this page only — the
  // URL parameter is stripped right away so a reload or a shared link cannot
  // loop back into the gate, and the Google round trip carries the ask in
  // its signed state instead (googleStartHref's return_to). A guest gets the
  // same login button the app itself clicks programmatically
  // (chat-auth-module.js); a member who is already signed in is left alone —
  // the return happens on a real sign-in answer only.
  // The ask lives in one module variable, not in browser storage: the B62
  // persistence gate keeps browser persistence primitives out of this file,
  // and the ask only needs to live as long as the tab's own login flow —
  // password sign-in answers in place, and the Google ask travels in the
  // signed OAuth state instead (chat-login-dialog-module's googleStartHref).
  let adminReturnPending = false;
  try {
    const params = new URLSearchParams(window.location.search);
    if (params.get("admin_return") === "1") {
      params.delete("admin_return");
      const rest = params.toString();
      window.history.replaceState(null, "",
        window.location.pathname + (rest ? "?" + rest : "") + window.location.hash);
      adminReturnPending = true;
    }
  } catch (_) {}
  window.addEventListener("padiem:auth-state", (event) => {
    if (event?.detail?.authenticated === true) {
      if (adminReturnPending) {
        adminReturnPending = false;
        window.location.replace("./admin");
      }
      return;
    }
    scheduleOpen();
  });

  /* The login button becomes clickable a beat after the first auth-state
   * event (the session read and the button visibility sync land in the same
   * status answer, and an unchanged session fires no second event), so the
   * open attempt polls briefly instead of trusting one event. Once the
   * dialog is open — or the short window passes — the guest clicks 로그인
   * exactly as they would have. */
  let openAttempts = 0;
  let openTimer = 0;
  let opened = false;
  function tryOpen() {
    const dialog = document.getElementById("authDialog");
    if (dialog && dialog.open) return true;
    const loginButton = document.getElementById("loginButton");
    if (loginButton && !loginButton.hidden && !loginButton.disabled) {
      loginButton.click();
      return true;
    }
    return false;
  }
  function pollOpen() {
    openTimer = 0;
    if (opened || !adminReturnPending) return;
    if (tryOpen()) {
      opened = true;
      return;
    }
    if (openAttempts >= 40) return; // ~2s, then the guest opens it themselves
    openAttempts += 1;
    openTimer = window.setTimeout(pollOpen, 50);
  }
  function scheduleOpen() {
    if (opened || openTimer) return;
    openTimer = window.setTimeout(pollOpen, 0);
  }

  window.PadiemAdminSession = Object.freeze({
    read,
    refresh: () => { invalidate(); return read(); },
    invalidate,
    current: () => cache,
    // #8312: the login dialog reads this to decide whether its Google ask
    // carries return_to=/admin (the server's exact allowlist decides).
    pendingAdminReturn: () => adminReturnPending,
  });
})();
