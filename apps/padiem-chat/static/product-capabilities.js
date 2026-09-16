(() => {
  "use strict";

  const nativeFetch = window.fetch.bind(window);
  const sidebarSearchButton = document.getElementById("sidebarSearchButton");
  const webSearchButton = document.getElementById("webSearchButton");
  const webSearchStarter = document.getElementById("webSearchStarterButton");
  const deepResearchButton = document.getElementById("deepResearchButton");
  const loginButton = document.getElementById("loginButton");
  const accountName = document.getElementById("accountName");
  const accountContainer = document.querySelector(".sidebar-account");
  const projectsNavButton = document.getElementById("projectsNavButton");
  const messageInput = document.getElementById("messageInput");
  const mobileClose = document.getElementById("mobileClose");
  const modePill = document.querySelector(".model-pill");
  const modeHost = document.querySelector(".composer-tools");

  const SESSION_STATES = new Set(["unavailable", "guest", "signed_in", "expired"]);
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
    sessionState: "unavailable",
    displayName: "",
  });

  const AVAILABLE_TIERS = Object.freeze(["plus", "pro"]);

  const TIER_COPY = Object.freeze({
    ko: Object.freeze({
      label: "AI 등급",
      title: "Padiem AI",
      description: "Chat과 Claw에서 함께 사용할 AI 등급을 선택합니다.",
      truth: "모델·제공자 선택은 파디엠 서버가 관리하며 브라우저에는 노출하지 않습니다.",
      available: "사용 가능",
      plus: ["Padiem Plus", "일상 대화와 일반 작업"],
      pro: ["Padiem Pro", "더 복잡한 대화와 업무"],
    }),
    en: Object.freeze({
      label: "AI tier",
      title: "Padiem AI",
      description: "Choose the AI tier shared by Chat and Claw.",
      truth: "Provider and model routing stays server-managed and is not browser-selectable.",
      available: "Available",
      plus: ["Padiem Plus", "Everyday chat and general tasks"],
      pro: ["Padiem Pro", "More complex chat and work"],
    }),
  });

  let selectedTier = "pro";

  const ACCOUNT_COPY = Object.freeze({
    ko: Object.freeze({
      guest: "게스트",
      signedIn: "로그인됨",
      expired: "세션 만료",
      login: "로그인",
      logout: "로그아웃",
      signInAgain: "다시 로그인",
      loginTitle: "Google 계정으로 로그인합니다",
      logoutTitle: "현재 계정에서 로그아웃합니다",
      expiredTitle: "세션이 만료되었습니다. 다시 로그인합니다",
    }),
    en: Object.freeze({
      guest: "Guest",
      signedIn: "Signed in",
      expired: "Session expired",
      login: "Sign in",
      logout: "Sign out",
      signInAgain: "Sign in again",
      loginTitle: "Sign in with your Google account",
      logoutTitle: "Sign out of the current account",
      expiredTitle: "Your session expired. Sign in again",
    }),
  });

  let deployment = EMPTY_DEPLOYMENT;
  let auth = EMPTY_AUTH;
  let authRefreshQueued = false;
  let authRefreshTail = Promise.resolve();
  let modePanel = null;
  let accountAvatar = null;

  function bool(value) {
    return value === true;
  }

  function text(value, max = 80) {
    return typeof value === "string" ? value.trim().slice(0, max) : "";
  }

  function setText(element, value) {
    if (element && element.textContent !== value) element.textContent = value;
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
    const ready = bool(data.ready);
    const authenticated = ready && bool(data.authenticated);
    let sessionState = SESSION_STATES.has(data.session_state) ? data.session_state : "guest";
    if (!ready) sessionState = "unavailable";
    else if (authenticated) sessionState = "signed_in";
    else if (sessionState === "signed_in") sessionState = "guest";
    const displayName = authenticated && data.user && typeof data.user === "object"
      ? text(data.user.name)
      : "";
    return Object.freeze({
      loaded: true,
      ready,
      authenticated,
      historyReady: bool(data.history_ready),
      projectFilesReady: bool(data.project_files_ready),
      sessionState,
      displayName,
    });
  }

  function publicState() {
    return Object.freeze({ deployment, auth });
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

  function currentAccountCopy() {
    return ACCOUNT_COPY[document.documentElement.lang === "en" ? "en" : "ko"];
  }

  function expectedAccountActionText() {
    const copy = currentAccountCopy();
    if (auth.sessionState === "signed_in") return copy.logout;
    if (auth.sessionState === "expired") return copy.signInAgain;
    return copy.login;
  }

  function expectedAccountNameText() {
    const copy = currentAccountCopy();
    if (auth.sessionState === "signed_in") return auth.displayName || copy.signedIn;
    if (auth.sessionState === "expired") return copy.expired;
    if (auth.sessionState === "guest") return copy.guest;
    return "";
  }

  function ensureAccountAvatar() {
    if (!accountContainer || accountAvatar) return accountAvatar;
    accountAvatar = document.createElement("span");
    accountAvatar.className = "account-avatar";
    accountAvatar.setAttribute("aria-hidden", "true");
    if (accountName) accountContainer.insertBefore(accountAvatar, accountName);
    else accountContainer.prepend(accountAvatar);
    return accountAvatar;
  }

  function syncAccountPresentation() {
    if (!loginButton || !accountContainer) return;
    const copy = currentAccountCopy();
    const state = auth.loaded ? auth.sessionState : "unavailable";
    const available = auth.loaded && auth.ready && state !== "unavailable";
    accountContainer.dataset.accountState = state;
    accountContainer.hidden = !available;
    loginButton.hidden = !available;
    loginButton.removeAttribute("aria-busy");
    loginButton.disabled = !available;
    loginButton.setAttribute("aria-disabled", available ? "false" : "true");

    if (!available) {
      if (accountName) {
        accountName.hidden = true;
        setText(accountName, "");
      }
      if (accountAvatar) accountAvatar.hidden = true;
      return;
    }

    const avatar = ensureAccountAvatar();
    avatar.hidden = false;
    if (state === "signed_in") {
      const visibleName = auth.displayName || copy.signedIn;
      setText(accountName, visibleName);
      accountName.hidden = false;
      setText(avatar, visibleName.charAt(0).toUpperCase() || "P");
      setText(loginButton, copy.logout);
      loginButton.title = copy.logoutTitle;
      return;
    }
    if (state === "expired") {
      setText(accountName, copy.expired);
      accountName.hidden = false;
      setText(avatar, "!");
      setText(loginButton, copy.signInAgain);
      loginButton.title = copy.expiredTitle;
      return;
    }
    setText(accountName, copy.guest);
    accountName.hidden = false;
    setText(avatar, document.documentElement.lang === "en" ? "G" : "게");
    setText(loginButton, copy.login);
    loginButton.title = copy.loginTitle;
  }

  function accountPresentationMatchesTrustedState() {
    if (!loginButton || !accountContainer) return true;
    const state = auth.loaded ? auth.sessionState : "unavailable";
    const available = auth.loaded && auth.ready && state !== "unavailable";
    if (accountContainer.hidden !== !available || loginButton.hidden !== !available) return false;
    if (!available) {
      if (!accountName) return true;
      return accountName.hidden && accountName.textContent.trim() === "";
    }
    if (loginButton.textContent.trim() !== expectedAccountActionText()) return false;
    if (accountContainer.dataset.accountState !== state) return false;
    if (accountName && (accountName.hidden || accountName.textContent.trim() !== expectedAccountNameText())) return false;
    return true;
  }

  function syncAccountVisibility() {
    const authAvailable = auth.loaded && auth.ready && auth.sessionState !== "unavailable";
    const projectsAvailable = deployment.loaded
      && deployment.projects
      && authAvailable
      && auth.authenticated
      && auth.historyReady;
    syncAccountPresentation();
    setHidden(projectsNavButton, !projectsAvailable);
  }

  function syncAll() {
    syncDeploymentVisibility();
    syncAccountVisibility();
    dispatch();
  }

  function currentModeCopy() {
    return TIER_COPY[document.documentElement.lang === "en" ? "en" : "ko"];
  }

  function ensureModeStyles() {
    if (document.querySelector('link[data-b62-mode-styles="true"]')) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "./mode-presentation.css";
    link.dataset.b62ModeStyles = "true";
    document.head.appendChild(link);
  }

  function selectTier(tier) {
    if (!AVAILABLE_TIERS.includes(tier)) return false;
    selectedTier = tier;
    syncModeCopy();
    window.dispatchEvent(new CustomEvent("padiem:tierchange", { detail: { tier } }));
    return true;
  }

  function createModeOption(tier) {
    const copy = currentModeCopy();
    const button = document.createElement("button");
    button.type = "button";
    button.className = "mode-option";
    button.dataset.modeValue = tier;
    button.disabled = false;
    button.setAttribute("aria-disabled", "false");
    button.setAttribute("aria-pressed", tier === selectedTier ? "true" : "false");

    const textContainer = document.createElement("span");
    const title = document.createElement("strong");
    const detail = document.createElement("small");
    title.textContent = copy[tier][0];
    detail.textContent = copy[tier][1];
    textContainer.append(title, detail);

    const state = document.createElement("span");
    state.className = "mode-option-state";
    state.textContent = copy.available;
    button.append(textContainer, state);
    button.addEventListener("click", () => {
      if (!selectTier(tier)) return;
      closeModePanel({ restoreFocus: true });
    });
    return button;
  }

  function syncModeCopy() {
    if (!modePill || !modePanel) return;
    const copy = currentModeCopy();
    const label = modePill.querySelector("span:last-child");
    if (label) label.textContent = copy[selectedTier][0];
    modePill.setAttribute("aria-label", `${copy.label}: ${copy[selectedTier][0]}`);
    const title = modePanel.querySelector("[data-mode-title]");
    const description = modePanel.querySelector("[data-mode-description]");
    const truth = modePanel.querySelector("[data-mode-truth]");
    if (title) title.textContent = copy.title;
    if (description) description.textContent = copy.description;
    if (truth) truth.textContent = copy.truth;
    modePanel.querySelectorAll("[data-mode-value]").forEach((button) => {
      const tier = button.dataset.modeValue;
      if (!copy[tier]) return;
      const optionTitle = button.querySelector("strong");
      const optionDetail = button.querySelector("small");
      const state = button.querySelector(".mode-option-state");
      if (optionTitle) optionTitle.textContent = copy[tier][0];
      if (optionDetail) optionDetail.textContent = copy[tier][1];
      if (state) state.textContent = copy.available;
      button.setAttribute("aria-pressed", tier === selectedTier ? "true" : "false");
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
    const active = modePanel.querySelector(`[data-mode-value="${selectedTier}"]`);
    if (active) active.focus();
  }

  function toggleModePanel() {
    if (!modePanel || modePanel.hidden) openModePanel(); else closeModePanel({ restoreFocus: true });
  }

  function installModePresentation() {
    if (!modePill || !modeHost || modePill.dataset.modeControl === "true") return;
    ensureModeStyles();
    modePill.dataset.modeControl = "true";
    modeHost.classList.add("tier-control-host");
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
      createModeOption("plus"),
      createModeOption("pro"),
    );

    const truth = document.createElement("p");
    truth.className = "mode-presentation-truth";
    truth.dataset.modeTruth = "true";
    modePanel.append(header, list, truth);
    modeHost.appendChild(modePanel);
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

  async function readAuthFresh() {
    let nextAuth = EMPTY_AUTH;
    try {
      const response = await nativeFetch("/api/auth/status", {
        headers: { "Accept": "application/json" },
        cache: "no-store",
      });
      const data = await response.json().catch(() => null);
      nextAuth = response.ok ? projectAuth(data) : EMPTY_AUTH;
    } catch (_) {
      nextAuth = EMPTY_AUTH;
    }
    auth = nextAuth;
    syncAll();
    return auth;
  }

  function refreshAuth() {
    const run = authRefreshTail.then(readAuthFresh, readAuthFresh);
    authRefreshTail = run.catch(() => EMPTY_AUTH);
    return run;
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
    const authUiObserver = new MutationObserver(() => {
      if (auth.sessionState !== "signed_in") return;
      const expectedAction = expectedAccountActionText();
      const actualAction = loginButton.textContent.trim();
      if (actualAction !== expectedAction) queueAuthRefresh();
    });
    authUiObserver.observe(loginButton, { childList: true, subtree: true });
    loginButton.addEventListener("click", () => {
      if (auth.sessionState !== "signed_in") return;
      loginButton.disabled = true;
      loginButton.setAttribute("aria-disabled", "true");
      loginButton.setAttribute("aria-busy", "true");
    }, { capture: true });
  }

  function reconcileAccountPresentationAfterLocaleBootstrap() {
    window.setTimeout(() => {
      if (auth.loaded) syncAccountPresentation();
    }, 0);
  }

  if (document.readyState === "complete") {
    reconcileAccountPresentationAfterLocaleBootstrap();
  } else {
    window.addEventListener("load", reconcileAccountPresentationAfterLocaleBootstrap, { once: true });
  }

  window.addEventListener("pageshow", () => {
    refreshDeployment();
    refreshAuth();
  });
  window.addEventListener("focus", queueAuthRefresh);
  window.addEventListener("padiem:localechange", () => {
    syncModeCopy();
    reconcileAccountPresentationAfterLocaleBootstrap();
  });

  window.PadiemProductCapabilities = Object.freeze({
    get: publicState,
    refresh: async () => {
      await Promise.all([refreshDeployment(), refreshAuth()]);
      return publicState();
    },
  });
  window.PadiemTierSelection = Object.freeze({
    get: () => selectedTier,
    set: (tier) => selectTier(String(tier || "").toLowerCase()),
    available: () => AVAILABLE_TIERS.slice(),
    open: openModePanel,
    close: () => closeModePanel({ restoreFocus: true }),
  });

  installModePresentation();
  syncAll();
  Promise.all([refreshDeployment(), refreshAuth()]);
})();