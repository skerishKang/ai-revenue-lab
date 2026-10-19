/* #5108: reveal the admin hub entry only for the server-attested role. */
(() => {
  "use strict";
  const link = document.getElementById("adminHubLink");
  if (!link) return;

  async function refresh() {
    try {
      const response = await fetch("/api/admin/session", {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!response.ok) {
        link.hidden = true;
        return;
      }
      const data = await response.json();
      const authorized = Boolean(data && data.authenticated === true && typeof data.role === "string");
      link.hidden = !authorized;
      if (authorized) link.dataset.role = data.role;
      else delete link.dataset.role;
    } catch (_) {
      link.hidden = true;
    }
  }

  window.addEventListener("padiem:auth-state", () => void refresh());
  window.addEventListener("focus", () => void refresh());
  void refresh();
})();
