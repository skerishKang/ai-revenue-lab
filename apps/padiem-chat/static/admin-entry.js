/* #5108: reveal the admin hub entry only for the server-attested role.
 * #5560: the hub entry moved from the sidebar bottom into Settings, so the
 * same server check owns the Settings section that carries it.
 */
(() => {
  "use strict";
  const link = document.getElementById("adminHubLink");
  if (!link) return;
  const section = document.getElementById("adminSettingsSection");

  function apply(authorized) {
    link.hidden = !authorized;
    if (section) section.hidden = !authorized;
  }

  let inFlight = null;
  // The role cannot change without a new session, so one answered check per
  // signed-in session is enough. The boot check and the auth notification used
  // to run back to back on the first screen.
  let answeredSignedIn = false;

  function refresh() {
    if (inFlight) return inFlight;
    inFlight = check().finally(() => { inFlight = null; });
    return inFlight;
  }

  async function check() {
    try {
      const response = await fetch("/api/admin/session", {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!response.ok) {
        apply(false);
        delete link.dataset.role;
        return;
      }
      const data = await response.json();
      const authenticated = Boolean(data && data.authenticated === true);
      if (authenticated) answeredSignedIn = true;
      const authorized = authenticated && typeof data.role === "string";
      apply(authorized);
      if (authorized) link.dataset.role = data.role;
      else delete link.dataset.role;
    } catch (_) {
      apply(false);
      delete link.dataset.role;
    }
  }

  window.addEventListener("padiem:auth-state", (event) => {
    if (event?.detail?.authenticated !== true) {
      // Sign-out is answered immediately and must never keep a stale entry.
      answeredSignedIn = false;
      apply(false);
      delete link.dataset.role;
      return;
    }
    if (answeredSignedIn) return;
    void refresh();
  });
  void refresh();
})();
