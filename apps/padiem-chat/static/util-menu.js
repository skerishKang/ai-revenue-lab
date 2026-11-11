/*
 * #7460 · Left sidebar Util entry & expandable submenu.
 *
 * All Util submenu items render from window.PadiemUtilManifest so the cards,
 * the tool-screen chips and the sidebar menu stay in lockstep. Every item
 * navigates inside the Util app (#util/<id>) — never to an external page.
 */
(() => {
  "use strict";

  function ready(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn, { once: true });
    } else {
      fn();
    }
  }

  function lang() {
    const root = document.documentElement;
    return root && root.lang === "en" ? "en" : "ko";
  }

  function manifest() {
    return window.PadiemUtilManifest || null;
  }

  function tools() {
    const reg = manifest();
    return reg && Array.isArray(reg.TOOLS) ? reg.TOOLS : [];
  }

  function toolLabel(tool) {
    const locale = lang();
    if (tool && tool.name) return tool.name[locale] || tool.name.ko || tool.id;
    if (tool && tool[locale] && tool[locale].title) return tool[locale].title;
    return tool ? tool.id : "";
  }

  ready(() => {
    const utilNav = document.getElementById("utilNavButton");
    const utilView = document.getElementById("utilView");
    const utilSubmenu = document.getElementById("utilSubmenu");
    if (!utilNav || !utilView) return;

    let utilSubmenuItems = [];

    function closeMobileSidebar() {
      const shell = document.querySelector(".app-shell");
      if (!shell || !shell.classList.contains("sidebar-open")) return;
      shell.classList.remove("sidebar-open");
      const menu = document.getElementById("mobileMenu");
      if (menu) menu.setAttribute("aria-expanded", "false");
      const scrim = document.getElementById("sidebarScrim");
      if (scrim) scrim.hidden = true;
    }

    function setUtilSubmenuOpen(open) {
      if (!utilSubmenu) return;
      utilSubmenu.hidden = !open;
      utilNav.setAttribute("aria-expanded", open ? "true" : "false");
      const chevron = utilNav.querySelector(".side-chevron");
      if (chevron) chevron.textContent = open ? "⌄" : "›";
    }

    function markActiveUtilSubmenuItem(key) {
      if (!utilSubmenu) return;
      utilSubmenuItems.forEach((item) => {
        const active = key != null && item.dataset.util === key;
        item.classList.toggle("active", active);
        item.setAttribute("aria-current", active ? "page" : "false");
      });
    }

    function showUtil() {
      const shell = document.querySelector(".app-shell");
      if (shell) shell.dataset.state = "util";
      utilView.hidden = false;
      utilNav.setAttribute("aria-current", "page");
    }

    function navigateHash(hash) {
      showUtil();
      if (window.PadiemUtilApp && typeof window.PadiemUtilApp.navigate === "function") {
        window.PadiemUtilApp.navigate(hash);
      } else if (window.location) {
        window.location.hash = hash;
      }
    }

    function openUtilEntry(key) {
      const reg = manifest();
      const route = reg && typeof reg.toolHref === "function" ? reg.toolHref(key) : "#util/" + key;
      setUtilSubmenuOpen(true);
      markActiveUtilSubmenuItem(key);
      navigateHash(route);
      closeMobileSidebar();
    }

    function renderSubmenu() {
      if (!utilSubmenu) return [];
      const activeEl = utilSubmenuItems.find((item) => item.classList.contains("active"));
      const activeKey = activeEl ? activeEl.dataset.util : null;
      const built = tools().map((tool) => {
        const btn = document.createElement("button");
        btn.className = "util-submenu-item";
        btn.type = "button";
        btn.dataset.util = tool.id;
        btn.setAttribute("data-util-route", tool.route);
        btn.setAttribute("aria-current", "false");
        btn.textContent = toolLabel(tool);
        btn.addEventListener("click", () => openUtilEntry(tool.id));
        return btn;
      });
      utilSubmenu.replaceChildren(...built);
      utilSubmenuItems = built;
      markActiveUtilSubmenuItem(activeKey);
      return built;
    }

    function syncFromHash() {
      const app = window.PadiemUtilApp;
      const hash = window.location ? String(window.location.hash || "") : "";
      const parsed = app && typeof app.parseHash === "function" ? app.parseHash(hash) : null;
      if (!parsed) {
        markActiveUtilSubmenuItem(null);
        return;
      }
      if (parsed.screen === "tool" && parsed.id) {
        setUtilSubmenuOpen(true);
        markActiveUtilSubmenuItem(parsed.id);
      } else {
        markActiveUtilSubmenuItem(null);
      }
    }

    renderSubmenu();
    syncFromHash();

    utilNav.addEventListener("click", () => {
      const reg = manifest();
      const listRoute = reg && typeof reg.listHref === "function" ? reg.listHref() : "#util";
      const shell = document.querySelector(".app-shell");
      const inUtil = Boolean(shell && shell.dataset.state === "util");
      const currentHash = window.location ? String(window.location.hash || "") : "";
      if (!inUtil || currentHash !== listRoute) {
        navigateHash(listRoute);
        markActiveUtilSubmenuItem(null);
        setUtilSubmenuOpen(true);
        return;
      }
      if (utilSubmenu) {
        const nextOpen = utilSubmenu.hidden;
        setUtilSubmenuOpen(nextOpen);
        if (!nextOpen) closeMobileSidebar();
      }
    });

    if (utilSubmenu && typeof MutationObserver === "function") {
      new MutationObserver(() => {
        if (utilNav.getAttribute("aria-current") === "false") {
          markActiveUtilSubmenuItem(null);
        }
      }).observe(utilNav, { attributes: true, attributeFilter: ["aria-current"] });
    }

    window.addEventListener("hashchange", syncFromHash);
    window.addEventListener("padiem:util-route", syncFromHash);
    window.addEventListener("padiem:localechange", () => {
      renderSubmenu();
      syncFromHash();
    });

    window.PadiemUtilMenu = Object.freeze({
      renderSubmenu: renderSubmenu,
      setSubmenuOpen: setUtilSubmenuOpen,
      markActive: markActiveUtilSubmenuItem,
    });
  });
})();
