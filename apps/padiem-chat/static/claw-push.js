/*
 * #5034 PADIEM Web Push opt-in client.
 *
 * This is the ONE reviewed browser file allowed to touch the service-worker
 * API (owner decision 2026-10-23). The allowance is narrow on purpose: one
 * file, one declared service-worker path, and a closed set of call shapes that
 * .github/scripts/b62_browser_persistence_audit.py verifies exactly.
 *
 * What this file does:
 *   - asks for notification permission only after a user action;
 *   - registers the push service worker and subscribes this device;
 *   - registers/unregisters the subscription on the existing server route;
 *   - cleans the subscription up on sign-out or account change.
 *
 * What this file never does:
 *   - it stores nothing in the browser (no local or session storage, no
 *     browser-side database, no cookie). The device subscription lives on the
 *     server, keyed by the signed-in account, exactly like the rest of the
 *     product's state;
 *   - it never treats a push permission as a substitute for the web inbox. The
 *     inbox keeps working when push is denied, unsupported or unconfigured.
 */

"use strict";

const PADIEM_PUSH_SW_PATH = "/push-sw.js";
const PADIEM_PUSH_CAPABILITY_PATH = "/api/claw/inbox/push/capability";
const PADIEM_PUSH_SUBSCRIPTION_PATH = "/api/claw/inbox/push/subscription";

const PUSH_STATE = {
  unsupported: "unsupported",
  denied: "denied",
  unconfigured: "unconfigured",
  off: "off",
  on: "on",
  error: "error"
};

function base64UrlToUint8Array(value) {
  const padding = "=".repeat((4 - (value.length % 4)) % 4);
  const normalized = (value + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(normalized);
  const output = new Uint8Array(raw.length);
  for (let index = 0; index < raw.length; index += 1) {
    output[index] = raw.charCodeAt(index);
  }
  return output;
}

function subscriptionKeys(subscription) {
  if (!subscription || !subscription.toJSON) {
    return null;
  }
  const json = subscription.toJSON();
  const keys = json && json.keys;
  if (!keys || !keys.p256dh || !keys.auth) {
    return null;
  }
  return { endpoint: json.endpoint, p256dh: keys.p256dh, auth: keys.auth };
}

async function readCapability() {
  try {
    const response = await fetch(PADIEM_PUSH_CAPABILITY_PATH, {
      method: "GET",
      credentials: "same-origin",
      headers: { Accept: "application/json" }
    });
    if (!response.ok) {
      return { enabled: false };
    }
    const body = await response.json();
    return body && body.ok === true ? body : { enabled: false };
  } catch (error) {
    return { enabled: false };
  }
}

async function registerSubscription(subscription, scope) {
  const keys = subscriptionKeys(subscription);
  if (!keys) {
    return false;
  }
  try {
    const response = await fetch(PADIEM_PUSH_SUBSCRIPTION_PATH, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        endpoint: keys.endpoint,
        keys: { p256dh: keys.p256dh, auth: keys.auth },
        scope: scope
      })
    });
    return response.ok;
  } catch (error) {
    return false;
  }
}

async function removeSubscription(subscriptionId) {
  try {
    const response = await fetch(PADIEM_PUSH_SUBSCRIPTION_PATH, {
      method: "DELETE",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ subscription_id: subscriptionId })
    });
    return response.ok;
  } catch (error) {
    return false;
  }
}

/**
 * Report the current push state without changing it.
 *
 * Used on load to render the toggle honestly: a browser that has never granted
 * permission, a deployment with no VAPID authority, and an unsupported browser
 * are three different answers.
 */
async function currentPushState() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    return PUSH_STATE.unsupported;
  }
  if (typeof Notification === "undefined") {
    return PUSH_STATE.unsupported;
  }
  if (Notification.permission === "denied") {
    return PUSH_STATE.denied;
  }
  const capability = await readCapability();
  if (!capability.enabled) {
    return PUSH_STATE.unconfigured;
  }
  try {
    const registration = await navigator.serviceWorker.getRegistration();
    if (!registration) {
      return PUSH_STATE.off;
    }
    const subscription = await registration.pushManager.getSubscription();
    return subscription ? PUSH_STATE.on : PUSH_STATE.off;
  } catch (error) {
    return PUSH_STATE.error;
  }
}

/**
 * Turn push on for this device. Must be called from a user gesture.
 *
 * Returns one of the PUSH_STATE values. A denial is a normal answer, not an
 * error: the web inbox stays the source of truth either way.
 */
