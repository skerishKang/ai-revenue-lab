(() => {
  "use strict";
  // In-memory presentation state only; never a credential or access authority.
  let session = null;
  const text = (value, limit) => typeof value === "string" ? value.trim().slice(0, limit) : "";

  function update(status, generation) {
    const data = status && typeof status === "object" ? status : {};
    const authenticated = data.ready === true && data.authenticated === true;
    const user = authenticated && data.user && typeof data.user === "object" ? data.user : {};
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

  window.PadiemAuthSession = Object.freeze({ get: () => session, update });
})();
