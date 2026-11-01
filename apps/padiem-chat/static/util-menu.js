/*
 * Chat util menu — after the 2026-11-01 unification.
 *
 * The three 의원3종 tools (축사·인사말 / SNS 홍보 / 회의정리·활동집) are no
 * longer duplicated inside Chat. Their one product surface is the independent
 * app at /apps/council/, which keeps the same login session: a util entry
 * navigates there with the tool in the fragment (#speech, #sns, #meeting).
 *
 * What stays here is the util page shell and the PDF → Markdown menu, which is
 * a different utility. No second copy of the council tools, their store or
 * their PC bridge lives in this file.
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

  // One destination per tool. Same origin, same session cookie.
  const COUNCIL_TOOL_HREF = Object.freeze({
    speech: "/apps/council/#speech",
    sns: "/apps/council/#sns",
    meeting: "/apps/council/#meeting",
  });

  function openCouncilTool(key) {
    const href = COUNCIL_TOOL_HREF[key];
    if (!href) return false;
    window.location.assign(href);
    return true;
  }

  ready(() => {
    const utilNav = document.getElementById("utilNavButton");
    const utilView = document.getElementById("utilView");
    if (!utilNav || !utilView) return;

    const utilTitleEl = document.getElementById("utilTitle");
    const utilKickerEl = document.getElementById("utilKicker");
    const utilTaglineEl = document.getElementById("utilTagline");
    const tabs = document.querySelectorAll(".util-tab");
    const panels = {
      pdfmd: document.getElementById("utilPdfmdPanel"),
    };

    const utilSubmenu = document.getElementById("utilSubmenu");
    const utilSubmenuItems = utilSubmenu
      ? Array.from(utilSubmenu.querySelectorAll(".util-submenu-item"))
      : [];

    // #5608: the util page is its own shell state. The sibling views are gated
    // by CSS (util-menu.css), so entering the state is enough.
    function showUtil() {
      const shell = document.querySelector(".app-shell");
      if (shell) shell.dataset.state = "util";
      utilView.hidden = false;
      utilNav.setAttribute("aria-current", "page");
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
        item.setAttribute("aria-current", active ? "true" : "false");
      });
    }

    function closeMobileSidebar() {
      const shell = document.querySelector(".app-shell");
      if (!shell || !shell.classList.contains("sidebar-open")) return;
      shell.classList.remove("sidebar-open");
      const menu = document.getElementById("mobileMenu");
      if (menu) menu.setAttribute("aria-expanded", "false");
      const scrim = document.getElementById("sidebarScrim");
      if (scrim) scrim.hidden = true;
    }

    function activateUtilTab(tab) {
      tabs.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      const key = tab.dataset.util;
      Object.keys(panels).forEach((k) => {
        if (panels[k]) panels[k].hidden = k !== key;
      });
      if (utilTitleEl && tab.textContent.trim()) utilTitleEl.textContent = tab.textContent.trim();
      if (utilKickerEl) utilKickerEl.textContent = tab.dataset.kicker || "Padiem Util";
      if (utilTaglineEl) utilTaglineEl.textContent = tab.dataset.tagline || "AI 홍보·기록 비서";
      if (key === "pdfmd" && panels.pdfmd && !panels.pdfmd.dataset.loaded) {
        panels.pdfmd.dataset.loaded = "1";
        if (typeof window.initPdfMdUtility === "function") window.initPdfMdUtility(panels.pdfmd);
      }
    }

    function openUtilEntry(key) {
      // The council tools belong to their own app; the util page never hosts a
      // second editor for them.
      if (openCouncilTool(key)) return;
      showUtil();
      setUtilSubmenuOpen(true);
      markActiveUtilSubmenuItem(key);
      const tab = Array.prototype.find.call(tabs, (t) => t.dataset.util === key);
      if (tab) activateUtilTab(tab);
      closeMobileSidebar();
    }

    utilNav.addEventListener("click", () => {
      showUtil();
      if (utilSubmenu) setUtilSubmenuOpen(utilSubmenu.hidden);
    });
    utilSubmenuItems.forEach((item) => {
      item.addEventListener("click", () => openUtilEntry(item.dataset.util));
    });
    markActiveUtilSubmenuItem("pdfmd");

    // Leaving the util view (any other nav) must not leave a stale highlight.
    if (utilSubmenu && typeof MutationObserver === "function") {
      new MutationObserver(() => {
        if (utilNav.getAttribute("aria-current") === "false") {
          markActiveUtilSubmenuItem(null);
        }
      }).observe(utilNav, { attributes: true, attributeFilter: ["aria-current"] });
    }

    tabs.forEach((tab) => {
      tab.addEventListener("click", () => {
        if (openCouncilTool(tab.dataset.util)) return;
        showUtil();
        activateUtilTab(tab);
        markActiveUtilSubmenuItem(tab.dataset.util);
      });
    });

    // #5908: the quick-run toolbox. Council cards navigate to the app; the two
    // Claw cards route to the existing Claw workspace, whose own chip handler
    // stays the owner of the quote action.
    document.querySelectorAll("[data-quick-util]").forEach((button) => {
      button.addEventListener("click", () => {
        const key = button.dataset.quickUtil;
        if (openCouncilTool(key)) return;
        const target = document.querySelector('[data-util-tool="' + key + '"]');
        if (!target) return;
        showUtil();
        target.click();
        closeMobileSidebar();
      });
    });
    const toolGrid = document.getElementById("utilToolGrid");
    const toolButtons = toolGrid
      ? Array.from(toolGrid.querySelectorAll("[data-util-tool]"))
      : [];
    toolButtons.forEach((btn) => {
      btn.addEventListener("click", () => {
        const key = btn.getAttribute("data-util-tool");
        if (openCouncilTool(key)) return;
        if (key === "claw-quote" || key === "claw-excel") {
          const clawNav = document.getElementById("clawNavButton");
          if (clawNav) clawNav.click();
          if (key === "claw-quote") {
            const chip = document.getElementById("clawQuoteCard");
            if (chip) chip.click();
          }
          return;
        }
        const tab = Array.prototype.find.call(tabs, (t) => t.dataset.util === key);
        if (tab) {
          activateUtilTab(tab);
          markActiveUtilSubmenuItem(key);
        }
      });
    });
  });
})();
