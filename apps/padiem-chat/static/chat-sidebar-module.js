// #7216 R5 1단계 — 사이드바 구역 (app.js 클로저에서 이동).
// 동작·문구·DOM id·이벤트 이름 변경 없음. 공유 상태와 DOM 참조는 deps getter로만
// 읽는다. app.js는 같은 이름의 한 줄 전달 함수를 유지한다.
(() => {
  "use strict";
  window.PadiemChatSidebarModule = {
    create(deps) {
      // #7812 R5 B5: sidebar-only DOM refs live here (create() reads no deps).
      const mobileMenu = document.getElementById("mobileMenu");
      const mobileClose = document.getElementById("mobileClose");
      const sidebarCollapseButton = document.getElementById("sidebarCollapseButton");
      const sidebarRestoreButton = document.getElementById("sidebarRestoreButton");
      const sidebarScrim = document.getElementById("sidebarScrim");

      // Static, accessible sidebar actions: keep the translated button text
      // and ARIA labels; only replace the low-contrast visual affordance.
      function sidebarActionIcon(kind) {
        const ns = "http://www.w3.org/2000/svg";
        const svg = document.createElementNS(ns, "svg");
        svg.setAttribute("viewBox", "0 0 24 24");
        svg.setAttribute("fill", "none");
        svg.setAttribute("stroke", "currentColor");
        svg.setAttribute("stroke-width", "1.9");
        svg.setAttribute("stroke-linecap", "round");
        svg.setAttribute("stroke-linejoin", "round");
        svg.setAttribute("aria-hidden", "true");
        svg.setAttribute("focusable", "false");
        if (kind === "more") {
          for (const cy of [5, 12, 19]) {
            const dot = document.createElementNS(ns, "circle");
            dot.setAttribute("cx", "12");
            dot.setAttribute("cy", String(cy));
            dot.setAttribute("r", "1.65");
            dot.setAttribute("fill", "currentColor");
            dot.setAttribute("stroke", "none");
            svg.appendChild(dot);
          }
          return svg;
        }
        const shape = document.createElementNS(ns, "path");
        const paths = {
          settings: "M12 2l1.5 2.4 2.8.5 1.9-1.2 2 3.5-1.9 1.9.1 2.9 1.8 1.9-2 3.5-2.8-.5-2.4 1.4L12 21l-3.1-2.7-2.4-1.4-2.8.5-2-3.5 1.8-1.9.1-2.9-1.9-1.9 2-3.5 1.9 1.2 2.8-.5L12 2Z",
          rename: "M4 20h4.2L19 9.2 14.8 5 4 15.8V20Z M13.6 6.2l4.2 4.2",
          pin: "M9.5 3.5h5l-.8 5.4 2.9 2.9v1.7H7.4v-1.7l2.9-2.9-.8-5.4Z M12 13.5V21",
          unpin: "M9.5 3.5h5l-.8 5.4 2.9 2.9v1.7H7.4v-1.7l2.9-2.9-.8-5.4Z M12 13.5V21 M4 3l16 17",
          trash: "M4 6h16M9 6V4h6v2M6 6l1 15h10l1-15M10 10v7M14 10v7",
        };
        shape.setAttribute("d", paths[kind] || paths.trash);
        svg.appendChild(shape);
        if (kind === "settings") {
          const center = document.createElementNS(ns, "circle");
          center.setAttribute("cx", "12");
          center.setAttribute("cy", "11.5");
          center.setAttribute("r", "3.1");
          svg.appendChild(center);
        }
        return svg;
      }
      // Desktop layout preference is ephemeral: never change mobile overlay
      // behavior, authentication, or per-user server state to store it.
      function setSidebarCollapsed(collapsed) {
        if (window.matchMedia("(max-width: 920px)").matches) return;
        deps.shell.classList.toggle("sidebar-collapsed", collapsed);
        sidebarCollapseButton?.setAttribute("aria-expanded", collapsed ? "false" : "true");
        sidebarRestoreButton?.setAttribute("aria-expanded", collapsed ? "false" : "true");
        if (collapsed) sidebarRestoreButton?.focus();
        else sidebarCollapseButton?.focus();
      }
      function closeSidebar() {
        deps.closeProfilePanel();
        deps.shell.classList.remove("sidebar-open");
        mobileMenu.setAttribute("aria-expanded", "false");
        sidebarScrim.hidden = true;
      }
      function openSidebar() {
        deps.shell.classList.add("sidebar-open");
        mobileMenu.setAttribute("aria-expanded", "true");
        sidebarScrim.hidden = false;
        mobileClose.focus();
      }
      // #7812 R5 B5 (rule (b)): the five click listeners register from app.js at
      // the original block, after the settings dialog listeners.
      // B7 (CTO 06:41): the piece key is wireSidebarListeners — the registry
      // flat namespace already had a `wire` from localPcPanel.
      function wireSidebarListeners() {
        sidebarCollapseButton?.addEventListener("click", () => setSidebarCollapsed(true));
        sidebarRestoreButton?.addEventListener("click", () => setSidebarCollapsed(false));
        mobileMenu.addEventListener("click", openSidebar);
        mobileClose.addEventListener("click", closeSidebar);
        sidebarScrim.addEventListener("click", closeSidebar);
      }

      return { sidebarActionIcon, setSidebarCollapsed, closeSidebar, openSidebar, wireSidebarListeners };
    },
  };
})();
