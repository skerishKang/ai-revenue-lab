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
      check: "PC 연결 확인",
      connectHint: "컴퓨터가 연결되어 있지 않습니다. 클릭하면 컴퓨터 연결 안내를 엽니다.",
      connectedHint: "컴퓨터가 연결되어 있습니다. 클릭하면 연결된 컴퓨터 정보를 확인합니다.",
      checkHint: "컴퓨터 연결 상태를 확인하지 못했습니다. 클릭하면 연결 상태를 다시 확인합니다.",
      checkingHint: "컴퓨터 연결 상태를 확인하는 중입니다. 클릭하면 컴퓨터 연결 안내를 엽니다.",
    },
    en: {
      connect: "PC connect",
      connected: "PC connected",
      check: "PC check",
      connectHint: "No computer is connected. Click to open the computer connection guide.",
      connectedHint: "A computer is connected. Click to review the connected computer.",
      checkHint: "The computer connection status could not be confirmed. Click to check it again.",
      checkingHint: "Checking the computer connection status. Click to open the computer connection guide.",
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

  function install() {
    const form = document.getElementById("composerForm");
    const input = document.getElementById("messageInput");
    if (!form || !input) return;
    // One control for both products: Chat and Claw share this composer.
    if (document.getElementById("composerPcStatus")) return;

    const button = element("button", "composer-pc-status");
    button.type = "button";
    button.id = "composerPcStatus";
    button.dataset.state = "unknown";
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

    let state = "unknown";

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
      if (next === "check") return t.checkHint;
      if (next === "unknown") return t.checkingHint;
      return t.connectHint;
    }

    function labelFor(next) {
      const t = locale();
      if (next === "connected") return t.connected;
      if (next === "check") return t.check;
      return t.connect;
    }

    function paint(next) {
      state = next;
      button.dataset.state = next;
      label.textContent = labelFor(next);
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
    // expired.
    function classify(snapshot) {
      if (!snapshot || snapshot.readCompleted !== true) return "unknown";
      const status = typeof snapshot.statusCode === "string" ? snapshot.statusCode : "";
      // The directory itself could not be read or is not configured.
      if (status === "unavailable" || status === "unconfigured" ||
          status === "readFailed" || status === "failed") return "check";
      if (status === "login") return "disconnected";
      if (snapshot.available !== true) return "check";
      const devices = Array.isArray(snapshot.devices) ? snapshot.devices : [];
      if (!devices.length) return "disconnected";
      const usable = (device) => Boolean(
        device && device.online === true &&
        device.revoked !== true && device.expired !== true,
      );
      const savedTargetId = typeof snapshot.savedTargetId === "string"
        ? snapshot.savedTargetId
        : "";
      if (savedTargetId) {
        // Claw already chose an execution target: that target's own state is
        // the state the reader asked about. No other PC is substituted for it.
        const target = devices.find((device) => device.deviceId === savedTargetId);
        if (!target) return "check";
        if (usable(target)) return "connected";
        if (target.revoked === true || target.expired === true) return "check";
        return "disconnected";
      }
      if (devices.some(usable)) return "connected";
      const needsAttention = devices.every((device) => (
        device.revoked === true || device.expired === true ||
        device.state === "ACTION_REQUIRED"
      ));
      return needsAttention ? "check" : "disconnected";
    }

    function apply(snapshot) {
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

    button.addEventListener("click", openExistingPanel);

    // The shared snapshot is the only input. This module never reads the
    // directory endpoint itself, so it can never become a second reader or a
    // second polling system.
    window.addEventListener(SNAPSHOT_EVENT, (event) => {
      apply(event && event.detail ? event.detail : window.PadiemClawDeviceDirectory);
    });
    new MutationObserver(() => paint(state)).observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["lang"],
    });

    if (typeof ResizeObserver === "function") {
      new ResizeObserver(() => syncLayout()).observe(form);
    }
    window.addEventListener("resize", syncLayout);

    paint("unknown");
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
