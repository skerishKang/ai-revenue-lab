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
  }
  function authMethodEnabled(name) {
    return Boolean(deps.authState && deps.authState.methods && deps.authState.methods[name] === true);
  }
  function setAuthFormError(node, message = "") {
    if (!node) return;
    node.textContent = message;
    node.hidden = !message;
  }
  function syncAuthDialogMethods() {
    if (!deps.authDialog) return;
    const googleEnabled = deps.authMethodEnabled("google");
    const passwordEnabled = deps.authMethodEnabled("password");
    if (deps.googleLoginButton) deps.googleLoginButton.hidden = !googleEnabled;
    if (deps.authDivider) deps.authDivider.hidden = !(googleEnabled && passwordEnabled);
    // #5481: the login view and the two reset views are mutually exclusive.
    const showLogin = passwordEnabled && deps.authDialogView === "login";
    if (deps.passwordLoginForm) deps.passwordLoginForm.hidden = !showLogin;
    if (deps.passwordRegisterSection) deps.passwordRegisterSection.hidden = !showLogin;
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
    if (deps.authHandoff && !deps.authHandoff.value) {
      deps.authHandoff.value = deps.loveTreeHandoffFromLocation();
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
    deps.setAuthFormError(deps.passwordRegisterError);
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
    else if (deps.authMethodEnabled("password") && deps.passwordLoginIdentifier) deps.passwordLoginIdentifier.focus();
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
      throw error;
    }
    // A 2xx without a route answer is not a success: reporting one here would
    // claim a password was set that the server never stored.
    if (!answered) throw deps.authServerUnreachableError();
    return data;
  }
  async function submitPasswordLogin(event) {
    event.preventDefault();
    if (!deps.authMethodEnabled("password") || !deps.passwordLoginForm) return;
    deps.setAuthFormError(deps.passwordLoginError);
    deps.passwordLoginSubmit.disabled = true;
    try {
      const result = await deps.passwordAuthRequest("/api/auth/password/login", {
        identifier: deps.passwordLoginIdentifier.value,
        password: deps.passwordLoginPassword.value,
        // A pending LoveTree sign-in travels back exactly as it arrived. The server
        // binds it only after a verified login and answers with the hop it owns.
        ...(deps.authHandoff && deps.authHandoff.value ? { handoff: deps.authHandoff.value } : {}),
      });
      if (result && typeof result.handoff_return === "string" && /^https?:\/\//.test(result.handoff_return)) {
        window.location.assign(result.handoff_return);
        return;
      }
      deps.passwordLoginPassword.value = "";
      deps.closeAuthDialog();
      await deps.loadAuthStatus();
    } catch (error) {
      deps.setAuthFormError(
        deps.passwordLoginError,
        error instanceof Error ? error.message : deps.uiT("auth-error-generic"),
      );
    } finally {
      deps.passwordLoginSubmit.disabled = false;
    }
  }
  async function submitPasswordRegister(event) {
    event.preventDefault();
    if (!deps.authMethodEnabled("password") || !deps.passwordRegisterForm) return;
    deps.setAuthFormError(deps.passwordRegisterError);
    deps.passwordRegisterSubmit.disabled = true;
    try {
      await deps.passwordAuthRequest("/api/auth/password/register", {
        email: deps.passwordRegisterEmail.value,
        name: deps.passwordRegisterName.value,
        password: deps.passwordRegisterPassword.value,
      });
      deps.passwordRegisterPassword.value = "";
      deps.closeAuthDialog();
      await deps.loadAuthStatus();
    } catch (error) {
      deps.setAuthFormError(
        deps.passwordRegisterError,
        error instanceof Error ? error.message : deps.uiT("auth-error-generic"),
      );
    } finally {
      deps.passwordRegisterSubmit.disabled = false;
    }
  }
  function setAuthStatusMessage(node, message = "") {
    if (!node) return;
    node.textContent = message;
    node.hidden = !message;
  }
  function passwordResetTokenFromLocation() {
    try {
      const raw = window.location.hash || "";
      const match = /^#reset=([A-Za-z0-9_-]{16,256})$/.exec(raw);
      return match ? match[1] : "";
    } catch (_) {
      return "";
    }
  }
  function clearPasswordResetFragment() {
    // The one-time token leaves the address bar as soon as the member leaves
    // the reset view, so a shared link never lingers in the browser history
    // of the next person who opens this window.
    try {
      if (!window.location.hash) return;
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
    } catch (_) {}
  }
  function showPasswordResetView(view) {
    deps.authDialogView = view;
    if (deps.passwordResetPanel) deps.passwordResetPanel.hidden = false;
    if (deps.passwordLoginForm) deps.passwordLoginForm.hidden = view !== "login";
    if (deps.passwordRegisterSection) deps.passwordRegisterSection.hidden = view !== "login";
    if (deps.passwordResetRequestView) deps.passwordResetRequestView.hidden = view !== "request";
    if (deps.passwordResetConfirmView) deps.passwordResetConfirmView.hidden = view !== "confirm";
  }
  function hidePasswordResetViews() {
    deps.passwordResetToken = "";
    deps.authDialogView = "login";
    deps.clearPasswordResetFragment();
    if (deps.passwordResetPanel) deps.passwordResetPanel.hidden = true;
    if (deps.passwordResetRequestView) deps.passwordResetRequestView.hidden = true;
    if (deps.passwordResetConfirmView) deps.passwordResetConfirmView.hidden = true;
    if (deps.passwordResetOpen) deps.passwordResetOpen.hidden = !deps.authMethodEnabled("password");
    if (deps.passwordResetEmail) deps.passwordResetEmail.value = "";
    if (deps.passwordResetNew) deps.passwordResetNew.value = "";
    if (deps.passwordResetConfirm) deps.passwordResetConfirm.value = "";
    deps.setAuthFormError(deps.passwordResetRequestError);
    deps.setAuthFormError(deps.passwordResetConfirmError);
    deps.setAuthStatusMessage(deps.passwordResetRequestStatus);
    deps.setAuthStatusMessage(deps.passwordResetConfirmStatus);
  }
  function openPasswordResetRequest() {
    if (!deps.authMethodEnabled("password")) return;
    deps.setAuthFormError(deps.passwordResetRequestError);
    deps.setAuthStatusMessage(deps.passwordResetRequestStatus);
    deps.showPasswordResetView("request");
    if (deps.passwordResetEmail && deps.passwordLoginIdentifier && !deps.passwordResetEmail.value) {
      deps.passwordResetEmail.value = deps.passwordLoginIdentifier.value.trim();
    }
    deps.passwordResetEmail?.focus();
  }
  function openPasswordResetConfirm(token) {
    if (!deps.authMethodEnabled("password")) return;
    deps.passwordResetToken = typeof token === "string" ? token : "";
    deps.setAuthFormError(deps.passwordResetConfirmError);
    deps.setAuthStatusMessage(deps.passwordResetConfirmStatus);
    deps.showPasswordResetView("confirm");
    deps.passwordResetNew?.focus();
  }
  function closePasswordResetViews() {
    deps.passwordResetToken = "";
    deps.hidePasswordResetViews();
    if (deps.passwordResetEmail) deps.passwordResetEmail.value = "";
    if (deps.passwordResetNew) deps.passwordResetNew.value = "";
    if (deps.passwordResetConfirm) deps.passwordResetConfirm.value = "";
    deps.setAuthFormError(deps.passwordResetRequestError);
    deps.setAuthFormError(deps.passwordResetConfirmError);
    deps.setAuthStatusMessage(deps.passwordResetRequestStatus);
    deps.setAuthStatusMessage(deps.passwordResetConfirmStatus);
  }
  async function submitPasswordResetRequest(event) {
    event.preventDefault();
    if (!deps.authMethodEnabled("password") || !deps.passwordResetRequestForm) return;
    deps.setAuthFormError(deps.passwordResetRequestError);
    deps.setAuthStatusMessage(deps.passwordResetRequestStatus);
    deps.passwordResetRequestSubmit.disabled = true;
    try {
      await deps.passwordAuthRequest("/api/auth/password/reset/request", {
        email: deps.passwordResetEmail.value,
      });
      // The server answers the same way for every address, so the browser
      // shows the same confirmation either way.
      deps.setAuthStatusMessage(deps.passwordResetRequestStatus, deps.uiT("auth-reset-request-sent"));
    } catch (error) {
      deps.setAuthFormError(
        deps.passwordResetRequestError,
        error instanceof Error ? error.message : deps.uiT("auth-error-generic"),
      );
    } finally {
      deps.passwordResetRequestSubmit.disabled = false;
    }
  }
  async function submitPasswordResetConfirm(event) {
    event.preventDefault();
    if (!deps.authMethodEnabled("password") || !deps.passwordResetConfirmForm) return;
    deps.setAuthFormError(deps.passwordResetConfirmError);
    deps.setAuthStatusMessage(deps.passwordResetConfirmStatus);
    const newPassword = deps.passwordResetNew?.value || "";
    const confirmPassword = deps.passwordResetConfirm?.value || "";
    if (!newPassword || !confirmPassword) {
      deps.setAuthFormError(deps.passwordResetConfirmError, deps.uiT("auth-reset-confirm-incomplete"));
      return;
    }
    if (newPassword !== confirmPassword) {
      deps.setAuthFormError(deps.passwordResetConfirmError, deps.uiT("auth-reset-confirm-mismatch"));
      return;
    }
    if (!deps.passwordResetToken) {
      deps.setAuthFormError(deps.passwordResetConfirmError, deps.uiT("auth-reset-expired"));
      return;
    }
    deps.passwordResetConfirmSubmit.disabled = true;
    try {
      await deps.passwordAuthRequest("/api/auth/password/reset/confirm", {
        token: deps.passwordResetToken,
        new_password: newPassword,
      }, { retryUnreachable: true });
      deps.passwordResetToken = "";
      deps.clearPasswordResetFragment();
      if (deps.passwordResetNew) deps.passwordResetNew.value = "";
      if (deps.passwordResetConfirm) deps.passwordResetConfirm.value = "";
      deps.setAuthStatusMessage(deps.passwordResetConfirmStatus, deps.uiT("auth-reset-confirm-done"));
      deps.closeAuthDialog();
      await deps.loadAuthStatus();
    } catch (error) {
      deps.setAuthFormError(
        deps.passwordResetConfirmError,
        error instanceof Error ? error.message : deps.uiT("auth-error-generic"),
      );
    } finally {
      deps.passwordResetConfirmSubmit.disabled = false;
    }
  }
  function openPasswordChangeDialog() {
    if (!deps.passwordChangeDialog) return;
    deps.setAuthFormError(deps.passwordChangeError);
    if (deps.passwordChangeCurrent) deps.passwordChangeCurrent.value = "";
    if (deps.passwordChangeNew) deps.passwordChangeNew.value = "";
    if (deps.passwordChangeConfirm) deps.passwordChangeConfirm.value = "";
    if (typeof deps.passwordChangeDialog.showModal === "function") deps.passwordChangeDialog.showModal();
    else deps.passwordChangeDialog.setAttribute("open", "");
    deps.passwordChangeCurrent?.focus();
  }
  function closePasswordChangeDialog() {
    if (!deps.passwordChangeDialog) return;
    if (deps.passwordChangeDialog.open && typeof deps.passwordChangeDialog.close === "function") deps.passwordChangeDialog.close();
    else deps.passwordChangeDialog.removeAttribute("open");
  }
  async function submitPasswordChange(event) {
    event.preventDefault();
    if (!deps.passwordChangeForm) return;
    deps.setAuthFormError(deps.passwordChangeError);
    const currentPassword = deps.passwordChangeCurrent?.value || "";
    const newPassword = deps.passwordChangeNew?.value || "";
    const confirmPassword = deps.passwordChangeConfirm?.value || "";
    if (!currentPassword || !newPassword) {
      deps.setAuthFormError(deps.passwordChangeError, deps.uiT("password-change-incomplete"));
      return;
    }
    if (newPassword !== confirmPassword) {
      deps.setAuthFormError(deps.passwordChangeError, deps.uiT("password-change-mismatch"));
      return;
    }
    if (newPassword === currentPassword) {
      deps.setAuthFormError(deps.passwordChangeError, deps.uiT("password-change-unchanged"));
      return;
    }
    deps.passwordChangeSubmit.disabled = true;
    try {
      await deps.passwordAuthRequest("/api/auth/password/change", {
        current_password: currentPassword,
        new_password: newPassword,
      });
      // The server ends the session it changed the credential for, so the
      // browser signs in again with the new password.
      if (deps.passwordChangeCurrent) deps.passwordChangeCurrent.value = "";
      if (deps.passwordChangeNew) deps.passwordChangeNew.value = "";
      if (deps.passwordChangeConfirm) deps.passwordChangeConfirm.value = "";
      deps.closePasswordChangeDialog();
      deps.closeSettings();
      await deps.loadAuthStatus();
      if (deps.authDialog && !deps.authDialog.open) deps.openAuthDialog();
      deps.setAuthFormError(deps.passwordLoginError, deps.uiT("password-change-done"));
    } catch (error) {
      deps.setAuthFormError(
        deps.passwordChangeError,
        error instanceof Error ? error.message : deps.uiT("auth-error-generic"),
      );
    } finally {
      deps.passwordChangeSubmit.disabled = false;
    }
  }
  function resetAccountDeleteConfirm() {
    if (deps.accountDeleteConfirmEmail) deps.accountDeleteConfirmEmail.value = "";
    if (deps.accountDeleteButton) deps.accountDeleteButton.disabled = true;
    deps.setAuthFormError(deps.accountDeleteError);
  }
  function resetAccountSharedDeleteConfirm() {
    if (deps.accountSharedDeleteConfirmEmail) deps.accountSharedDeleteConfirmEmail.value = "";
    if (deps.accountSharedDeleteButton) deps.accountSharedDeleteButton.disabled = true;
    deps.setAuthFormError(deps.accountSharedDeleteError);
  }
  function openAccountDeleteConfirm() {
    if (!deps.accountDeleteConfirm) return;
    deps.resetAccountDeleteConfirm();
    deps.resetAccountSharedDeleteConfirm();
    if (deps.accountSharedDeleteConfirm) deps.accountSharedDeleteConfirm.hidden = true;
    deps.accountDeleteConfirm.hidden = false;
    deps.accountDeleteConfirmEmail?.focus();
  }
  function openAccountSharedDeleteConfirm() {
    if (!deps.accountSharedDeleteConfirm) return;
    deps.resetAccountDeleteConfirm();
    deps.resetAccountSharedDeleteConfirm();
    if (deps.accountDeleteConfirm) deps.accountDeleteConfirm.hidden = true;
    deps.accountSharedDeleteConfirm.hidden = false;
    deps.accountSharedDeleteConfirmEmail?.focus();
  }
  function syncAccountDeleteButton() {
    deps.syncDeleteButton(deps.accountDeleteButton, deps.accountDeleteConfirmEmail);
  }
  function syncAccountSharedDeleteButton() {
    deps.syncDeleteButton(deps.accountSharedDeleteButton, deps.accountSharedDeleteConfirmEmail);
  }
  async function submitAccountDelete(deleteAllServices = false) {
    const button = deleteAllServices ? deps.accountSharedDeleteButton : deps.accountDeleteButton;
    const inputElement = deleteAllServices ? deps.accountSharedDeleteConfirmEmail : deps.accountDeleteConfirmEmail;
    const errorElement = deleteAllServices ? deps.accountSharedDeleteError : deps.accountDeleteError;
    if (!button || button.disabled) return;
    deps.setAuthFormError(errorElement);
    const typed = inputElement?.value || "";
    button.disabled = true;
    try {
      const endpoint = deleteAllServices ? "/api/account/shared-delete" : "/api/account/delete";
      await deps.passwordAuthRequest(endpoint, { confirm: typed });
      deps.resetAccountDeleteConfirm();
      deps.resetAccountSharedDeleteConfirm();
      if (deps.accountDeleteConfirm) deps.accountDeleteConfirm.hidden = true;
      if (deps.accountSharedDeleteConfirm) deps.accountSharedDeleteConfirm.hidden = true;
      // Successful deletion revokes this service session and clears its cookie.
      deps.closeSettings();
      await deps.loadAuthStatus();
      if (deps.authDialog && !deps.authDialog.open) deps.openAuthDialog();
      deps.setAuthFormError(
        deps.passwordLoginError,
        deps.uiT(deleteAllServices ? "account-shared-delete-done" : "account-delete-done"),
      );
    } catch (error) {
      deps.setAuthFormError(
        errorElement,
        error instanceof Error ? error.message : deps.uiT("auth-error-generic"),
      );
      button.disabled = false;
    }
  }
  async function loadAuthStatus() {
    // #6114: a Python Worker restart can eat the first status read (1101/1102).
    // A request that produced NO answer is never a signed-out answer: ask once
    // more before the browser presents unreachable. A definitive guest answer
    // (a 200 that says ready and not authenticated) is never re-asked.
    let data = null;
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        data = await deps.fetchAuthStatusOnce();
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
              data = await deps.fetchAuthStatusOnce();
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
      deps.scheduleSharedRefresh();
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
  async function signOutCurrentAccount() {
    try {
      if (deps.authState.shared_login_enabled === true && deps.authState.shared_session_present === true) {
        const sharedLogout = await fetch("/auth/shared/logout", { method: "POST", headers: { "Accept": "application/json" }, cache: "no-store" });
        if (!sharedLogout.ok) throw new Error("shared logout unavailable");
      }
      await fetch("/api/auth/logout", { method: "POST", headers: { "Accept": "application/json" } });
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
      return {
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
        submitPasswordLogin,
        submitPasswordRegister,
        setAuthStatusMessage,
        passwordResetTokenFromLocation,
        clearPasswordResetFragment,
        showPasswordResetView,
        hidePasswordResetViews,
        openPasswordResetRequest,
        openPasswordResetConfirm,
        closePasswordResetViews,
        submitPasswordResetRequest,
        submitPasswordResetConfirm,
        openPasswordChangeDialog,
        closePasswordChangeDialog,
        submitPasswordChange,
        resetAccountDeleteConfirm,
        resetAccountSharedDeleteConfirm,
        openAccountDeleteConfirm,
        openAccountSharedDeleteConfirm,
        syncAccountDeleteButton,
        syncAccountSharedDeleteButton,
        submitAccountDelete,
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
