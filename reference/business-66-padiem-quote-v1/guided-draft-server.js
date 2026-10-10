/* B66 #3396: authenticated guided-draft transport. No browser owner authority. */
(() => {
  "use strict";
  const URL = "/api/padiem/b66/guided-draft";
  async function request(method, state) {
    try {
      const init = { method, credentials: "same-origin", cache: "no-store" };
      if (method === "PUT") {
        init.headers = { "Content-Type": "application/json" };
        init.body = JSON.stringify(state);
      }
      const response = await fetch(URL, init);
      const payload = await response.json().catch(() => null);
      if (!response.ok || payload?.ok !== true) {
        return { ok: false, status: response.status, error: payload?.error?.code || "guided_state_unavailable" };
      }
      return { ok: true, state: payload.state || null };
    } catch (_) {
      return { ok: false, error: "guided_state_network_unavailable" };
    }
  }
  window.B66GuidedDraftServer = Object.freeze({
    load: () => request("GET"),
    save: (state) => request("PUT", state),
    clear: () => request("DELETE")
  });
})();
