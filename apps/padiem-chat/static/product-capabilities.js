(() => {
  "use strict";

  const nativeFetch = window.fetch.bind(window);
  // #sidebarSearchButton (conversation search) intentionally has no script
  // wiring here: it must never toggle web-search mode or the center web card.
  const webSearchButton = document.getElementById("webSearchButton");
  const webSearchStarter = document.getElementById("webSearchStarterButton");
  const deepResearchButton = document.getElementById("deepResearchButton");
  const loginButton = document.getElementById("loginButton");
  const accountName = document.getElementById("accountName");
  const accountContainer = document.querySelector(".sidebar-account");
  const projectsNavButton = document.getElementById("projectsNavButton");
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
    memberGrade: "free",
  });

  const TIER_ORDER = Object.freeze(["free", "plus", "pro", "max"]);
  function availableTiers() {
    const current = auth.memberGrade;
    const index = TIER_ORDER.indexOf(current);
    return TIER_ORDER.slice(0, index < 0 ? 1 : index + 1);
  }
  function tierStatus(tier) {
    // System failure: auth loaded but not ready → unavailable for all.
    if (auth.loaded && !auth.ready) return "unavailable";
    return availableTiers().includes(tier) ? "available" : "upgrade";
  }

  const TIER_COPY = Object.freeze({
    ko: Object.freeze({
      label: "AI 등급",
      title: "Padiem AI",
      description: "등급이 높을수록 더 고급 모델을 사용할 수 있습니다.",
      truth: "더 높은 등급의 모델을 사용하려면 업그레이드가 필요합니다.",
      available: "사용 가능",
      unavailable: "사용 불가",
      upgrade: "업그레이드",
      adminNote: "관리자 전용 모델로 호출합니다.",
      free: ["Padiem Free", ""],
      plus: ["Padiem Plus", ""],
      pro: ["Padiem Pro", ""],
      max: ["Padiem Max", ""],
      admin: ["Padiem 관리자", ""],
    }),
    en: Object.freeze({
      label: "AI tier",
      title: "Padiem AI",
      description: "Higher tiers unlock more advanced models.",
      truth: "Upgrade is required to use higher-tier models.",
      available: "Available",
      unavailable: "Unavailable",
      upgrade: "Upgrade",
      adminNote: "Calls the admin-only model.",
      free: ["Padiem Free", ""],
      plus: ["Padiem Plus", ""],
      pro: ["Padiem Pro", ""],
      max: ["Padiem Max", ""],
      admin: ["Padiem 관리자", ""],
    }),
  });

  // Existing tier picker derives its availability only from server-verified membership.
  const TIER_LIST = Object.freeze(["free", "plus", "pro", "max"]);

  let selectedTier = "free";
  // Administrator entry visibility is proven per session by the server-side
  // global model admin gate; it is never derived from a username or grade.
  let adminAvailable = false;
  let adminProbeInFlight = null;
  let adminProbeAt = 0;
  const ADMIN_PROBE_TTL_MS = 60000;

  // PADIEM Custom (BYOK) is a customer-owned provider key lane. It is a
  // separate selection from the PADIEM-provided tiers, never derived from a
  // member grade, and only the server-returned last four key characters are
  // ever rendered. The raw key is written once and never read back.
  const CUSTOM_COPY = Object.freeze({
    ko: Object.freeze({
      heading: "내 API 키 (Padiem Custom)",
      description: "Padiem 제공 모델과 별개로, 직접 등록한 공급사 키로 호출합니다.",
      option: "Padiem Custom",
      truth: "내 API 키로 선택한 공급사 모델을 직접 호출합니다. Padiem 등급 모델과 별개입니다.",
      stateReady: "사용 가능",
      stateKey: "키 필요",
      stateLogin: "로그인 필요",
      stateExpired: "세션 만료",
      stateUnavailable: "사용 불가",
      stateLoading: "확인 중",
      credential: "등록된 키: ••••",
      noCredential: "등록된 키가 없습니다.",
      keyLabel: "API 키",
      keyPlaceholder: "API 키를 입력하세요 (16자 이상)",
      keyHint: "키 원문은 저장 후 다시 표시되지 않으며, Padiem 서버에 암호화되어 보관됩니다.",
      save: "키 저장",
      replace: "키 교체",
      remove: "삭제",
      saveBusy: "저장 중…",
      deleteBusy: "삭제 중…",
      saved: "API 키를 저장했습니다.",
      replaced: "API 키를 교체했습니다.",
      deleted: "API 키를 삭제했습니다.",
      deleteNoop: "삭제할 키가 없습니다.",
      deleteConfirm: "저장된 API 키를 삭제할까요? 삭제하면 Padiem Custom을 사용할 수 없습니다.",
      loginNeeded: "로그인 후 Padiem Custom을 사용할 수 있습니다.",
      authExpired: "로그인이 만료되었습니다. 다시 로그인한 뒤 키를 저장해 주세요.",
      unavailable: "Padiem Custom을 현재 사용할 수 없습니다.",
      checkFailed: "Padiem Custom 자격증명 상태를 확인하지 못했습니다.",
      retry: "다시 확인",
      keyLength: "API 키는 공백 없이 16자 이상 512자 이하여야 합니다.",
      saveFailed: "API 키를 저장하지 못했습니다.",
      deleteFailed: "API 키를 삭제하지 못했습니다.",
    }),
    en: Object.freeze({
      heading: "My API key (Padiem Custom)",
      description: "Calls your own provider key, separate from Padiem-provided models.",
      option: "Padiem Custom",
      truth: "Calls the selected provider model directly with your own key, separate from Padiem tiers.",
      stateReady: "Available",
      stateKey: "Key required",
      stateLogin: "Sign-in required",
      stateExpired: "Session expired",
      stateUnavailable: "Unavailable",
      stateLoading: "Checking",
      credential: "Registered key: ••••",
      noCredential: "No key registered.",
      keyLabel: "API key",
      keyPlaceholder: "Enter your API key (16+ characters)",
      keyHint: "The raw key is shown once and never again; it is stored encrypted on the Padiem server.",
      save: "Save key",
      replace: "Replace key",
      remove: "Delete",
      saveBusy: "Saving…",
      deleteBusy: "Deleting…",
      saved: "API key saved.",
      replaced: "API key replaced.",
      deleted: "API key deleted.",
      deleteNoop: "There was no key to delete.",
      deleteConfirm: "Delete the stored API key? Padiem Custom will stop working until you register another key.",
      loginNeeded: "Sign in to use Padiem Custom.",
      authExpired: "Your session expired. Sign in again before saving a key.",
      unavailable: "Padiem Custom is currently unavailable.",
      checkFailed: "Could not verify the Padiem Custom credential status.",
      retry: "Check again",
      keyLength: "An API key must be 16 to 512 characters with no spaces.",
      saveFailed: "Could not save the API key.",
      deleteFailed: "Could not delete the API key.",
    }),
  });

  let customSelection = null;
  let customProviders = [];
  let customCredentials = [];
  let customLoadState = "idle";
  let customLoadError = "";
  let customMutation = null;
  let customRequestSeq = 0;
  let customAuthRefreshAt = 0;
  let customFocusPending = false;
  let customMessageText = "";
  let customMessageState = "info";
  let customOption = null;
  let customOptionTitle = null;
  let customOptionState = null;
  let customHeadingEl = null;
  let customDescriptionEl = null;
  let customKeyLabelEl = null;
  let customKeyHintEl = null;
  let customPanel = null;
  let customStatusEl = null;
  let customGuestNote = null;
  let customInput = null;
  let customSaveButton = null;
  let customDeleteButton = null;
  let customMessageEl = null;
  let customRetryButton = null;

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
      memberGrade: authenticated && TIER_ORDER.includes(data.member_grade) ? data.member_grade : "free",
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

  function syncDeploymentVisibility() {
    const webAvailable = deployment.loaded && deployment.webSearch;
    const researchAvailable = deployment.loaded && deployment.deepResearch;
    setHidden(webSearchButton, !webAvailable);
    setHidden(webSearchStarter, !webAvailable);
    setHidden(deepResearchButton, !researchAvailable);
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

  // locale.js localizes the same button and runs after every capabilitychange,
  // so its copy is a legitimate presentation and must not look like a foreign
  // mutation to the observer below.
  function localeAccountActionText() {
    const locale = window.__padiemLocale;
    if (!locale || typeof locale.text !== "function") return "";
    const key = auth.sessionState === "signed_in"
      ? "logout"
      : auth.sessionState === "expired" ? "sign-in-again" : "login";
    try {
      return text(locale.text(key), 40);
    } catch (_) {
      return "";
    }
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
    if (tier === "admin") {
      if (!adminAvailable) return false;
      selectedTier = tier;
      customSelection = null;
      syncModeCopy();
      window.dispatchEvent(new CustomEvent("padiem:tierchange", { detail: { tier } }));
      return true;
    }
    if (!availableTiers().includes(tier)) return false;
    selectedTier = tier;
    customSelection = null;
    syncModeCopy();
    window.dispatchEvent(new CustomEvent("padiem:tierchange", { detail: { tier } }));
    return true;
  }

  function customCopy() {
    return CUSTOM_COPY[document.documentElement.lang === "en" ? "en" : "ko"];
  }

  function customProvider() {
    return customProviders.length ? customProviders[0] : null;
  }

  function customCredential() {
    const provider = customProvider();
    if (!provider) return null;
    return customCredentials.find((row) => row.provider === provider.provider) || null;
  }

  function customUsageState() {
    if (!auth.authenticated) {
      if (!auth.loaded || !auth.ready) return "unavailable";
      return auth.sessionState === "expired" ? "expired" : "login";
    }
    if (customLoadState === "loading" || customLoadState === "idle") return "loading";
    if (customLoadState === "auth") return "expired";
    if (customLoadState === "unavailable" || !customProvider()) return "unavailable";
    return customCredential() ? "ready" : "key";
  }

  function customIsSelectable() {
    const state = customUsageState();
    return state === "ready" || state === "key";
  }

  function errorMessage(data) {
    return data && data.error && typeof data.error.message === "string"
      ? text(data.error.message, 200)
      : "";
  }

  function setCustomMessage(message, state = "info") {
    customMessageText = text(message, 240);
    customMessageState = state;
    syncCustomSection();
  }

  function clearCustomState() {
    customProviders = [];
    customCredentials = [];
    customLoadState = "idle";
    customLoadError = "";
    customMutation = null;
    customSelection = null;
    customRequestSeq += 1;
    syncModeCopy();
  }

  function syncCustomSection() {
    if (!customOption) return;
    const copy = customCopy();
    if (customHeadingEl) customHeadingEl.textContent = copy.heading;
    if (customDescriptionEl) customDescriptionEl.textContent = copy.description;
    if (customKeyLabelEl) customKeyLabelEl.textContent = copy.keyLabel;
    if (customKeyHintEl) customKeyHintEl.textContent = copy.keyHint;
    if (customRetryButton) customRetryButton.textContent = copy.retry;
    const state = customUsageState();
    const selectable = state === "ready" || state === "key";
    const credential = customCredential();
    const provider = customProvider();
    const busy = customMutation !== null;

    customOption.disabled = !selectable;
    customOption.setAttribute("aria-disabled", selectable ? "false" : "true");
    customOption.setAttribute("aria-pressed", customSelection && selectable ? "true" : "false");
    customOption.dataset.modeStatus = state === "ready" ? "available" : state === "key" ? "key" : "unavailable";
    if (customOptionTitle) customOptionTitle.textContent = provider ? provider.display_name : copy.option;
    if (customOptionState) {
      const labels = {
        ready: copy.stateReady,
        key: copy.stateKey,
        loading: copy.stateLoading,
        login: copy.stateLogin,
        expired: copy.stateExpired,
        unavailable: copy.stateUnavailable,
      };
      customOptionState.textContent = labels[state] || copy.stateUnavailable;
      customOptionState.className = "mode-option-state mode-option-state--"
        + (state === "ready" ? "available" : state === "unavailable" ? "unavailable" : "upgrade");
    }

    if (customPanel) customPanel.hidden = !auth.authenticated;
    if (customGuestNote) {
      customGuestNote.hidden = auth.authenticated;
      customGuestNote.textContent = !auth.loaded || !auth.ready
        ? copy.unavailable
        : auth.sessionState === "expired" ? copy.authExpired : copy.loginNeeded;
    }
    if (customStatusEl) {
      customStatusEl.textContent = state === "loading" ? copy.stateLoading
        : state === "expired" ? copy.authExpired
        : state === "unavailable" ? (customLoadError || copy.unavailable)
        : credential ? copy.credential + String(credential.key_last4 || "")
        : copy.noCredential;
      customStatusEl.dataset.state = state;
    }
    if (customInput) {
      customInput.disabled = busy || !auth.authenticated
        || state === "loading" || state === "unavailable" || state === "expired";
      customInput.placeholder = copy.keyPlaceholder;
    }
    if (customSaveButton) {
      customSaveButton.textContent = busy && customMutation === "save"
        ? copy.saveBusy : credential ? copy.replace : copy.save;
      customSaveButton.disabled = busy || (customInput ? customInput.disabled : true);
    }
    if (customDeleteButton) {
      customDeleteButton.textContent = busy && customMutation === "delete" ? copy.deleteBusy : copy.remove;
      customDeleteButton.hidden = !credential;
      customDeleteButton.disabled = busy || !credential;
    }
    if (customMessageEl) {
      customMessageEl.textContent = customMessageText;
      customMessageEl.dataset.state = customMessageState;
      customMessageEl.hidden = !customMessageText;
    }
    if (customRetryButton) {
      customRetryButton.hidden = !(auth.authenticated && state === "unavailable");
    }
    if (customFocusPending && customInput && !customInput.disabled
        && modePanel && !modePanel.hidden) {
      customFocusPending = false;
      window.setTimeout(() => {
        try { customInput.focus(); } catch (_) { /* focus is an enhancement */ }
      }, 0);
    }
  }

  function selectCustom() {
    const provider = customProvider();
    if (!provider || !auth.authenticated) return false;
    const state = customUsageState();
    if (state !== "ready" && state !== "key") return false;
    customSelection = { provider: provider.provider, model: provider.model };
    customMessageText = "";
    customMessageState = "info";
    syncModeCopy();
    if (state === "key") {
      // Stay open with the key form so the next action is obvious.
      customFocusPending = true;
      syncCustomSection();
      return true;
    }
    closeModePanel({ restoreFocus: true });
    return true;
  }

  function openCustomCredentials() {
    openModePanel();
    if (!auth.authenticated) return false;
    customFocusPending = true;
    syncCustomSection();
    return true;
  }

  async function refreshCustomStatus() {
    const ticket = ++customRequestSeq;
    if (!auth.authenticated) {
      customProviders = [];
      customCredentials = [];
      customLoadState = "idle";
      customLoadError = "";
      customSelection = null;
      syncModeCopy();
      return;
    }
    customLoadState = "loading";
    customLoadError = "";
    syncCustomSection();
    try {
      const response = await nativeFetch("/api/chat/custom/credential", {
        headers: { "Accept": "application/json" },
        cache: "no-store",
        credentials: "same-origin",
      });
      if (ticket !== customRequestSeq) return;
      if (response.status === 401) {
        customProviders = [];
        customCredentials = [];
        customLoadState = "auth";
        customSelection = null;
        // Refresh the account presentation once; the guard prevents a loop if
        // the server keeps reporting an unusable session.
        if (Date.now() - customAuthRefreshAt > 30000) {
          customAuthRefreshAt = Date.now();
          void refreshAuth();
        }
        syncModeCopy();
        return;
      }
      const data = await response.json().catch(() => null);
      if (ticket !== customRequestSeq) return;
      if (!response.ok || !data || data.ok !== true) {
        customProviders = [];
        customCredentials = [];
        customLoadState = "unavailable";
        customLoadError = response.status === 503
          ? errorMessage(data) || customCopy().unavailable
          : customCopy().checkFailed;
        customSelection = null;
        syncModeCopy();
        return;
      }
      const providers = Array.isArray(data.providers) ? data.providers : [];
      const credentials = Array.isArray(data.credentials) ? data.credentials : [];
      customProviders = providers
        .filter((row) => row && typeof row.provider === "string" && row.provider
          && typeof row.model === "string" && row.model)
        .slice(0, 4)
        .map((row) => Object.freeze({
          provider: row.provider,
          model: row.model,
          display_name: text(row.display_name, 120) || customCopy().option,
        }));
      const known = new Set(customProviders.map((row) => row.provider));
      customCredentials = credentials
        .filter((row) => row && known.has(row.provider)
          && typeof row.key_last4 === "string" && row.key_last4.length > 0)
        .map((row) => Object.freeze({
          provider: row.provider,
          key_last4: row.key_last4.replace(/[^A-Za-z0-9]/g, "").slice(-4),
        }));
      customLoadState = customProviders.length ? "ready" : "unavailable";
      if (!customProviders.length) customLoadError = customCopy().unavailable;
      if (customSelection) {
        const selectedProvider = customProviders.find(
          (row) => row.provider === customSelection.provider
            && row.model === customSelection.model,
        );
        customSelection = selectedProvider
          ? { provider: selectedProvider.provider, model: selectedProvider.model }
          : null;
      }
      syncModeCopy();
    } catch (_) {
      if (ticket !== customRequestSeq) return;
      customProviders = [];
      customCredentials = [];
      customLoadState = "unavailable";
      customLoadError = customCopy().checkFailed;
      customSelection = null;
      syncModeCopy();
    }
  }

  async function saveCustomKey() {
    if (customMutation || !customInput) return;
    const provider = customProvider();
    if (!provider || !auth.authenticated) return;
    const copy = customCopy();
    const key = String(customInput.value || "").trim();
    if (key.length < 16 || key.length > 512 || /[^\x21-\x7e]/.test(key)) {
      setCustomMessage(copy.keyLength, "error");
      customInput.focus();
      return;
    }
    customMutation = "save";
    customMessageText = "";
    customMessageState = "info";
    syncCustomSection();
    try {
      const response = await nativeFetch("/api/chat/custom/credential", {
        method: "PUT",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        cache: "no-store",
        credentials: "same-origin",
        body: JSON.stringify({ provider: provider.provider, api_key: key }),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || data.ok !== true) {
        if (response.status === 401) {
          customMutation = null;
          clearCustomState();
          setCustomMessage(copy.authExpired, "error");
          void refreshAuth();
          return;
        }
        setCustomMessage(errorMessage(data) || copy.saveFailed, "error");
        return;
      }
      const hadCredential = customCredential() !== null;
      // Never keep or re-render the raw key after the write succeeds.
      customInput.value = "";
      customMutation = null;
      await refreshCustomStatus();
      setCustomMessage(hadCredential ? copy.replaced : copy.saved, "ok");
    } catch (_) {
      setCustomMessage(copy.saveFailed, "error");
    } finally {
      customMutation = null;
      syncCustomSection();
    }
  }

  async function deleteCustomKey() {
    if (customMutation || !auth.authenticated) return;
    const provider = customProvider();
    if (!provider || !customCredential()) return;
    const copy = customCopy();
    if (typeof window.confirm === "function" && !window.confirm(copy.deleteConfirm)) return;
    customMutation = "delete";
    customMessageText = "";
    customMessageState = "info";
    syncCustomSection();
    try {
      const response = await nativeFetch(
        "/api/chat/custom/credential?provider=" + encodeURIComponent(provider.provider),
        {
          method: "DELETE",
          headers: { "Accept": "application/json" },
          cache: "no-store",
          credentials: "same-origin",
        },
      );
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || data.ok !== true) {
        if (response.status === 401) {
          customMutation = null;
          clearCustomState();
          setCustomMessage(copy.authExpired, "error");
          void refreshAuth();
          return;
        }
        setCustomMessage(errorMessage(data) || copy.deleteFailed, "error");
        return;
      }
      if (customInput) customInput.value = "";
      customMutation = null;
      await refreshCustomStatus();
      setCustomMessage(data.deleted === true ? copy.deleted : copy.deleteNoop, "ok");
    } catch (_) {
      setCustomMessage(copy.deleteFailed, "error");
    } finally {
      customMutation = null;
      syncCustomSection();
    }
  }

  function createCustomSection() {
    const copy = customCopy();
    const section = document.createElement("section");
    section.className = "mode-custom-section";
    section.setAttribute("aria-labelledby", "modeCustomTitle");

    const heading = document.createElement("div");
    heading.className = "mode-custom-heading";
    const title = document.createElement("strong");
    title.id = "modeCustomTitle";
    title.textContent = copy.heading;
    const description = document.createElement("small");
    description.textContent = copy.description;
    heading.append(title, description);
    customHeadingEl = title;
    customDescriptionEl = description;

    customOption = document.createElement("button");
    customOption.type = "button";
    customOption.className = "mode-option mode-option--custom";
    customOption.dataset.modeValue = "custom";
    customOptionTitle = document.createElement("strong");
    customOptionState = document.createElement("span");
    customOptionState.className = "mode-option-state";
    customOption.append(customOptionTitle, customOptionState);
    customOption.addEventListener("click", () => {
      if (!customIsSelectable()) return;
      selectCustom();
    });

    const form = document.createElement("div");
    form.className = "mode-custom-credential";
    form.hidden = true;

    const status = document.createElement("p");
    status.className = "mode-custom-status";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");

    const label = document.createElement("label");
    label.className = "mode-custom-key-label";
    label.htmlFor = "modeCustomApiKey";
    label.textContent = copy.keyLabel;
    customKeyLabelEl = label;
    customInput = document.createElement("input");
    customInput.type = "password";
    customInput.id = "modeCustomApiKey";
    customInput.className = "mode-custom-key-input";
    customInput.autocomplete = "new-password";
    customInput.maxLength = 512;
    customInput.placeholder = copy.keyPlaceholder;
    customInput.setAttribute("autocapitalize", "off");
    customInput.setAttribute("spellcheck", "false");
    customInput.setAttribute("aria-describedby", "modeCustomKeyHint");
    customInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        void saveCustomKey();
      }
    });

    const actions = document.createElement("div");
    actions.className = "mode-custom-actions";
    customSaveButton = document.createElement("button");
    customSaveButton.type = "button";
    customSaveButton.className = "mode-custom-action mode-custom-save";
    customSaveButton.addEventListener("click", () => void saveCustomKey());
    customDeleteButton = document.createElement("button");
    customDeleteButton.type = "button";
    customDeleteButton.className = "mode-custom-action mode-custom-delete";
    customDeleteButton.addEventListener("click", () => void deleteCustomKey());
    actions.append(customSaveButton, customDeleteButton);

    const hint = document.createElement("small");
    hint.className = "mode-custom-hint";
    hint.id = "modeCustomKeyHint";
    hint.textContent = copy.keyHint;
    customKeyHintEl = hint;

    customMessageEl = document.createElement("p");
    customMessageEl.className = "mode-custom-message";
    customMessageEl.setAttribute("role", "status");
    customMessageEl.setAttribute("aria-live", "polite");

    customRetryButton = document.createElement("button");
    customRetryButton.type = "button";
    customRetryButton.className = "mode-custom-retry";
    customRetryButton.textContent = copy.retry;
    customRetryButton.addEventListener("click", () => void refreshCustomStatus());

    form.append(status, label, customInput, actions, hint, customMessageEl, customRetryButton);

    customGuestNote = document.createElement("p");
    customGuestNote.className = "mode-custom-guest-note";
    customGuestNote.setAttribute("role", "status");

    customPanel = form;
    customStatusEl = status;
    section.append(heading, customOption, form, customGuestNote);
    return section;
  }

  function createModeOption(tier) {
    const copy = currentModeCopy();
    const status = tier === "admin" ? "available" : tierStatus(tier);
    const available = status === "available";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "mode-option";
    button.dataset.modeValue = tier;
    button.dataset.modeStatus = status;
    button.disabled = status === "unavailable";
    button.setAttribute("aria-disabled", status === "unavailable" ? "true" : "false");
    button.setAttribute("aria-pressed", tier === selectedTier && available ? "true" : "false");

    const title = document.createElement("strong");
    title.textContent = copy[tier][0];
    const state = document.createElement("span");
    state.className = "mode-option-state mode-option-state--" + status;
    const icon = document.createElement("span");
    icon.className = "mode-option-state-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = status === "available" ? "✓" : status === "upgrade" ? "↑" : "—";
    const label = document.createElement("span");
    label.textContent = status === "available" ? copy.available : status === "upgrade" ? copy.upgrade : copy.unavailable;
    state.append(icon, label);
    button.append(title, state);
    button.addEventListener("click", () => {
      if (tier === "admin") {
        if (!selectTier(tier)) return;
        closeModePanel({ restoreFocus: true });
        return;
      }
      const currentStatus = tierStatus(tier);
      if (currentStatus === "unavailable") return;
      if (currentStatus === "upgrade") {
        const truthEl = modePanel?.querySelector("[data-mode-truth]");
        if (truthEl) truthEl.textContent = copy.truth;
        if (truthEl) {
          truthEl.classList.add("is-highlighted");
          window.setTimeout(() => truthEl.classList.remove("is-highlighted"), 1200);
        }
        return;
      }
      if (!selectTier(tier)) return;
      closeModePanel({ restoreFocus: true });
    });
    return button;
  }

  function syncModeCopy() {
    if (!modePill || !modePanel) return;
    syncAdminOption();
    const copy = currentModeCopy();
    const custom = customSelection ? customCopy() : null;
    const activeLabel = custom ? custom.option : copy[selectedTier][0];
    const label = modePill.querySelector("span:last-child");
    if (label) label.textContent = activeLabel;
    modePill.setAttribute("aria-label", `${copy.label}: ${activeLabel}`);
    modePill.dataset.modelSelection = custom ? "custom" : selectedTier;
    const title = modePanel.querySelector("[data-mode-title]");
    const description = modePanel.querySelector("[data-mode-description]");
    const truth = modePanel.querySelector("[data-mode-truth]");
    if (title) title.textContent = copy.title;
    if (description) description.textContent = copy.description;
    if (truth) {
      truth.textContent = custom
        ? custom.truth
        : selectedTier === "admin" ? copy.adminNote : copy.truth;
    }
    modePanel.querySelectorAll("[data-mode-value]").forEach((button) => {
      const tier = button.dataset.modeValue;
      if (!copy[tier]) return;
      const status = tier === "admin" ? "available" : tierStatus(tier);
      const available = status === "available";
      button.dataset.modeStatus = status;
      button.disabled = status === "unavailable";
      button.setAttribute("aria-disabled", status === "unavailable" ? "true" : "false");
      button.setAttribute("aria-pressed", tier === selectedTier && available && !custom ? "true" : "false");
      const optionTitle = button.querySelector("strong");
      const stateEl = button.querySelector(".mode-option-state");
      if (optionTitle) optionTitle.textContent = copy[tier][0];
      if (stateEl) {
        stateEl.className = "mode-option-state mode-option-state--" + status;
        stateEl.textContent = "";
        const icon = document.createElement("span");
        icon.className = "mode-option-state-icon";
        icon.setAttribute("aria-hidden", "true");
        icon.textContent = status === "available" ? "✓" : status === "upgrade" ? "↑" : "—";
        const stateLabel = document.createElement("span");
        stateLabel.textContent = status === "available" ? copy.available : status === "upgrade" ? copy.upgrade : copy.unavailable;
        stateEl.append(icon, stateLabel);
      }
    });
    syncCustomSection();
  }

  function closeModePanel({ restoreFocus = false } = {}) {
    if (!modePill || !modePanel || modePanel.hidden) return;
    modePanel.hidden = true;
    modePill.setAttribute("aria-expanded", "false");
    if (restoreFocus) modePill.focus();
  }

  function openModePanel() {
    if (!modePill || !modePanel) return;
    if (auth.authenticated) {
      void refreshAdminPresence().then(() => {
        if (!modePanel || modePanel.hidden) return;
        syncModeCopy();
      });
      void refreshCustomStatus();
    }
    modePanel.hidden = false;
    modePill.setAttribute("aria-expanded", "true");
    const active = customSelection && customOption
      ? customOption
      : modePanel.querySelector(`[data-mode-value="${selectedTier}"]`);
    if (active) active.focus();
  }

  function syncAdminOption() {
    if (!modePanel) return;
    const list = modePanel.querySelector(".mode-option-list");
    if (!list) return;
    let adminButton = list.querySelector('[data-mode-value="admin"]');
    if (!adminAvailable) {
      if (adminButton) adminButton.remove();
      return;
    }
    if (!adminButton) {
      adminButton = createModeOption("admin");
      list.appendChild(adminButton);
    }
  }

  async function refreshAdminPresence() {
    // The B62 product's own operator authority (/api/b66/admin/me) reports
    // the verified Google admin with HTTP 200 {ok, admin} — guests and
    // ordinary members simply get admin:false, so no error text is needed.
    if (!auth.authenticated) {
      adminAvailable = false;
      adminProbeInFlight = null;
      adminProbeAt = 0;
      syncAdminOption();
      return false;
    }
    if (Date.now() - adminProbeAt < ADMIN_PROBE_TTL_MS) {
      return adminAvailable;
    }
    if (adminProbeInFlight) {
      try {
        await adminProbeInFlight;
      } catch (_) {
        // A failed probe hides the administrator entry by default.
      }
      return adminAvailable;
    }
    const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    const timer = window.setTimeout(() => {
      try {
        if (controller) controller.abort();
      } catch (_) {
        // Ignore abort errors; the probe fails closed below.
      }
    }, 5000);
    const probe = (async () => {
      try {
        const response = await nativeFetch("/api/b66/admin/me", {
          headers: { Accept: "application/json" },
          cache: "no-store",
          signal: controller ? controller.signal : undefined,
        });
        if (!response.ok) return false;
        const data = await response.json().catch(() => null);
        return !!(data && data.ok === true && data.admin === true);
      } catch (_) {
        return false;
      } finally {
        window.clearTimeout(timer);
      }
    })();
    adminProbeInFlight = probe;
    try {
      adminAvailable = await probe;
      adminProbeAt = Date.now();
    } finally {
      adminProbeInFlight = null;
    }
    if (!adminAvailable && selectedTier === "admin") {
      selectedTier = "free";
      window.dispatchEvent(new CustomEvent("padiem:tierchange", { detail: { tier: selectedTier } }));
    }
    syncAdminOption();
    return adminAvailable;
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
    list.append(...TIER_LIST.map((tier) => createModeOption(tier)));

    const truth = document.createElement("p");
    truth.className = "mode-presentation-truth";
    truth.dataset.modeTruth = "true";
    // PADIEM Custom is a customer-owned key lane, visually separated from the
    // PADIEM-provided tiers and intentionally absent from TIER_LIST.
    modePanel.append(header, list, truth, createCustomSection());
    syncCustomSection();
    syncAdminOption();
    // One common Chat/Claw tier picker. Move, never clone, the existing
    // owner-verified Claw exact-model controls into this picker. Their IDs,
    // listeners and submit-time snapshots stay authoritative and unchanged.
    // The composer itself now has exactly the Chat visual hierarchy.
    const exactModelControl = document.querySelector("#composerForm > label.claw-model-choice");
    const advancedModelControl = document.querySelector("#composerForm > details.claw-model-advanced");
    if (exactModelControl) {
      const optionalModels = document.createElement("div");
      optionalModels.className = "claw-tier-model-options";
      optionalModels.appendChild(exactModelControl);
      if (advancedModelControl) optionalModels.appendChild(advancedModelControl);
      modePanel.appendChild(optionalModels);
    }
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
    if (!auth.authenticated) clearCustomState();
    await refreshAdminPresence();
    const selectionValid = selectedTier === "admin"
      ? adminAvailable
      : availableTiers().includes(selectedTier);
    if (!selectionValid) {
      selectedTier = "free";
      window.dispatchEvent(new CustomEvent("padiem:tierchange", { detail: { tier: selectedTier } }));
    }
    syncModeCopy();
    syncAll();
    if (auth.authenticated) void refreshCustomStatus();
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

  if (loginButton) {
    const authUiObserver = new MutationObserver(() => {
      if (auth.sessionState !== "signed_in") return;
      const expectedAction = expectedAccountActionText();
      const actualAction = loginButton.textContent.trim();
      if (actualAction !== expectedAction && actualAction !== localeAccountActionText()) queueAuthRefresh();
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
    syncCustomSection();
    reconcileAccountPresentationAfterLocaleBootstrap();
  });
  let customAuthEventState = null;
  window.addEventListener("padiem:auth-state", (event) => {
    const authenticated = Boolean(event && event.detail && event.detail.authenticated === true);
    if (customAuthEventState === authenticated) return;
    customAuthEventState = authenticated;
    if (!authenticated) {
      clearCustomState();
      syncCustomSection();
      return;
    }
    void refreshCustomStatus();
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
    available: () => availableTiers(),
    open: openModePanel,
    close: () => closeModePanel({ restoreFocus: true }),
  });
  window.PadiemCustomSelection = Object.freeze({
    get: () => (customSelection
      ? Object.freeze({ provider: customSelection.provider, model: customSelection.model })
      : null),
    select: () => selectCustom(),
    open: openCustomCredentials,
    refresh: refreshCustomStatus,
  });

  installModePresentation();
  syncAll();
  Promise.all([refreshDeployment(), refreshAuth()]);
})();