async function enablePush() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    return PUSH_STATE.unsupported;
  }
  if (typeof Notification === "undefined") {
    return PUSH_STATE.unsupported;
  }
  const capability = await readCapability();
  if (!capability.enabled || !capability.public_key) {
    return PUSH_STATE.unconfigured;
  }
  let permission = Notification.permission;
  if (permission === "default") {
    permission = await Notification.requestPermission();
  }
  if (permission !== "granted") {
    return PUSH_STATE.denied;
  }
  try {
    const registration = await navigator.serviceWorker.register(PADIEM_PUSH_SW_PATH);
    await navigator.serviceWorker.ready;
    let subscription = await registration.pushManager.getSubscription();
    if (!subscription) {
      subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: base64UrlToUint8Array(capability.public_key)
      });
    }
    const scope = capability.scope || self.location.origin + "/";
    const saved = await registerSubscription(subscription, scope);
    return saved ? PUSH_STATE.on : PUSH_STATE.error;
  } catch (error) {
    return PUSH_STATE.error;
  }
}

/**
 * Turn push off for this device and drop the server row.
 *
 * The local subscription is removed first so this device stops receiving even
 * if the server call fails; the server row then expires on its own.
 */
async function disablePush() {
  if (!("serviceWorker" in navigator)) {
    return PUSH_STATE.unsupported;
  }
  try {
    const registration = await navigator.serviceWorker.getRegistration();
    if (!registration) {
      return PUSH_STATE.off;
    }
    const subscription = await registration.pushManager.getSubscription();
    if (!subscription) {
      return PUSH_STATE.off;
    }
    const keys = subscriptionKeys(subscription);
    if (keys) {
      /* The server id is the endpoint digest; the client never sees the endpoint. */
      const digest = await crypto.subtle.digest(
        "SHA-256",
        new TextEncoder().encode(keys.endpoint)
      );
      const hex = Array.from(new Uint8Array(digest))
        .map((byte) => byte.toString(16).padStart(2, "0"))
        .join("");
      await removeSubscription("push_" + hex.slice(0, 32));
    }
    await subscription.unsubscribe();
    return PUSH_STATE.off;
  } catch (error) {
    return PUSH_STATE.error;
  }
}

/**
 * Drop this device's subscription on sign-out or account change.
 *
 * Called by the product's existing sign-out path. It never throws: a failure
 * here must not block the sign-out itself.
 */
async function clearPushOnSignOut() {
  try {
    await disablePush();
  } catch (error) {
    /* sign-out must always proceed */
  }
}

if (typeof window !== "undefined") {
  window.PadiemPush = {
    STATE: PUSH_STATE,
    currentState: currentPushState,
    enable: enablePush,
    disable: disablePush,
    clearOnSignOut: clearPushOnSignOut
  };
}

/* ------------------------------------------------------------------ *
 * Inbox toggle wiring
 *
 * The toggle lives in the existing inbox header. It is only shown when the
 * deployment actually has push authority AND the browser supports it: a
 * toggle that could never deliver is worse than no toggle. When push is
 * denied or unsupported the web inbox stays exactly as it is.
 * ------------------------------------------------------------------ */

const PUSH_LABELS = {
  enable: "이 기기에서 알림 받기",
  disable: "이 기기 알림 끄기",
  on: "이 기기로 알림을 받습니다.",
  off: "이 기기 알림이 꺼져 있습니다.",
  denied: "브라우저에서 알림이 차단되었습니다. 사이트 설정에서 허용해 주세요.",
  unsupported: "이 브라우저는 백그라운드 알림을 지원하지 않습니다. 알림함은 그대로 사용할 수 있습니다.",
  unconfigured: "",
  error: "알림 설정을 변경하지 못했습니다. 알림함은 그대로 사용할 수 있습니다."
};

function renderPushToggle(state) {
  const setting = document.getElementById("clawPushSetting");
  const toggle = document.getElementById("clawPushToggle");
  const status = document.getElementById("clawPushStatus");
  if (!setting || !toggle || !status) {
    return;
  }
  if (state === PUSH_STATE.unconfigured) {
    /* No VAPID authority on this deployment: offer nothing. */
    setting.hidden = true;
    return;
  }
  setting.hidden = false;
  const isOn = state === PUSH_STATE.on;
  toggle.textContent = isOn ? PUSH_LABELS.disable : PUSH_LABELS.enable;
  toggle.setAttribute("aria-pressed", isOn ? "true" : "false");
  toggle.disabled = state === PUSH_STATE.unsupported;
  status.textContent = PUSH_LABELS[state] || "";
}

async function refreshPushToggle() {
  try {
    renderPushToggle(await currentPushState());
  } catch (error) {
    renderPushToggle(PUSH_STATE.error);
  }
}

function wirePushToggle() {
  const toggle = document.getElementById("clawPushToggle");
  if (!toggle || toggle.dataset.pushWired === "1") {
    return;
  }
  toggle.dataset.pushWired = "1";
  toggle.addEventListener("click", async () => {
    /* A user gesture is required for the permission prompt. */
    toggle.disabled = true;
    try {
      const current = await currentPushState();
      const next = current === PUSH_STATE.on ? await disablePush() : await enablePush();
      renderPushToggle(next);
    } catch (error) {
      renderPushToggle(PUSH_STATE.error);
    } finally {
      toggle.disabled = false;
    }
  });
  refreshPushToggle();
}

if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wirePushToggle);
  } else {
    wirePushToggle();
  }
}
