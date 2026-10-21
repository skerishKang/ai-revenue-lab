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
      title: "모델 선택",
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
      title: "Choose model",
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
  // #5222: "adminVerified" means the server PROVED this account is (not) an
  // administrator. A probe that could not complete stays unverified, so a
  // temporary failure is never cached as a denial and never destroys the
  // account's stored preference.
  let adminVerified = false;
  let adminProbeInFlight = null;
  let adminProbeAt = 0;
  const ADMIN_PROBE_TTL_MS = 60000;
  // A probe that could not complete is cached only briefly and retried soon,
  // so a temporary failure never pins the administrator lane as a denial.
  const ADMIN_PROBE_UNVERIFIED_TTL_MS = 2000;
  const ADMIN_PROBE_RETRY_MS = 5000;
  let adminProbeRetryTimer = null;
  // #5222: the account's last explicitly selected tier. It lives on the server
  // under the signed session's own account, so the browser never names the
  // account and one account can never inherit another account's selection.
  const MODEL_SELECTION_PATH = "/api/account/model-selection";
  let accountSelection = null;
  // Monotonic auth generation: a response that belongs to an older session is
  // never applied to the current one.
  let authEpoch = 0;
  // Monotonic explicit-choice sequence: a server read that started before the
  // user's own choice must never undo that choice.
  let selectionWriteSeq = 0;

  // PADIEM Custom (BYOK) is a customer-owned provider key lane. It is a
  // separate selection from the PADIEM-provided tiers, never derived from a
  // member grade, and only the server-returned last four key characters are
  // ever rendered. The raw key is written once and never read back.
  const CUSTOM_COPY = Object.freeze({
    ko: Object.freeze({
      heading: "내 API 키",
      description: "공급사 모델을 내 API 키로 직접 호출합니다. Padiem 등급 모델과 별개입니다.",
      option: "Padiem Custom",
      modelLabel: "모델",
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
      providerLabel: "공급사",
      modelNotSet: "모델을 선택하세요",
      modelPlaceholder: "공급사 모델 ID를 입력하세요",
      modelRequired: "모델 ID를 먼저 선택하거나 입력해 주세요.",
      loadModels: "모델 목록 불러오기",
      loadingModels: "모델 목록 확인 중…",
      modelsLoaded: "공급사 모델 목록을 불러왔습니다.",
      modelsFailed: "모델 목록을 불러오지 못했습니다.",
      endpointLabel: "API 엔드포인트 (선택)",
      endpointPlaceholder: "https://<your-endpoint>/v1",
      endpointHint: "비워 두면 공급사 기본 주소를 사용합니다. 공개 HTTPS 주소만 저장됩니다.",
      test: "연결 테스트",
      testing: "확인 중…",
      testOk: "공급사 연결을 확인했습니다.",
      testFailed: "공급사 연결을 확인하지 못했습니다.",
      keyRequired: "API 키를 저장한 뒤 Padiem Custom을 선택할 수 있습니다.",
    }),
    en: Object.freeze({
      heading: "My API key",
      description: "Calls the provider model directly with your API key, separate from Padiem models.",
      option: "Padiem Custom",
      modelLabel: "Model",
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
      providerLabel: "Provider",
      modelNotSet: "Choose a model",
      modelPlaceholder: "Enter the provider model ID",
      modelRequired: "Choose or enter a model ID first.",
      loadModels: "Load model list",
      loadingModels: "Checking model list…",
      modelsLoaded: "Loaded the provider model list.",
      modelsFailed: "Could not load the provider model list.",
      endpointLabel: "API endpoint (optional)",
      endpointPlaceholder: "https://<your-endpoint>/v1",
      endpointHint: "Leave empty to use the provider's default address. Only public HTTPS addresses are stored.",
      test: "Test connection",
      testing: "Checking…",
      testOk: "Provider connection verified.",
      testFailed: "Could not verify the provider connection.",
      keyRequired: "Save an API key before selecting Padiem Custom.",
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
  let customProviderId = null;
  let customProviderSignature = "";
  let customModelValue = "";
  let customModelOptions = [];
  let customModelState = "idle";
  let customModelSeq = 0;
  let customTestState = "idle";
  let customOption = null;
  let customOptionTitle = null;
  let customOptionModel = null;
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
  let customProviderLabelEl = null;
  let customProviderSelect = null;
  let customModelLabelEl = null;
  let customModelSelect = null;
  let customModelInput = null;
  let customModelDatalist = null;
  let customModelListButton = null;
  let customEndpointLabelEl = null;
  let customEndpointInput = null;
  let customEndpointHintEl = null;
  let customTestButton = null;

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

  function commitTier(tier, { force = false, keepCustom = false } = {}) {
    if (!force && selectedTier === tier) return false;
    selectedTier = tier;
    // #5222: restoring the account's own tier never cancels the customer's
    // separate PADIEM Custom (BYOK) selection.
    if (!keepCustom) customSelection = null;
    syncModeCopy();
    window.dispatchEvent(new CustomEvent("padiem:tierchange", { detail: { tier } }));
    return true;
  }

  function selectTier(tier) {
    if (tier === "admin") {
      if (!adminAvailable) return false;
      commitTier(tier, { force: true });
      return true;
    }
    if (!availableTiers().includes(tier)) return false;
    commitTier(tier, { force: true });
    return true;
  }

  // #5222: the tier this account may actually use right now, highest first.
  // The server-verified member grade is the ceiling, not a floor: the user may
  // still pick any lower tier. The administrator lane is the default only
  // once the server has verified it, so an unverified probe never presents it
  // as executable.
  function highestAvailableTier() {
    if (adminAvailable && adminVerified) return "admin";
    const tiers = availableTiers();
    return tiers.length ? tiers[tiers.length - 1] : "free";
  }

  // #5222: an explicit user choice replaces the account's stored preference.
  // Restoring the account's own preference never writes one back.
  async function persistAccountSelection(tier) {
    if (!auth.authenticated) return false;
    const ticket = authEpoch;
    selectionWriteSeq += 1;
    try {
      const response = await nativeFetch(MODEL_SELECTION_PATH, {
        method: "PUT",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        cache: "no-store",
        credentials: "same-origin",
        body: JSON.stringify({ tier }),
      });
      if (ticket !== authEpoch) return false;
      if (response.status === 403) {
        // The server refused this tier for this account. The central policy
        // wins: re-read the authoritative state instead of keeping a tier the
        // account may not use.
        void refreshAuth();
        return false;
      }
      if (!response.ok) return false;
      const data = await response.json().catch(() => null);
      if (ticket !== authEpoch) return false;
      if (data && data.ok === true) {
        accountSelection = data.selection && typeof data.selection === "object"
          ? data.selection
          : null;
      }
      return true;
    } catch (_) {
      // A transient write failure never clears the stored preference; the next
      // successful read still returns the account's own last choice.
      return false;
    }
  }

  function applyAccountSelection(payload) {
    const restorable = payload && typeof payload.restorable_tier === "string"
      ? payload.restorable_tier
      : "";
    // #5222: with no usable stored preference the account keeps the tier it
    // really has, instead of falling back to the Free tier. An administrator
    // therefore lands on the administrator lane, and a Max member on Max.
    let next = highestAvailableTier();
    if (restorable === "admin") {
      // The administrator lane is executable only after the server verified
      // this account; an unverified probe never presents it as usable.
      if (adminAvailable && adminVerified) next = "admin";
    } else if (restorable && availableTiers().includes(restorable)) {
      next = restorable;
    }
    commitTier(next, { keepCustom: true });
  }

  async function refreshAccountSelection(epoch) {
    const ticket = epoch === undefined ? authEpoch : epoch;
    // A read that started before an explicit user choice must never undo it.
    const writeTicket = selectionWriteSeq;
    try {
      const response = await nativeFetch(MODEL_SELECTION_PATH, {
        headers: { "Accept": "application/json" },
        cache: "no-store",
        credentials: "same-origin",
      });
      if (ticket !== authEpoch || writeTicket !== selectionWriteSeq) return null;
      if (!response.ok) return null;
      const data = await response.json().catch(() => null);
      if (ticket !== authEpoch || writeTicket !== selectionWriteSeq) return null;
      if (!data || data.ok !== true) return null;
      accountSelection = data.selection && typeof data.selection === "object"
        ? data.selection
        : null;
      applyAccountSelection(data);
      return data;
    } catch (_) {
      // A transient read failure never destroys the stored preference: it stays
      // on the server for this account and returns with the next read.
      return null;
    }
  }

  function tierSelectionReady() {
    // The restore for the current auth generation has settled. A request that
    // waits for this never leaves with a tier that was not verified yet.
    return authRefreshTail.then(() => undefined, () => undefined);
  }

  function customCopy() {
    return CUSTOM_COPY[document.documentElement.lang === "en" ? "en" : "ko"];
  }

  function customProvider() {
    if (!customProviders.length) return null;
    return customProviders.find((row) => row.provider === customProviderId) || customProviders[0];
  }

  function customCredential() {
    const provider = customProvider();
    if (!provider) return null;
    return customCredentials.find((row) => row.provider === provider.provider) || null;
  }

  function customModelId() {
    const provider = customProvider();
    if (!provider) return "";
    if (provider.manual_model) {
      return customModelInput ? String(customModelInput.value || "").trim() : customModelValue;
    }
    return customModelSelect ? String(customModelSelect.value || "").trim() : customModelValue;
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
    customProviderId = null;
    customProviderSignature = "";
    customModelValue = "";
    customModelOptions = [];
    customModelState = "idle";
    customModelSeq += 1;
    customTestState = "idle";
    customRequestSeq += 1;
    syncModeCopy();
  }

  function syncProviderOptions() {
    if (!customProviderSelect) return;
    const signature = customProviders.map((row) => row.provider).join("|");
    if (signature !== customProviderSignature) {
      customProviderSignature = signature;
      customProviderSelect.textContent = "";
      customProviders.forEach((row) => {
        const option = document.createElement("option");
        option.value = row.provider;
        option.textContent = row.display_name;
        customProviderSelect.appendChild(option);
      });
    }
    const provider = customProvider();
    if (provider) customProviderSelect.value = provider.provider;
  }

  function syncModelOptions(provider) {
    const registry = Boolean(provider && !provider.manual_model);
    if (customModelLabelEl) {
      customModelLabelEl.htmlFor = registry ? "modeCustomModelSelect" : "modeCustomModelInput";
    }
    if (customModelSelect) {
      customModelSelect.hidden = !registry;
      const listed = registry && Array.isArray(provider.models) ? provider.models : [];
      const signature = listed.join("|");
      if (customModelSelect.dataset.signature !== signature) {
        customModelSelect.dataset.signature = signature;
        customModelSelect.textContent = "";
        listed.forEach((model) => {
          const option = document.createElement("option");
          option.value = model;
          option.textContent = model;
          customModelSelect.appendChild(option);
        });
      }
      if (registry) {
        if (!listed.length) customModelValue = "";
        else if (!listed.includes(customModelValue)) customModelValue = listed[0];
        customModelSelect.value = customModelValue;
      }
    }
    if (customModelInput) customModelInput.hidden = registry;
    if (customModelDatalist) {
      const signature = customModelOptions.join("|");
      if (customModelDatalist.dataset.signature !== signature) {
        customModelDatalist.dataset.signature = signature;
        customModelDatalist.textContent = "";
        customModelOptions.forEach((model) => {
          const option = document.createElement("option");
          option.value = model;
          customModelDatalist.appendChild(option);
        });
      }
    }
  }

  function syncCustomSection() {
    if (!customOption) return;
    const copy = customCopy();
    if (customHeadingEl) customHeadingEl.textContent = copy.heading;
    if (customDescriptionEl) customDescriptionEl.textContent = copy.description;
    if (customKeyLabelEl) customKeyLabelEl.textContent = copy.keyLabel;
    if (customKeyHintEl) customKeyHintEl.textContent = copy.keyHint;
    if (customProviderLabelEl) customProviderLabelEl.textContent = copy.providerLabel;
    if (customModelLabelEl) customModelLabelEl.textContent = copy.modelLabel;
    if (customEndpointLabelEl) customEndpointLabelEl.textContent = copy.endpointLabel;
    if (customEndpointHintEl) customEndpointHintEl.textContent = copy.endpointHint;
    if (customRetryButton) customRetryButton.textContent = copy.retry;
    const state = customUsageState();
    const selectable = state === "ready" || state === "key";
    const credential = customCredential();
    const provider = customProvider();
    const busy = customMutation !== null;

    syncProviderOptions();
    syncModelOptions(provider);
    const model = customModelId();

    customOption.disabled = !selectable;
    customOption.setAttribute("aria-disabled", selectable ? "false" : "true");
    customOption.setAttribute("aria-pressed", customSelection && selectable ? "true" : "false");
    customOption.dataset.modeStatus = state === "ready" ? "available" : state === "key" ? "key" : "unavailable";
    if (customOptionTitle) customOptionTitle.textContent = provider ? provider.display_name : copy.option;
    if (customOptionModel) {
      customOptionModel.textContent = provider
        ? copy.modelLabel + " " + (model || copy.modelNotSet)
        : "";
      customOptionModel.hidden = !provider;
    }
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
        : credential
          ? copy.credential + String(credential.key_last4 || "")
            + (credential.endpoint_is_default === false && credential.endpoint
              ? " · " + credential.endpoint : "")
          : copy.noCredential;
      customStatusEl.dataset.state = state;
    }

    const controlsDisabled = busy || !auth.authenticated
      || state === "loading" || state === "unavailable" || state === "expired";
    if (customProviderSelect) {
      customProviderSelect.disabled = controlsDisabled || !customProviders.length;
    }
    if (customModelSelect) {
      customModelSelect.disabled = controlsDisabled || !provider || !provider.models.length;
    }
    if (customModelInput) {
      customModelInput.disabled = controlsDisabled || !provider;
      customModelInput.placeholder = copy.modelPlaceholder;
    }
    if (customModelListButton) {
      customModelListButton.hidden = !provider || !provider.supports_model_listing;
      customModelListButton.disabled = controlsDisabled || !credential
        || customModelState === "loading";
      customModelListButton.textContent = customModelState === "loading"
        ? copy.loadingModels : copy.loadModels;
    }
    if (customEndpointLabelEl) {
      customEndpointLabelEl.hidden = !provider || !provider.supports_custom_endpoint;
    }
    if (customEndpointInput) {
      customEndpointInput.hidden = !provider || !provider.supports_custom_endpoint;
      customEndpointInput.disabled = controlsDisabled || !provider;
      customEndpointInput.placeholder = provider && provider.default_endpoint
        ? provider.default_endpoint : copy.endpointPlaceholder;
    }
    if (customEndpointHintEl) {
      customEndpointHintEl.hidden = !provider || !provider.supports_custom_endpoint;
    }
    if (customTestButton) {
      customTestButton.hidden = !provider || !provider.supports_connection_test || !credential;
      customTestButton.disabled = controlsDisabled || !credential
        || customTestState === "testing";
      customTestButton.textContent = customTestState === "testing"
        ? copy.testing : copy.test;
    }
    if (customInput) {
      customInput.disabled = controlsDisabled;
      customInput.placeholder = copy.keyPlaceholder;
    }
    if (customSaveButton) {
      customSaveButton.textContent = busy && customMutation === "save"
        ? copy.saveBusy : credential ? copy.replace : copy.save;
      customSaveButton.disabled = controlsDisabled || !provider;
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
    if (customFocusPending && !controlsDisabled && modePanel && !modePanel.hidden) {
      customFocusPending = false;
      const target = customModelInput && !customModelInput.hidden && !model
        ? customModelInput
        : customInput;
      window.setTimeout(() => {
        try { target.focus(); } catch (_) { /* focus is an enhancement */ }
      }, 0);
    }
  }

  function focusCustomModel() {
    const target = customModelInput && !customModelInput.hidden
      ? customModelInput : customModelSelect;
    try { if (target) target.focus(); } catch (_) { /* focus is an enhancement */ }
  }

  function selectCustom() {
    const provider = customProvider();
    if (!provider || !auth.authenticated) return false;
    const state = customUsageState();
    if (state !== "ready" && state !== "key") return false;
    const model = customModelId();
    if (!model) {
      // A typed-but-unknown model id is never accepted as a success.
      setCustomMessage(customCopy().modelRequired, "error");
      focusCustomModel();
      return false;
    }
    customSelection = { provider: provider.provider, model };
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

  function selectCustomProvider(providerId) {
    if (!customProviders.some((row) => row.provider === providerId)) return;
    customProviderId = providerId;
    const provider = customProvider();
    customModelValue = provider && !provider.manual_model && provider.models.length
      ? provider.models[0] : "";
    customModelOptions = provider && Array.isArray(provider.models)
      ? provider.models.slice() : [];
    customModelState = "idle";
    customModelSeq += 1;
    customTestState = "idle";
    customMessageText = "";
    customMessageState = "info";
    if (customModelInput) customModelInput.value = customModelValue;
    const credential = customCredential();
    if (customEndpointInput) {
      customEndpointInput.value = credential
        && credential.endpoint_is_default === false && credential.endpoint
        ? credential.endpoint : "";
    }
    syncModeCopy();
  }

  function onCustomModelChanged() {
    customModelValue = customModelId();
    customMessageText = "";
    customMessageState = "info";
    syncCustomSection();
  }

  async function loadCustomModels() {
    const provider = customProvider();
    if (!provider || !provider.supports_model_listing || customModelState === "loading") return;
    const copy = customCopy();
    if (!customCredential()) {
      setCustomMessage(copy.keyRequired, "info");
      return;
    }
    const ticket = ++customModelSeq;
    customModelState = "loading";
    syncCustomSection();
    try {
      const response = await nativeFetch(
        "/api/chat/custom/models?provider=" + encodeURIComponent(provider.provider),
        {
          headers: { "Accept": "application/json" },
          cache: "no-store",
          credentials: "same-origin",
        },
      );
      const data = await response.json().catch(() => null);
      if (ticket !== customModelSeq) return;
      if (!response.ok || !data || data.ok !== true) {
        customModelState = "error";
        setCustomMessage(errorMessage(data) || copy.modelsFailed, "error");
        return;
      }
      customModelOptions = (Array.isArray(data.models) ? data.models : [])
        .filter((row) => typeof row === "string" && row.length > 0 && row.length <= 200)
        .slice(0, 500);
      customModelState = "ready";
      setCustomMessage(copy.modelsLoaded, "ok");
    } catch (_) {
      if (ticket !== customModelSeq) return;
      customModelState = "error";
      setCustomMessage(copy.modelsFailed, "error");
    }
    syncCustomSection();
  }

  async function testCustomConnection() {
    const provider = customProvider();
    if (!provider || !provider.supports_connection_test || customTestState === "testing") return;
    const copy = customCopy();
    if (!customCredential()) {
      setCustomMessage(copy.keyRequired, "info");
      return;
    }
    customTestState = "testing";
    setCustomMessage("", "info");
    syncCustomSection();
    try {
      const response = await nativeFetch(
        "/api/chat/custom/credential/test?provider=" + encodeURIComponent(provider.provider),
        {
          headers: { "Accept": "application/json" },
          cache: "no-store",
          credentials: "same-origin",
        },
      );
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || data.ok !== true) {
        if (response.status === 401) {
          customTestState = "idle";
          clearCustomState();
          setCustomMessage(copy.authExpired, "error");
          void refreshAuth();
          return;
        }
        customTestState = "idle";
        setCustomMessage(errorMessage(data) || copy.testFailed, "error");
        return;
      }
      customTestState = "idle";
      setCustomMessage(copy.testOk, "ok");
    } catch (_) {
      customTestState = "idle";
      setCustomMessage(copy.testFailed, "error");
    }
    syncCustomSection();
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
        .filter((row) => row && typeof row.provider === "string" && row.provider)
        .slice(0, 8)
        .map((row) => {
          const listed = Array.isArray(row.models)
            ? row.models.filter((model) => typeof model === "string"
              && model.length > 0 && model.length <= 200)
            : (typeof row.model === "string" && row.model ? [row.model] : []);
          return Object.freeze({
            provider: row.provider,
            display_name: text(row.display_name, 120) || customCopy().option,
            models: Object.freeze(listed.slice(0, 500)),
            manual_model: row.manual_model === true,
            supports_model_listing: row.supports_model_listing === true,
            supports_connection_test: row.supports_connection_test === true,
            supports_custom_endpoint: row.supports_custom_endpoint === true,
            default_endpoint: typeof row.default_endpoint === "string" ? row.default_endpoint : "",
          });
        });
      const known = new Set(customProviders.map((row) => row.provider));
      customCredentials = credentials
        .filter((row) => row && known.has(row.provider)
          && typeof row.key_last4 === "string" && row.key_last4.length > 0)
        .map((row) => Object.freeze({
          provider: row.provider,
          key_last4: row.key_last4.replace(/[^A-Za-z0-9]/g, "").slice(-4),
          endpoint: typeof row.endpoint === "string" ? row.endpoint : "",
          endpoint_is_default: row.endpoint_is_default !== false,
        }));
      customLoadState = customProviders.length ? "ready" : "unavailable";
      if (!customProviders.length) customLoadError = customCopy().unavailable;
      if (!customProviders.some((row) => row.provider === customProviderId)) {
        customProviderId = customProviders.length ? customProviders[0].provider : null;
        customModelValue = "";
        customModelOptions = [];
        customModelState = "idle";
        customModelSeq += 1;
        customTestState = "idle";
        if (customModelInput) customModelInput.value = "";
        if (customEndpointInput) customEndpointInput.value = "";
      }
      const provider = customProvider();
      if (provider) {
        if (!provider.manual_model && !provider.models.includes(customModelValue)) {
          customModelValue = provider.models[0] || "";
        }
        if (customModelInput) customModelInput.value = customModelValue;
      }
      if (customSelection) {
        const selectedProvider = customProviders.find(
          (row) => row.provider === customSelection.provider,
        );
        const stillValid = selectedProvider && customSelection.model
          && (selectedProvider.manual_model
            || selectedProvider.models.includes(customSelection.model));
        customSelection = stillValid
          ? { provider: selectedProvider.provider, model: customSelection.model }
          : null;
      }
      const credential = customCredential();
      if (customEndpointInput && credential
          && credential.endpoint_is_default === false && credential.endpoint) {
        customEndpointInput.value = credential.endpoint;
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
    const endpoint = customEndpointInput
      ? String(customEndpointInput.value || "").trim() : "";
    const payload = { provider: provider.provider, api_key: key };
    if (endpoint) payload.endpoint = endpoint;
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
        body: JSON.stringify(payload),
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
      const stored = customCredential();
      if (customEndpointInput) {
        customEndpointInput.value = stored
          && stored.endpoint_is_default === false && stored.endpoint
          ? stored.endpoint : "";
      }
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
      if (customEndpointInput) customEndpointInput.value = "";
      customTestState = "idle";
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
    const customCopyBlock = document.createElement("span");
    customCopyBlock.className = "mode-option-copy";
    customOptionTitle = document.createElement("strong");
    customOptionModel = document.createElement("small");
    customOptionModel.className = "mode-option-model";
    customCopyBlock.append(customOptionTitle, customOptionModel);
    customOptionState = document.createElement("span");
    customOptionState.className = "mode-option-state";
    customOption.append(customCopyBlock, customOptionState);
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

    // Every provider and model rendered here comes from the server capability
    // payload. The browser never invents a provider/model that the server will
    // not accept, and a manually typed model is passed through for the provider
    // to accept or reject rather than being treated as a success.
    customProviderLabelEl = document.createElement("label");
    customProviderLabelEl.className = "mode-custom-key-label";
    customProviderLabelEl.htmlFor = "modeCustomProvider";
    customProviderLabelEl.textContent = copy.providerLabel;
    customProviderSelect = document.createElement("select");
    customProviderSelect.id = "modeCustomProvider";
    customProviderSelect.className = "mode-custom-select";
    customProviderSelect.addEventListener("change", () => {
      selectCustomProvider(customProviderSelect.value);
    });

    customModelLabelEl = document.createElement("label");
    customModelLabelEl.className = "mode-custom-key-label";
    customModelLabelEl.htmlFor = "modeCustomModelSelect";
    customModelLabelEl.textContent = copy.modelLabel;
    customModelSelect = document.createElement("select");
    customModelSelect.id = "modeCustomModelSelect";
    customModelSelect.className = "mode-custom-select";
    customModelSelect.addEventListener("change", onCustomModelChanged);
    customModelInput = document.createElement("input");
    customModelInput.type = "text";
    customModelInput.id = "modeCustomModelInput";
    customModelInput.className = "mode-custom-key-input";
    customModelInput.autocomplete = "off";
    customModelInput.maxLength = 200;
    customModelInput.placeholder = copy.modelPlaceholder;
    customModelInput.setAttribute("list", "modeCustomModelOptions");
    customModelInput.setAttribute("autocapitalize", "off");
    customModelInput.setAttribute("spellcheck", "false");
    customModelInput.hidden = true;
    customModelInput.addEventListener("input", onCustomModelChanged);
    customModelDatalist = document.createElement("datalist");
    customModelDatalist.id = "modeCustomModelOptions";
    customModelListButton = document.createElement("button");
    customModelListButton.type = "button";
    customModelListButton.className = "mode-custom-action mode-custom-model-load";
    customModelListButton.textContent = copy.loadModels;
    customModelListButton.hidden = true;
    customModelListButton.addEventListener("click", () => void loadCustomModels());

    customEndpointLabelEl = document.createElement("label");
    customEndpointLabelEl.className = "mode-custom-key-label";
    customEndpointLabelEl.htmlFor = "modeCustomEndpoint";
    customEndpointLabelEl.textContent = copy.endpointLabel;
    customEndpointInput = document.createElement("input");
    customEndpointInput.type = "url";
    customEndpointInput.id = "modeCustomEndpoint";
    customEndpointInput.className = "mode-custom-key-input";
    customEndpointInput.autocomplete = "off";
    customEndpointInput.maxLength = 2048;
    customEndpointInput.setAttribute("autocapitalize", "off");
    customEndpointInput.setAttribute("spellcheck", "false");
    customEndpointInput.setAttribute("aria-describedby", "modeCustomEndpointHint");
    customEndpointHintEl = document.createElement("small");
    customEndpointHintEl.className = "mode-custom-hint";
    customEndpointHintEl.id = "modeCustomEndpointHint";
    customEndpointHintEl.textContent = copy.endpointHint;

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
    customTestButton = document.createElement("button");
    customTestButton.type = "button";
    customTestButton.className = "mode-custom-action mode-custom-test";
    customTestButton.textContent = copy.test;
    customTestButton.hidden = true;
    customTestButton.addEventListener("click", () => void testCustomConnection());
    actions.append(customSaveButton, customDeleteButton, customTestButton);

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

    form.append(
      status,
      customProviderLabelEl,
      customProviderSelect,
      customModelLabelEl,
      customModelSelect,
      customModelInput,
      customModelDatalist,
      customModelListButton,
      customEndpointLabelEl,
      customEndpointInput,
      customEndpointHintEl,
      label,
      customInput,
      actions,
      hint,
      customMessageEl,
      customRetryButton,
    );

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
        void persistAccountSelection(tier);
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
      void persistAccountSelection(tier);
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
      truth.textContent = selectedTier === "admin" ? copy.adminNote : copy.truth;
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

  async function refreshAdminPresence(epoch) {
    // The B62 product's own operator authority (/api/b66/admin/me) reports
    // the verified Google admin with HTTP 200 {ok, admin} — guests and
    // ordinary members simply get admin:false, so no error text is needed.
    // #5222: a probe that could not complete is reported as unknown, never as
    // a denial, so a temporary failure neither hides nor destroys anything.
    if (!auth.authenticated) {
      adminAvailable = false;
      adminVerified = false;
      adminProbeInFlight = null;
      adminProbeAt = 0;
      syncAdminOption();
      return false;
    }
    const ticket = epoch === undefined ? authEpoch : epoch;
    const ttl = adminVerified ? ADMIN_PROBE_TTL_MS : ADMIN_PROBE_UNVERIFIED_TTL_MS;
    if (Date.now() - adminProbeAt < ttl) {
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
        if (!response.ok) return "unknown";
        const data = await response.json().catch(() => null);
        if (!data || data.ok !== true) return "unknown";
        const state = typeof data.state === "string" ? data.state : "";
        if (state === "admin") return "admin";
        if (state === "not_admin" || state === "guest") return "not_admin";
        if (state === "unavailable") return "unknown";
        if (typeof data.admin === "boolean") return data.admin === true ? "admin" : "not_admin";
        return "unknown";
      } catch (_) {
        return "unknown";
      } finally {
        window.clearTimeout(timer);
      }
    })();
    adminProbeInFlight = probe;
    let state = "unknown";
    try {
      state = await probe;
    } finally {
      adminProbeInFlight = null;
    }
    if (ticket !== authEpoch) return adminAvailable;
    adminAvailable = state === "admin";
    adminVerified = state === "admin" || state === "not_admin";
    adminProbeAt = Date.now();
    if (!adminAvailable && selectedTier === "admin") {
      // The administrator lane is not executable right now. The account's
      // stored preference stays on the server and returns with the next
      // verified administrator probe. What the browser shows meanwhile is the
      // account's own highest tier that IS executable right now.
      commitTier(highestAvailableTier());
    }
    syncAdminOption();
    if (!adminAvailable && !adminVerified) {
      scheduleAdminProbeRetry();
    }
    return adminAvailable;
  }

  function scheduleAdminProbeRetry() {
    if (adminProbeRetryTimer !== null) return;
    adminProbeRetryTimer = window.setTimeout(() => {
      adminProbeRetryTimer = null;
      if (!auth.authenticated) return;
      void refreshAuth();
    }, ADMIN_PROBE_RETRY_MS);
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
    authEpoch += 1;
    const epoch = authEpoch;
    if (!auth.authenticated) clearCustomState();
    await refreshAdminPresence(epoch);
    if (auth.authenticated) {
      // #5222: restore this account's own last selection, after the server
      // re-verified the member grade and the administrator lane.
      await refreshAccountSelection(epoch);
    } else {
      // A signed-out browser keeps no account selection.
      accountSelection = null;
    }
    const selectionValid = selectedTier === "admin"
      ? adminAvailable
      : availableTiers().includes(selectedTier);
    if (!selectionValid) {
      // The account keeps the tier it really has; it never falls back to the
      // Free tier while a higher tier is the one it is entitled to.
      selectedTier = highestAvailableTier();
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
      // #5222: a signed-out browser keeps no account selection. The other
      // account's stored preference stays on the server for that account only.
      accountSelection = null;
      commitTier("free");
      clearCustomState();
      syncCustomSection();
      void refreshAuth();
      return;
    }
    void refreshCustomStatus();
    // A new sign-in is a different account: re-read the server state so this
    // account's own stored preference is restored, never the previous one.
    void refreshAuth();
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
    set: (tier) => {
      const value = String(tier || "").toLowerCase();
      if (!selectTier(value)) return false;
      void persistAccountSelection(value);
      return true;
    },
    available: () => availableTiers(),
    open: openModePanel,
    close: () => closeModePanel({ restoreFocus: true }),
    ready: tierSelectionReady,
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