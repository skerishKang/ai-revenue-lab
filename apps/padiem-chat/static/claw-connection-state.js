/* B62 Padiem Chat / B54 Padiem Claw — the ONE computer connection state.
 *
 * The device directory module is the only reader of the canonical directory
 * endpoint and it publishes the shared directory snapshot. This module turns
 * that snapshot into the single state that BOTH the composer status control
 * and the Connectors computer card render, so the two surfaces can never
 * disagree about whether a computer is connected.
 *
 * The state vocabulary is the one the Connectors screen uses:
 *
 *   connected    — the server proved a usable computer
 *   connecting   — the state is still being read
 *   disconnected — no computer is connected
 *   unavailable  — the state could NOT be read (an error, never an OFF)
 *   preparing    — the computer connection lane is not set up here
 *
 * Nothing here ever claims a connection the server did not prove, and this
 * module opens no connection of its own: it only reads the published
 * snapshot and asks the existing directory control to re-read it.
 */
(() => {
  "use strict";

  const DIRECTORY_EVENT = "padiem:claw-device-directory";
  const STATE_EVENT = "padiem:computer-connection";

  const STATE = Object.freeze({
    CONNECTED: "connected",
    CONNECTING: "connecting",
    DISCONNECTED: "disconnected",
    UNAVAILABLE: "unavailable",
    PREPARING: "preparing",
  });

  function current() {
    const snapshot = window.PadiemClawDeviceDirectory;
    return snapshot && typeof snapshot === "object" ? snapshot : null;
  }

  function usableDevice(device) {
    return Boolean(
      device && device.online === true &&
      device.revoked !== true && device.expired !== true,
    );
  }

  /* The one classification. The saved execution target decides the state when
     there is one: no other computer is substituted for it. */
  function classify(snapshot) {
    if (!snapshot || snapshot.readCompleted !== true) return STATE.CONNECTING;
    const status = typeof snapshot.statusCode === "string" ? snapshot.statusCode : "";
    if (status === "loading") return STATE.CONNECTING;
    if (status === "unconfigured") return STATE.PREPARING;
    if (status === "unavailable" || status === "readFailed" || status === "failed") {
      return STATE.UNAVAILABLE;
    }
    if (status === "login") return STATE.DISCONNECTED;
    if (snapshot.available !== true) return STATE.UNAVAILABLE;
    const devices = Array.isArray(snapshot.devices) ? snapshot.devices : [];
    if (!devices.length) return STATE.DISCONNECTED;
    const savedTargetId = typeof snapshot.savedTargetId === "string"
      ? snapshot.savedTargetId
      : "";
    if (savedTargetId) {
      const target = devices.find((device) => device.deviceId === savedTargetId);
      if (!target) return STATE.UNAVAILABLE;
      if (usableDevice(target)) return STATE.CONNECTED;
      if (target.revoked === true || target.expired === true) return STATE.UNAVAILABLE;
      return STATE.DISCONNECTED;
    }
    if (devices.some(usableDevice)) return STATE.CONNECTED;
    const needsAttention = devices.every((device) => (
      device.revoked === true || device.expired === true ||
      device.state === "ACTION_REQUIRED"
    ));
    return needsAttention ? STATE.UNAVAILABLE : STATE.DISCONNECTED;
  }

  function publish() {
    const snapshot = current();
    const state = classify(snapshot);
    const detail = {
      state: state,
      devices: snapshot && Array.isArray(snapshot.devices) ? snapshot.devices : [],
      readCompleted: Boolean(snapshot && snapshot.readCompleted === true),
      statusCode: snapshot && typeof snapshot.statusCode === "string"
        ? snapshot.statusCode
        : "",
    };
    window.PadiemComputerConnection = detail;
    if (typeof window.dispatchEvent === "function" && typeof CustomEvent === "function") {
      window.dispatchEvent(new CustomEvent(STATE_EVENT, { detail: detail }));
    }
    return detail;
  }

  /* Ask the EXISTING directory control to re-read the canonical endpoint.
     The directory module stays the only reader; this only triggers its own
     refresh control, so no second connection and no second authority. */
  function requestRead() {
    const refresh = document.querySelector(".claw-device-manager-refresh");
    if (refresh && typeof refresh.click === "function") {
      refresh.click();
      return true;
    }
    return false;
  }

  function install() {
    window.addEventListener(DIRECTORY_EVENT, () => { publish(); });
    for (const evt of ["padiem:auth-state", "padiem:auth-changed", "padiem:account-changed"]) {
      window.addEventListener(evt, () => { publish(); });
    }
    publish();
  }

  if (typeof window === "undefined" || typeof document === "undefined") return;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", install, { once: true });
  } else {
    install();
  }

  window.PadiemComputerConnectionState = Object.freeze({
    STATE: STATE,
    classify: classify,
    current: publish,
    requestRead: requestRead,
  });
})();
