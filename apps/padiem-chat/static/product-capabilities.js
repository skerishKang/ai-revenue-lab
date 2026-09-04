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
  const modePill = document.querySelector(".model-pill");

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

  const MODE_PRESENTATION = Object.freeze({
    selected: "auto",
    available: Object.freeze(["auto"]),
    previewOnly: Object.freeze(["fast", "balanced", "deep"]),
  });

  const MODE_COPY = Object.freeze({
    ko: Object.freeze({
      label: "대화 모드",
      title: "대화 모드",
      description: "현재 실제 실행은 Auto만 연결되어 있습니다.",
      truth: "Fast · Balanced · Deep은 UI 준비 상태이며 실제 모델 연결 전까지 선택할 수 없습니다.",
      available: "사용 가능",
      preview: "준비 중",
      auto: ["Auto", "질문에 맞는 기본 실행 경로"],
      fast: ["Fast", "빠른 응답을 위한 모드"],
      balanced: ["Balanced", "속도와 품질의 균형 모드"],
      deep: ["Deep", "더 깊은 작업을 위한 모드"],
    }),
    en: Object.freeze({
      label: "Chat mode",
      title: "Chat mode",
      description: "Only Auto is connected to live execution right now.",
      truth: "Fast, Balanced, and Deep are UI-ready but cannot be selected until trusted backend mappings are active.",
      available: "Available",
      preview: "Coming soon",
      auto: ["Auto", "Default execution path for your request"],
      fast: ["Fast", "Mode for quicker responses"],
      balanced: ["Balanced", "Mode balancing speed and quality"],
      deep: ["Deep", "Mode for deeper work"],
    }),
  });

  let deployment = EMPTY_DEPLOYMENT;
  let auth = EMPTY_AUTH;
  let authRefreshQueued = false;
  let modePanel = null;

  function bool(value) {
    return value === true;
  }

  function projectDeployment(data) {
    if (!data || typeof data !== "object" || Array.isArray(data)) return EMPTY_DEPLOYMENT;
    return Object.freeze({
      loaded: true,
      webSearch: bool(data.web_tools_ready),
      deepResearch: bool(data.deep_research_ready),
      auth: bool(data.auth_configured) && bool(data.history_store_bound),
      projects: bool(data.projects_code_ready),
      projectFiles: bool(data.project_files_code_ready) && bool(data.project_file_store_bound),
      savedOutputs: bool(data.saved_outputs_code_ready) && bool(data.saved_output_store_bound),
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
    const authAvailable = auth.loaded && auth.ready;
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

  function currentModeCopy() {
    return MODE_COPY[document.documentElement.lang === "en" ? "en" : "ko"];
  }

  function ensureModeStyles() {
    if (document.querySelector('link[data-b62-mode-styles="true"]')) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "./mode-presentation.css";
    link.dataset.b62ModeStyles = "true";
    document.head.appendChild(link);
  }

  function createModeOption(mode, enabled) {
    const copy = currentModeCopy();
    const button = document.createElement("button");
    button.type = "button";
    button.className = "mode-option";
    button.dataset.modeValue = mode;
    button.disabled = !enabled;
    button.setAttribute("aria-disabled", enabled ? "false" : "true");
    button.setAttribute("aria-pressed", mode === MODE_PRESENTATION.selected ? "true" : "false");

    const text = document.createElement("span");
    const title = document.createElement("strong");
    const detail = document.createElement("small");
    title.textContent = copy[mode][0];
    detail.textContent = copy[mode][1];
    text.append(title, detail);

    const state = document.createElement("span");
    state.className = "mode-option-state";
    state.textContent = enabled ? copy.available : copy.preview;
    button.append(text, state);
    return button;
  }

  function syncModeCopy() {
    if (!modePill || !modePanel) return;
    const copy = currentModeCopy();
    const label = modePill.querySelector("span:last-child");
    if (label) label.textContent = copy.auto[0];
    modePill.setAttribute("aria-label", `${copy.label}: ${copy.auto[0]}`);
    const title = modePanel.querySelector("[data-mode-title]");
    const description = modePanel.querySelector("[data-mode-description]");
    const truth = modePanel.querySelector("[data-mode-truth]");
    if (title) title.textContent = copy.title;
    if (description) description.textContent = copy.description;
    if (truth) truth.textContent = copy.truth;
    modePanel.querySelectorAll("[data-mode-value]").forEach((button) => {
      const mode = button.dataset.modeValue;
      if (!copy[mode]) return;
      const optionTitle = button.querySelector("strong");
      const optionDetail = button.querySelector("small");
      const state = button.querySelector(".mode-option-state");
      if (optionTitle) optionTitle.textContent = copy[mode][0];
      if (optionDetail) optionDetail.textContent = copy[mode][1];
      if (state) state.textContent = button.disabled ? copy.preview : copy.available;
    });
  }

  function closeModePanel({ restoreFocus = false } = {}) {
    if (!modePill || !modePanel || modePanel.hidden) return;
    modePanel.hidden = true;
    modePill.setAttribute("aria-expanded", "false");
    if (restoreFocus) modePill.focus();
  }

  function openModePanel() {
    if (!modePill || !modePanel) return;
    modePanel.hidden = false;
    modePill.setAttribute("aria-expanded", "true");
    const active = modePanel.querySelector('[data-mode-value="auto"]');
    if (active) active.focus();
  }

  function toggleModePanel() {
    if (!modePanel || modePanel.hidden) openModePanel(); else closeModePanel({ restoreFocus: true });
  }

  function installModePresentation() {
    if (!modePill || modePill.dataset.modeControl === "true") return;
    ensureModeStyles();
    modePill.dataset.modeControl = "true";
    modePill.setAttribute("role", "button");
    modePill.setAttribute("tabindex", "0");
    modePill.setAttribute("aria-haspopup", "dialog");
    modePill.setAttribute("aria-expanded", "false");

    modePanel = document.createElement("section");
    modePanel.className = "mode-presentation-panel";
    modePanel.id = "modePresentationPanel";
    modePanel.hidden = true;
    modePanel.setAttribute("role", "dialog");
    modePanel.setAttribute("aria-modal", "false");
    modePanel.setAttribute("aria-labelledby", "modePresentationTitle");

    const header = document.createElement("div");
    header.className = "mode-presentation-header";
    const title = document.createElement("strong");
    title.id = "modePresentationTitle";
    title.dataset.modeTitle = "true";
    const description = document.createElement("small");
    description.dataset.modeDescription = "true";
    header.append(title, description);

    const list = document.createElement("div");
    list.className = "mode-option-list";
    list.setAttribute("role", "group");
    list.append(
      createModeOption("auto", true),
      createModeOption("fast", false),
      createModeOption("balanced", false),
      createModeOption("deep", false),
    );

    const truth = document.createElement("p");
    truth.className = "mode-presentation-truth";
    truth.dataset.modeTruth = "true";
    modePanel.append(header, list, truth);
    document.body.appendChild(modePanel);
    syncModeCopy();

    modePill.addEventListener("click", toggleModePanel);
    modePill.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        toggleModePanel();
      }
      if (event.key === "Escape") closeModePanel({ restoreFocus: true });
    });
    modePanel.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeModePanel({ restoreFocus: true });
      }
    });
    document.addEventListener("pointerdown", (event) => {
      if (!modePanel || modePanel.hidden) return;
      if (modePanel.contains(event.target) || modePill.contains(event.target)) return;
      closeModePanel();
    });
    window.addEventListener("padiem:localechange", syncModeCopy);
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
  window.PadiemModePresentation = Object.freeze({
    get: () => MODE_PRESENTATION,
    open: openModePanel,
    close: () => closeModePanel({ restoreFocus: true }),
  });

  installModePresentation();
  syncAll();
  Promise.all([refreshDeployment(), refreshAuth()]);
})();
