// #4139 S2 — read-only multi-PC directory and explicit Web target candidate.
// This is NOT a device authority, an approval surface or an execution route.
// A future server must check session owner+workspace and per-ticket P01 before
// any device ID can be used. The current production route may be unconfigured.
(() => {
  "use strict";

  const ENDPOINT = "/api/claw/local-access/devices";
  const SELECT_ENDPOINT = "/api/claw/local-access/devices/select";
  // Match the owner's drive comparison interval; only an open, visible
  // directory reads again. This never sends a PC command or confirmation.
  const DRIVE_REFRESH_MS = 30000;
  const READ_TIMEOUT_MS = 12000;
  const SAVE_TIMEOUT_MS = 12000;
  const COPY = Object.freeze({
    ko: {
      title: "연결된 내 컴퓨터",
      close: "닫기",
      refresh: "새로고침",
      help: "내 PC 작업은 바로 진행되고, 덮어쓰기·삭제 전에는 자동으로 백업돼요. 메일·메시지 보내기는 보내기 전에 한 번 확인해요.",
      entryTitle: "컴퓨터와 연결해 보세요",
      entryDescription: "내 컴퓨터의 파일과 프로그램을 Padiem에서 사용할 수 있어요.",
      connectAction: "컴퓨터 연결하기",
      loading: "서버에서 컴퓨터 연결 상태를 확인하고 있습니다.",
      unavailable: "컴퓨터 연결 서비스가 아직 준비되지 않았습니다. 연결된 PC를 확인할 수 없습니다.",
      unconfigured: "컴퓨터 연결 서비스가 아직 설정되지 않았습니다. 연결 서비스가 설정되면 이 목록을 확인할 수 있습니다.",
      readFailed: "연결 서비스 조회 중 문제가 발생했습니다. 잠시 후 다시 새로고침을 눌러 확인해 주세요.",
      login: "로그인한 뒤 내 컴퓨터 목록을 확인할 수 있습니다.",
      failed: "연결 상태를 확인하지 못했습니다. 다시 시도해 주세요.",
      empty: "현재 계정에서 확인된 컴퓨터가 없습니다. Claw Connect 설치·연결을 먼저 완료해 주세요.",
      selection: "작업할 컴퓨터를 선택하세요. 선택만으로 파일 작업이 시작되지는 않습니다.",
      selected: "선택됨. 실제 작업은 바로 진행되고, 덮어쓰기·삭제 전에는 자동으로 백업돼요.",
      restored: "저장된 작업 대상을 복원했습니다. 실제 작업은 바로 진행되고, 덮어쓰기·삭제 전에는 자동으로 백업돼요.",
      selectedOffline: "저장된 PC가 오프라인 또는 연결 해제 상태입니다. 다른 PC로 자동 전환하지 않습니다.",
      selectedMissing: "저장된 PC를 현재 목록에서 확인할 수 없습니다. 작업 대상을 다시 선택해 주세요.",
      saveFailed: "작업 대상 저장을 확인하지 못했습니다. 다시 선택해 주세요.",
      online: "온라인 · 바로 작업",
      offline: "오프라인",
      revoked: "연결 해제",
      expired: "인증이 만료되었습니다 · 다시 연결해 주세요",
      required: "연결 확인 필요",
      executable: "실행 대상 준비 · 온라인 상태 미확인",
      choose: "작업 대상 후보로 선택",
      drivesTitle: "드라이브",
      drivesPending: "드라이브 목록을 기다리고 있어요.",
      drivesUnavailable: "드라이브 목록을 확인하지 못했습니다.",
      drivesEmpty: "현재 보고된 드라이브가 없습니다.",
      drivesUpdated: "마지막 확인",
      driveFree: "여유 {size}",
      driveFreeUnknown: "여유 공간 확인 안 됨",
      driveKinds: { fixed: "내장 디스크", removable: "이동식 디스크", network: "네트워크 드라이브", cdrom: "CD/DVD", ramdisk: "메모리 디스크", unknown: "종류 확인 안 됨" },
    },
    en: {
      title: "My connected computers",
      close: "Close",
      refresh: "Refresh",
      help: "Work on your PC runs right away; overwrites and deletes are backed up automatically first. Sending email or messages asks once before sending.",
      entryTitle: "Connect your computer",
      entryDescription: "Use the files and programs on your computer in Padiem.",
      connectAction: "Connect a computer",
      loading: "Checking your devices with the server.",
      unavailable: "Computer connection service is not ready yet. Device status cannot be confirmed.",
      unconfigured: "The computer connection service is not configured yet. Once it is set up, this list can be shown.",
      readFailed: "Something went wrong while reading the connection service. Press ‘Refresh’ to check again.",
      login: "Sign in to view your computers.",
      failed: "Could not verify device status. Please retry.",
      empty: "No computers confirmed for this account. Install and pair Claw Connect first.",
      selection: "Choose a computer. Selecting it does not start a local task.",
      selected: "Selected. Work runs right away; overwrites and deletes are backed up automatically first.",
      restored: "Restored the saved target. Work runs right away; overwrites and deletes are backed up automatically first.",
      selectedOffline: "The saved PC is offline or disconnected. No other PC is substituted automatically.",
      selectedMissing: "The saved PC is not in the current list. Choose a target again.",
      saveFailed: "Could not confirm the target selection. Please choose again.",
      online: "Online · ready",
      offline: "Offline",
      revoked: "Disconnected",
      expired: "Credential expired · reconnect",
      required: "Connection needs verification",
      executable: "Execution target ready · online status unverified",
      choose: "Select as candidate device",
      drivesTitle: "Drives",
      drivesPending: "Waiting for the drive list.",
      drivesUnavailable: "Could not read the drive list.",
      drivesEmpty: "No drives are currently reported.",
      drivesUpdated: "Last checked",
      driveFree: "{size} free",
      driveFreeUnknown: "Free space not available",
      driveKinds: { fixed: "Fixed disk", removable: "Removable disk", network: "Network drive", cdrom: "CD/DVD", ramdisk: "RAM disk", unknown: "Unknown type" },
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

  function formatBytes(value) {
    const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];
    let amount = value;
    let unit = 0;
    while (amount >= 1024 && unit < units.length - 1) {
      amount /= 1024;
      unit += 1;
    }
    return new Intl.NumberFormat(locale() === COPY.en ? "en" : "ko", {
      maximumFractionDigits: unit ? 1 : 0,
    }).format(amount) + " " + units[unit];
  }

  // Never display a server-supplied HTML fragment, token or exception detail.
  function install() {
    const shell = document.querySelector(".app-shell");
    // Chat and Claw share one composer surface; mounting above it makes the
    // same "My computers" panel available in both products without a second
    // device authority or a product-specific copy.
    const composer = document.getElementById("composerForm");
    const projector = window.PadiemClawLocalHandoff?.deriveDeviceDirectory;
    if (!shell || !composer || typeof projector !== "function") return;

    const root = element("section", "claw-device-manager");
    root.id = "clawDeviceManager";
    root.hidden = true;
    const toggle = element("button", "claw-device-manager-toggle");
    toggle.id = "clawDeviceManagerToggle";
    toggle.type = "button";
    toggle.setAttribute("aria-controls", "clawDeviceManagerPanel");
    toggle.setAttribute("aria-expanded", "false");
    const toggleTitle = element("span", "claw-device-manager-toggle-title");
    const toggleState = element("span", "claw-device-manager-state");
    toggleState.hidden = true;
    toggle.append(toggleTitle, toggleState);
    // The entry carries its own headline and state: the connection guidance
    // before a PC is confirmed, and the real PC name plus its server-confirmed
    // state afterwards. One control, one line, no second device authority.
    const panel = element("section", "claw-device-manager-panel");
    panel.id = "clawDeviceManagerPanel";
    panel.setAttribute("aria-labelledby", "clawDeviceManagerTitle");
    panel.hidden = true;
    const head = element("div", "claw-device-manager-head");
    // The panel title, its short refresh action and the close button share one
    // line: refresh sits next to the title and close stays on the right. The
    // close button is declared before refresh in the DOM so a keyboard user
    // still reaches the refresh action with a forward Tab from it.
    const title = element("h2", "", "");
    title.id = "clawDeviceManagerTitle";
    const close = element("button", "claw-device-manager-close");
    close.type = "button";
    const refresh = element("button", "claw-device-manager-refresh");
    refresh.type = "button";
    const help = element("p", "claw-device-manager-help");
    const status = element("p", "claw-device-manager-status");
    status.id = "clawDeviceManagerStatus";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    const list = element("ul", "claw-device-manager-list");
    list.id = "clawDeviceManagerList";
    list.hidden = true;
    // The not-connected guidance and its one action into the EXISTING Claw
    // computer connect screen. It is appended last so the panel's control
    // order (refresh, close, device rows) stays the same.
    const connect = element("div", "claw-device-manager-connect");
    connect.id = "clawDeviceManagerConnect";
    const connectTitle = element("h3", "claw-device-manager-connect-title");
    const connectCopy = element("p", "claw-device-manager-connect-copy");
    const connectAction = element("button", "claw-device-manager-connect-action");
    connectAction.id = "clawDeviceManagerConnectAction";
    connectAction.type = "button";
    connect.append(connectTitle, connectCopy, connectAction);
    head.append(title, close, refresh);
    panel.append(head, help, status, list, connect);
    // The directory panel is owned by the shared composer: it opens directly
    // above the composer area, stays inside the composer's width and never
    // overlaps the message input.
    root.append(toggle, panel);
    composer.parentElement.insertBefore(root, composer);

    let sequence = 0;
    let pendingController = null;
    let pendingSelection = null;
    let selectionSequence = 0;
    let selectionQueue = Promise.resolve();
    let selectedId = null;
    let savedTargetId = null;
    let lastDirectory = null;
    let opened = false;
    let stateCode = "unavailable";
    let readCompleted = false;
    let refreshTimer = null;

    function stopRefresh() {
      if (refreshTimer !== null) window.clearTimeout(refreshTimer);
      refreshTimer = null;
    }

    function scheduleRefresh() {
      stopRefresh();
      if (!opened || document.visibilityState === "hidden") return;
      refreshTimer = window.setTimeout(() => {
        refreshTimer = null;
        if (pendingController || pendingSelection) scheduleRefresh();
        else void load({ backgroundRefresh: true });
      }, DRIVE_REFRESH_MS);
    }

    // The shared directory snapshot. The composer status control reads this
    // instead of opening a second connection to the directory endpoint, so
    // this module stays the only reader and the only device authority.
    function publishDirectory() {
      const directory = lastDirectory;
      const snapshot = {
        readCompleted: readCompleted,
        available: Boolean(directory && directory.available),
        reason: directory ? directory.reason : null,
        statusCode: stateCode,
        // The server-owned preference and the device it resolves to are both
        // published, so a consumer can tell "no target chosen" from "the
        // chosen target is gone".
        savedTargetId: savedTargetId,
        selectedDeviceId: directory ? directory.selectedDeviceId : null,
        canTarget: Boolean(directory && directory.canTarget),
        devices: confirmedDevices().map((device) => ({
          deviceId: device.deviceId,
          deviceName: device.deviceName,
          platform: device.platform,
          state: device.state,
          online: device.online === true,
          revoked: device.revoked === true,
          expired: device.expired === true,
          executable: device.executable === true,
          selectable: device.selectable === true,
          drivesStatus: device.drivesStatus,
          ...(device.drivesStatus === "ready" ? {
            drives: device.drives,
            drivesUpdatedAt: device.drivesUpdatedAt,
          } : {}),
        })),
      };
      window.PadiemClawDeviceDirectory = snapshot;
      if (typeof window.dispatchEvent === "function" && typeof CustomEvent === "function") {
        window.dispatchEvent(new CustomEvent("padiem:claw-device-directory", { detail: snapshot }));
      }
    }

    function setStatus(value) {
      stateCode = value;
      const t = locale();
      status.textContent = t[value] || t.failed;
    }

    function deviceLabel(device) {
      const t = locale();
      if (device.revoked) return t.revoked;
      // An expired credential and a PC that is merely offline are different
      // problems with different fixes. The server already distinguishes them,
      // so the label names the real one.
      if (device.expired) return t.expired;
      if (device.executable && device.selectable && !device.online) return t.executable;
      if (device.online) return t.online;
      return device.state === "OFFLINE" ? t.offline : t.required;
    }

    // The directory rows the server confirmed for this owner. This module stays
    // the only reader of that endpoint, so the entry line below and the panel
    // below always describe the same server-confirmed snapshot.
    function confirmedDevices() {
      if (!lastDirectory || !lastDirectory.available) return [];
      return Array.isArray(lastDirectory.devices) ? lastDirectory.devices : [];
    }

    function primaryDevice() {
      const devices = confirmedDevices();
      if (!devices.length) return null;
      return devices.find((device) => device.online && !device.revoked) || devices[0];
    }

    // The shared entry line: the connection guidance while no PC is confirmed,
    // and the real PC name plus its confirmed state afterwards. Desktop and
    // mobile read the same snapshot, so both always agree.
    function renderEntry() {
      const t = locale();
      const device = primaryDevice();
      if (device) {
        toggleTitle.textContent = device.deviceName || device.deviceId;
        toggleState.textContent = deviceLabel(device);
        toggleState.dataset.state = device.state;
        toggleState.hidden = false;
      } else {
        toggleTitle.textContent = t.entryTitle;
        toggleState.textContent = "";
        toggleState.removeAttribute("data-state");
        toggleState.hidden = true;
      }
      connectTitle.textContent = t.entryTitle;
      connectCopy.textContent = t.entryDescription;
      connectAction.textContent = t.connectAction;
      // The guidance belongs to the not-connected state only.
      connect.hidden = Boolean(device);
    }

    // The EXISTING Claw computer connect screen: the Connectors surface that
    // already owns the computer card. No new screen, no new pairing, no
    // second registration system. The Connectors surface is a standalone
    // view, so the existing sidebar entry is the only navigation needed.
    function openComputerConnectScreen() {
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

    function renderDirectory() {
      const t = locale();
      list.replaceChildren();
      list.hidden = !lastDirectory || !lastDirectory.available || !lastDirectory.devices.length;
      renderEntry();
      if (!lastDirectory || !lastDirectory.available) return;
      for (const device of lastDirectory.devices) {
        const item = element("li", "claw-device-manager-item");
        const detail = element("div", "claw-device-manager-detail");
        const name = element("strong", "", device.deviceName || device.deviceId);
        name.title = device.deviceName || device.deviceId;
        const meta = element("small", "", device.platform || "");
        // The server-owned ID stays a detail value: truncated on screen and
        // readable in full on hover or focus, never a line of its own.
        if (device.deviceId && device.deviceId !== (device.deviceName || "")) {
          const id = element("small", "claw-device-manager-id", device.deviceId);
          id.title = device.deviceId;
          detail.append(name, meta, id);
        } else {
          detail.append(name, meta);
        }
        const chip = element("span", "claw-device-manager-state", deviceLabel(device));
        chip.dataset.state = device.state;
        detail.append(chip);
        const drives = element("div", "claw-device-manager-drives");
        drives.setAttribute("aria-label", t.drivesTitle);
        if (device.drivesStatus === "ready") {
          if (!device.drives.length) {
            drives.append(element("small", "claw-device-manager-drive-empty", t.drivesEmpty));
          }
          for (const drive of device.drives) {
            const line = element("div", "claw-device-manager-drive");
            const label = drive.name ? drive.name + " (" + drive.path + ")" : drive.path;
            line.append(element("span", "claw-device-manager-drive-name", label));
            line.append(element("small", "claw-device-manager-drive-kind", t.driveKinds[drive.kind]));
            const free = drive.free_bytes === null ? t.driveFreeUnknown :
              t.driveFree.replace("{size}", formatBytes(drive.free_bytes));
            line.append(element("small", "claw-device-manager-drive-free", free));
            drives.append(line);
          }
          drives.append(element("small", "claw-device-manager-drive-updated",
            t.drivesUpdated + ": " + new Date(device.drivesUpdatedAt).toLocaleString(
              locale() === COPY.en ? "en" : "ko")));
        } else {
          drives.append(element("small", "claw-device-manager-drive-status",
            device.drivesStatus === "unavailable" ? t.drivesUnavailable : t.drivesPending));
        }
        detail.append(drives);
        const pick = element("button", "claw-device-manager-select", t.choose);
        pick.type = "button";
        pick.disabled = !device.selectable;
        pick.setAttribute("aria-pressed", String(Boolean(lastDirectory.canTarget &&
          lastDirectory.selectedDeviceId === device.deviceId)));
        pick.setAttribute("aria-label", t.choose + ": " + (device.deviceName || device.deviceId));
        pick.addEventListener("click", async () => {
          // The latest verified snapshot is only presentation evidence.
          // The choice is saved server-side as a PREFERENCE; execution
          // re-verifies owner, device and Mesh target.
          if (!lastDirectory || !lastDirectory.available) return;
          const candidate = projector(lastEnvelope, device.deviceId);
          if (!candidate.canTarget) return;
          pick.disabled = true;
          const saved = await saveSelection(device.deviceId);
          pick.disabled = !device.selectable;
          if (!saved) {
            setStatus("saveFailed");
            return;
          }
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
      stopRefresh();
      if (pendingController) pendingController.abort();
      pendingController = null;
      if (pendingSelection) pendingSelection.abort();
      pendingSelection = null;
      // Any queued/in-flight selection result now belongs to a previous
      // session generation and must not repaint the new account.
      selectionSequence += 1;
      panel.removeAttribute("aria-busy");
      sequence += 1; // invalidate any in-flight response or previous owner snapshot
      selectedId = null;
      savedTargetId = null;
      lastEnvelope = null;
      lastDirectory = null;
      list.replaceChildren();
      list.hidden = true;
      // A new account generation starts from the not-connected guidance again.
      renderEntry();
      // The shared snapshot returns to "not read yet", so no consumer can
      // show a connection that belongs to the previous owner.
      readCompleted = false;
      publishDirectory();
    }

    async function postSelection(deviceId) {
      const controller = new AbortController();
      pendingSelection = controller;
      const timer = window.setTimeout(() => controller.abort(), SAVE_TIMEOUT_MS);
      try {
        const response = await fetch(SELECT_ENDPOINT, {
          method: "POST",
          credentials: "same-origin",
          cache: "no-store",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ device_id: deviceId }),
          signal: controller.signal,
        });
        if (!response.ok) return false;
        const data = await response.json().catch(() => null);
        // Readback: the server must confirm the exact saved identifier.
        return Boolean(data && data.ok === true && data.selectedDeviceId === deviceId);
      } catch {
        return false;
      } finally {
        window.clearTimeout(timer);
        if (pendingSelection === controller) pendingSelection = null;
      }
    }

    async function saveSelection(deviceId) {
      // Serialize writes so rapid consecutive clicks cannot commit out of
      // order; only the latest click may repaint the selection. A queued
      // write from a previous account generation never runs.
      const generation = sequence;
      const requestSequence = ++selectionSequence;
      const run = selectionQueue.then(() => (
        generation === sequence ? postSelection(deviceId) : false
      ));
      selectionQueue = run.then(() => undefined, () => undefined);
      const saved = await run;
      return requestSequence === selectionSequence && saved === true;
    }

    async function load(options = {}) {
      // Opening the panel reads the directory. One authenticated-session
      // restore also reads it without opening, so a new conversation can use
      // the saved target. Only an open visible panel refreshes its inventory.
      if (window.PadiemAuthGate?.authenticated() === false) {
        reset(); if (opened) setStatus("login"); return;
      }
      const restoreOnly = options && options.restoreOnly === true;
      if (!opened && !restoreOnly) return;
      // Refreshing also invalidates the previous request. A late response can
      // never repopulate an account-switched or dismissed directory.
      if (pendingController) pendingController.abort();
      const controller = new AbortController();
      pendingController = controller;
      const request = ++sequence;
      const clearDirectory = () => {
        lastEnvelope = null;
        lastDirectory = null;
        list.replaceChildren();
        list.hidden = true;
      };
      // A scheduled read is not a deselection. Keep the last verified target
      // while HTTP is pending so a concurrent Chat message still carries it.
      // Account changes reset it immediately; every settled response replaces
      // it, including denial, disappearance and a failed read.
      if (options.backgroundRefresh !== true) clearDirectory();
      panel.setAttribute("aria-busy", "true");
      setStatus("loading");
      // Cover both HTTP dispatch and response body reads, not only fetch().
      const timer = window.setTimeout(() => controller.abort(), READ_TIMEOUT_MS);
      try {
        const response = await fetch(ENDPOINT, {
          method: "GET",
          credentials: "same-origin",
          cache: "no-store",
          headers: { Accept: "application/json" },
          signal: controller.signal,
        });
        if (request !== sequence) return;
        if (!response.ok) clearDirectory();
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
        const rawText = await response.text();
        if (request !== sequence) return;
        clearDirectory();
        const payload = JSON.parse(rawText);
        // The reviewed unavailable envelope distinguishes "not configured yet"
        // from "the read failed and should be retried". Only these two reason
        // codes are interpreted; every other value keeps the existing safe
        // refusal, and no server-supplied text is ever rendered.
        if (payload && payload.ok === true && payload.available === false) {
          selectedId = null;
          if (payload.reason === "device_directory_unconfigured") {
            setStatus("unconfigured");
          } else if (payload.reason === "device_directory_read_failed") {
            setStatus("readFailed");
          } else {
            setStatus("unavailable");
          }
          return;
        }
        if (!payload || payload.ok !== true || payload.available !== true ||
            payload.ownerScoped !== true) {
          selectedId = null;
          setStatus("unavailable");
          return;
        }
        // The server-owned preference is the restore source for a new
        // conversation/reload. It never substitutes another device.
        const restored = typeof payload.selectedDeviceId === "string" &&
          payload.selectedDeviceId ? payload.selectedDeviceId : null;
        savedTargetId = restored;
        const directory = projector(payload, restored);
        if (!directory.available) {
          selectedId = null;
          setStatus("failed");
          return;
        }
        // Keep only the verified, non-secret directory projection.
        lastEnvelope = {
          available: true, ownerScoped: true,
          devices: directory.devices.map((d) => ({
            deviceId: d.deviceId,
            deviceName: d.deviceName,
            platform: d.platform,
            state: d.state,
            usable: d.online,
            revoked: d.revoked,
            expired: d.expired,
            executable: d.executable,
            selectable: d.selectable,
            drivesStatus: d.drivesStatus,
            ...(d.drivesStatus === "ready" ? {
              drives: d.drives,
              drivesUpdatedAt: d.drivesUpdatedAt,
            } : {}),
          })),
        };
        lastDirectory = directory;
        selectedId = directory.canTarget ? directory.selectedDeviceId : null;
        if (restored && directory.canTarget) {
          setStatus("restored");
        } else if (restored && payload.selectedState === "NOT_REGISTERED") {
          setStatus("selectedMissing");
        } else if (restored) {
          setStatus("selectedOffline");
        } else {
          setStatus(directory.devices.length ? "selection" : "empty");
        }
        renderDirectory();
      } catch {
        if (request === sequence) {
          selectedId = null;
          clearDirectory();
          setStatus("failed");
        }
      } finally {
        window.clearTimeout(timer);
        if (pendingController === controller) pendingController = null;
        if (request === sequence) {
          panel.removeAttribute("aria-busy");
          // Every read attempt publishes its own result, so the shared
          // snapshot never keeps a state that the server did not confirm.
          // A superseded read publishes nothing: its owner generation is
          // already gone.
          readCompleted = true;
          publishDirectory();
          scheduleRefresh();
        }
      }
    }

    function translations() {
      const t = locale();
      title.textContent = t.title;
      close.textContent = t.close;
      help.textContent = t.help;
      refresh.textContent = t.refresh;
      // The entry headline follows the confirmed connection state, so a locale
      // switch and a state switch repaint the same entry.
      renderEntry();
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
      // The panel is mounted once above the shared composer and is available
      // in both Chat and Claw. Its own container governs visibility.
      root.hidden = false;
    }

    toggle.addEventListener("click", () => {
      if (opened) {
        closePanel();
        return;
      }
      opened = true;
      panel.hidden = false;
      toggle.setAttribute("aria-expanded", "true");
      // The panel is mounted above the composer area, so it is the next
      // element in the reading order. Move the focus into it when it opens:
      // that is the standard disclosure behaviour and it keeps every panel
      // control reachable with the keyboard.
      close.focus({ preventScroll: true });
      void load();
    });
    close.addEventListener("click", closePanel);
    // Close when clicking outside the panel. The composer status control that
    // opens it, the first-screen computer card that reuses the same entry, and
    // the guidance surface that reads this panel's own rendered states are
    // handled separately so their clicks do not close (and clear) the panel.
    document.addEventListener("click", (event) => {
      if (!opened) return;
      const target = event && event.target;
      if (target && typeof target.closest === "function" &&
          target.closest("#composerPcStatus, #pcConnectStarter, #clawDeviceGuidance")) return;
      if (root.contains(target)) return;
      closePanel();
    });
    // Escape closes the panel from anywhere, including when focus has left it.
    document.addEventListener("keydown", (event) => {
      if (opened && event && event.key === "Escape") {
        event.preventDefault();
        closePanel();
      }
    });
    // The not-connected action opens the EXISTING Claw computer connect
    // screen. It never pairs, registers or grants anything by itself.
    connectAction.addEventListener("click", () => {
      openComputerConnectScreen();
    });
    refresh.addEventListener("click", () => {
      selectedId = null;
      void load();
    });
    // Escape closes the directory from anywhere inside it. The panel lives
    // in the content column, so it carries its own listener next to the
    // entry's.
    const closeOnEscape = (event) => {
      if (event.key === "Escape" && opened) {
        event.preventDefault();
        closePanel();
      }
    };
    root.addEventListener("keydown", closeOnEscape);
    panel.addEventListener("keydown", closeOnEscape);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible" && opened) {
        // Returning from pairing may change device truth; GET only.
        selectedId = null;
        void load();
      } else {
        stopRefresh();
      }
    });
    window.addEventListener("pageshow", (event) => {
      if (event.persisted && opened) {
        selectedId = null;
        void load();
      }
    });
    for (const evt of ["padiem:auth-state", "padiem:auth-changed", "padiem:account-changed"]) {
      window.addEventListener(evt, () => {
        reset();
        // One restore read per authenticated session generation. A signed-out
        // read returns 401 and never becomes a selection.
        void load({ restoreOnly: true });
      });
    }
    // Selection hint for both product transports. This is a server-restored
    // preference, not a device grant; every execution rechecks Identity,
    // Broker and the Mesh target.
    const selectedDevice = () => (
      lastDirectory?.canTarget ? selectedId : null
    );
    window.padiemSelectedDeviceId = selectedDevice;
    window.padiemClawSelectedDeviceId = selectedDevice;
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
