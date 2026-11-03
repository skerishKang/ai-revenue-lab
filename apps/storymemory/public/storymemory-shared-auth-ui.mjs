export async function initializeStoryMemorySharedAuth({
  fetcher = fetch,
  location = globalThis.location,
  bridge = globalThis
} = {}) {
  if (typeof bridge.installStoryMemoryAuthBridge !== "function" || typeof bridge.setStoryMemoryAuthSession !== "function") return { configured: false, authenticated: false };

  let status = null;
  try {
    const response = await fetcher("/auth/status", {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      headers: { accept: "application/json" }
    });
    status = await response.json();
    if (!status || typeof status !== "object" || Array.isArray(status)) status = null;
    if (status && !response.ok) status.authenticated = false;
  } catch {
    status = null;
  }

  const configured = status?.configured === true;
  const authenticated = configured && status?.authenticated === true;
  bridge.installStoryMemoryAuthBridge({
    configured,
    authenticated,
    syncEnabled: false,
    openSignIn: async () => {
      if (!configured || !location || typeof location.assign !== "function") throw new Error("AUTH_NOT_CONFIGURED");
      location.assign("/auth/login?next=%2F");
    },
    signOut: async () => {
      const response = await fetcher("/auth/logout", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: { accept: "application/json" }
      });
      if (!response.ok) throw new Error("LOGOUT_FAILED");
      bridge.setStoryMemoryAuthSession({ authenticated: false });
    }
  });
  try {
    const currentUrl = new URL(location?.href || "https://storymemory-padiem.pages.dev/");
    if (currentUrl.searchParams.get("shared_login") === "failed") {
      bridge.showStoryMemoryAuthError?.();
      currentUrl.searchParams.delete("shared_login");
      globalThis.history?.replaceState?.(null, "", currentUrl.pathname + currentUrl.search + currentUrl.hash);
    }
  } catch { /* a URL parsing failure does not alter local reading data */ }
  return { configured, authenticated, syncEnabled: false };
}

if (typeof window !== "undefined" && typeof window.installStoryMemoryAuthBridge === "function") {
  void initializeStoryMemorySharedAuth({ bridge: window, location: window.location });
}
