// #4139 S2 — read-only multi-PC directory and explicit Web target candidate.
// This is NOT a device authority, an approval surface or an execution route.
// A future server must check session owner+workspace and per-ticket P01 before
// any device ID can be used. The current production route may be unconfigured.
(() => {
  "use strict";

  const ENDPOINT = "/api/claw/local-access/devices";
  const MAX_RESPONSE_BYTES = 32768;
  const COPY = Object.freeze({
    ko: {
      toggle: "내 컴퓨터",
      title: "연결된 내 컴퓨터",
      close: "닫기",
      refresh: "연결 상태 새로고침",
      help: "연결된 컴퓨터를 확인합니다. PC 작업은 별도의 승인이 필요합니다.",
      loading: "서버에서 컴퓨터 연결 상태를 확인하고 있습니다.",
      unavailable: "컴퓨터 연결 서비스가 아직 준비되지 않았습니다. 연결된 PC를 확인할 수 없습니다.",
      login: "로그인한 뒤 내 컴퓨터 목록을 확인할 수 있습니다.",
      failed: "연결 상태를 확인하지 못했습니다. 다시 시도해 주세요.",
      empty: "현재 계정에서 확인된 컴퓨터가 없습니다. Claw Connect 설치·연결을 먼저 완료해 주세요.",
      selection: "작업할 컴퓨터를 선택하세요. 선택만으로 파일 작업이 시작되지는 않습니다.",
      selected: "선택됨. 실제 작업은 서버의 권한 확인과 별도 승인 후 진행됩니다.",
      online: "온라인 · 작업 승인 필요",
      offline: "오프라인",
      revoked: "연결 해제",
      required: "연결 확인 필요",
      choose: "작업 대상 후보로 선택",
    },
    en: {
      toggle: "My computers",
      title: "My connected computers",
      close: "Close",
      refresh: "Refresh connection status",
      help: "Review connected devices. Running local tasks requires separate approval.",
      loading: "Checking your devices with the server.",
      unavailable: "Computer connection service is not ready yet. Device status cannot be confirmed.",
      login: "Sign in to view your computers.",
      failed: "Could not verify device status. Please retry.",
      empty: "No computers confirmed for this account. Install and pair Claw Connect first.",
      selection: "Choose a computer. Selecting it does not start a local task.",
      selected: "Selected. Any work still requires server authorization and separate approval.",
      online: "Online · approval required",
      offline: "Offline",
      revoked: "Disconnected",
      required: "Connection needs verification",
      choose: "Select as candidate device",
    },
  });

  function locale() {
    const current = window.__padiemLocale &&
      typeof window.__padiemLocale.getCurrent === "function"
        ? window.__padiemLocale.getCurrent()
        : document.documentElement.lang;
    return current === "en" ? COPY.en : COPY.ko;
  }

  function element(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (typeof text === "string") el.textContent = text;
    return el;
  }

  // Never display a server-supplied HTML fragment, token or exception detail.
  function install() {
    const shell = document.querySelector(".app-shell");
    // The active Claw workspace is separate from the ordinary Chat conversation.
    // Mount here; hidden chat surfaces are not visible in Claw mode.
    const workspace = document.getElementById("clawWorkspace");
    const projector = window.PadiemClawLocalHandoff?.deriveDeviceDirectory;
    if (!shell || !workspace || typeof projector !== "function") return;

    const root = element("section", "claw-device-manager");
    root.id = "clawDeviceManager";
    root.hidden = true;
    const toggle = element("button", "claw-device-manager-toggle");
    toggle.id = "clawDeviceManagerToggle";
    toggle.type = "button";
    toggle.setAttribute("aria-controls", "clawDeviceManagerPanel");
    toggle.setAttribute("aria-expanded", "false");
    const panel = element("section", "claw-device-manager-panel");
    panel.id = "clawDeviceManagerPanel";
    panel.setAttribute("aria-labelledby", "clawDeviceManagerTitle");
    panel.hidden = true;
    const head = element("div", "claw-device-manager-head");
    const title = element("h2", "", "");
    title.id = "clawDeviceManagerTitle";
    const close = element("button", "claw-device-manager-close");
    close.type = "button";
    const help = element("p", "claw-device-manager-help");
    const actions = element("div", "claw-device-manager-actions");
    const refresh = element("button", "claw-device-manager-refresh");
    refresh.type = "button";
    actions.appendChild(refresh);
    const status = element("p", "claw-device-manager-status");
    status.id = "clawDeviceManagerStatus";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    const list = element("ul", "claw-device-manager-list");
    list.id = "clawDeviceManagerList";
    list.hidden = true;
    head.append(title, close);
    panel.append(head, help, actions, status, list);
    root.append(toggle, panel);
    workspace.insertBefore(root, workspace.querySelector(".claw-workspace-tagline") || workspace.firstChild);

    let sequence = 0;
    let selectedId = null;
    let lastDirectory = null;
    let opened = false;
    let stateCode = "unavailable";

    function isClaw() {
      return shell.getAttribute("data-state") === "claw";
    }

    function setStatus(value) {
      stateCode = value;
      const t = locale();
      status.textContent = t[value] || t.failed;
    }

    function deviceLabel(device) {
      const t = locale();
      if (device.revoked) return t.revoked;
      if (device.online) return t.online;
      return device.state === "OFFLINE" ? t.offline : t.required;
    }

    function renderDirectory() {
      const t = locale();
      list.replaceChildren();
      list.hidden = !lastDirectory || !lastDirectory.available || !lastDirectory.devices.length;
      if (!lastDirectory || !lastDirectory.available) return;
      for (const device of lastDirectory.devices) {
        const item = element("li", "claw-device-manager-item");
        const detail = element("div", "claw-device-manager-detail");
        const name = element("strong", "", device.deviceName || device.deviceId);
        const meta = element("small", "", device.platform || "");
        const chip = element("span", "claw-device-manager-state", deviceLabel(device));
        chip.dataset.state = device.state;
        detail.append(name, meta, chip);
        const pick = element("button", "claw-device-manager-select", t.choose);
        pick.type = "button";
        pick.disabled = !device.online;
        pick.setAttribute("aria-pressed", String(Boolean(lastDirectory.canTarget &&
          lastDirectory.selectedDeviceId === device.deviceId)));
        pick.setAttribute("aria-label", t.choose + ": " + (device.deviceName || device.deviceId));
        pick.addEventListener("click", () => {
          // The latest verified snapshot is only presentation evidence.
          // This choice stays in memory and never creates an execution grant.
          if (!lastDirectory || !lastDirectory.available) return;
          const candidate = projector(lastEnvelope, device.deviceId);
          if (!candidate.canTarget) return;
          selectedId = device.deviceId;
          lastDirectory = candidate;
          setStatus("selected");
          renderDirectory();
        });
        item.append(detail, pick);
        list.appendChild(item);
      }
    }

    let lastEnvelope = null;
    function reset() {
      sequence += 1; // invalidate any in-flight response or previous owner snapshot
      selectedId = null;
      lastEnvelope = null;
      lastDirectory = null;
      list.replaceChildren();
      list.hidden = true;
    }

    async function load() {
      if (!opened || !isClaw()) return;
      const request = ++sequence;
      lastEnvelope = null;
      lastDirectory = null;
      list.replaceChildren();
      list.hidden = true;
      setStatus("loading");
      let response;
      try {
        response = await fetch(ENDPOINT, {
          method: "GET",
          credentials: "same-origin",
          cache: "no-store",
          headers: { Accept: "application/json" },
        });
      } catch {
        if (sequence === request && opened && isClaw()) {
          selectedId = null;
          setStatus("failed");
        }
        return;
      }
      if (request !== sequence || !opened || !isClaw()) return;
      if (response.status === 401 || response.status === 403) {
        selectedId = null;
        setStatus("login");
        return;
      }
      if (response.status === 404 || response.status === 501 || response.status === 503) {
        selectedId = null;
        setStatus("unavailable");
        return;
      }
      if (!response.ok) {
        selectedId = null;
        setStatus("failed");
        return;
      }
      try {
        const rawText = await response.text();
        if (request !== sequence || !opened || !isClaw()) return;
        if (rawText.length > MAX_RESPONSE_BYTES) throw Error("oversize");
        const payload = JSON.parse(rawText);
        if (!payload || payload.ok !== true || payload.available !== true ||
            payload.ownerScoped !== true) {
          selectedId = null;
          setStatus("unavailable");
          return;
        }
        const directory = projector(payload, selectedId);
        if (!directory.available) {
          selectedId = null;
          setStatus("failed");
          return;
        }
        // Retain only fields explicitly sanitized by the existing projection.
        // Drop raw response objects immediately (including any extra secrets).
        lastEnvelope = {
          available: true, ownerScoped: true,
          devices: directory.devices.map((d) => ({
            deviceId: d.deviceId,
            deviceName: d.deviceName,
            platform: d.platform,
            state: d.state,
            usable: d.online,
            revoked: d.revoked,
          })),
        };
        lastDirectory = directory;
        selectedId = directory.canTarget ? directory.selectedDeviceId : null;
        setStatus(directory.devices.length ? "selection" : "empty");
        renderDirectory();
      } catch {
        if (request === sequence && opened && isClaw()) {
          selectedId = null;
          lastEnvelope = null;
          lastDirectory = null;
          setStatus("failed");
        }
      }
    }

    function translations() {
      const t = locale();
      toggle.textContent = t.toggle;
      title.textContent = t.title;
      close.textContent = t.close;
      help.textContent = t.help;
      refresh.textContent = t.refresh;
      if (opened) {
        if (lastDirectory?.available) {
          setStatus(lastDirectory.canTarget ? "selected" :
            lastDirectory.devices.length ? "selection" : "empty");
          renderDirectory();
        } else {
          setStatus(stateCode);
        }
      }
    }

    function closePanel() {
      opened = false;
      reset();
      panel.hidden = true;
      toggle.setAttribute("aria-expanded", "false");
      toggle.focus();
    }

    function sync() {
      if (isClaw()) {
        root.hidden = false;
        return;
      }
      root.hidden = true;
      if (opened) closePanel();
      else reset();
    }

    toggle.addEventListener("click", () => {
      if (!isClaw()) return;
      if (opened) {
        closePanel();
        return;
      }
      opened = true;
      panel.hidden = false;
      toggle.setAttribute("aria-expanded", "true");
      void load();
    });
    close.addEventListener("click", closePanel);
    refresh.addEventListener("click", () => {
      selectedId = null;
      void load();
    });
    root.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && opened) {
        event.preventDefault();
        closePanel();
      }
    });
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible" && opened) {
        // Returning from pairing may change device truth; GET only.
        selectedId = null;
        void load();
      }
    });
    window.addEventListener("pageshow", (event) => {
      if (event.persisted && opened) {
        selectedId = null;
        void load();
      }
    });
    for (const evt of ["padiem:auth-changed", "padiem:account-changed"]) {
      window.addEventListener(evt, () => {
        reset();
        if (opened && isClaw()) void load();
      });
    }
    new MutationObserver(sync).observe(shell, { attributes: true, attributeFilter: ["data-state"] });
    new MutationObserver(translations).observe(document.documentElement, {
      attributes: true, attributeFilter: ["lang"],
    });
    translations();
    sync();
  }

  if (typeof window === "undefined" || typeof document === "undefined") return;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", install, { once: true });
  } else {
    install();
  }
})();
