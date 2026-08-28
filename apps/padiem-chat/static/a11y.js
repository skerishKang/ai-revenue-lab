(() => {
  "use strict";

  const shell = document.querySelector(".app-shell");
  const sidebar = document.getElementById("sidebar");
  const mainPanel = document.querySelector(".main-panel");
  const mobileMenu = document.getElementById("mobileMenu");
  const mobileClose = document.getElementById("mobileClose");
  const sidebarScrim = document.getElementById("sidebarScrim");
  if (!shell || !sidebar || !mainPanel || !mobileMenu || !mobileClose || !sidebarScrim) return;

  const mobileViewport = window.matchMedia("(max-width: 920px)");
  let escapeStartedOpen = false;

  function syncDrawerAccessibility() {
    const mobile = mobileViewport.matches;
    const open = mobile && shell.classList.contains("sidebar-open");

    if (!mobile) {
      sidebar.inert = false;
      mainPanel.inert = false;
      shell.classList.remove("sidebar-open");
      mobileMenu.setAttribute("aria-expanded", "false");
      sidebarScrim.hidden = true;
      return;
    }

    sidebar.inert = !open;
    mainPanel.inert = open;
    mobileMenu.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function restoreMenuFocus() {
    if (!mobileViewport.matches) return;
    syncDrawerAccessibility();
    mobileMenu.focus();
  }

  mobileMenu.addEventListener("click", () => {
    syncDrawerAccessibility();
    if (shell.classList.contains("sidebar-open")) mobileClose.focus();
  });

  mobileClose.addEventListener("click", restoreMenuFocus);
  sidebarScrim.addEventListener("click", restoreMenuFocus);

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") escapeStartedOpen = mobileViewport.matches && shell.classList.contains("sidebar-open");
  }, true);

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !escapeStartedOpen) return;
    escapeStartedOpen = false;
    queueMicrotask(restoreMenuFocus);
  });

  mobileViewport.addEventListener("change", syncDrawerAccessibility);
  syncDrawerAccessibility();
})();
