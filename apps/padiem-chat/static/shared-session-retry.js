/*
 * #6460 4-2: the shared access cookie (__Host-padiem-shared-access) lives 15
 * minutes while the refresh cookie lives 30 days, so a PC API call can land
 * in the window where the access cookie has expired but the session is still
 * refreshable. The screen used to answer that window with a bare 401.
 *
 * One helper, one silent refresh, one retry — never a loop, never a queue of
 * parallel refreshes. The retry keeps only safe init shapes (GET or a body
 * that is a string), so a consumed stream can never be replayed.
 */
(() => {
  "use strict";

  let refreshInFlight = null;

  function refreshOnce() {
    if (!refreshInFlight) {
      refreshInFlight = fetch("/auth/shared/refresh", {
        method: "POST",
        headers: { Accept: "application/json" },
        cache: "no-store",
      }).then((response) => response.ok).catch(() => false).finally(() => {
        refreshInFlight = null;
      });
    }
    return refreshInFlight;
  }

  async function fetchWithSessionRetry(url, init) {
    const options = init || {};
    const body = options.body;
    const replaySafe = typeof body === "string" || body == null;
    const response = await fetch(url, options);
    if (response.status !== 401 || !replaySafe) return response;
    const refreshed = await refreshOnce();
    if (!refreshed) return response;
    return fetch(url, options);
  }

  window.PadiemSharedSession = { refreshOnce, fetchWithSessionRetry };
})();
