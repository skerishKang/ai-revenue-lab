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

  async function refresh() {
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
      const authorized = Boolean(data && data.authenticated === true && typeof data.role === "string");
      apply(authorized);
      if (authorized) link.dataset.role = data.role;
      else delete link.dataset.role;
    } catch (_) {
      apply(false);
      delete link.dataset.role;
    }
  }

  window.addEventListener("padiem:auth-state", () => void refresh());
  void refresh();
})();
