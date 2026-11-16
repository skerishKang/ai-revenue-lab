// #7216 R5 - auth section (moved out of the app.js closure).
// No behavior, copy, DOM id or event name change. Shared state and DOM refs are
// read/written only through the deps getters/setters. app.js keeps the same-named
// one-line forwarders.
(() => {
  "use strict";
  window.PadiemChatAuthModule = {
    create(deps) {
  function closeProfilePanel(restoreFocus = false) {
    deps.profilePanel.hidden = true;
    deps.profileToggle.setAttribute("aria-expanded", "false");
    if (restoreFocus && !deps.accountContainer?.hidden) deps.profileToggle.focus();
  }
  function accountInitial(name) {
    const text = String(name || "").trim();
    if (!text) return "";
    const first = Array.from(text)[0] || "";
    return first.toLocaleUpperCase();
  }
  function resolveSessionPresentation(sessionState) {
    return deps.SESSION_PRESENTATION[sessionState] || deps.SESSION_PRESENTATION.unreachable;
  }
  function setLoginButtonCopy(text, title) {
    // #7164: identical writes are skipped. Writing textContent replaces the
    // child node even when the value is the same, and the login button's
    // DOM watcher (product-capabilities.js) treats every rewrite
    // as a signal and re-fetch.
    if (deps.loginButton.textContent !== text) deps.loginButton.textContent = text;
    if (deps.loginButton.getAttribute("title") !== title) deps.loginButton.setAttribute("title", title);
  }
  function applyAuthState(data) {
    deps.authViewEpoch += 1;
    deps.authState = data && typeof data === "object" ? data : { ready: false, authenticated: false, user: null, history_ready: false, project_files_ready: false };
    const ready = deps.authState.ready === true;
    const authenticated = ready && deps.authState.authenticated === true;
    if (authenticated && deps.pendingNotificationRunId) {
      const notificationRunId = deps.pendingNotificationRunId;
      deps.pendingNotificationRunId = "";
      const remaining = String((window.location && window.location.search) || "")
        .replace(/^\?/, "").split("&").filter(Boolean)
        .filter((part) => part !== "notify=run" && !part.startsWith("run_id="));
      window.history.replaceState(
        null, "",
        window.location.pathname + (remaining.length ? `?${remaining.join("&")}` : "") + (window.location.hash || ""),
      );
      deps.openClawRunTarget(notificationRunId);
    }
    if (authenticated && deps.pendingNotificationConversationId) {
      const notificationConversationId = deps.pendingNotificationConversationId;
      deps.pendingNotificationConversationId = "";
      const remaining = String((window.location && window.location.search) || "")
        .replace(/^\?/, "").split("&").filter(Boolean)
        .filter((part) => part !== "notify=conversation" && !part.startsWith("conversation_id="));
      window.history.replaceState(
        null, "",
        window.location.pathname + (remaining.length ? `?${remaining.join("&")}` : "") + (window.location.hash || ""),
      );
      deps.openSavedConversation(notificationConversationId);
    }
    window.PadiemAuthSession.update(deps.authState, deps.authViewEpoch);
    // #5434: the password change is offered only for an account that owns a
    // password credential. The server owns that fact.
    // #5560: the Account section itself carries the sign-out entry for every
    // signed-in account; only the password change is method-specific.
    if (deps.accountSettingsSection) {
      deps.accountSettingsSection.hidden = !authenticated;
    }
    // #7476 본문 2: the basic settings dialog shows the signed-in account email
    // in full. The value is the session projection the client already owns
    // (authState.user.email, the same one the delete confirm uses); no request
    // is made here and no new API is introduced.
    if (deps.settingsAccountEmail) {
      const accountEmail = authenticated && deps.authState.user && typeof deps.authState.user.email === "string"
        ? deps.authState.user.email.trim()
        : "";
      deps.settingsAccountEmail.textContent = accountEmail;
      deps.settingsAccountEmail.hidden = !accountEmail;
    }
    // The advanced settings page carries the same account entries; its data
    // export section stays outside this gate so guests can export too.
    if (deps.advancedAccountSection) {
      deps.advancedAccountSection.hidden = !authenticated;
    }
    if (deps.accountPasswordActions) {
      deps.accountPasswordActions.hidden = !(authenticated && deps.authState.account_method === "password");
    }
    // The deletion entry follows the account section itself (every signed-in
    // account); the confirm block always resets when the auth state moves.
    if (deps.accountDeleteActions) {
      deps.accountDeleteActions.hidden = !authenticated;
    }
    if (deps.accountDeleteConfirm) {
      deps.accountDeleteConfirm.hidden = true;
      deps.resetAccountDeleteConfirm();
    }
    if (!authenticated) {
      // Auth loss hides the standalone Connectors/Automation pages the same
      // way the Claw automation panel never outlives its session. The moved
      // nodes stay mounted; reopening after sign-in reloads fresh state.
      const connectorsView = document.getElementById("connectorsView");
      if (connectorsView) connectorsView.hidden = true;
      if (deps.advancedSettingsView) deps.advancedSettingsView.hidden = true;
      const automationView = document.getElementById("automationView");
      if (automationView) automationView.hidden = true;
      if (deps.shell && (deps.shell.dataset.state === "connectors"
        || deps.shell.dataset.state === "automation"
        || deps.shell.dataset.state === "settings")) {
        deps.shell.dataset.state = "home";
        deps.setNavActive();
      }
    }
    // #5479: "unreachable" (the status request produced no answer) is a
    // different session state from "unavailable" (the server answered that the
    // session store is not ready). Only the latter is the server's own word.
    const sessionState = !ready
      ? (deps.authState.status_reachable === false ? "unreachable" : "unavailable")
      : authenticated
        ? "signed_in"
        : deps.authState.session_state === "expired"
          ? "expired"
          : "guest";
    const presentation = deps.resolveSessionPresentation(sessionState);
    // Owner decision 2026-11-05: invite a guest to sign in with one quiet line
    // on the first screen. The flag keeps this off the network-free CI mock.
    const guestLoginHint = document.getElementById("guestLoginHint");
    if (guestLoginHint) {
      guestLoginHint.hidden = !(sessionState === "guest" && deps.authState.model_requires_session === true);
    }

    if (deps.accountContainer) {
      deps.accountContainer.dataset.accountState = sessionState;
      deps.accountContainer.hidden = presentation.accountHidden;
    }
    deps.closeProfilePanel();
    if (deps.accountAvatar) {
      const displayName = sessionState === "signed_in" && typeof deps.authState.user?.name === "string"
        ? deps.authState.user.name.trim() : "";
      const firstCharacter = displayName ? Array.from(displayName)[0] : "";
      deps.accountAvatar.textContent = sessionState === "signed_in"
        ? (firstCharacter ? firstCharacter.toLocaleUpperCase() : "●")
        : sessionState === "expired" ? "!" : "●";
    }
    // #5560: the sign-out entry moved into Settings > Account, so the sidebar
    // keeps only the profile (name and avatar) as the one-step Settings entry.
    // The button element and its text stay: the auth projection and the
    // capability projection reads them as the session signal.
    deps.loginButton.hidden = presentation.loginHidden;
    const pendingLogin = document.getElementById("loginPending");
    if (pendingLogin) { pendingLogin.hidden = true; pendingLogin.style.display = "none"; }
    deps.loginButton.disabled = presentation.loginDisabled;
    deps.syncAuthDialogMethods();
    deps.loginButton.setAttribute("aria-disabled", presentation.loginDisabled ? "true" : "false");

    if (sessionState === "unavailable" || sessionState === "unreachable") {
      deps.setLoginButtonCopy(deps.uiT("login"), deps.uiT(sessionState === "unreachable" ? "login-unreachable-title" : "login-unavailable-title"));
      deps.accountName.hidden = presentation.accountNameHidden;
      deps.accountName.textContent = "";
      return;
    }

    if (sessionState === "signed_in") {
      deps.setLoginButtonCopy(deps.uiT("logout"), deps.uiT("logout-title"));
      const name = deps.authState.user && typeof deps.authState.user.name === "string" ? deps.authState.user.name.trim() : "";
      deps.accountName.textContent = name || deps.uiT("signed-in");
      deps.accountName.hidden = false;
      deps.historySection.hidden = false;
      if (deps.projectsBadge) deps.projectsBadge.textContent = deps.uiT("checking");
      return;
    }

    if (sessionState === "expired") {
      deps.setLoginButtonCopy(deps.uiT("sign-in-again"), deps.uiT("expired-title"));
      deps.accountName.textContent = deps.uiT("session-expired");
      deps.accountName.hidden = false;
      return;
    }

    deps.setLoginButtonCopy(deps.uiT("login"), deps.uiT("login-title"));
    deps.accountName.textContent = deps.uiT("guest");
    deps.accountName.hidden = false;
    // #7365: a guest sees the same 내 자료 group, honestly empty — the
    // section heading and the empty-state notes render without a fetch.
    deps.historyList.replaceChildren();
    deps.historySection.hidden = false;
    deps.historyEmpty.hidden = false;
    if (deps.historyActionStatus) {
      deps.historyActionStatus.hidden = true;
      deps.historyActionStatus.textContent = "";
    }
  }
  function authMethodEnabled(name) {
    return Boolean(deps.authState && deps.authState.methods && deps.authState.methods[name] === true);
  }
  function setAuthFormError(node, message = "") {
    if (!node) return;
    node.textContent = message;
    node.hidden = !message;
  }
  // #7729: the email entry is a plain link to the common login, so this dialog
  // owns no input fields. app.js adds no declaration for it — the module reads
  // the element itself, and a harness that injects it through deps still wins.
  function emailContinueElement() {
    if (deps.passwordLoginContinue) return deps.passwordLoginContinue;
    if (typeof document === "undefined") return null;
    return document.getElementById("passwordLoginContinue");
  }
  function syncAuthDialogMethods() {
    if (!deps.authDialog) return;
    const googleEnabled = deps.authMethodEnabled("google");
    const passwordEnabled = deps.authMethodEnabled("password");
    if (deps.googleLoginButton) deps.googleLoginButton.hidden = !googleEnabled;
    if (deps.authDivider) deps.authDivider.hidden = !(googleEnabled && passwordEnabled);
    // #5481: the login view and the two reset views are mutually exclusive.
    // The email entry is a link to the common login; no input fields remain
    // in this dialog, so it toggles exactly where the login form used to.
    const showLogin = passwordEnabled && deps.authDialogView === "login";
    const emailContinue = emailContinueElement();
    if (emailContinue) emailContinue.hidden = !showLogin;
    if (deps.passwordResetOpen) deps.passwordResetOpen.hidden = !passwordEnabled || deps.authDialogView !== "login";
    if (deps.passwordResetPanel) deps.passwordResetPanel.hidden = deps.authDialogView === "login";
    if (deps.passwordResetRequestView) deps.passwordResetRequestView.hidden = deps.authDialogView !== "request";
    if (deps.passwordResetConfirmView) deps.passwordResetConfirmView.hidden = deps.authDialogView !== "confirm";
    deps.renderAndroidHandoff();
  }
  function openAuthDialog() {
    if (!deps.authDialog) {
      if (deps.authMethodEnabled("google")) {
        if (deps.isAndroidWebView()) deps.startAndroidHandoff();
        else window.location.assign("/auth/google/start");
      }
      return;
    }
    // #5481: a mailed one-time link opens the reset confirm view directly.
    const token = deps.passwordResetTokenFromLocation();
    if (token) {
      deps.authDialogView = "confirm";
      deps.passwordResetToken = token;
    } else {
      deps.authDialogView = "login";
    }
    deps.syncAuthDialogMethods();
    deps.setAuthFormError(deps.passwordLoginError);
    deps.setAuthFormError(deps.passwordResetRequestError);
    deps.setAuthFormError(deps.passwordResetConfirmError);
    deps.setAuthStatusMessage(deps.passwordResetRequestStatus);
    deps.setAuthStatusMessage(deps.passwordResetConfirmStatus);
    if (typeof deps.authDialog.showModal === "function") {
      deps.authDialog.showModal();
    } else {
      deps.authDialog.setAttribute("open", "");
    }
    if (deps.authDialogView === "confirm") deps.passwordResetNew?.focus();
    else if (deps.authDialogView === "request") deps.passwordResetEmail?.focus();
    else if (emailContinueElement()) emailContinueElement().focus();
  }
  function closeAuthDialog() {
    if (!deps.authDialog) return;
    if (typeof deps.authDialog.close === "function") deps.authDialog.close();
    else deps.authDialog.removeAttribute("open");
  }
  function authServerUnreachableError() {
    const error = new Error(deps.uiT("auth-server-unreachable"));
    error.code = deps.AUTH_SERVER_UNREACHABLE;
    return error;
  }
  function passwordAuthAnswer(data) {
    return data !== null && typeof data === "object" && !Array.isArray(data);
  }
  async function passwordAuthRequest(path, payload, options = {}) {
    const attempts = options.retryUnreachable ? 2 : 1;
    let response = null;
    let data = null;
    let answered = false;
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      if (attempt > 0) {
        await new Promise((resolve) => setTimeout(resolve, deps.AUTH_UNREACHABLE_RETRY_DELAY_MS));
      }
      response = await fetch(path, {
        method: "POST",
        headers: {
          "Accept": "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });
      data = null;
      try {
        data = await response.json();
      } catch (_) {}
      answered = deps.passwordAuthAnswer(data);
      // A route answer, success or refusal, is final: replaying it would
      // repeat a write. Only a body no route produced is worth the one replay.
      if (response.ok || answered) break;
    }
    if (!response.ok) {
      if (!answered) throw deps.authServerUnreachableError();
      const message = data.error && typeof data.error.message === "string"
        ? data.error.message
        : deps.uiT("auth-error-generic");
      const error = new Error(message);
      error.code = data.error && typeof data.error.code === "string" ? data.error.code : "auth_error";
      if (typeof data.login_url === "string" && data.login_url) error.loginUrl = data.login_url;
      throw error;
    }
    // A 2xx without a route answer is not a success: reporting one here would
    // claim a password was set that the server never stored.
    if (!answered) throw deps.authServerUnreachableError();
    return data;
  }
  function setAuthStatusMessage(node, message = "") {
    if (!node) return;
    node.textContent = message;
    node.hidden = !message;
  }
  async function loadAuthStatus() {
    // #6114: a Python Worker restart can eat the first status read (1101/1102).
    // A request that produced NO answer is never a signed-out answer: ask once
    // more before the browser presents unreachable. A definitive guest answer
    // (a 200 that says ready and not authenticated) is never re-asked.
    let data = null;
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        data = await fetchAuthStatusOnce();
        // The server reports a display-only hint; cookies remain HttpOnly.
        if (data.shared_login_enabled === true && data.ready === true && !data.authenticated &&
            (data.session_state === "guest" || data.session_state === "expired") && data.shared_session_present === true) {
          // #6679: a stale shared-session cookie makes the refresh endpooint
          // answer 503/401 while /api/auth/status still answers definitively.
          // A refresh failure is not "unreachable": the status above is a real
          // server answer naming this browser a guest, and the login entry
          // must act on it instead of hiding behind a failed renewal. The
          // server clears a rejected shared cookie itself (401 path), so the
          // next status read converges on a plain guest.
          try {
            const renewed = await fetch("/auth/shared/refresh", { method: "POST", headers: { "Accept": "application/json" }, cache: "no-store" });
            if (renewed.ok) {
              data = await fetchAuthStatusOnce();
            }
          } catch (_) { /* keep the definitive guest status; never mask it as unreachable */ }
        }
        break;
      } catch (_) {
        if (attempt === 1) data = null;
      }
    }
    try {
      if (!data) throw new Error("auth status unavailable");
      deps.applyAuthState(data);
      scheduleSharedRefresh();
      const sidebarReads = [];
      if (deps.authState.authenticated) {
        sidebarReads.push(deps.loadProjects(), deps.loadRecentConversations());
      }
      deps.syncApprovedMemoryVisibility();
      deps.syncClawRunHistoryVisibility();
      await Promise.allSettled(sidebarReads);
    } catch (_) {
      // #5479: a status request that never produced an answer is "unreachable",
      // not "signed out". The Chat Worker can fail every route, /api/auth/status
      // included, when the runtime loses the GIL while it starts a Python
      // instance (NoGilError, cloudflare/workerd#6624). The sign-in entry point
      // stays visible and the login button retries the status.
      deps.applyAuthState({ ready: false, authenticated: false, user: null, history_ready: false, project_files_ready: false, status_reachable: false });
    }
  }
  function requireSessionForModelUse() {
    if (deps.authState.authenticated === true) return true;
    if (deps.authState.model_requires_session !== true) return true;
    deps.setNote(deps.uiT("model-requires-login"), "error");
    if (deps.loginButton && !deps.loginButton.hidden && !deps.loginButton.disabled) deps.loginButton.click();
    else deps.openAuthDialog();
    return false;
  }
  // #7554: a sign-out whose server-side session could not be ended answers
  // 503 session_revocation_failed. The cookies are already gone; the member is
  // told so and can sign in and sign out again.
  async function logoutRevocationFailureMessage(response) {
    if (!response || response.status !== 503) return "";
    try {
      const body = await response.clone().json();
      const error = body && body.error;
      if (error && error.code === "session_revocation_failed" && typeof error.message === "string") return error.message;
    } catch (_) {}
    return "";
  }
  async function signOutCurrentAccount() {
    let revocationNote = "";
    try {
      if (deps.authState.shared_login_enabled === true && deps.authState.shared_session_present === true) {
        const sharedLogout = await fetch("/auth/shared/logout", { method: "POST", headers: { "Accept": "application/json" }, cache: "no-store" });
        revocationNote = await logoutRevocationFailureMessage(sharedLogout);
        if (!sharedLogout.ok && !revocationNote) throw new Error("shared logout unavailable");
      }
      const localLogout = await fetch("/api/auth/logout", { method: "POST", headers: { "Accept": "application/json" } });
      revocationNote = revocationNote || await logoutRevocationFailureMessage(localLogout);
    } finally {
      // #5034: drop this device's Web Push subscription on sign-out so a
      // signed-out browser stops receiving this account's task notifications.
      // Never blocks the sign-out itself.
      if (window.PadiemPush && typeof window.PadiemPush.clearOnSignOut === "function") {
        await window.PadiemPush.clearOnSignOut();
      }
      deps.resetConversationView(false);
      deps.clearProjectsUI();
      await deps.loadAuthStatus();
      if (revocationNote) deps.setNote(revocationNote, "error");
    }
  }
  function invalidateClawApprovalSession() {
    deps.clawApprovalEpoch += 1;
    // Release the shared single-flight flag so the next session can decide at
    // all. The stale promise's own finally is epoch-guarded, so it can never
    // release a newer session's busy state instead.
    deps.clawApprovalInFlight = false;
  }
  function noteClawApprovalSession(authenticated) {
    const token = authenticated
      ? "in:" + (typeof deps.authState.user?.name === "string" ? deps.authState.user.name.trim() : "")
      : "out";
    if (token !== deps.clawApprovalSessionToken) {
      deps.clawApprovalSessionToken = token;
      deps.invalidateClawApprovalSession();
    }
  }
  function reviewedGoogleAuthorizationUrl(value) {
    if (typeof value !== "string" || !value) return null;
    let url;
    try {
      url = new URL(value);
    } catch (_) {
      return null;
    }
    if (url.protocol !== "https:" || url.hostname !== "accounts.google.com") return null;
    if (url.pathname !== "/o/oauth2/v2/auth" || url.username || url.password || url.hash) return null;
    return url.toString();
  }

  // R5 A7 후속: app.js에 남았던 4함수를 auth 모듈로 합쳤다(본문 불변).
  // deps.authState·deps.loadAuthStatus는 기존 deps getter를 통해 읽는다.
  let sharedRefreshTimer = null;

  function loveTreeHandoffFromLocation() {
    try {
      const raw = window.location.search || "";
      const match = /[?&]handoff=([A-Za-z0-9_.-]{1,1024})(?:&|$)/.exec(raw);
      return match ? match[1] : "";
    } catch (_) {
      return "";
    }
  }


  async function fetchAuthStatusOnce() {
    const response = await fetch("/api/auth/status", { headers: { "Accept": "application/json" }, cache: "no-store" });
    const data = await response.json().catch(() => null);
    if (!response.ok || !data) throw new Error("auth status unavailable");
    return data;
  }

  function scheduleSharedRefresh() {
    if (sharedRefreshTimer) clearTimeout(sharedRefreshTimer);
    if (deps.authState.shared_login_enabled !== true || deps.authState.shared_session_present !== true) return;
    sharedRefreshTimer = setTimeout(async () => {
      try {
        const response = await fetch("/auth/shared/refresh", { method: "POST", headers: { "Accept": "application/json" }, cache: "no-store" });
        if (response.ok) await deps.loadAuthStatus();
      } catch (_) { /* The next status read retries without treating failure as sign-out. */ }
    }, 14 * 60 * 1000);
  }

      return {
        loveTreeHandoffFromLocation,
        fetchAuthStatusOnce,
        scheduleSharedRefresh,
        closeProfilePanel,
        accountInitial,
        resolveSessionPresentation,
        setLoginButtonCopy,
        applyAuthState,
        authMethodEnabled,
        setAuthFormError,
        syncAuthDialogMethods,
        openAuthDialog,
        closeAuthDialog,
        authServerUnreachableError,
        passwordAuthAnswer,
        passwordAuthRequest,
        setAuthStatusMessage,
        loadAuthStatus,
        requireSessionForModelUse,
        signOutCurrentAccount,
        invalidateClawApprovalSession,
        noteClawApprovalSession,
        reviewedGoogleAuthorizationUrl,
      };
    },
  };
})();
