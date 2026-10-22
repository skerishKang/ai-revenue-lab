/*
 * #5034 PADIEM Web Push service worker.
 *
 * SCOPE: receive a push and show a notification. Nothing else.
 *
 * This worker deliberately holds NO user state. It has no cache, no browser
 * storage of any kind, no cookie access and no fetch handler that could persist
 * a response. The browser-persistence privacy gate
 * (.github/scripts/b62_browser_persistence_audit.py) still scans this file and
 * still forbids every one of those primitives here.
 *
 * The push payload is the minimum the lock screen may show: a short status and
 * a result link. The server never puts document content, ERP data or a secret
 * in it, and this worker never reads anything else.
 *
 * A push that cannot be parsed still produces a bounded generic notification,
 * so a malformed payload never becomes a silent drop.
 */

"use strict";

var DEFAULT_TITLE = "Padiem";
var DEFAULT_BODY = "작업이 완료되었습니다.";
var DEFAULT_TAG = "padiem-task";

function readPayload(event) {
  if (!event.data) {
    return {};
  }
  try {
    var parsed = event.data.json();
    if (parsed && typeof parsed === "object") {
      return parsed;
    }
  } catch (error) {
    /* fall through to the bounded default below */
  }
  return {};
}

function boundedText(value, fallback, limit) {
  if (typeof value !== "string") {
    return fallback;
  }
  var text = value.trim();
  if (!text) {
    return fallback;
  }
  return text.length > limit ? text.slice(0, limit) : text;
}

function safeUrl(value) {
  if (typeof value !== "string" || !value) {
    return "/";
  }
  /* Same-origin relative paths only: a push never redirects the user off-site. */
  if (value.charAt(0) !== "/" || value.charAt(1) === "/") {
    return "/";
  }
  return value;
}

self.addEventListener("push", function (event) {
  var payload = readPayload(event);
  var title = boundedText(payload.title, DEFAULT_TITLE, 120);
  var body = boundedText(payload.body, DEFAULT_BODY, 200);
  var tag = boundedText(payload.tag, DEFAULT_TAG, 64);
  var target = safeUrl(payload.url);

  event.waitUntil(
    self.registration.showNotification(title, {
      body: body,
      tag: tag,
      /* One task, one notification: a re-sent push replaces, never stacks. */
      renotify: false,
      data: { url: target },
      badge: "/favicon.ico",
      icon: "/favicon.ico"
    })
  );
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  var target = safeUrl(event.notification.data && event.notification.data.url);

  event.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then(function (clientList) {
        for (var index = 0; index < clientList.length; index += 1) {
          var client = clientList[index];
          if (client.url && new URL(client.url).origin === self.location.origin) {
            /* Reuse the open PADIEM tab instead of opening a second one. */
            return client.focus().then(function (focused) {
              if (focused && typeof focused.navigate === "function") {
                return focused.navigate(target);
              }
              return focused;
            });
          }
        }
        if (self.clients.openWindow) {
          return self.clients.openWindow(target);
        }
        return undefined;
      })
  );
});

/*
 * A subscription the browser has already dropped must not keep receiving
 * attempts. This worker cannot delete the server row (it has no session), so it
 * only stops the local subscription; the client re-syncs on next load.
 */
self.addEventListener("pushsubscriptionchange", function (event) {
  event.waitUntil(
    self.registration.pushManager
      .getSubscription()
      .then(function (subscription) {
        if (subscription) {
          return subscription.unsubscribe();
        }
        return undefined;
      })
      .catch(function () {
        return undefined;
      })
  );
});
