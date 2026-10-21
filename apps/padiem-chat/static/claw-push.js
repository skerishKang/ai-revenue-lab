/* #5034 — opt-in Web Push for the existing PADIEM user web-alert inbox.
 *
 * This module never owns a notification. The web inbox
 * (/api/claw/inbox/{tasks,alerts}) stays the source of truth; push is an
 * additional way to learn that something already happened.
 *
 * Contract:
 * - the user opts in explicitly; a denied or unsupported permission is a
 *   bounded state, never an error thrown into the inbox flow;
 * - with no push authority configured on the server the honest state is
 *   "not_configured" and the web inbox is untouched;
 * - the endpoint and the browser keys are sent to the server once and never
 *   read back;
 * - unsubscribing removes the server-side subscription as well.
 */
(function (global) {
  "use strict";

  var CAPABILITY_PATH = "/api/claw/inbox/push/capability";
  var SUBSCRIPTION_PATH = "/api/claw/inbox/push/subscription";
  var SERVICE_WORKER_PATH = "/claw-push-sw.js";

  var STATE = {
    UNSUPPORTED: "unsupported",
    DENIED: "denied",
    NOT_CONFIGURED: "not_configured",
    READY: "ready",
    FAILED: "failed",
  };

  function stateOf() {
    return {
      // A browser without the APIs is unsupported, not broken. The check is
      // value based: a browser may expose the name and still not the API.
      supported: typeof global.navigator !== "undefined"
        && !!global.navigator.serviceWorker
        && !!global.navigator.PushManager,
      permission: "default",
      state: STATE.UNSUPPORTED,
    };
  }

  function currentState() {
    var state = stateOf();
    if (!state.supported) return state;
    if (global.navigator.permissions
      && typeof global.navigator.permissions.query === "function") {
      // The permission state is read where the browser exposes it; the
      // caller never blocks on it.
      try {
        state.permission = String(global.navigator.permission || "default");
      } catch (_) {
        state.permission = "default";
      }
    }
    return state;
  }

  function fetchJson(url, options) {
    return global.fetch(url, Object.assign({
      headers: { "Accept": "application/json" },
      cache: "no-store",
      credentials: "same-origin",
    }, options || {}));
  }

  function registerServiceWorker() {
    if (!("serviceWorker" in global.navigator)) {
      return Promise.reject(new Error("unsupported"));
    }
    return global.navigator.serviceWorker
      .register(SERVICE_WORKER_PATH, { scope: "/" })
      .then(function (registration) {
        return global.navigator.serviceWorker.ready.then(function () {
          return registration;
        });
      });
  }

  function toBase64(buffer) {
    var bytes = new Uint8Array(buffer);
    var binary = "";
    for (var i = 0; i < bytes.byteLength; i += 1) {
      binary += String.fromCharCode(bytes[i]);
    }
    return global.btoa(binary);
  }

  function urlBase64ToUint8Array(value) {
    var padding = "=".repeat((4 - (value.length % 4)) % 4);
    var base64 = (value + padding).replace(/-/g, "+").replace(/_/g, "/");
    var raw = global.atob(base64);
    var output = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i += 1) {
      output[i] = raw.charCodeAt(i);
    }
    return output;
  }

  function subscribe(publicKey) {
    return global.navigator.serviceWorker.ready
      .then(function (registration) {
        return registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(publicKey),
        });
      });
  }

  function subscriptionPayload(subscription, scope) {
    var json = subscription.toJSON ? subscription.toJSON() : {};
    return {
      endpoint: json.endpoint,
      keys: {
        p256dh: json.keys ? json.keys.p256dh : "",
        auth: json.keys ? json.keys.auth : "",
      },
      scope: scope,
    };
  }

  /* Opt in. Resolves with a bounded state; it never rejects, so a caller in
   * the inbox flow cannot be broken by a denied or missing push. */
  function enable() {
    if (!stateOf().supported) {
      return Promise.resolve({ ok: true, state: STATE.UNSUPPORTED });
    }
    return global.navigator.permissions
      .request({ userVisibleOnly: true })
      .then(function (permission) {
        if (permission !== "granted") {
          return { ok: true, state: STATE.DENIED };
        }
        return fetchJson(CAPABILITY_PATH)
          .then(function (response) { return response.json(); })
          .then(function (capability) {
            if (!capability || capability.ok !== true || !capability.enabled
              || !capability.public_key) {
              return { ok: true, state: STATE.NOT_CONFIGURED };
            }
            return registerServiceWorker()
              .then(function () { return subscribe(capability.public_key); })
              .then(function (subscription) {
                return fetchJson(SUBSCRIPTION_PATH, {
                  method: "POST",
                  headers: {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                  },
                  body: JSON.stringify(
                    subscriptionPayload(subscription, capability.scope)
                  ),
                });
              })
              .then(function (response) { return response.json(); })
              .then(function (body) {
                if (!body || body.ok !== true) {
                  return { ok: true, state: STATE.FAILED };
                }
                return { ok: true, state: STATE.READY };
              });
          });
      })
      .catch(function () {
        return { ok: true, state: STATE.FAILED };
      });
  }

  /* Opt out. The server-side subscription is removed as well. */
  function disable(subscriptionId) {
    var target = subscriptionId
      || (global.PadiemClawPush && global.PadiemClawPush.subscriptionId);
    var removal = target
      ? fetchJson(SUBSCRIPTION_PATH, {
        method: "DELETE",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json",
        },
        body: JSON.stringify({ subscription_id: target }),
      }).catch(function () { return null; })
      : Promise.resolve(null);
    return removal
      .then(function () {
        if (!("serviceWorker" in global.navigator)) {
          return { ok: true, state: STATE.UNSUPPORTED };
        }
        return global.navigator.serviceWorker.ready
          .then(function (registration) {
            return registration.pushManager
              .getSubscription()
              .then(function (subscription) {
                if (!subscription) return null;
                return subscription.unsubscribe();
              });
          })
          .then(function () { return { ok: true, state: STATE.DENIED }; })
          .catch(function () { return { ok: true, state: STATE.FAILED }; });
      });
  }

  global.PadiemClawPush = {
    STATE: STATE,
    capability: function () {
      return fetchJson(CAPABILITY_PATH)
        .then(function (response) { return response.json(); })
        .catch(function () {
          return { ok: false, enabled: false, public_key: null };
        });
    },
    currentState: currentState,
    enable: enable,
    disable: disable,
    subscriptionId: null,
  };
})(typeof window !== "undefined" ? window : this);
