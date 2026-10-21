/* #5034 — the receiving end of an opted-in browser push.
 *
 * The service worker only *shows* what the web inbox already persisted. It
 * never owns a notification, never fetches on its own, and never talks to the
 * B14 or the product API. A push that arrives opens the inbox, which remains
 * the authoritative place where the record and its read state live.
 */
self.addEventListener("install", function (event) {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", function (event) {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", function (event) {
  var payload = { title: "PADIEM", body: "새로운 알림이 있습니다." };
  if (event.data) {
    try {
      var parsed = event.data.json();
      if (parsed && typeof parsed.title === "string") payload.title = parsed.title;
      if (parsed && typeof parsed.body === "string") payload.body = parsed.body;
      if (parsed && typeof parsed.url === "string") payload.url = parsed.url;
    } catch (_) {
      // A non-JSON payload keeps the bounded default copy.
    }
  }
  event.waitUntil(self.registration.showNotification(payload.title, {
    body: payload.body,
    icon: "/favicon.ico",
    badge: "/favicon.ico",
    tag: payload.url || "padiem-inbox",
    data: { url: payload.url || "/?inbox=1" },
  }));
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  var target = (event.notification.data && event.notification.data.url) || "/?inbox=1";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (windows) {
      for (var i = 0; i < windows.length; i += 1) {
        if ("focus" in windows[i]) {
          windows[i].navigate(target);
          return windows[i].focus();
        }
      }
      return self.clients.openWindow(target);
    })
  );
});
