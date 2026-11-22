(() => {
  "use strict";

  const VALID_LOCALES = ["ko", "en"];
  const TRUSTED_AUTH_SESSION_STATES = new Set(["pending", "unavailable", "unreachable", "guest", "signed_in", "expired"]);
  const attachmentCapabilities = window.PadiemAttachmentCapabilities;
  const nativeConfirm = typeof window.confirm === "function" ? window.confirm.bind(window) : null;

  const labels = { ko: {}, en: {} };
  for (const group of Object.values(window.PadiemLocaleGroups || {})) {
    Object.assign(labels.ko, group.ko || {});
    Object.assign(labels.en, group.en || {});
  }

  const promptCopy = {
    ko: {
      explain: "AI를 아주 쉽게 설명해줘", trip: "3박 4일 제주도 가족 여행 계획을 짜줘", dinner: "오늘 저녁 메뉴를 세 가지 추천해줘",
      starterExplain: "AI를 처음 쓰는 사람에게 AI가 뭔지 아주 쉽게 설명해줘", starterLife: "이번 주말 가족과 집 근처에서 할 만한 일을 추천해줘", starterWriting: "목적과 읽는 사람에 맞는 이메일이나 문장 초안을 작성해줘"
    },
    en: {
      explain: "Explain AI in very simple terms.", trip: "Plan a four-day family trip to Jeju.", dinner: "Suggest three dinner ideas for tonight.",
      starterExplain: "Explain what AI is in very simple terms for someone using it for the first time.", starterLife: "Suggest things my family can do near home this weekend.", starterWriting: "Draft an email or short piece of writing for the intended audience and purpose."
    }
  };

  const exactPairs = [
    ["프로젝트 삭제", "Delete project"], ["관리", "Manage"], ["삭제", "Delete"], ["저장", "Save"], ["복사", "Copy"], ["다운로드", "Download"],
    ["답변 준비 중", "Preparing answer"], ["저장된 대화", "Saved conversation"], ["모의 응답 · 실제 모델 호출 없음", "Preview response · no live model call"], ["AI 응답", "AI response"],
    ["어떤 AI가 답했나요?", "Which AI answered?"], ["다시 시도", "Try again"], ["응답 시간 초과", "Response timed out"], ["연결 오류", "Connection error"],
    ["설정 필요", "Setup needed"], ["로그인 후", "Log in first"], ["확인 중", "Checking"], ["새로 만들기", "Create new"], ["비어 있음", "Empty"],
    ["프로젝트 지침·파일", "Project instructions & files"], ["새 프로젝트", "New project"], ["복사됨", "Copied"], ["복사 실패", "Copy failed"], ["저장됨", "Saved"], ["저장 실패", "Save failed"],
    ["코드", "Code"], ["표", "Table"], ["CSV 다운로드", "Download CSV"], ["출처", "Sources"], ["대화 내보내기", "Export conversation"], ["답변 작업", "Answer actions"]
  ];

  function normalizeLocale(value) {
    return VALID_LOCALES.includes(value) ? value : null;
  }

  function getUrlLocale() {
    try {
      return normalizeLocale(new URLSearchParams(window.location.search).get("lang"));
    } catch (_) {
      return null;
    }
  }

  function getCurrent() {
    return document.documentElement.lang === "en" ? "en" : "ko";
  }

  function text(key, lang = getCurrent(), variables = null) {
    const locale = normalizeLocale(lang) || "ko";
    let value = labels[locale][key] || labels.ko[key] || key;
    if (variables && typeof variables === "object") {
      Object.entries(variables).forEach(([name, replacement]) => {
        value = value.replaceAll(`{${name}}`, String(replacement));
      });
    }
    return value;
  }

  function setText(selector, key, lang) {
    const element = document.querySelector(selector);
    const value = text(key, lang);
    if (element && element.textContent !== value) element.textContent = value;
  }

  function setAttribute(selector, attribute, key, lang) {
    const element = document.querySelector(selector);
    if (!element) return;
    const value = text(key, lang);
    if (element.getAttribute(attribute) !== value) element.setAttribute(attribute, value);
  }

  function setPrompt(selector, key, lang) {
    const element = document.querySelector(selector);
    if (!element) return;
    const value = promptCopy[lang][key];
    if (value && element.dataset.prompt !== value) element.dataset.prompt = value;
  }

  function setCombinedHeading(lang) {
    const heading = document.querySelector(".empty-state h1");
    if (!heading) return;
    // Shared Chat/Claw heading must keep BOTH product-specific spans in the
    // original DOM. Replacing children destroys Claw copy and mode CSS.
    if (heading.querySelector(".claw-hero-line")) {
      for (const key of ("hello", "ask", "claw-home-intro", "claw-home-question")) {
        const target = heading.querySelector('[data-locale-key="' + key + '"]');
        if (target) target.textContent = text(key, lang);
      }
      return;
    }
    const first = document.createElement("span");
    first.dataset.localeKey = "hello";
    first.textContent = text("hello", lang);
    const second = document.createElement("span");
    second.dataset.localeKey = "ask";
    second.textContent = text("ask", lang);
    heading.replaceChildren(first, document.createElement("br"), second);
  }

  function syncLoginButton(lang) {
    const button = document.getElementById("loginButton");
    if (!button) return;
    const accountRoot = button.closest(".sidebar-account");
    const state = accountRoot?.dataset.accountState || "";
    const raw = button.textContent.trim();

    if (state === "unreachable") {
      // #5479: the status request produced no answer. This is not a signed-out
      // account, so the button keeps the sign-in label and says why.
      button.dataset.authenticated = "false";
      button.textContent = text("login", lang);
      button.title = text("login-unreachable-title", lang);
      return;
    }

    if (state === "expired" || raw === "다시 로그인" || raw === "Sign in again") {
      button.dataset.authenticated = "false";
      button.textContent = text("sign-in-again", lang);
      button.title = text("expired-title", lang);
      return;
    }

    if (state === "signed_in" || raw === "로그아웃" || raw === "Log out") {
      button.dataset.authenticated = "true";
    } else if (state === "guest" || state === "unavailable" || state === "pending" || raw === "로그인" || raw === "Log in") {
      button.dataset.authenticated = "false";
    }

    const authenticated = button.dataset.authenticated === "true";
    button.textContent = authenticated ? text("logout", lang) : text("login", lang);
    button.title = state === "unavailable" || button.disabled
      ? text("login-unavailable-title", lang)
      : authenticated
        ? text("logout-title", lang)
        : text("login-title", lang);
  }

  function syncLoginButtonFromCapability(event) {
    const state = event?.detail?.auth?.sessionState;
    if (!TRUSTED_AUTH_SESSION_STATES.has(state)) return;
    const button = document.getElementById("loginButton");
    const accountRoot = button?.closest(".sidebar-account");
    if (!button || !accountRoot || accountRoot.dataset.accountState !== state) return;
    syncLoginButton(getCurrent());
  }

  function applyStaticBindings(lang) {
    const textBindings = [
      ["#newChatButton span:last-child", "new-chat"], ["#sidebarSearchButton span:last-child", "search"], ["#projectsNavButton span:nth-child(2)", "projects"], ["#outputsNavButton span:nth-child(2)", "saved"],
      [".empty-copy", "copy"], ["#pcConnectStarter strong", "pc-connect-title"], [".starter:nth-child(2) strong", "life-title"], [".starter:nth-child(2) small", "life-copy"],
      [".starter:nth-child(3) strong", "document-title"], ["#attachmentButton span:last-child", "file"], [".sidebar-footer span:last-child", "footer"],
      ["#projectsTitle", "projects"], ["#projectsEmpty", "projects-empty"], ["#historyTitle", "history-title"], ["#historyEmpty", "history-empty"], ["#outputsTitle", "saved"], ["#outputsEmpty", "outputs-empty"],
      ["#writingStarterButton strong", "writing-starter-title"], ["#writingStarterButton small", "writing-starter-copy"], [".project-banner-copy > span", "project-banner"], ["#editProjectButton", "project-edit"], ["#exitProjectButton", "project-exit"],
      ["#projectDialogTitle", "project-new"], ["label[for='projectNameInput']", "project-name"], ["#projectFilesTitle", "project-files"], [".project-files-heading small", "project-files-limit"], [".project-file-add", "project-file-add"],
      ["#projectFilesEmpty", "project-files-empty"], [".project-files-note", "project-files-note"], ["#projectDialogCancel", "cancel"], ["#projectSaveButton", "save"],
      ["#savedOutputDialogTitle", "saved-output-title"], ["label[for='savedOutputTitleInput']", "title"], ["#savedOutputCopy", "copy-action"], ["#savedOutputDownload", "download"], ["#savedOutputRename", "save-title"], ["#savedOutputDelete", "delete"], ["#cancelStreamButton", "cancel"]
    ];
    textBindings.forEach(([selector, key]) => setText(selector, key, lang));
    document.querySelectorAll("[data-locale-key]").forEach((element) => {
      const key = element.dataset.localeKey;
      if (key) element.textContent = text(key, lang);
    });
    document.querySelectorAll("[data-locale-aria-label]").forEach((element) => {
      const key = element.dataset.localeAriaLabel;
      if (key) element.setAttribute("aria-label", text(key, lang));
    });
    [
      ["data-locale-placeholder", "placeholder", "localePlaceholder"],
      ["data-locale-title", "title", "localeTitle"],
      ["data-locale-alt", "alt", "localeAlt"],
      ["data-locale-content", "content", "localeContent"]
    ].forEach(([attribute, target, datasetKey]) => {
      document.querySelectorAll(`[${attribute}]`).forEach((element) => {
        const key = element.dataset[datasetKey];
        if (!key) return;
        // Owner 2026-10-20: an element that carries the shared PADIEM chip
        // tooltip keeps its hint on the chip. Writing a native title here
        // would show the browser popup next to the chip.
        if (attribute === "data-locale-title" && element.hasAttribute("data-padiem-tooltip")) return;
        element.setAttribute(target, text(key, lang));
      });
    });
    // The shared chip label follows the locale like any other hint.
    document.querySelectorAll("[data-padiem-tooltip][data-locale-title]").forEach((element) => {
      const key = element.dataset.localeTitle;
      if (!key) return;
      element.setAttribute("data-padiem-tooltip", text(key, lang));
      element.removeAttribute("title");
    });
    setCombinedHeading(lang);
    const input = document.getElementById("messageInput");
    if (input) input.placeholder = text("input", lang);
    const projectName = document.getElementById("projectNameInput");
    if (projectName) projectName.placeholder = text("project-name-placeholder", lang);
    const projectInstructions = document.getElementById("projectInstructionsInput");
    if (projectInstructions) projectInstructions.placeholder = text("project-instructions-placeholder", lang);
    const clawSender = document.getElementById("clawSender");
    if (clawSender) clawSender.placeholder = text("claw-sender-placeholder", lang);
    // #2532: the Claw request placeholder now lives on #messageInput and is re-applied
    // by app.js on the padiem:localechange event while data-state="claw".
    const instructionLabel = document.querySelector("label[for='projectInstructionsInput']");
    if (instructionLabel) {
      const primary = instructionLabel.querySelector("[data-project-instructions-label]");
      const optional = instructionLabel.querySelector("[data-project-instructions-optional]");
      if (primary) primary.textContent = text("project-instructions", lang);
      if (optional) optional.textContent = text("optional", lang);
    }
    setText(".project-form-note", "project-instructions-note", lang);
    [
      ["#sidebar", "aria-label", "main-menu"], ["#mobileClose", "aria-label", "close-menu"], [".brand", "aria-label", "home-aria"], [".home-link", "aria-label", "home-open"], [".side-nav", "aria-label", "chat-menu"], ["#workspaceNav", "aria-label", "tools-menu"],
      ["#projectCreateButton", "aria-label", "create-project-aria"], [".sidebar-bottom", "aria-label", "account-settings"], ["#mobileMenu", "aria-label", "open-menu"], [".model-pill", "aria-label", "tier"], ["#settingsCloseButton", "aria-label", "settings-close"],
      ["#themePicker", "aria-label", "theme-picker"], ["#languagePicker", "aria-label", "language-picker"], [".starter-grid", "aria-label", "starter-grid"], [".composer-wrap", "aria-label", "composer"], ["#attachmentThumb", "alt", "attachment-preview-alt"],
      ["#removeAttachment", "aria-label", "attachment-remove"], ["#cancelStreamButton", "aria-label", "cancel-answer"], ["#sendButton", "aria-label", "send"],
      ["#projectDialogClose", "aria-label", "project-close"], ["#savedOutputClose", "aria-label", "saved-output-close"], ["#savedOutputContent", "aria-label", "saved-output-content"],
      ["#clawManualForm", "aria-label", "claw-form-aria"], [".claw-chips", "aria-label", "claw-actions-aria"], ["#connectorsDialog .capability-grid, #connectorsViewBody .capability-grid", "aria-label", "connectors-grid-aria"]
    ].forEach(([selector, attribute, key]) => setAttribute(selector, attribute, key, lang));
    const messageLabel = document.querySelector("label[for='messageInput']");
    if (messageLabel) messageLabel.textContent = text("message-input-label", lang);
    // The #1735 sidebar no longer carries a demo question list, so no binding
    // here may address the shared recent-row class: project, conversation,
    // search-hit and saved answer rows all carry it, and an unscoped
    // nth-of-type binding would overwrite a stored row's title (or its click
    // prompt) with starter copy whenever the row happened to render before this
    // function ran.
    // #5634: the first first-screen card is the computer connection entry, not a
    // prompt, so it carries no data-prompt and gets no prompt copy.
    setPrompt(".starter:nth-child(2)", "starterLife", lang);
    setPrompt("#writingStarterButton", "starterWriting", lang);
  }

  function syncAttachmentCapabilityCopy(lang) {
    if (!attachmentCapabilities) return;
    const capabilityCopy = attachmentCapabilities.copy(lang);
    const documentCopy = document.querySelector(".starter:nth-child(3) small");
    if (documentCopy) {
      const formats = capabilityCopy.documentFormats;
      documentCopy.textContent = lang === "en" ? formats : formats.split("·").join(" · \u200b");
    }
    const attachmentInput = document.getElementById("attachmentFileInput");
    if (attachmentInput) attachmentInput.accept = attachmentCapabilities.accept;
    const attachmentButton = document.getElementById("attachmentButton");
    if (attachmentButton) window.PadiemSharedTooltip?.label?.(attachmentButton, capabilityCopy.fileButtonTitle);
  }

  window.addEventListener("padiem:file-lane-capability", () => syncAttachmentCapabilityCopy(getCurrent()));

  function syncBinaryAttachmentSupport() {
    if (typeof fetch !== "function") return;
    fetch("/health", { headers: { "Accept": "application/json" }, cache: "no-store" })
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (!data || typeof data.binary_document_attachment_ready !== "boolean") return;
        if (typeof attachmentCapabilities.setBinarySupport !== "function") return;
        attachmentCapabilities.setBinarySupport(data.binary_document_attachment_ready);
        syncAttachmentCapabilityCopy(getCurrent());
        window.dispatchEvent(new CustomEvent("padiem:attachmentcapabilitychange"));
      })
      .catch(() => {});
  }

  function syncGlassCopy(lang) {
    const glassTheme = document.querySelector('[data-theme-value="padiem-glass"]');
    if (glassTheme) glassTheme.textContent = text("glass-theme", lang);
    const label = document.querySelector(".glass-variant-label");
    if (label) label.textContent = text("glass-background", lang);
    const group = document.querySelector(".glass-variant-picker");
    if (group) group.setAttribute("aria-label", text("glass-background-selection", lang));
    const a = document.querySelector('[data-glass-variant-value="female"]');
    const b = document.querySelector('[data-glass-variant-value="male"]');
    if (a) a.textContent = text("glass-a", lang);
    if (b) b.textContent = text("glass-b", lang);
  }

  function exactTranslation(value, lang) {
    const raw = String(value || "").trim();
    for (const [ko, en] of exactPairs) {
      if (raw === ko || raw === en) return lang === "en" ? en : ko;
    }
    return raw;
  }

  function localizeExistingDynamicControls(lang) {
    const selectors = [
      ".project-manage", ".project-file-row button", ".history-delete", "#projectDeleteButton", ".demo-label[data-runtime-label]", ".retry-button",
      ".answer-actions", ".answer-action", ".rich-code-header > span", ".rich-code-copy", ".rich-table-actions > span", ".rich-table-download", ".answer-sources-title", "#conversationExportButton"
    ];
    selectors.forEach((selector) => document.querySelectorAll(selector).forEach((element) => {
      const translated = exactTranslation(element.textContent, lang);
      if (translated !== element.textContent) element.textContent = translated;
    }));
    document.querySelectorAll(".project-manage").forEach((button) => {
      const name = button.closest(".project-row")?.querySelector(".project-item")?.textContent || "";
      if (name) button.setAttribute("aria-label", lang === "en" ? `Manage project ‘${name}’` : `‘${name}’ 프로젝트 관리`);
    });
    document.querySelectorAll(".history-delete").forEach((button) => {
      const title = button.closest(".history-row")?.querySelector(".history-item")?.textContent || "";
      if (title) button.setAttribute("aria-label", lang === "en" ? `Delete conversation ‘${title}’` : `‘${title}’ 대화 삭제`);
    });
    const projectDelete = document.getElementById("projectDeleteButton");
    if (projectDelete) projectDelete.setAttribute("aria-label", text("project-delete-aria", lang));
    const answerActions = document.querySelectorAll(".answer-actions");
    answerActions.forEach((element) => element.setAttribute("aria-label", text("answer-actions", lang)));
    const sources = document.querySelectorAll(".answer-sources");
    sources.forEach((element) => element.setAttribute("aria-label", text("sources-aria", lang)));
    const exportButton = document.getElementById("conversationExportButton");
    if (exportButton) exportButton.setAttribute("aria-label", text("export-aria", lang));
    if (exportButton) exportButton.textContent = text("export", lang);
  }

  function translateConfirmMessage(message, lang) {
    const raw = String(message || "");
    let match = raw.match(/^‘(.+)’ 파일을 프로젝트에서 삭제할까요\?$|^Remove ‘(.+)’ from this project\?$/);
    if (match) {
      const name = match[1] || match[2];
      return lang === "en" ? `Remove ‘${name}’ from this project?` : `‘${name}’ 파일을 프로젝트에서 삭제할까요?`;
    }
    match = raw.match(/^‘(.+)’ 대화를 삭제할까요\?\n삭제한 대화는 되돌릴 수 없습니다\.$|^Delete conversation ‘(.+)’\?\nThis cannot be undone\.$/);
    if (match) {
      const title = match[1] || match[2];
      return lang === "en" ? `Delete conversation ‘${title}’?\nThis cannot be undone.` : `‘${title}’ 대화를 삭제할까요?\n삭제한 대화는 되돌릴 수 없습니다.`;
    }
    match = raw.match(/^‘(.+)’ 프로젝트를 삭제할까요\?\n프로젝트의 대화는 남지만 프로젝트 연결은 해제됩니다\. 삭제한 프로젝트는 되돌릴 수 없습니다\.$|^Delete project ‘(.+)’\?\nIts conversations remain, but the project link is removed\. This cannot be undone\.$/);
    if (match) {
      const name = match[1] || match[2];
      return lang === "en" ? `Delete project ‘${name}’?\nIts conversations remain, but the project link is removed. This cannot be undone.` : `‘${name}’ 프로젝트를 삭제할까요?\n프로젝트의 대화는 남지만 프로젝트 연결은 해제됩니다. 삭제한 프로젝트는 되돌릴 수 없습니다.`;
    }
    if (raw === "이 저장한 답변을 삭제할까요? 원래 대화는 삭제되지 않습니다." || raw === "Delete this saved answer? The original conversation will remain.") {
      return lang === "en" ? "Delete this saved answer? The original conversation will remain." : "이 저장한 답변을 삭제할까요? 원래 대화는 삭제되지 않습니다.";
    }
    return raw;
  }

  function installConfirmLocalization() {
    if (!nativeConfirm || window.confirm.__padiemLocalized === true) return;
    const localizedConfirm = (message) => nativeConfirm(translateConfirmMessage(message, getCurrent()));
    localizedConfirm.__padiemLocalized = true;
    window.confirm = localizedConfirm;
  }

  function persistLocale(lang) {
    try {
      const url = new URL(window.location.href);
      if (url.searchParams.get("lang") === lang) return;
      url.searchParams.set("lang", lang);
      history.replaceState(null, "", url.toString());
    } catch (_) {}
  }

  function apply(lang, persist = false) {
    const locale = normalizeLocale(lang) || "ko";
    const previous = document.documentElement.lang;
    document.documentElement.lang = locale;
    if (persist) persistLocale(locale);
    applyStaticBindings(locale);
    syncAttachmentCapabilityCopy(locale);
    syncGlassCopy(locale);
    syncLoginButton(locale);
    localizeExistingDynamicControls(locale);
    document.querySelectorAll("[data-locale-value]").forEach((button) => {
      const active = button.dataset.localeValue === locale;
      button.setAttribute("aria-pressed", String(active));
      if (active) button.setAttribute("aria-current", "true"); else button.removeAttribute("aria-current");
    });
    // The event reports a change, not a paint. The first paint of a page whose
    // markup already carries this locale changes nothing, and dispatching it
    // anyway re-enters the app boot: app.js answers localechange with
    // applyAuthState(), which opens a new session generation and drops the
    // conversation read that is still in flight — the sidebar then keeps its
    // loading skeleton until something else reloads it.
    if (previous !== locale) {
      window.dispatchEvent(new CustomEvent("padiem:localechange", { detail: { lang: locale } }));
    }
    return locale;
  }

  function init() {
    installConfirmLocalization();
    apply(getUrlLocale() || "ko", false);
    syncBinaryAttachmentSupport();
    document.getElementById("languagePicker")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-locale-value]");
      const requested = button ? normalizeLocale(button.dataset.localeValue) : null;
      if (requested) apply(requested, true);
    });
    window.addEventListener("popstate", () => apply(getUrlLocale() || "ko", false));
  }

  window.__padiemLocale = {
    VALID: VALID_LOCALES.slice(), apply, getCurrent, getUrlLocale,
    text: (key, variables = null) => text(key, getCurrent(), variables),
    localizeExisting: () => localizeExistingDynamicControls(getCurrent())
  };

  window.addEventListener("padiem:capabilitychange", syncLoginButtonFromCapability);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true }); else init();
})();
