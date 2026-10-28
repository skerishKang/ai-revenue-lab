/* B62 Padiem Chat / B54 Padiem Claw — the computer connection status inside the
 * shared message composer.
 *
 * The server is the only authority for the state, and the EXISTING device
 * directory module is the only reader of the canonical directory endpoint.
 * This module is a pure view over the snapshot that module publishes
 * (window.PadiemClawDeviceDirectory / "padiem:claw-device-directory"), so it
 * adds no endpoint, no second device authority, no polling loop and no new
 * request of its own.
 *
 * Clicking the control opens the EXISTING computer connection management
 * surface (the device directory panel that already sits above the shared
 * composer). Nothing is displayed as connected before the server confirmed it.
 */
(() => {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";
  const SNAPSHOT_EVENT = "padiem:claw-device-directory";

  const COPY = Object.freeze({
    ko: {
      connect: "컴퓨터 연결",
      connected: "PC 연결됨",
      connecting: "연결 확인 중",
      disconnected: "컴퓨터 미연결",
      check: "상태 확인 불가",
      preparing: "준비 중",
      connectHint: "컴퓨터가 연결되어 있지 않습니다. 클릭하면 컴퓨터 연결 안내를 엽니다.",
      connectedHint: "컴퓨터가 연결되어 있습니다. 클릭하면 연결된 컴퓨터 정보를 확인합니다.",
      connectingHint: "컴퓨터 연결 상태를 확인하는 중입니다. 클릭하면 컴퓨터 연결 안내를 엽니다.",
      checkHint: "컴퓨터 연결 상태를 확인하지 못했습니다. 클릭하면 연결 상태를 다시 확인합니다.",
      executableHint: "PC 실행 대상은 확인되었지만 온라인 상태는 확인되지 않았습니다. 클릭하면 연결 상태를 다시 확인합니다.",
      preparingHint: "컴퓨터 연결 기능은 아직 준비 중입니다. 클릭하면 연결 안내를 엽니다.",
    },
    en: {
      connect: "PC connect",
      connected: "PC connected",
      connecting: "Checking…",
      disconnected: "PC not connected",
      check: "Status unavailable",
      preparing: "Coming soon",
      connectHint: "No computer is connected. Click to open the computer connection guide.",
      connectedHint: "A computer is connected. Click to review the connected computer.",
      connectingHint: "Checking the computer connection status. Click to open the computer connection guide.",
      checkHint: "The computer connection status could not be confirmed. Click to check it again.",
      executableHint: "The PC is an execution target, but its online state is not confirmed. Click to check it again.",
      preparingHint: "The computer connection feature is not available yet. Click to open the guide.",
    },
  });

  function locale() {
    const current = window.__padiemLocale &&
      typeof window.__padiemLocale.getCurrent === "function"
        ? window.__padiemLocale.getCurrent()
        : document.documentElement.lang;
    return current === "en" ? COPY.en : COPY.ko;
  }

  function element(tag, className) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    return node;
  }

  // A constant monitor mark, built as SVG nodes. No markup is ever injected
  // and no server value ever reaches the document.
  function monitorIcon() {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.8");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("focusable", "false");
    svg.setAttribute("aria-hidden", "true");
    const screen = document.createElementNS(SVG_NS, "rect");
    screen.setAttribute("x", "3");
    screen.setAttribute("y", "4");
    screen.setAttribute("width", "18");
    screen.setAttribute("height", "13");
    screen.setAttribute("rx", "2");
    const stand = document.createElementNS(SVG_NS, "path");
    stand.setAttribute("d", "M8 21h8M12 17v4");
    svg.append(screen, stand);
    return svg;
  }

  /* #5553: one small mark per state, drawn inside the screen of the monitor so
     the four states differ by wording, colour AND icon — never by colour alone.
     connected=check, connecting=clock (state being read), disconnected=slash
     across the screen, unavailable=alert, preparing=dotted screen. */
  function stateMark(state) {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2.2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("focusable", "false");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("class", "composer-pc-status-mark");
    const mark = document.createElementNS(SVG_NS, "path");
    if (state === "connected") {
      mark.setAttribute("d", "M7.5 10.5l3 3 6-6");
    } else if (state === "connecting" || state === "preparing") {
      const circle = document.createElementNS(SVG_NS, "circle");
      circle.setAttribute("cx", "12");
      circle.setAttribute("cy", "10.5");
      circle.setAttribute("r", "3.6");
      svg.append(circle);
      mark.setAttribute("d", "M12 8.7v1.8l1.4 1.1");
    } else if (state === "disconnected") {
      mark.setAttribute("d", "M7 14.5L17 6.5");
    } else {
      mark.setAttribute("d", "M12 6.8v4.6M12 14.1v.01");
    }
    svg.append(mark);
    return svg;
  }

  function install() {
    const form = document.getElementById("composerForm");
    const input = document.getElementById("messageInput");
    if (!form || !input) return;
    // One control for both products: Chat and Claw share this composer.
    if (document.getElementById("composerPcStatus")) return;

    const button = element("button", "composer-pc-status");
    button.type = "button";
    button.id = "composerPcStatus";
    button.dataset.state = "connecting";
    const face = element("span", "composer-pc-status-face");
    const dot = element("span", "composer-pc-status-dot");
    dot.setAttribute("aria-hidden", "true");
    const icon = element("span", "composer-pc-status-icon");
    icon.setAttribute("aria-hidden", "true");
    icon.append(monitorIcon());
    const label = element("span", "composer-pc-status-label");
    label.setAttribute("aria-live", "polite");
    face.append(dot, icon, label);
    button.append(face);
    form.append(button);
    form.dataset.pcStatus = "ready";

    let state = "connecting";
    // A server-confirmed execution target whose online state is unobserved.
    // It never makes the control connected; it only names the reason the
    // state is unconfirmed instead of a generic read failure.
    let executableReady = false;

    // The composer grows with its content (attachment tray, model row, text).
    // The control sits on the textarea's own top-right corner, so its offset
    // and the reserved text gutter are measured, never guessed.
    function syncLayout() {
      const top = input.offsetTop + 6;
      button.style.top = Math.max(0, Math.round(top)) + "px";
      const box = button.getBoundingClientRect();
      const width = Math.ceil(box.width);
      form.style.setProperty(
        "--composer-pc-status-gutter",
        (width > 0 ? width + 10 : 0) + "px",
      );
      // The transient inline hint is anchored to the same top-right corner of
      // the composer. It moves below the control so the two never overlap.
      const hint = document.getElementById("composerInlineHint");
      if (hint) {
        const height = Math.ceil(box.height);
        hint.style.top = Math.max(34, Math.round(top) + height + 4) + "px";
      }
    }

    function hintFor(next) {
      const t = locale();
      if (next === "connected") return t.connectedHint;
      if (next === "connecting") return t.connectingHint;
      if (next === "unavailable") return executableReady ? t.executableHint : t.checkHint;
      if (next === "preparing") return t.preparingHint;
      return t.connectHint;
    }

    function labelFor(next) {
      const t = locale();
      if (next === "connected") return t.connected;
      if (next === "connecting") return t.connecting;
      if (next === "disconnected") return t.disconnected;
      if (next === "unavailable") return t.check;
      if (next === "preparing") return t.preparing;
      return t.connect;
    }

    function paint(next) {
      state = next;
      button.dataset.state = next;
      label.textContent = labelFor(next);
      // #5553: the mark inside the monitor swaps with the state, so the glyph
      // itself — not only the dot colour — names the state.
      const previousMark = icon.querySelector(".composer-pc-status-mark");
      if (previousMark) previousMark.remove();
      icon.append(stateMark(next));
      const hint = hintFor(next);
      button.setAttribute("aria-label", hint);
      // The shared product tooltip replaces the native popup, so the owner
      // never sees two hints at once.
      if (window.PadiemSharedTooltip &&
        typeof window.PadiemSharedTooltip.label === "function") {
        window.PadiemSharedTooltip.label(button, hint);
      } else {
        button.setAttribute("title", hint);
      }
    }

    // The truth is the server projection that the device directory module
    // already published. A device counts as connected only when the server
    // marked it CONNECTED and usable, and never while it is revoked or
    // expired. The classification itself lives in the ONE shared state
    // module, so this control and the Connectors computer card can never
    // disagree.
    function classify(snapshot) {
      const shared = window.PadiemComputerConnectionState;
      if (shared && typeof shared.classify === "function") {
        return shared.classify(snapshot);
      }
      return "connecting";
    }

    function syncExecutable() {
      const shared = window.PadiemComputerConnection;
      executableReady = Boolean(shared && shared.executableReady === true);
    }

    function apply(snapshot) {
      syncExecutable();
      paint(classify(snapshot));
      watchPanel();
      syncPanelState();
    }

    // The EXISTING computer connection management UI. The device directory
    // panel already owns the guidance, the device rows, the execution target
    // choice and the action into the existing Connectors computer card.
    const PANEL_ID = "clawDeviceManagerPanel";
    let watchedPanel = null;

    // The composer control is the visible owner of the management panel: the
    // duplicate entry line above the composer is not shown any more, so this
    // control carries the expanded state and the focus follows the panel.
    function syncPanelState() {
      const panel = document.getElementById(PANEL_ID);
      if (!panel) return;
      const open = !panel.hidden;
      button.setAttribute("aria-controls", PANEL_ID);
      button.setAttribute("aria-expanded", open ? "true" : "false");
      const active = document.activeElement;
      if (open) {
        if (!active || active === button || active === document.body) {
          const close = panel.querySelector(".claw-device-manager-close");
          const target = close || panel;
          if (target === panel && !target.hasAttribute("tabindex")) {
            target.setAttribute("tabindex", "-1");
          }
          if (typeof target.focus === "function") {
            target.focus({ preventScroll: true });
          }
        }
        return;
      }
      // The manager returns the focus to its own entry control, which is no
      // longer shown and therefore cannot take it. The visible composer
      // control takes it back instead.
      if (active && panel.contains(active)) {
        button.focus({ preventScroll: true });
      }
    }

    function watchPanel() {
      const panel = document.getElementById(PANEL_ID);
      if (!panel || panel === watchedPanel) return;
      watchedPanel = panel;
      if (typeof MutationObserver === "function") {
        new MutationObserver(syncPanelState).observe(panel, {
          attributes: true,
          attributeFilter: ["hidden"],
        });
      }
    }

    function openExistingPanel() {
      const shell = document.querySelector(".app-shell");
      if (shell && shell.dataset.clawComposerCollapsed === "true") {
        const composerToggle = document.getElementById("clawMobileComposerToggle");
        if (composerToggle) composerToggle.click();
      }
      const toggle = document.getElementById("clawDeviceManagerToggle");
      if (toggle) {
        toggle.click();
        syncPanelState();
        return;
      }
      const opener = document.getElementById("connectorsNavButton");
      if (!opener) return;
      opener.click();
      const card = document.getElementById("connectorComputerCard");
      if (!card) return;
      if (!card.hasAttribute("tabindex")) card.setAttribute("tabindex", "-1");
      card.focus({ preventScroll: true });
      if (typeof card.scrollIntoView === "function") {
        card.scrollIntoView({ block: "nearest", behavior: "instant" });
      }
    }

    // #5573 step 1 (2026-10-29 redesign): this control no longer opens the
    // device directory panel. A connected account gets the small PC-list
    // popover; otherwise the ONE connect flow takes over (modal, download,
    // self-closing wait). The panel path stays as the fallback for a page
    // where the connect-flow module did not load.
    button.addEventListener("click", () => {
      const flow = window.PadiemPcConnectFlow;
      if (!flow || typeof flow.open !== "function") {
        openExistingPanel();
        return;
      }
      if (state === "connected" && typeof flow.togglePopover === "function") {
        flow.togglePopover(button);
        return;
      }
      void flow.open();
    });

    // The starter card's own wiring moved to pc-connect-flow.js, which owns the
    // one connect flow the card now opens.

    // The shared snapshot is the only input. This module never reads the
    // directory endpoint itself, so it can never become a second reader or a
    // second polling system.
    window.addEventListener(SNAPSHOT_EVENT, (event) => {
      apply(event && event.detail ? event.detail : window.PadiemClawDeviceDirectory);
    });
    // The shared state module republishes the classified state, so this control
    // and the Connectors computer card always show the same state.
    window.addEventListener("padiem:computer-connection", (event) => {
      const detail = event && event.detail ? event.detail : null;
      if (!detail || typeof detail.state !== "string") return;
      executableReady = detail.executableReady === true;
      paint(detail.state);
      watchPanel();
      syncPanelState();
    });
    // #5573 step 1: the pairing list (/api/pc/pairings) is the PC-list truth
    // the 2026-10-29 redesign asks for. When the connect-flow module has
    // actually read it (read === "ok"), that state wins here; any other read
    // keeps the directory-driven state above, so a static or unconfigured
    // deployment never flips this control on its own.
    window.addEventListener("padiem:pc-pairing-state", (event) => {
      const detail = event && event.detail ? event.detail : null;
      if (!detail || detail.read !== "ok" || typeof detail.state !== "string") return;
      paint(detail.state);
    });
    new MutationObserver(() => paint(state)).observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["lang"],
    });

    if (typeof ResizeObserver === "function") {
      new ResizeObserver(() => syncLayout()).observe(form);
    }
    window.addEventListener("resize", syncLayout);

    paint("connecting");
    watchPanel();
    syncPanelState();
    syncLayout();
    // The snapshot may already be published when this module installs.
    apply(window.PadiemClawDeviceDirectory);
    // The first paint can land before the fonts settle; re-measure once.
    window.setTimeout(syncLayout, 120);
  }

  if (typeof window === "undefined" || typeof document === "undefined") return;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", install, { once: true });
  } else {
    install();
  }
})();
