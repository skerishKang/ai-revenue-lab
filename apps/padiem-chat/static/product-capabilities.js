(() => {
  "use strict";

  const nativeFetch = window.fetch.bind(window);
  const sidebarSearchButton = document.getElementById("sidebarSearchButton");
  const webSearchButton = document.getElementById("webSearchButton");
  const webSearchStarter = document.getElementById("webSearchStarterButton");
  const deepResearchButton = document.getElementById("deepResearchButton");
  const loginButton = document.getElementById("loginButton");
  const projectsNavButton = document.getElementById("projectsNavButton");
  const messageInput = document.getElementById("messageInput");
  const mobileClose = document.getElementById("mobileClose");

  const EMPTY_DEPLOYMENT = Object.freeze({
    loaded: false,
    webSearch: false,
    deepResearch: false,
    auth: false,
    projects: false,
    projectFiles: false,
    savedOutputs: false,
  });
  const EMPTY_AUTH = Object.freeze({
    loaded: false,
    ready: false,
    authenticated: false,
    historyReady: false,
    projectFilesReady: false,
  });

  let deployment = EMPTY_DEPLOYMENT;
  let auth = EMPTY_AUTH;
  let authRefreshQueued = false;

  function bool(value) {
    return value === true;
  }

  function projectDeployment(data) {
    if (!data || typeof data !== "object" || Array.isArray(data)) return EMPTY_DEPLOYMENT;
    const authConfigured = bool(data.auth_configured);
    const historyBound = bool(data.history_store_bound);
    return Object.freeze({
      loaded: true,
      webSearch: bool(data.web_tools_ready),
      deepResearch: bool(data.deep_research_ready),
      auth: authConfigured && historyBound,
      projects: authConfigured && historyBound && bool(data.projects_code_ready),
      projectFiles: authConfigured && historyBound && bool(data.project_files_code_ready) && bool(data.project_file_store_bound),
      savedOutputs: authConfigured && historyBound && bool(data.saved_outputs_code_ready) && bool(data.saved_output_store_bound),
    });
  }

  function projectAuth(data) {
    if (!data || typeof data !== "object" || Array.isArray(data)) return EMPTY_AUTH;
    return Object.freeze({
      loaded: true,
      ready: bool(data.ready),
      authenticated: bool(data.authenticated),
      historyReady: bool(data.history_ready),
      projectFilesReady: bool(data.project_files_ready),
    });
  }

  function publicState() {
    return Object.freeze({
      deployment,
      auth,
    });
  }

  function dispatch() {
    window.dispatchEvent(new CustomEvent("padiem:capabilitychange", { detail: publicState() }));
  }

  function setHidden(element, hidden) {
    if (element) element.hidden = Boolean(hidden);
  }

  function syncSidebarSearch() {
    if (!sidebarSearchButton || !webSearchButton) return;
    const available = deployment.loaded && deployment.webSearch;
    sidebarSearchButton.hidden = !available;
    if (!available) {
      sidebarSearchButton.disabled = true;
      sidebarSearchButton.setAttribute("aria-disabled", "true");
      sidebarSearchButton.setAttribute("aria-pressed", "false");
      sidebarSearchButton.classList.remove("is-active");
      return;
    }
    const busy = webSearchButton.disabled;
    sidebarSearchButton.disabled = busy;
    sidebarSearchButton.setAttribute("aria-disabled", busy ? "true" : "false");
    const pressed = webSearchButton.getAttribute("aria-pressed") === "true";
    sidebarSearchButton.setAttribute("aria-pressed", pressed ? "true" : "false");
    sidebarSearchButton.classList.toggle("is-active", pressed);
  }

  function syncDeploymentVisibility() {
    const webAvailable = deployment.loaded && deployment.webSearch;
    const researchAvailable = deployment.loaded && deployment.deepResearch;
    setHidden(webSearchButton, !webAvailable);
    setHidden(webSearchStarter, !webAvailable);
    setHidden(deepResearchButton, !researchAvailable);
    syncSidebarSearch();
  }

  function syncAccountVisibility() {
    const authAvailable = deployment.loaded && deployment.auth && auth.loaded && auth.ready;
    const projectsAvailable = deployment.loaded
      && deployment.projects
      && authAvailable
      && auth.authenticated
      && auth.historyReady;
    setHidden(loginButton, !authAvailable);
    setHidden(projectsNavButton, !projectsAvailable);
  }

  function syncAll() {
    syncDeploymentVisibility();
    syncAccountVisibility();
    dispatch();
  }

  async function refreshDeployment() {
    try {
      const response = await nativeFetch("/health", {
        headers: { "Accept": "application/json" },
        cache: "no-store",
      });
      const data = await response.json().catch(() => null);
      deployment = response.ok ? projectDeployment(data) : EMPTY_DEPLOYMENT;
    } catch (_) {
      deployment = EMPTY_DEPLOYMENT;
    }
    syncAll();
    return deployment;
  }

  async function refreshAuth() {
    try {
      const response = await nativeFetch("/api/auth/status", {
        headers: { "Accept": "application/json" },
        cache: "no-store",
      });
      const data = await response.json().catch(() => null);
      auth = response.ok ? projectAuth(data) : EMPTY_AUTH;
    } catch (_) {
      auth = EMPTY_AUTH;
    }
    syncAll();
    return auth;
  }

  function queueAuthRefresh() {
    if (authRefreshQueued) return;
    authRefreshQueued = true;
    window.setTimeout(() => {
      authRefreshQueued = false;
      refreshAuth();
    }, 0);
  }

  if (webSearchButton && sidebarSearchButton) {
    const webStateObserver = new MutationObserver(syncSidebarSearch);
    webStateObserver.observe(webSearchButton, {
      attributes: true,
      attributeFilter: ["disabled", "aria-pressed", "hidden"],
    });
    sidebarSearchButton.addEventListener("click", () => {
      if (sidebarSearchButton.disabled || webSearchButton.hidden) return;
      webSearchButton.click();
      if (messageInput) messageInput.focus();
      if (mobileClose) mobileClose.click();
    });
  }

  if (loginButton) {
    const authUiObserver = new MutationObserver(queueAuthRefresh);
    authUiObserver.observe(loginButton, { childList: true, subtree: true });
  }

  window.addEventListener("pageshow", () => {
    refreshDeployment();
    refreshAuth();
  });
  window.addEventListener("focus", queueAuthRefresh);

  window.PadiemProductCapabilities = Object.freeze({
    get: publicState,
    refresh: async () => {
      await Promise.all([refreshDeployment(), refreshAuth()]);
      return publicState();
    },
  });

  syncAll();
  Promise.all([refreshDeployment(), refreshAuth()]);
})();
