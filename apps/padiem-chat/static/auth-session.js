(() => {
  "use strict";
  // In-memory presentation state only; never a credential or access authority.
  let session = null;
  // #7459: the only value kept between loads is "was this browser signed in a
  // moment ago". It is a boolean hint for the first paint, never identity:
  // no name, email, id or token is written here.
  const LAST_SIGNED_IN_KEY = "padiem.chat.auth.lastSignedIn";
  const text = (value, limit) => typeof value === "string" ? value.trim().slice(0, limit) : "";

  function lastKnownAuthenticated() {
    try {
      return window.localStorage.getItem(LAST_SIGNED_IN_KEY) === "1";
    } catch (_) {
      return false;
    }
  }

  function rememberSignedIn(authenticated) {
    try {
      if (authenticated) window.localStorage.setItem(LAST_SIGNED_IN_KEY, "1");
      else window.localStorage.removeItem(LAST_SIGNED_IN_KEY);
    } catch (_) {
      // Storage can be unavailable (private mode, quota, disabled). The screen
      // still works; it just loses the first-paint hint.
    }
  }

  // Before the auth status answers, reserve the layout the previous visit used
  // so a signed-in browser does not first paint a guest sign-in shape. The
  // avatar/name stay neutral (empty): only the space is claimed.
  function applyPendingHint() {
    if (typeof document === "undefined" || typeof document.querySelector !== "function") return;
    const container = document.querySelector(".sidebar-account");
    if (!container) return;
    const signedInHint = lastKnownAuthenticated();
    container.dataset.accountHint = signedInHint ? "signed_in" : "";
    if (!signedInHint) return;
    const avatar = document.getElementById("accountAvatar");
    const pendingLogin = document.getElementById("loginPending");
    if (avatar) avatar.hidden = false;
    if (pendingLogin) pendingLogin.hidden = true;
  }

  function update(status, generation) {
    const data = status && typeof status === "object" ? status : {};
    const authenticated = data.ready === true && data.authenticated === true;
    const user = authenticated && data.user && typeof data.user === "object" ? data.user : {};
    // Only a confirmed answer changes the hint. A failed/unknown read leaves
    // the previous visit's hint alone so the retry keeps the same shape.
    if (data.ready === true) rememberSignedIn(authenticated);
    const next = Object.freeze({
      authenticated,
      ownerKey: text(user.email, 160),
      storage: data.project_files_ready === true,
      displayName: text(user.name, 80),
    });
    if (session && Object.keys(next).every((key) => session[key] === next[key])) return session;
    session = next;
    window.dispatchEvent(new CustomEvent("padiem:auth-state", {
      detail: Object.freeze({ authenticated, generation }),
    }));
    return session;
  }

  applyPendingHint();
  window.PadiemAuthSession = Object.freeze({
    get: () => session,
    update,
    lastKnownAuthenticated,
  });
})();
