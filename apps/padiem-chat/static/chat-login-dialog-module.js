// #7216 R5 - login dialog section (moved out of the app.js closure and the auth module).
// No behavior, copy, DOM id or event name change. Shared state and DOM refs are
// read/written only through the deps getters/setters. app.js keeps the same-named
// one-line forwarders.
(() => {
  "use strict";
  window.PadiemChatLoginDialogModule = {
    create(deps) {
      const authDialogClose = document.getElementById("authDialogClose");
      const authDivider = document.getElementById("authDivider");
      const guestLoginEntryButton = document.getElementById("guestLoginEntryButton");

      // #5664: the Chat Python Worker can fail isolate startup with
      // `NoGilError: Attempted to use PyProxy when Python GIL not held`
      // (cloudflare/workerd#6624) and then answers a plain-text 5xx that no route
      // produced. That body never describes the account, so it must not be shown
      // as a rejected credential or a failed sign-in.
      const AUTH_SERVER_UNREACHABLE = "auth_server_unreachable";
      // One replay is safe only where the route makes it safe: the reset confirm is
      // guarded by its one-time token, whose atomic consume applies at most once,
      // and the failed request never reached the route. Every other auth write
      // keeps its single attempt.
      const AUTH_UNREACHABLE_RETRY_DELAY_MS = 600;

      // The visible account name/avatar is the one-step Settings entry.
      // Reuse the existing settings action; do not create a second settings flow.
      const profilePanel = document.createElement("div");
      profilePanel.id = "accountProfilePanel";
      profilePanel.className = "account-profile-panel";
      profilePanel.hidden = true;
      const profileSettingsAction = document.createElement("button");
      profileSettingsAction.type = "button";
      profileSettingsAction.className = "account-profile-settings";
      profileSettingsAction.dataset.localeKey = "account-profile-settings";
      profileSettingsAction.textContent = deps.uiT("account-profile-settings");
      profilePanel.append(profileSettingsAction);
      deps.accountContainer?.append(profilePanel);

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
        if (authDivider) authDivider.hidden = !(googleEnabled && passwordEnabled);
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
        syncAuthDialogMethods();
        setAuthFormError(deps.passwordLoginError);
        setAuthFormError(deps.passwordResetRequestError);
        setAuthFormError(deps.passwordResetConfirmError);
        setAuthStatusMessage(deps.passwordResetRequestStatus);
        setAuthStatusMessage(deps.passwordResetConfirmStatus);
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
        error.code = AUTH_SERVER_UNREACHABLE;
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
            await new Promise((resolve) => setTimeout(resolve, AUTH_UNREACHABLE_RETRY_DELAY_MS));
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
          answered = passwordAuthAnswer(data);
          // A route answer, success or refusal, is final: replaying it would
          // repeat a write. Only a body no route produced is worth the one replay.
          if (response.ok || answered) break;
        }
        if (!response.ok) {
          if (!answered) throw authServerUnreachableError();
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
        if (!answered) throw authServerUnreachableError();
        return data;
      }
      function setAuthStatusMessage(node, message = "") {
        if (!node) return;
        node.textContent = message;
        node.hidden = !message;
      }

      function wireGuestLogin() {
        if (guestLoginEntryButton) guestLoginEntryButton.addEventListener("click", openAuthDialog);
      }

      function wireDialogClose() {
        if (authDialogClose) authDialogClose.addEventListener("click", closeAuthDialog);
        if (deps.authDialog) {
          deps.authDialog.addEventListener("cancel", (event) => {
            event.preventDefault();
            closeAuthDialog();
          });
        }
      }

      function wireGoogleLogin() {
        if (deps.googleLoginButton) {
          deps.googleLoginButton.addEventListener("click", () => {
            if (!deps.authMethodEnabled("google")) return;
            if (deps.isAndroidWebView()) {
              deps.startAndroidHandoff();
              return;
            }
            window.location.assign("/auth/google/start");
          });
        }
      }

      function wireProfileToggle() {
        deps.profileToggle.addEventListener("click", () => { if (deps.accountContainer?.hidden) return; window.PadiemChatProfileMenu?.toggle?.(); });
      }

      function wireProfileSettings() {
        profileSettingsAction.addEventListener("click", () => {
          deps.closeProfilePanel();
          deps.settingsButton.click(); // keep the existing settings-dialog authority
        });
      }

      function wireProfileDismiss() {
        document.addEventListener("pointerdown", (event) => {
          if (!profilePanel.hidden && !deps.accountContainer?.contains(event.target)) deps.closeProfilePanel();
        });
      }

      function profilePanelElement() { return profilePanel; }

      return {
        setAuthFormError,
        emailContinueElement,
        syncAuthDialogMethods,
        openAuthDialog,
        closeAuthDialog,
        authServerUnreachableError,
        passwordAuthAnswer,
        passwordAuthRequest,
        setAuthStatusMessage,
        profilePanelElement,
        wireGuestLogin,
        wireDialogClose,
        wireGoogleLogin,
        wireProfileToggle,
        wireProfileSettings,
        wireProfileDismiss,
      };
    },
  };
})();
